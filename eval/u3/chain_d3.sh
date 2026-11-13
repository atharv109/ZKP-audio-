#!/bin/sh
# D3 (RawNet2 NII) post-dev chain + metrics; 800 MB gate (small CPU model).
# Run after the D3 dev-subset run completes.
set -e
cd ""
export EVAL_RAM_GATE_MB=800
for m in clean a2 a3 u1c1 u1c2; do
  python -u eval/u3/score_u3.py "$m" D3 >> eval/u3/D3_chain.log 2>&1
done
python -u eval/u3/u3_metrics.py D3 full >> eval/u3/D3_chain.log 2>&1
echo CHAIN-DONE >> eval/u3/D3_chain.log
