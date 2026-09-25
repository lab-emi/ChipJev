"""Batched GP surrogates and the fused Thompson-sampling kernels (chipjev.surrogate)."""

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from chipjev.circuits.space import ClassSpace  # noqa: E402
from chipjev.surrogate.gp import BatchedGP, TopoGP  # noqa: E402


def test_gp_recovers_smooth_function_and_thompson_respects_exclusions():
    rng = np.random.default_rng(0)
    x = rng.random((40, 3))
    y = np.stack([np.sin(3 * x[:, 0]) + x[:, 1], x[:, 2] ** 2], 1)
    y[3, 1] = np.nan  # a missing observation is masked, not imputed
    gp = BatchedGP("cpu", seed=0).fit(x, y, steps=80)
    test = rng.random((200, 3))
    mean, std = gp.predict(test)
    truth = np.stack([np.sin(3 * test[:, 0]) + test[:, 1], test[:, 2] ** 2], 1)
    assert np.sqrt(np.mean((mean - truth) ** 2)) < 0.1
    assert np.all(std >= 0)
    exclude = np.zeros(len(test), dtype=bool)
    exclude[:100] = True
    index, _ = gp.thompson(test, samples=4, score=lambda v: v[..., 0], exclude=exclude, top=5)
    assert index.shape == (4, 5) and np.all(index >= 100)


class _Grid:
    """A mixed-radix grid of normalized coordinates, as the kernel's grid mode expects."""

    def __init__(self, levels):
        self.levels = np.array(levels)
        self.size = int(np.prod(levels))

    def chunk(self, begin, end, device, dtype):
        rest = torch.arange(begin, end, device=device, dtype=torch.int64)
        columns = []
        for level in self.levels[::-1]:
            columns.append(rest % int(level))
            rest = rest // int(level)
        points = torch.stack(columns[::-1], dim=-1).to(dtype)
        return points / torch.as_tensor(self.levels - 1, device=device, dtype=dtype)


@pytest.mark.skipif(not torch.cuda.is_available(), reason="no CUDA device")
def test_fused_kernel_matches_eager_thompson_paths():
    from chipjev.surrogate import grid_kernel as kernels
    from chipjev.surrogate.gp import _matern52

    if not kernels.available(torch.device("cuda")):
        pytest.skip("no Triton")
    g = torch.Generator().manual_seed(0)
    device, m, d, D, S, n = torch.device("cuda"), 3, 6, 256, 5, 21
    space = _Grid([17] * d)
    omega = (torch.randn(m, d, D, generator=g) * 4).to(device)
    phase = (6.283 * torch.rand(m, 1, D, generator=g)).to(device)
    weights = torch.randn(S, m, D, generator=g).to(device)
    scale = torch.full((m, 1, 1), 0.05).to(device)
    train = torch.rand(n, d, generator=g).to(device)
    ls = (0.2 + torch.rand(m, d, generator=g)).to(device)
    os_ = (0.5 + torch.rand(m, generator=g)).to(device)
    update = torch.randn(m, n, S, generator=g).to(device)
    begin, count = 7_000_001, 3000
    part = space.chunk(begin, begin + count, device, torch.float32)
    phi = scale * torch.cos(part[None] @ omega + phase)
    ks = _matern52(train[None].expand(m, n, d), part[None].expand(m, *part.shape), ls, os_)
    eager = torch.einsum("smd,mnd->smn", weights, phi) + torch.einsum("mnN,mns->smN", ks, update)
    eager = eager.permute(0, 2, 1)
    for source, offset in ((space, begin), (part, 0)):
        fused = kernels.pathwise(
            source, offset, count, omega, phase, weights, scale, train, ls, os_, update
        )
        assert fused.shape == (S, count, m)
        assert (fused - eager).abs().max().item() < 1e-3


def test_pool_kernel_matches_the_eager_thompson_path():
    from chipjev.surrogate import pool_kernel

    device = torch.device("cuda") if torch.cuda.is_available() else None
    if device is None or not pool_kernel.available(device, 64):
        pytest.skip("CUDA with Triton not available")
    space = ClassSpace("opampN")
    rng = np.random.default_rng(0)
    x = space.features(space.random(rng, 200))
    y = rng.standard_normal((200, 3))
    y[rng.random(y.shape) < 0.1] = np.nan
    points = torch.as_tensor(space.features(space.random(rng, 5000)), device=device)
    paths = {}
    for wide in (True, False):
        gp = TopoGP(device, seed=3, wide=wide).fit(x, y, steps=3)
        captured = []
        gp.thompson(points, samples=5, score=lambda v, c=captured: c.append(v) or v[..., 0])
        paths[wide] = torch.cat(captured, 1)
    assert torch.allclose(paths[True], paths[False], rtol=1e-4, atol=1e-4)
