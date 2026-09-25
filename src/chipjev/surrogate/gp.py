"""Batched Gaussian-process surrogates for every measured constraint (PyTorch).

One exact GP (Matern-5/2, ARD) per output, fitted jointly as a batch. Thompson samples
use pathwise conditioning: a random-Fourier-feature prior draw corrected by the exact
posterior update. Device placement follows the arithmetic: the small n x n fits and
solves run on the CPU in float64, while every design-space-wide evaluation (millions of
candidates x features) runs on the accelerator (CUDA, else Apple MPS, else CPU).
Outputs are standardized; missing observations are masked out of each output's GP.
On CUDA, the design-space-wide pass over a sizing grid runs as one fused Triton kernel
(grid_kernel.py).

TopoGP applies the same GPs to explicit candidate pools of the joint topology-and-sizing
space (circuits/space.py). Its Thompson pass runs almost entirely on the accelerator: the
random-feature draws and the prior at the observed designs are computed there, only the
n x n solve of the pathwise correction stays on the CPU in FP64, and on CUDA the
candidate-wide evaluation is one fused Triton kernel for up to 64 features
(pool_kernel.pathwise_wide) instead of materializing the candidates x random-features and
candidates x observations matrices. The eager path (Apple MPS, CPU, or CUDA without the
kernel) evaluates the same draws.
"""

import math
import time

import numpy as np

from . import pool_kernel

__all__ = ["BatchedGP", "Points", "TopoGP", "device_info", "pick_device", "synchronize"]


def pick_device(preferred=None):
    import torch

    if preferred:
        return torch.device(preferred)
    if torch.cuda.is_available():
        return torch.device("cuda")
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def device_info(device):
    import torch

    if device.type == "cuda":
        return f"cuda ({torch.cuda.get_device_name(device)})"
    return device.type


def synchronize(device):
    import torch

    if device.type == "cuda":
        torch.cuda.synchronize(device)
    elif device.type == "mps":
        torch.mps.synchronize()


def _matern52(x1, x2, lengthscale, outputscale):
    """x1 [M,n,d], x2 [M,m,d], lengthscale [M,d], outputscale [M] -> [M,n,m]."""
    import torch

    a = x1 / lengthscale[:, None, :]
    b = x2 / lengthscale[:, None, :]
    d2 = (a * a).sum(-1)[:, :, None] + (b * b).sum(-1)[:, None, :] - 2 * a @ b.transpose(1, 2)
    d2 = d2.clamp_min(0)
    s5 = torch.sqrt(5.0 * d2 + 1e-12)
    return outputscale[:, None, None] * (1 + s5 + 5.0 / 3.0 * d2) * torch.exp(-s5)


