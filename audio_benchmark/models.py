"""Pluggable model interface for the audio anti-spoofing benchmark.

Two backends share one contract:

    class ModelBackend:
        def score(self, audio_path: str) -> float: ...   # higher = more bonafide
        @property
        def name(self) -> str: ...

`score()` returns a single scalar where **higher = more likely bonafide**.
The decision threshold is applied by the caller (default 0.0).

Backends
--------
PlaceholderModel
    Deterministic, weight-free scorer over hand-crafted spectral features
    (spectral flatness / centroid / RMS). Exists ONLY to exercise the full
    inference -> CSV -> metrics pipeline without external weights or data.
    Its outputs are NOT AASIST outputs and are NOT comparable to the Minnah
    paper. See AUDIO_TRACK_REPORT.md.

AASISTModel
    Drop-in loader for the real clovaai/aasist model
    (https://github.com/clovaai/aasist). It activates ONLY when:
      1. the AASIST `Model` class is importable (pass --aasist-repo <clone>
         or pip-install the repo), and
      2. a pretrained weights file is supplied via --weights.
    Otherwise it raises a clear RuntimeError — there is NO silent fallback
    to the placeholder for the `aasist` backend. See README.md "Wiring real
    AASIST" for setup steps.
"""

from __future__ import annotations

import os
from typing import Any, Protocol


class ModelBackend(Protocol):
    name: str

    def score(self, audio_path: str) -> float: ...


# ---------------------------------------------------------------------------
# Placeholder backend
# ---------------------------------------------------------------------------


class PlaceholderModel:
    """Weight-free, deterministic spectral-feature scorer.

    Heuristic intuition: bona-fide human speech tends to be spectrally
    *structured* (low flatness, clear formant energy), while many naive
    synthesis/spoof artifacts are spectrally *flat* (noise-like). We turn
    that into a bonafide log-odds-style scalar. This is a toy heuristic,
    not a trained detector.
    """

    name = "placeholder"

    def __init__(self, sr: int = 16000) -> None:
        import librosa  # imported lazily so --help works without deps

        self.sr = sr
        self._librosa = librosa

    def score(self, audio_path: str) -> float:
        y, sr = self._librosa.load(audio_path, sr=self.sr, mono=True)
        if y.size == 0:
            return 0.0
        hop = 512
        flatness = self._librosa.feature.spectral_flatness(y=y, hop_length=hop)[0]
        centroid = self._librosa.feature.spectral_centroid(y=y, sr=sr, hop_length=hop)[0]
        rms = self._librosa.feature.rms(y=y, frame_length=hop)[0]

        mean_flat = float(flatness.mean())      # 0 (tonal) .. 1 (noise)
        mean_cent = float(centroid.mean())      # Hz
        mean_rms = float(rms.mean()) + 1e-8

        # higher = more bonafide. Tonal + energy-rich -> high score.
        cent_term = min(mean_cent / 4000.0, 1.0)
        s = (1.0 - mean_flat) * 5.0 + cent_term * 1.0 + (mean_rms * 2.0) - 3.0
        return float(s)


# ---------------------------------------------------------------------------
# Real AASIST backend (drop-in)
# ---------------------------------------------------------------------------


