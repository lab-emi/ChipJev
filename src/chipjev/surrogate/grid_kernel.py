"""Fused CUDA kernel (Triton) for design-space-wide pathwise Thompson sampling.

One pass per candidate block evaluates every sampled GP path without materializing the
candidates x features matrix: grid indices are decoded to coordinates in registers, the
random-Fourier-feature prior is accumulated feature block by feature block, and the exact
Matern-5/2 posterior correction is accumulated over the observed designs. The result is
identical in distribution to gp.BatchedGP's eager path (same random draws) and
agrees with it to float32 rounding (IEEE float32 dot products; the hardware cosine after
explicit range reduction has an absolute error below 1e-6). The eager path remains the
implementation on the CPU and on Apple MPS.
"""

__all__ = ["available", "pathwise"]

_TRITON = None


def available(device):
    """True when the fused kernel can run on ``device`` (CUDA with Triton)."""
    global _TRITON
    if device.type != "cuda":
        return False
    if _TRITON is None:
        try:
            import triton  # noqa: F401

            _TRITON = True
        except ImportError:
            _TRITON = False
    return _TRITON


def _build():
    import triton
    import triton.language as tl

    @triton.jit
    def column(x, columns, j: tl.constexpr, d: tl.constexpr):
        # One coordinate as a vector (zero beyond the dimension), hoisted out of the loops.
        if j < d:
            return tl.sum(tl.where(columns[None, :] == j, x, 0.0), axis=1)
        return tl.sum(x * 0.0, axis=1)

    @triton.jit
    def fma(angle, xj, omega_ptr, row, D: tl.constexpr, f, j: tl.constexpr, d: tl.constexpr):
        if j < d:
            angle += xj[:, None] * tl.load(omega_ptr + (row + j) * D + f)[None, :]
        return angle

    @triton.jit
    def cosine(angle, FAST: tl.constexpr):
        # Range reduction to [-pi, pi], then the hardware approximation (abs. error < 1e-6).
        angle -= 6.283185307179586 * tl.floor(angle * 0.15915494309189535 + 0.5)
        if FAST:
            return tl.inline_asm_elementwise(
                "cos.approx.f32 $0, $1;", "=r,r", [angle], dtype=tl.float32, is_pure=True, pack=1
            )
        return tl.cos(angle)

    @triton.jit
    def kernel(
        out_ptr,  # [M, SP, N] float32
        x_ptr,  # [N, d] float32 (explicit candidates) or unused
        levels_ptr,  # [d] int64 (grid candidates)
        begin,  # first grid index of this launch
        count,  # candidates in this launch
        omega_ptr,  # [M, d, D]
        phase_ptr,  # [M, D]
        weight_ptr,  # [M, D, SP]: sample weights times the RFF scale, zero padded
        train_ptr,  # [n, d]
        inverse_ptr,  # [M, d] inverse lengthscales
        outputscale_ptr,  # [M]
        update_ptr,  # [M, n, SP], zero padded
        n,
        d: tl.constexpr,
        D: tl.constexpr,
        SP: tl.constexpr,
        GRID: tl.constexpr,
        BLOCK_N: tl.constexpr,
        BLOCK_D: tl.constexpr,
        BLOCK_I: tl.constexpr,
        PRECISION: tl.constexpr,
        FAST: tl.constexpr,
    ):
        block = tl.program_id(0)
        m = tl.program_id(1)
        rows = block * BLOCK_N + tl.arange(0, BLOCK_N)
        valid = rows < count
        samples = tl.arange(0, SP)
        columns = tl.arange(0, 16)  # parameters, zero padded to the minimum dot width
        used = columns < d
        acc = tl.zeros((BLOCK_N, SP), dtype=tl.float32)

        # Normalized coordinates [BLOCK_N, 16], decoded in registers for grid candidates
        # (mixed radix, last parameter fastest, exactly as Space.enumerate).
        if GRID:
            x = tl.zeros((BLOCK_N, 16), dtype=tl.float32)
            index = begin + rows.to(tl.int64)
            for jj in tl.static_range(d):
                level = tl.load(levels_ptr + (d - 1 - jj))
                digit = index % level
                index = index // level
                value = digit.to(tl.float32) / (level - 1).to(tl.float32)
                x = tl.where(columns[None, :] == (d - 1 - jj), value[:, None], x)
        else:
            x = tl.load(
                x_ptr + rows[:, None] * d + columns[None, :],
                mask=valid[:, None] & used[None, :],
                other=0.0,
            )
        x0 = column(x, columns, 0, d)
        x1 = column(x, columns, 1, d)
        x2 = column(x, columns, 2, d)
        x3 = column(x, columns, 3, d)
        x4 = column(x, columns, 4, d)
        x5 = column(x, columns, 5, d)
        x6 = column(x, columns, 6, d)
        x7 = column(x, columns, 7, d)

        # Random-Fourier-feature prior, one feature block at a time (never materialized).
        features = tl.arange(0, BLOCK_D)
        row = m * d
        for start in range(0, D, BLOCK_D):
            f = start + features
            angle = (
                tl.zeros((BLOCK_N, BLOCK_D), tl.float32) + tl.load(phase_ptr + m * D + f)[None, :]
            )
            angle = fma(angle, x0, omega_ptr, row, D, f, 0, d)
            angle = fma(angle, x1, omega_ptr, row, D, f, 1, d)
            angle = fma(angle, x2, omega_ptr, row, D, f, 2, d)
            angle = fma(angle, x3, omega_ptr, row, D, f, 3, d)
            angle = fma(angle, x4, omega_ptr, row, D, f, 4, d)
            angle = fma(angle, x5, omega_ptr, row, D, f, 5, d)
            angle = fma(angle, x6, omega_ptr, row, D, f, 6, d)
            angle = fma(angle, x7, omega_ptr, row, D, f, 7, d)
            basis = cosine(angle, FAST)
            weights = tl.load(weight_ptr + (m * D + f)[:, None] * SP + samples[None, :])
            acc += tl.dot(basis, weights, input_precision=PRECISION)

        # Exact posterior correction: Matern-5/2 kernel to every observed design.
        inverse = tl.load(inverse_ptr + m * d + columns, mask=used, other=0.0)
        a = x * inverse[None, :]
        a2 = tl.sum(a * a, axis=1)
        scale = tl.load(outputscale_ptr + m)
        observed = tl.arange(0, BLOCK_I)
        for start in range(0, n, BLOCK_I):
            i = start + observed
            present = i < n
            t = tl.load(
                train_ptr + i[:, None] * d + columns[None, :],
                mask=present[:, None] & used[None, :],
                other=0.0,
            )
            b = t * inverse[None, :]
            b2 = tl.sum(b * b, axis=1)
            cross = tl.dot(a, tl.trans(b), input_precision="ieee")
            d2 = tl.maximum(a2[:, None] + b2[None, :] - 2.0 * cross, 0.0)
            r5 = tl.sqrt(5.0 * d2 + 1e-12)
            k = scale * (1.0 + r5 + (5.0 / 3.0) * d2) * tl.exp(-r5)
            k = tl.where(present[None, :], k, 0.0)
            u = tl.load(
                update_ptr + (m * n + i)[:, None] * SP + samples[None, :],
                mask=present[:, None],
                other=0.0,
            )
            acc += tl.dot(k, u, input_precision=PRECISION)

        pointer = out_ptr + (m * SP + samples[None, :]) * count + rows[:, None]
        tl.store(pointer, acc, mask=valid[:, None])

    return kernel


