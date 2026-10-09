"""Run the three #1663 quality campaigns back to back (4B MTP-on, 4B MTP-off, 14B).

``--supplement`` runs the post-review supplement job lists instead.
"""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
run = REPO / "docs/performance/_run"
extra = ["--supplement"] if "--supplement" in sys.argv else []
status = "campaign_q_supp.jsonl" if extra else "campaign_q.jsonl"
for model, out in (("4b-on", "q4b_on"), ("4b-off", "q4b_off"), ("14b", "q14b")):
    code = subprocess.run(
        [sys.executable, str(REPO / "scripts/run_phase1_campaign.py"), "--model", model,
         "--out-dir", str(run / out), "--status-file", str(run / status), *extra]
    ).returncode
    print(model, "exit", code, flush=True)