class AASISTModel:
    """Thin wrapper around the clovaai/aasist PyTorch model.

    Construction succeeds only when the real model + weights are available.
    On any missing piece it raises RuntimeError describing exactly what to
    install. There is NO silent fallback to the placeholder for the
    `aasist` backend — a failed load is a hard error so no one accidentally
    reports placeholder numbers as AASIST numbers.

    Parameters
    ----------
    weights_path : str
        Path to a pretrained AASIST checkpoint (.pt). Required.
    aasist_repo : str, optional
        Path to a clone of https://github.com/clovaai/aasist. Added to
        sys.path so `from models.aasist import Model` resolves. If omitted,
        we also try `from aasist.models.aasist import Model` (pip install).
    config_path : str, optional
        JSON file whose top-level object is the AASIST `model_cfg` dict
        (keys: filts, gat_dims, pool_ratios, norm). If omitted, a default
        AASIST-L config is used — but for real weights you should pass the
        config the checkpoint was trained with (a wrong config is silently
        masked by strict=False load_state_dict and yields garbage scores).
    bonafide_idx : int
        For 2-logit CE heads, the index of the bonafide class. AASIST's own
        data loader encodes `1 if label == "bonafide" else 0`, so the trained
        checkpoint has bonafide at index 1 (spoof at 0). score =
        logit[bonafide_idx] - logit[other] (higher = more bonafide).
    """

    name = "aasist"

    # Default = AASIST-L model_config (matches config/AASIST-L.conf in the repo
    # and the bundled models/weights/AASIST-L.pth). Model.__init__ consumes
    # filts, gat_dims, pool_ratios, temperatures, first_conv.
    _DEFAULT_CFG = {
        "architecture": "AASIST",
        "nb_samp": 64600,
        "first_conv": 128,
        "filts": [70, [1, 32], [32, 32], [32, 24], [24, 24]],
        "gat_dims": [24, 32],
        "pool_ratios": [0.4, 0.5, 0.7, 0.5],
        "temperatures": [2.0, 2.0, 100.0, 100.0],
    }

    def __init__(
        self,
        weights_path: str,
        sr: int = 16000,
        device: str = "cpu",
        aasist_repo: str | None = None,
        config_path: str | None = None,
        bonafide_idx: int = 1,
    ) -> None:
        import importlib.util
        import json
        import sys

        if not weights_path or not os.path.isfile(weights_path):
            raise RuntimeError(
                f"AASIST weights not found at: {weights_path!r}. "
                "Download AASIST-L weights from the clovaai/aasist release page "
                "and pass --weights <path>. See README.md."
            )

        # Resolve the Model class. Prefer loading models/AASIST.py directly by
        # file path — this avoids the `models` package-name collision with this
        # module's own models.py when run from audio_benchmark/. AASIST.py has
        # no relative/sibling imports, so a standalone file load is safe.
        Model = None
        import_errs: list[str] = []
        if aasist_repo:
            repo_abs = os.path.abspath(aasist_repo)
            models_dir = os.path.join(repo_abs, "models")
            aasist_file = ""
            if os.path.isdir(models_dir):
                for fn in os.listdir(models_dir):
                    if fn.lower() == "aasist.py":
                        aasist_file = os.path.join(models_dir, fn)
                        break
            if aasist_file and os.path.isfile(aasist_file):
                try:
                    spec = importlib.util.spec_from_file_location(
                        "aasist_repo_AASIST", aasist_file)
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)  # type: ignore[union-attr]
                    Model = getattr(mod, "Model", None)
                except Exception as e:  # pragma: no cover - optional pkg
                    import_errs.append(f"direct load {aasist_file!r}: {e!r}")
            if repo_abs not in sys.path:
                sys.path.insert(0, repo_abs)

        # Fallback: package-style imports (case-insensitive on Windows).
        if Model is None:
            for import_stmt in ("from aasist.models.aasist import Model",
                                "from aasist.models.AASIST import Model",
                                "from models.aasist import Model",
                                "from models.AASIST import Model"):
                try:
                    ns: dict[str, Any] = {}
                    exec(import_stmt, ns)  # noqa: S102
                    Model = ns["Model"]
                    break
                except Exception as e:  # pragma: no cover - optional pkg
                    import_errs.append(f"{import_stmt!r}: {e!r}")

        if Model is None:
            raise RuntimeError(
                "Could not import the AASIST Model class. Pass "
                "--aasist-repo <path to a clone of clovaai/aasist> (or install "
                "it as a package). Tried:\n  - " + "\n  - ".join(import_errs)
            )

        import torch

        cfg = self._DEFAULT_CFG
        if config_path:
            if not os.path.isfile(config_path):
                raise RuntimeError(f"AASIST config not found at: {config_path!r}")
            with open(config_path, encoding="utf-8") as fh:
                cfg = json.load(fh)

        # The repo's config/AASIST-L.conf is a full JSON config whose
        # architecture params live under a "model_config" key. Accept either
        # that full config or a bare model_cfg dict.
        if isinstance(cfg, dict) and "model_config" in cfg:
            cfg = cfg["model_config"]

        self.sr = sr
        self.device = device
        self._torch = torch
        self.bonafide_idx = bonafide_idx
        self.nb_samp = int(cfg.get("nb_samp", 0)) if isinstance(cfg, dict) else 0

        # Model() may take (cfg) or (cfg, device) depending on repo version.
        try:
            self.net = Model(cfg).to(device).eval()
        except TypeError:
            self.net = Model(cfg, device).to(device).eval()

        # weights_only=True avoids unpickling arbitrary objects (RCE risk).
        # Fall back to False only for older checkpoints that store non-tensor
        # objects, and warn loudly so the user knows the trust assumption.
        try:
            state = torch.load(weights_path, map_location=device, weights_only=True)
        except TypeError:
            state = torch.load(weights_path, map_location=device)
        except Exception as e:
            print(
                f"[AASISTModel] weights_only=True load failed ({e!r}); "
                "retrying with weights_only=False. Only do this with a "
                "checkpoint from a trusted source.",
                file=sys.stderr,
            )
            state = torch.load(weights_path, map_location=device, weights_only=False)

        if isinstance(state, dict) and "model" in state and isinstance(state["model"], dict):
            state = state["model"]
        missing, unexpected = self.net.load_state_dict(state, strict=False)
        if missing:
            print(f"[AASISTModel] load_state_dict missing keys: "
                  f"{len(missing)} (e.g. {missing[:3]})", file=sys.stderr)
        if unexpected:
            print(f"[AASISTModel] load_state_dict unexpected keys: "
                  f"{len(unexpected)} (e.g. {unexpected[:3]})", file=sys.stderr)

    def score(self, audio_path: str) -> float:
        import librosa
        import numpy as np

        y, _ = librosa.load(audio_path, sr=self.sr, mono=True)
        # AASIST's graph positional embedding (pos_S) assumes a fixed input
        # length (nb_samp, 64600 for AASIST-L) so the spectral axis comes out
        # as 23 nodes. Match the repo's data_utils.pad exactly: truncate if
        # long, else TILE-REPEAT the clip (np.tile) to fill nb_samp. The repo
        # does NOT zero-pad — repeating real speech stays closer to the
        # training distribution than trailing silence, and using a different
        # padding strategy here would shift the model's scores.
        if self.nb_samp and y.size != self.nb_samp:
            if y.size >= self.nb_samp:
                y = y[: self.nb_samp]
            else:
                num_repeats = self.nb_samp // y.size + 1
                y = np.tile(y, num_repeats)[: self.nb_samp]
        x = self._torch.from_numpy(y).float().unsqueeze(0).to(self.device)
        with self._torch.no_grad():
            out = self.net(x)
            # AASIST's Model.forward returns (last_hidden, output) — a tuple
            # whose FIRST element is the ~160-dim embedding and whose LAST
            # element is the 2-logit classification head. Take the LAST element
            # (the logits); indexing the embedding by bonafide_idx yields
            # noise that only weakly correlates with class.
            if isinstance(out, (tuple, list)):
                out = out[-1]
        o = out.reshape(-1)
        if o.numel() >= 2:
            # Match the repo's evaluation score exactly (main.py
            # produce_evaluation_file): the raw bonafide logit
            # (batch_out[:, bonafide_idx]), higher = more bonafide. Do NOT
            # subtract the spoof logit — that re-ranks samples and changes
            # the EER, since EER is invariant only to monotonic score
            # transforms and logit[bon]-logit[spoof] is not monotonic in
            # logit[bon].
            return float(o[self.bonafide_idx].item())
        return float(o[0].item())


