"""Fused CUDA kernel (Triton) for pathwise Thompson sampling over joint topology-and-sizing
candidates with up to 64 features.

It generalizes the grid kernel (grid_kernel.py; at most 8 sizing parameters, decoded in
registers) to explicit feature vectors: grammar descriptors plus role-slot sizes. Per
block of candidates it evaluates every sampled path without materializing the
candidates x random-features matrix: the prior's projections are one IEEE float32 dot
product per feature block, and the exact Matern-5/2 posterior correction is accumulated
over the observed designs. Random draws and the correction are those of the eager path
(chipjev.surrogate.gp.BatchedGP.thompson), so both select from the same posterior samples.
"""

__all__ = ["available", "pathwise_wide"]

MAX_FEATURES = 64
_KERNEL = None


def available(device, dimension):
    if device.type != "cuda" or dimension > MAX_FEATURES:
        return False
    try:
        import triton  # noqa: F401
    except ImportError:
        return False
    return True


def _build():
    import triton
    import triton.language as tl

    @triton.jit
    def cosine(angle, FAST: tl.constexpr):
        angle -= 6.283185307179586 * tl.floor(angle * 0.15915494309189535 + 0.5)
        if FAST:
            return tl.inline_asm_elementwise(
                "cos.approx.f32 $0, $1;", "=r,r", [angle], dtype=tl.float32, is_pure=True, pack=1
            )
        return tl.cos(angle)

    @triton.jit
    def kernel(
        out_ptr,  # [M, SP, N]
        x_ptr,  # [N, d] float32
        count,
        omega_ptr,  # [M, d, D]
        phase_ptr,  # [M, D]
        weight_ptr,  # [M, D, SP]
        train_ptr,  # [n, d]
        inverse_ptr,  # [M, d]
        outputscale_ptr,  # [M]
        update_ptr,  # [M, n, SP]
        n,
        d: tl.constexpr,
        DP: tl.constexpr,
        D: tl.constexpr,
        SP: tl.constexpr,
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
        columns = tl.arange(0, DP)
        used = columns < d
        x = tl.load(
            x_ptr + rows[:, None].to(tl.int64) * d + columns[None, :],
            mask=valid[:, None] & used[None, :],
            other=0.0,
        )
        acc = tl.zeros((BLOCK_N, SP), dtype=tl.float32)
        features = tl.arange(0, BLOCK_D)
        for start in range(0, D, BLOCK_D):
            f = start + features
            omega = tl.load(
                omega_ptr + (m * d + columns[:, None]) * D + f[None, :],
                mask=used[:, None],
                other=0.0,
            )
            angle = tl.dot(x, omega, input_precision="ieee")
            angle += tl.load(phase_ptr + m * D + f)[None, :]
            basis = cosine(angle, FAST)
            weights = tl.load(weight_ptr + (m * D + f)[:, None] * SP + samples[None, :])
            acc += tl.dot(basis, weights, input_precision=PRECISION)
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
        pointer = out_ptr + (m * SP + samples[None, :]).to(tl.int64) * count + rows[:, None]
        tl.store(pointer, acc, mask=valid[:, None])

    return kernel


def pathwise_wide(
    points,
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
    blocks=(64, 32, 32),
):
    """Sampled paths [S, N, M] (standardized units) for explicit candidates [N, d].

    Arguments follow BatchedGP.thompson: omega [M,d,D], phase [M,1,D], weights [S,M,D],
    scale [M,1,1], train [n,d], lengthscale [M,d], outputscale [M], update [M,n,S].
    """
    import torch
    import triton

    global _KERNEL
    if _KERNEL is None:
        _KERNEL = _build()
    device = omega.device
    f32 = torch.float32
    m, d, features = omega.shape
    if d > MAX_FEATURES:
        raise ValueError(f"the wide kernel supports at most {MAX_FEATURES} features")
    samples = weights.shape[0]
    padded = max(16, 1 << (samples - 1).bit_length())
    width = max(16, 1 << (d - 1).bit_length())
    n = train.shape[0]
    count = points.shape[0]
    w = torch.zeros(m, features, padded, device=device, dtype=f32)
    w[:, :, :samples] = (weights * scale[None, :, :, 0]).permute(1, 2, 0)
    u = torch.zeros(m, max(n, 1), padded, device=device, dtype=f32)
    u[:, :n, :samples] = update
    out = torch.empty(m, padded, count, device=device, dtype=f32)
    block_n, block_d, block_i = blocks
    if features % block_d:
        raise ValueError(f"the feature count must be a multiple of {block_d}")
    _KERNEL[(triton.cdiv(count, block_n), m)](
        out,
        points.to(device=device, dtype=f32).contiguous(),
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
        DP=width,
        D=features,
        SP=padded,
        BLOCK_N=block_n,
        BLOCK_D=block_d,
        BLOCK_I=block_i,
        PRECISION=precision,
        FAST=fast,
    )
    return out[:, :samples].permute(1, 2, 0)
