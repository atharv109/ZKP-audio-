#!/bin/sh
# Master U3 pipeline: wait for the running D3 dev task, then everything else SERIALLY.
# Serial (not parallel) so the RAM gates of both detectors can never collide.
set -e
cd ""
LOG=eval/u3/chain_all.log
echo "chain_all start $(date)" >> "$LOG"

# 1. wait for D3 dev cache to reach its full dev-subset size (4,348)
until [ "$(python -c "import json,os;p='<HOME>/AppData/Local/Temp/u3work/u3_scores_D3_dev.json';print(len(json.load(open(p))) if os.path.exists(p) else 0)" 2>/dev/null)" = "4348" ]; do
  sleep 60
done
echo "D3 dev complete $(date)" >> "$LOG"

# 2. D3 post-dev experiments + D3 metrics
sh eval/u3/chain_d3.sh
echo "D3 chain complete $(date)" >> "$LOG"

# 3. D2 full dev scoring
EVAL_RAM_GATE_MB=1500 python -u eval/u3/score_u3.py dev D2 >> eval/u3/D2_dev4.log 2>&1
echo "D2 dev complete $(date)" >> "$LOG"

# 4. D2 post-dev chain + D1 clean + D1/D2 metrics
sh eval/u3/chain_d2.sh
echo "D2 chain complete $(date)" >> "$LOG"
echo ALL-DONE >> "$LOG"
