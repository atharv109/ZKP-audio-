# DEMO-ONLY issuer keypair — generated 2026-11-12

These two PEM files form an Ed25519 issuer keypair that was **generated fresh
on 2026-11-12** with Node's `crypto.generateKeyPairSync('ed25519')` solely so
this artifact's demo and test flows can run self-contained:

- `issuer_private.pem` — PKCS#8 PEM signing key (demo only)
- `issuer_public.pem`  — SPKI PEM verify key (demo only)

**Provenance guarantees:**

- Generated in situ at packaging time; **never copied from anywhere**,
  including the upstream authoring machine's original `zkp-demo-issuer-keys`
  keypair (which is intentionally NOT shipped with this artifact).
- No relation to any production key; the keys exist only so the demo
  issuer/verifier round-trip can execute.
- The verifier pin (`scripts/demo_assets.js -> issuerPubkeyPin()`, documented
  in `outputs/v4/PINS.md`) is set to the SHA-256 of the shipped
  `issuer_public.pem`:

  `a4ced10b91eecb2869ed118fc425bd5c67e1ab38973557a2f99834b51ee8edba`

**Do not use for anything real.** Anyone holding this artifact can sign
records with the shipped private key, so in this demo copy the "trusted
issuer" trust anchor is the demo key by construction. Real deployments must
generate their own keypair, keep the private key outside the repository, and
pin the public key's SHA-256 in the verifier.
