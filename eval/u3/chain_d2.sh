#!/bin/sh
# D2 post-dev chain + D1 clean + metrics; 1500 MB gate (observed D2 peak 1.05 GB)
set -e
cd ""
export EVAL_RAM_GATE_MB=1500
for m in clean eval a2 a3 u1c1 u1c2; do
  python -u eval/u3/score_u3.py "$m" D2 >> eval/u3/D2_chain.log 2>&1
done
python -u eval/u3/score_u3.py clean D1 >> eval/u3/D2_chain.log 2>&1
python -u eval/u3/u3_metrics.py D2 full >> eval/u3/D2_chain.log 2>&1
python -u eval/u3/u3_metrics.py D1 full >> eval/u3/D2_chain.log 2>&1
echo CHAIN-DONE >> eval/u3/D2_chain.log
