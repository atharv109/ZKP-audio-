# C1 setup note (laptop speaker -> laptop built-in mic)

User-provided (Nov 6 ~00:37 capture): quiet bedroom; laptop speakers + laptop
built-in microphone; system volume ~40%.

Devices (from the ffmpeg dshow device log):
- Playback: laptop built-in speakers (default output device).
- Capture: "Microphone Array (Intel Smart Sound Technology for Digital
  Microphones)" — the only audio input device listed.
- Recording: ffmpeg dshow, 44.1 kHz mono 16-bit PCM, fixed 589.98 s per take.
- Playback file: eval/u1/playback_48k.wav.

Measured on the captures (not user-known):
- Mic signal dominated by 240 Hz fan hum; playback level at the mic low
  (peak ~0.26 of full scale in the 1 kHz band; speech-band share 0.6-0.9 in
  clip regions).
- Take 2 is a silent-room mis-record (no playback signal at all).
- Both takes identical length (fixed-duration record); take 1 is a
  head-trimmed replay (no 2 s markers; playback entered ~2.5 s into track).

C2 note (2026-11-09): phone voice memo ~1 m, AAC 48 kHz mono, 555.93 s,
decoded to eval/u1/raw/c2_phone_16k.wav; playback launched from this session
start-to-end (ffplay played the whole track; markers included in this take).