_KERNEL = None


def pathwise(
    candidates,
    begin,
    count,
    omega,
    phase,
    weights,
    scale,
    train,
    lengthscale,
    outputscale,
    update,
    precision="ieee",
    fast=True,
    blocks=(128, 32, 32),
):
    """Sampled paths [S, count, M] (standardized units) for one candidate range.

    ``candidates`` is a Space-like object with ``levels`` (grid mode) or a float32 tensor
    [count, d] of normalized coordinates. Other arguments follow BatchedGP.thompson:
    omega [M,d,D], phase [M,1,D], weights [S,M,D], scale [M,1,1], train [n,d],
    lengthscale [M,d], outputscale [M], update [M,n,S].
    """
    import torch
    import triton

    global _KERNEL
    if _KERNEL is None:
        _KERNEL = _build()
    device = omega.device
    f32 = torch.float32
    m, d, features = omega.shape
    samples = weights.shape[0]
    padded = max(16, 1 << (samples - 1).bit_length())
    n = train.shape[0]
    w = torch.zeros(m, features, padded, device=device, dtype=f32)
    w[:, :, :samples] = (weights * scale[None, :, :, 0]).permute(1, 2, 0)
    u = torch.zeros(m, max(n, 1), padded, device=device, dtype=f32)
    u[:, :n, :samples] = update
    if d > 8:
        raise ValueError("the fused kernel supports at most 8 parameters")
    grid = hasattr(candidates, "levels")
    if grid:
        levels = torch.as_tensor(candidates.levels, device=device, dtype=torch.int64)
        x = torch.zeros(1, device=device, dtype=f32)
    else:
        levels = torch.zeros(1, device=device, dtype=torch.int64)
        x = candidates.to(device=device, dtype=f32).contiguous()
    out = torch.empty(m, padded, count, device=device, dtype=f32)
    block_n, block_d, block_i = blocks
    if features % block_d:
        raise ValueError("the feature count must be a multiple of 64")
    _KERNEL[(triton.cdiv(count, block_n), m)](
        out,
        x,
        levels,
        int(begin),
        int(count),
        omega.to(f32).contiguous(),
        phase.reshape(m, features).to(f32).contiguous(),
        w,
        train.to(f32).contiguous(),
        (1.0 / lengthscale).to(f32).contiguous(),
        outputscale.to(f32).contiguous(),
        u,
        n,
        d=d,
        D=features,
        SP=padded,
        GRID=grid,
        BLOCK_N=block_n,
        BLOCK_D=block_d,
        BLOCK_I=block_i,
        PRECISION=precision,
        FAST=fast,
    )
    return out[:, :samples].permute(1, 2, 0)