class BatchedGP:
    """M independent exact GPs over the same inputs, each with its own observation mask."""

    def __init__(self, device=None, features=1024, seed=0, fit_threads=4, dtype=None, fused=None):
        import torch

        from . import grid_kernel

        self.device = pick_device(device)  # design-space-wide evaluation
        if dtype is None:
            dtype = torch.float32 if self.device.type != "cpu" else torch.float64
        self.dtype = getattr(torch, dtype) if isinstance(dtype, str) else dtype
        # The fused CUDA kernel (grid_kernel.py) is used whenever it is available.
        available = grid_kernel.available(self.device) and self.dtype == torch.float32
        self.fused = available if fused is None else bool(fused) and available
        self.features = features
        self.generator = torch.Generator(device="cpu").manual_seed(seed)
        self.fit_threads = fit_threads
        self.state = None
        self.fit_seconds = 0.0

    def fit(self, x, y, steps=60, lr=0.1):
        """x [n,d] in [0,1]; y [n,M] with NaN for missing values (CPU, float64)."""
        import torch

        start = time.perf_counter()
        threads = torch.get_num_threads()
        torch.set_num_threads(self.fit_threads)
        try:
            x = np.asarray(x, dtype=float)
            y = np.asarray(y, dtype=float)
            n, d = x.shape
            m = y.shape[1]
            mask = np.isfinite(y)
            mean = np.array(
                [y[mask[:, j], j].mean() if mask[:, j].any() else 0.0 for j in range(m)]
            )
            std = np.array(
                [y[mask[:, j], j].std() if mask[:, j].sum() > 1 else 1.0 for j in range(m)]
            )
            std = np.where(std > 1e-9, std, 1.0)
            z = np.where(mask, (np.nan_to_num(y) - mean) / std, 0.0)
            f64 = torch.float64
            X = torch.as_tensor(x, dtype=f64)[None].expand(m, n, d)
            Z = torch.as_tensor(z.T, dtype=f64)
            W = torch.as_tensor(mask.T.astype(float), dtype=f64)
            if self.state is not None and tuple(self.state["raw"].shape) == (m, d + 2):
                raw = self.state["raw"].clone()
            else:
                raw = torch.zeros(m, d + 2, dtype=f64)
                raw[:, :d] = math.log(0.6)
                raw[:, d + 1] = math.log(1e-2)
            raw.requires_grad_(True)
            optimizer = torch.optim.Adam([raw], lr=lr)
            eye = torch.eye(n, dtype=f64)
            for _ in range(steps):
                optimizer.zero_grad()
                loss = self._nll(raw, X, Z, W, eye, d).sum()
                loss.backward()
                optimizer.step()
                with torch.no_grad():
                    raw[:, :d].clamp_(math.log(0.05), math.log(20.0))
                    raw[:, d].clamp_(math.log(0.05), math.log(20.0))
                    raw[:, d + 1].clamp_(math.log(1e-4), math.log(0.5))
            raw = raw.detach()
            lengthscale, outputscale, noise = self._unpack(raw, d)
            L, alpha = self._factor(X, Z, W, lengthscale, outputscale, noise, eye)
        finally:
            torch.set_num_threads(threads)
        self.state = {
            "raw": raw,
            "x": torch.as_tensor(x, dtype=f64),
            "L": L,
            "alpha": alpha,
            "Z": Z,
            "W": W,
            "mean": mean,
            "std": std,
            "lengthscale": lengthscale,
            "outputscale": outputscale,
            "noise": noise,
        }
        self.fit_seconds = time.perf_counter() - start
        return self

    @staticmethod
    def _unpack(raw, d):
        import torch

        return torch.exp(raw[:, :d]), torch.exp(raw[:, d]), torch.exp(raw[:, d + 1])

    @staticmethod
    def _factor(X, Z, W, lengthscale, outputscale, noise, eye):
        import torch

        K = _matern52(X, X, lengthscale, outputscale)
        # Missing observations receive enormous noise, removing them from that output.
        diag = noise[:, None] + (1 - W) * 1e6
        L = torch.linalg.cholesky(K + torch.diag_embed(diag) + 1e-8 * eye)
        alpha = torch.cholesky_solve((Z * W)[..., None], L)[..., 0]
        return L, alpha

    def _nll(self, raw, X, Z, W, eye, d):
        import torch

        lengthscale, outputscale, noise = self._unpack(raw, d)
        L, alpha = self._factor(X, Z, W, lengthscale, outputscale, noise, eye)
        count = W.sum(-1).clamp_min(1)
        logdet = (2 * torch.log(torch.diagonal(L, dim1=-2, dim2=-1)) * W).sum(-1)
        nll = 0.5 * ((Z * W) * alpha).sum(-1) + 0.5 * logdet
        # Weak log-normal priors keep hyperparameters physically plausible.
        prior = 0.5 * ((torch.log(lengthscale) - math.log(0.6)) ** 2).sum(-1)
        prior = prior + 0.25 * torch.log(outputscale) ** 2
        return (nll + prior) / count

    def _on_device(self, *tensors):
        return [t.to(self.device, self.dtype) for t in tensors]

    def predict(self, xc, chunk=65536):
        """Posterior latent mean/std in original units: arrays [N,M]."""
        import torch

        s = self.state
        m = s["L"].shape[0]
        x, ls, os_, alpha, L = self._on_device(
            s["x"], s["lengthscale"], s["outputscale"], s["alpha"], s["L"]
        )
        means, stds = [], []
        for begin in range(0, len(xc), chunk):
            part = torch.as_tensor(xc[begin : begin + chunk], dtype=self.dtype, device=self.device)
            Ks = _matern52(x[None].expand(m, *x.shape), part[None].expand(m, *part.shape), ls, os_)
            mu = (Ks * alpha[..., None]).sum(1)
            v = torch.linalg.solve_triangular(L, Ks, upper=False)
            var = (os_[:, None] - (v * v).sum(1)).clamp_min(1e-12)
            means.append(mu.T.cpu().numpy())
            stds.append(var.sqrt().T.cpu().numpy())
        return np.concatenate(means) * s["std"] + s["mean"], np.concatenate(stds) * s["std"]

    def thompson(self, xc, samples, score, exclude=None, top=None, chunk=None):
        """Pathwise Thompson samples scored on the device; returns (indices [S,k], scores [S,k]).

        ``score(values)`` maps a tensor [S,N,M] in original units to [S,N] (higher is
        better). Excluded candidates receive -inf. Only each sample's top-k survive.
        """
        import torch

        from . import grid_kernel

        s = self.state
        m, n, d = s["L"].shape[0], s["x"].shape[0], s["x"].shape[1]
        D, g = self.features, self.generator
        top = top or samples
        f64 = torch.float64
        # Matern-5/2 spectral density: multivariate Student-t, 5 degrees of freedom; the
        # chi-square(5) draw uses the seeded generator (five squared standard normals).
        normal = torch.randn(m, d, D, generator=g, dtype=f64)
        chi = (torch.randn(m, 1, D, 5, generator=g, dtype=f64) ** 2).sum(-1)
        omega = normal / torch.sqrt(chi / 5.0) / s["lengthscale"][:, :, None]
        phase = 2 * math.pi * torch.rand(m, 1, D, generator=g, dtype=f64)
        weights = torch.randn(samples, m, D, generator=g, dtype=f64)
        scale = torch.sqrt(2.0 * s["outputscale"] / D)[:, None, None]
        noise = torch.randn(samples, m, n, generator=g, dtype=f64)

        def prior(points, omega, phase, weights, scale):  # [N,d] -> [S,M,N]
            phi = scale * torch.cos(points[None] @ omega + phase)
            return torch.einsum("smd,mnd->smn", weights, phi)

        # n-sized pathwise correction in float64 on the CPU.
        residual = s["Z"][None] - prior(s["x"], omega, phase, weights, scale)
        residual = (residual - noise * torch.sqrt(s["noise"])[None, :, None]) * s["W"][None]
        update = torch.cholesky_solve(residual.permute(1, 2, 0), s["L"])  # [M,n,S]
        # Design-space-wide evaluation on the accelerator.
        x, ls, os_, update, omega, phase, weights, scale = self._on_device(
            s["x"], s["lengthscale"], s["outputscale"], update, omega, phase, weights, scale
        )
        mean = torch.as_tensor(s["mean"], dtype=self.dtype, device=self.device)
        std = torch.as_tensor(s["std"], dtype=self.dtype, device=self.device)
        best_scores, best_index = [], []
        grid = hasattr(xc, "chunk")
        count = xc.count if grid else len(xc)
        chunk = chunk or (1 << 21 if self.fused else 65536)
        if exclude is not None and not isinstance(exclude, torch.Tensor):
            exclude = torch.as_tensor(exclude, device=self.device)
        for begin in range(0, count, chunk):
            end = min(begin + chunk, count)
            if self.fused:
                # Grid indices are decoded inside the kernel; explicit points are copied.
                if grid:
                    source, offset = xc.space, begin
                else:
                    source = torch.as_tensor(xc[begin:end], dtype=self.dtype, device=self.device)
                    offset = 0
                path = grid_kernel.pathwise(
                    source, offset, end - begin, omega, phase, weights, scale, x, ls, os_, update
                )
                values = path * std + mean  # [S,N,M]
            else:
                if grid:
                    part = xc.chunk(begin, end, self.device, self.dtype)
                else:
                    part = torch.as_tensor(xc[begin:end], dtype=self.dtype, device=self.device)
                Ks = _matern52(x[None].expand(m, n, d), part[None].expand(m, *part.shape), ls, os_)
                path = prior(part, omega, phase, weights, scale) + torch.einsum(
                    "mnN,mns->smN", Ks, update
                )
                values = path.permute(0, 2, 1) * std + mean  # [S,N,M]
            value = score(values)
            if exclude is not None:
                value = value.masked_fill(exclude[begin:end][None], float("-inf"))
            k = min(top, value.shape[1])
            v, i = value.topk(k, dim=1)
            best_scores.append(v)
            best_index.append(i + begin)
        scores = torch.cat(best_scores, 1)
        index = torch.cat(best_index, 1)
        v, j = scores.topk(min(top, scores.shape[1]), dim=1)
        return index.gather(1, j).cpu().numpy(), v.cpu().numpy()


