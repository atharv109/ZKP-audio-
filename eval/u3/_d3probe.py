import sys, time, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rawnet2_nii import RawNet2Model
m = RawNet2Model()
paths = [
 r"eval\u1\C1_segments\000_spoof_LA_E_1002769.wav",
 r"ASVspoof2019_LA_dev\flac\LA_D_1047731.flac",
]
for p in paths:
    t = time.time(); s = m.score(p); print(f"{os.path.basename(p)}: {s:+.3f} in {time.time()-t:.2f}s", flush=True)
