#!/usr/bin/env python
"""eval/u3/rawnet2_nii.py -- D3 = RawNet2 (NII comparative-study checkpoint).

Weights: <HOME>\\external\\nii_asvspoof\\rawnet2\\01\\__pretrained\\
trained_network.pt (NII "03-asvspoof-mega" pretrained release, Zenodo record
8337778; RawNet2 trained on ASVspoof2019 LA, CCE loss).
Code: sandbox/block_rawnet (nii-yamagishilab/project-NN-Pytorch-scripts),
      fetched to <HOME>\\external\\nii_asvspoof\\code\\.

Input policy (model_01.py forward, INFER branch): non-overlapping segments of
m_seg_len=64,600 samples taken from the START of the utterance
(x[:, s:e] with s = idx*seg_len); per-segment inference logits are averaged
across segments; score = logit[class 1] (bonafide); higher = bonafide.
Same 16 kHz mono resampling as D1/D2.
"""
import os
import sys

import numpy as np

NII_CODE = r"<HOME>\external\nii_asvspoof\code"
NII_CKPT = (r"<HOME>\external\nii_asvspoof\rawnet2\01"
            r"\__pretrained\trained_network.pt")
SEG_LEN = 64600


class RawNet2Model:
    name = "rawnet2_nii"

    def __init__(self, nb_samp=SEG_LEN):
        for p in (NII_CODE, os.path.join(NII_CODE, "sandbox"),
                  os.path.join(NII_CODE, "core_scripts")):
            if p not in sys.path:
                sys.path.insert(0, p)
        import torch
        import types
        if "torchaudio" not in sys.modules:
            try:
                import torchaudio  # noqa: F401
            except Exception:
                stub = types.ModuleType("torchaudio")
                stub.__version__ = "stub (unused by block_rawnet)"
                sys.modules["torchaudio"] = stub
        import sandbox.block_rawnet as nii_rawnet
        self._torch = torch
        self.nb_samp = nb_samp
        self.dev = "cpu"
        ck = torch.load(NII_CKPT, map_location=self.dev, weights_only=True)
        in_dim = 1
        self.net = nii_rawnet.RawNet(20, 1025, in_dim, 16000,
                                     128, 512, 256, 3, 64, 2)
        sd = {k[len("m_rawnet."):]: v for k, v in ck.items() if k.startswith("m_rawnet.")}
        self.net.load_state_dict(sd, strict=True)
        self.net.eval()

    def score(self, audio_path: str) -> float:
        import librosa
        torch = self._torch
        y, _ = librosa.load(audio_path, sr=16000, mono=True)
        x = torch.from_numpy(y).float().view(1, -1, 1)
        with torch.no_grad():
            T = x.shape[1]
            if T < self.nb_samp:
                scores = [self.net.inference(x)]
            else:
                scores = []
                for idx in range(T // self.nb_samp):
                    st = idx * self.nb_samp
                    scores.append(self.net.inference(x[:, st: st + self.nb_samp]))
        sc = torch.stack(scores, dim=2).mean(dim=-1)
        return float(sc[0, -1].item())


if __name__ == "__main__":
    m = RawNet2Model()
    print("loaded strict OK; smoke scores:")
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import json
    man = json.load(open(os.path.join(base, "eval", "u1", "track_manifest.json")))
    print("  clean bona:", round(m.score(man["clips"][1]["src"]), 3))
    print("  C1 laundered spoof:", round(
        m.score(os.path.join(base, "eval", "u1", "C1_segments",
                             "000_spoof_LA_E_1002769.wav")), 3))