# ---------------------------------------------------------------------------
# Real ECAPA-TDNN backend (interface slot — NOT a Minnah reproduction)
# ---------------------------------------------------------------------------


class RawNet2NIIModel:
    """Delegating wrapper: D3 = NII comparative-study RawNet2 (LA, CCE).
    Real implementation lives in eval/u3/rawnet2_nii.py (U3-only harness)."""

    name = "rawnet2_nii"

    def __init__(self, weights_path=None, device="cpu", config_path=None,
                 aasist_repo=None, ecapa_repo=None, **_kw):
        import sys
        u3dir = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "eval", "u3")
        if u3dir not in sys.path:
            sys.path.insert(0, u3dir)
        from rawnet2_nii import RawNet2Model
        self._impl = RawNet2Model()

    def score(self, audio_path: str) -> float:
        return self._impl.score(audio_path)


class ECAPAModel:
    """ECAPA-TDNN anti-spoofing proxy backend (loads a trained proxy checkpoint).

    This backend loads a checkpoint produced by ``ecapa_proxy.train`` — an
    ECAPA-TDNN proxy *based on* the Minnah paper architecture, NOT an exact
    Minnah reproduction (the exact Minnah code/weights/seed are unavailable).
    The checkpoint is self-describing: it embeds the model config and the
    trained AAM-Softmax class weights, so only ``--weights <checkpoint.pt>`` is
    required.

    Inference correctness (the whole point of this proxy): the model uses the
    TRAINED AAM-Softmax weights saved in the checkpoint — the embedding and
    the learned class weights are L2-normalized and margin-free cosine logits are
    computed. There is NO untrained ``nn.Linear`` classifier and NO silent
    fallback to the placeholder.

    Score = ``bonafide_logit - spoof_logit`` (class 0 = bonafide), higher =
    more bonafide — matching ``evaluate.py`` (bonafide if score >= 0.0).

    On any missing asset (checkpoint file, or the ``ecapa_proxy`` package) it
    raises ``RuntimeError`` describing exactly what to provide.

    Parameters
    ----------
    weights_path : str
        Path to a trained ECAPA-TDNN proxy checkpoint (.pt) from
        ``ecapa_proxy.train`` (e.g. ``ecapa_proxy/checkpoints/<name>_best_dev_eer.pt``).
        Required.
    ecapa_repo, config_path : optional, accepted for CLI compatibility.
        The checkpoint embeds its config, so these are not needed and are
        ignored (a one-line note is printed if either is supplied).
    """

    name = "ecapa"

    def __init__(
        self,
        weights_path: str,
        sr: int = 16000,
        device: str = "cpu",
        ecapa_repo: str | None = None,
        config_path: str | None = None,
        bonafide_idx: int = 1,
    ) -> None:
        import sys

        # audio_benchmark/ is the parent of the ecapa_proxy package.
        ab_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if ab_dir not in sys.path:
            sys.path.insert(0, ab_dir)

        if not weights_path or not os.path.isfile(weights_path):
            raise RuntimeError(
                f"ECAPA proxy checkpoint not found at: {weights_path!r}. Train one "
                "with `python -m ecapa_proxy.train ...` and pass --weights "
                "<ecapa_proxy/checkpoints/<name>_best_dev_eer.pt>. "
                "No silent fallback: the placeholder is NOT used."
            )

        try:
            from ecapa_proxy.checkpoint import build_model_from_checkpoint, load_checkpoint
            from ecapa_proxy.dataset import _feature_kwargs
        except Exception as e:
            raise RuntimeError(
                f"Could not import the ecapa_proxy package (looked under {ab_dir!r}): "
                f"{e!r}. The ecapa backend requires the trained proxy package. "
                "No silent fallback: the placeholder is NOT used."
            ) from e

        if ecapa_repo or config_path:
            print("[ECAPAModel] note: --ecapa-repo/--config ignored — the proxy "
                  "checkpoint is self-describing (embeds its config).", file=sys.stderr)

        # Load once to get the config (for feature kwargs), then build the model.
        ckpt = load_checkpoint(weights_path, device)
        config = ckpt.get("config", {}) if isinstance(ckpt, dict) else {}
        built = build_model_from_checkpoint(weights_path, device)
        # build_model_from_checkpoint may return a bare model or a (model, ckpt)
        # tuple depending on version; accept both.
        self.net = built[0] if isinstance(built, tuple) and len(built) == 2 else built
        self.net.eval()

        self.sr = sr
        self.device = device
        self.feature_kwargs = _feature_kwargs(config)

    def score(self, audio_path: str) -> float:
        import numpy as np
        import torch

        from ecapa_proxy.features import extract_logmel

        mel = extract_logmel(audio_path, **self.feature_kwargs)  # (n_mels, T) np float32
        x = torch.from_numpy(np.ascontiguousarray(mel)).float().unsqueeze(0).unsqueeze(0)
        x = x.to(self.device)  # (1, 1, n_mels, T)
        with torch.no_grad():
            return float(self.net.score(x))  # logit0-logit1, higher = more bonafide


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_model(
    backend: str,
    weights: str | None = None,
    device: str = "cpu",
    aasist_repo: str | None = None,
    config_path: str | None = None,
    ecapa_repo: str | None = None,
) -> ModelBackend:
    """Return a model backend by name.

    backend="aasist" requires --weights and the aasist model code; any
    failure raises (no silent fallback). backend="ecapa" requires only
    --weights (a self-describing proxy checkpoint that embeds its config and
    trained AAM weights); --config/--ecapa-repo are accepted for CLI
    compatibility but ignored. Any failure raises (no silent fallback).
    backend="placeholder" never requires external assets.
    """
    if backend == "placeholder":
        return PlaceholderModel()
    if backend == "aasist":
        return AASISTModel(
            weights_path=weights or "",
            device=device,
            aasist_repo=aasist_repo,
            config_path=config_path,
        )
    if backend == "ecapa":
        return ECAPAModel(
            weights_path=weights or "",
            device=device,
            ecapa_repo=ecapa_repo,
            config_path=config_path,
        )
    if backend == "rawnet2_nii":
        return RawNet2NIIModel(
            weights_path=weights,
            device=device,
            config_path=config_path,
        )
    raise ValueError(
        f"unknown backend: {backend!r} "
        "(expected 'placeholder', 'aasist', 'ecapa', or 'rawnet2_nii')"
    )