class Points:
    """Explicit candidate points for BatchedGP.thompson (a bare tensor would be taken for a
    grid, because tensors have a ``chunk`` method)."""

    def __init__(self, tensor):
        self.tensor = tensor

    def __len__(self):
        return self.tensor.shape[0]

    def __getitem__(self, index):
        return self.tensor[index]


class TopoGP(BatchedGP):
    def __init__(self, device=None, features=1024, seed=0, wide=None, **kwargs):
        import torch

        super().__init__(device, features=features, seed=seed, fused=False, **kwargs)
        ok = pool_kernel.available(self.device, pool_kernel.MAX_FEATURES) and self.dtype == torch.float32
        self.wide = ok if wide is None else bool(wide) and ok
        self.device_generator = torch.Generator(device=self.device).manual_seed(seed)
        self._cache = None

    def fit(self, x, y, steps=60, lr=0.1):
        import torch

        super().fit(x, y, steps=steps, lr=lr)
        s = self.state
        self._cache = self._on_device(
            s["x"],
            s["lengthscale"],
            s["outputscale"],
            s["alpha"],
            s["Z"],
            s["W"],
            torch.sqrt(s["noise"]),
            torch.as_tensor(s["mean"]),
            torch.as_tensor(s["std"]),
        )
        return self

    def predict_mean(self, points):
        """Posterior latent mean [N, M] (original units) of candidates on the device."""
        import torch

        x, ls, os_, alpha, *_, mean, std = self._cache
        m = ls.shape[0]
        points = torch.as_tensor(points, dtype=self.dtype, device=self.device)
        k = _matern52(x[None].expand(m, *x.shape), points[None].expand(m, *points.shape), ls, os_)
        return (k * alpha[..., None]).sum(1).T * std + mean

    def draw(self, samples):
        """Random-feature prior draws and the exact pathwise correction for `samples`
        posterior samples: (omega [M,d,D], phase [M,1,D], weights [S,M,D], scale [M,1,1],
        update [M,n,S]), on the device."""
        import torch

        x, ls, os_, _, z, w, noise_std, *_ = self._cache
        m, n, d = z.shape[0], x.shape[0], x.shape[1]
        D, g = self.features, self.device_generator
        options = {"generator": g, "device": self.device, "dtype": self.dtype}
        # Matern-5/2 spectral density: multivariate Student-t with 5 degrees of freedom.
        normal = torch.randn(m, d, D, **options)
        chi = (torch.randn(m, 1, D, 5, **options) ** 2).sum(-1)
        omega = normal / torch.sqrt(chi / 5.0) / ls[:, :, None]
        phase = 2 * math.pi * torch.rand(m, 1, D, **options)
        weights = torch.randn(samples, m, D, **options)
        scale = torch.sqrt(2.0 * os_ / D)[:, None, None]
        noise = torch.randn(samples, m, n, **options)
        phi = scale * torch.cos(x[None] @ omega + phase)  # prior features at the data
        residual = z[None] - torch.einsum("smd,mnd->smn", weights, phi)
        residual = (residual - noise * noise_std[None, :, None]) * w[None]
        update = torch.cholesky_solve(
            residual.permute(1, 2, 0).to("cpu", torch.float64), self.state["L"]
        )
        return omega, phase, weights, scale, update.to(self.device, self.dtype)

    def thompson(self, xc, samples, score, exclude=None, top=None, chunk=None):
        """Pathwise Thompson samples over explicit points ([N, d] tensor or Points), scored
        on the device; returns (indices [S,k], scores [S,k]) like BatchedGP.thompson.
        ``score(values)`` maps [S,N,M] in original units to [S,N] (higher is better)."""
        import torch

        grid = hasattr(xc, "chunk") and not isinstance(xc, torch.Tensor)
        if grid:
            return super().thompson(xc, samples, score, exclude=exclude, top=top, chunk=chunk)
        points = xc.tensor if isinstance(xc, Points) else xc
        points = torch.as_tensor(points, dtype=self.dtype, device=self.device)
        x, ls, os_, *_, mean, std = self._cache
        m, n, d = ls.shape[0], x.shape[0], x.shape[1]
        wide = self.wide and d <= pool_kernel.MAX_FEATURES
        top = top or samples
        omega, phase, weights, scale, update = self.draw(samples)
        if exclude is not None:
            exclude = torch.as_tensor(exclude, device=self.device)
        count = points.shape[0]
        chunk = chunk or (1 << 20 if wide else 1 << 15)
        best_scores, best_index = [], []
        for begin in range(0, count, chunk):
            end = min(begin + chunk, count)
            part = points[begin:end]
            if wide:
                path = pool_kernel.pathwise_wide(part, omega, phase, weights, scale, x, ls, os_, update)
            else:
                phi = scale * torch.cos(part[None] @ omega + phase)  # [M,N,D]
                k = _matern52(x[None].expand(m, n, d), part[None].expand(m, *part.shape), ls, os_)
                path = torch.einsum("smd,mNd->sNm", weights, phi) + torch.einsum(
                    "mnN,mns->sNm", k, update
                )
            value = score(path * std + mean)  # [S,N,M] -> [S,N]
            if exclude is not None:
                value = value.masked_fill(exclude[begin:end][None], float("-inf"))
            v, i = value.topk(min(top, value.shape[1]), dim=1)
            best_scores.append(v)
            best_index.append(i + begin)
        scores = torch.cat(best_scores, 1)
        index = torch.cat(best_index, 1)
        v, j = scores.topk(min(top, scores.shape[1]), dim=1)
        return index.gather(1, j).cpu().numpy(), v.cpu().numpy()
