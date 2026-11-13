#!/bin/sh
# U3 supervisor: self-healing parallel pipeline. Every scorer is idempotent
# (resumable cache keyed by path; a completed mode is a no-op rescan), so a
# crashed child is simply re-run by the loop. D3 and D2 dev run in parallel;
# the RAM gate inside score_u3.py throttles D2 to >=1500 MB free.
set -u
cd ""
export EVAL_RAM_GATE_MB=800
LOG=eval/u3/supervisor.log
C3='<HOME>/AppData/Local/Temp/u3work/u3_scores_D3_dev.json'
C2='<HOME>/AppData/Local/Temp/u3work/u3_scores_D2_dev.json'
cnt() { python -c "import json,os,sys;p=sys.argv[1];print(len(json.load(open(p))) if os.path.exists(p) else 0)" "$1" 2>/dev/null || echo 0; }

echo "supervisor start $(date)" >> "$LOG"

run_d3_dev() {
  while [ "$(cnt "$C3")" != 4348 ]; do
    python -u eval/u3/score_u3.py dev D3 >> eval/u3/D3_dev2.log 2>&1 || sleep 10
  done
}
run_d2_dev() {
  while [ "$(cnt "$C2")" != 24844 ]; do
    EVAL_RAM_GATE_MB=1500 python -u eval/u3/score_u3.py dev D2 >> eval/u3/D2_dev4.log 2>&1 || sleep 10
  done
}

run_d3_dev & P3=$!
run_d2_dev & P2=$!
wait $P3 $P2
echo "dev scoring complete $(date)" >> "$LOG"

# post-dev chains: modes are idempotent, run each to completion
for m in clean a2 a3 u1c1 u1c2; do
  python -u eval/u3/score_u3.py "$m" D3 >> eval/u3/D3_chain.log 2>&1 || \
    python -u eval/u3/score_u3.py "$m" D3 >> eval/u3/D3_chain.log 2>&1
done
python -u eval/u3/u3_metrics.py D3 full >> eval/u3/D3_chain.log 2>&1
echo "D3 chain complete $(date)" >> "$LOG"

python -u eval/u3/score_u3.py clean D1 >> eval/u3/D2_chain.log 2>&1 || \
  python -u eval/u3/score_u3.py clean D1 >> eval/u3/D2_chain.log 2>&1
python -u eval/u3/score_u3.py eval D2 >> eval/u3/D2_chain.log 2>&1 || \
  python -u eval/u3/score_u3.py eval D2 >> eval/u3/D2_chain.log 2>&1
for m in a2 a3 u1c1 u1c2; do
  python -u eval/u3/score_u3.py "$m" D2 >> eval/u3/D2_chain.log 2>&1 || \
    python -u eval/u3/score_u3.py "$m" D2 >> eval/u3/D2_chain.log 2>&1
done
python -u eval/u3/u3_metrics.py D2 full >> eval/u3/D2_chain.log 2>&1
python -u eval/u3/u3_metrics.py D1 full >> eval/u3/D2_chain.log 2>&1
echo "D2 chain complete $(date)" >> "$LOG"
echo ALL-DONE >> "$LOG"
