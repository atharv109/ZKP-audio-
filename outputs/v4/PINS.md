4e9c575c7e7c980df70cef63c41780d5222ce3f4186a7fab1de2623647949561 *outputs/v4/provenance_v4.r1cs
ac30200e52a3e159a436b3e7c7c711333b5c9a573d28da69948a06fe9ad51e21 *outputs/v4/provenance_v4_js/provenance_v4.wasm
560906bcbfa476e9da9e1d0872f097e43a93887cdce291b87d9ee20a0ece3fb8 *outputs/v4/circuit_v4.zkey
a89ef3c25a3c00fc4d35240b994d30b9c58b6d5068f8235e169e9ae319d8b023 *outputs/v4/verification_key_v4.json
bd0e7ae3c524a80e561c1cb614f6c5c76e3f6f1433d88a38959bc0c082268f33 *circuits/provenance_v4.circom
a7f2641e86e9f19019b3b2c6e4ef76f67e8c23a41c1628ecc5c08d2e9b988a06 *pot12_final.ptau
814331d088032bb4c3fa61cc014789eadeed464209dd094ab3a2dd6ffbdce27a *models/AASIST-L.pth

# weights (added 2026-11-12, demo-asset follow-up)
#   AASIST-L checkpoint, downloaded from the OFFICIAL clovaai/aasist repo
#   (https://github.com/clovaai/aasist — the pretrained models are hosted IN
#   the repo, per config/AASIST-L.conf "model_path": ./models/weights/AASIST-L.pth):
#   https://raw.githubusercontent.com/clovaai/aasist/main/models/weights/AASIST-L.pth
#   Fetch/verify with: python scripts/fetch_weights.py
#   The pin above is the sha of the file downloaded from that URL; it is also
#   byte-identical to the pre-existing local checkpoint, confirmed by sha
#   comparison at packaging time. Tests refuse to run the detector against a
#   file whose sha differs from this pin (they SKIP instead of failing):
#   see scripts/demo_assets.js assetsStatus().

# issuer pubkey pin (demo mode, 2026-11-12)
#   This anonymized artifact ships its OWN demo Ed25519 issuer keypair
#   (demo_keys/, generated 2026-11-12 — see demo_keys/DEMO_ONLY.md; the
#   upstream keypair is deliberately NOT included). The verifier therefore
#   pins the SHA-256 of the shipped demo public key while this artifact is
#   in demo mode:
a4ced10b91eecb2869ed118fc425bd5c67e1ab38973557a2f99834b51ee8edba *demo_keys/issuer_public.pem
#   (the upstream artifact pinned a different issuer public key,
#   38fefd713279b33499c6450afb88d79881f48398351b82dfb09387e508ddf645, kept
#   here only as a reference value that does NOT apply to this copy.)
