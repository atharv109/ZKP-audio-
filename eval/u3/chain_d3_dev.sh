#!/bin/sh
# D3 dev-subset scoring only (launched detached; resumes the existing cache).
set -e
cd ""
export EVAL_RAM_GATE_MB=800
python -u eval/u3/score_u3.py dev D3 > eval/u3/D3_dev2.log 2>&1
echo D3-DEV-DONE >> eval/u3/chain_all.log
