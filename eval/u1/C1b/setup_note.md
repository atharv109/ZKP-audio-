# C1b setup note (rerun of C1, cleaner conditions)

Recorded 2026-11-10 ~21:50, user-confirmed pre-recording checklist:

- 1) Fan + HVAC + other noise sources OFF, room quiet: **YES**
- 2) Playback volume (system + player) set to ~70–80%: **YES**
- 3) Windows microphone "Audio enhancements" OFF + speaker effects OFF: **YES**
- 4) Laptop plugged into AC power: **YES**

Recording chain (matches C1): same laptop built-in speakers -> same built-in
mic ("Microphone Array (Intel Smart Sound Technology for Digital
Microphones)"), ffmpeg dshow. Deltas from C1: 48 kHz (C1 was 44.1 kHz),
recording starts BEFORE playback launch, full track played start-to-end
(both 2 s markers included), two full takes (C1b-1, C1b-2).

Assets reused unchanged: same 100 seed-44 clips, same playback track
(eval/u1/playback_48k.wav), same track_manifest.json, same segmentation
(segment3.py), scoring (score_u1.py), A8 (run_a8_e2e.py) scripts.

Original C1 data and RESULTS_U1.md C1 rows are untouched; C1b gets its own
eval/u1/C1b/ namespace.

## Retake (2026-11-10 ~22:45), user-approved

Root cause measured on takes 1-2: at 70-80% volume the mic chain suppresses
ALL 1 kHz tones (2 s markers + all 100 beeps) and the capture timeline
deviates non-affinely (local lag swings ~+-20%). Retake condition: fan off /
enhancements off / plugged in UNCHANGED (re-confirmed), playback volume
reduced to ~40% — the only volume at which C1's chain preserved the beeps
(12/13 stable). Retake-1 (and -2) will overwrite C1b_1.wav/C1b_2.wav paths?
NO — saved as C1b_1r/C1b_2r.wav; failed takes kept for the record.
