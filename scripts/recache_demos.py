"""Re-cache the curated demos through the full chain (incl. the new
parameter-diff stage), persisting to Spanner pipeline_runs so /demos and
/impact show the rich old→new parameter table. param_diff runs at full
depth; the obligation fan-out is capped (FAST_MODE) for cost/speed.

    source scripts/env.sh
    CURATOR_REAL_LLM=1 CURATOR_GROUNDING=spanner CURATOR_FAST_MODE=1 \
      .venv/bin/python scripts/recache_demos.py [demo-creditrisk|demo-capad|all]
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from app.fast_api_app import DEMOS, _FIXT, _RUNS, _RUNS_LOCK, launch_chain_run


def run_one(demo: dict) -> None:
    pdf_a = _FIXT / demo["doc_a"]
    pdf_b = _FIXT / demo["doc_b"]
    print(f"\n=== {demo['id']}: {pdf_a.name}  vs  {pdf_b.name} ===")
    run_id = launch_chain_run(
        pdf_a,
        pdf_b,
        namespace="capital-adequacy",
        amendment_id=demo["id"],
        resume=False,  # demo re-caching must run fresh to pick up code changes
    )
    print(f"run_id={run_id}  polling…")
    t0 = time.monotonic()
    while True:
        time.sleep(5)
        with _RUNS_LOCK:
            st = _RUNS.get(run_id, {})
            status = st.get("status")
            stats = st.get("stats")
        el = int(time.monotonic() - t0)
        print(f"  [{el:4d}s] status={status}")
        if status == "done":
            # The background daemon thread persists to Spanner AFTER flipping
            # status to "done". Wait for the row to actually land before we
            # let the process exit (else the daemon is killed mid-save).
            from app.observability.pipeline_store import load_pipeline_run

            for _ in range(24):
                if load_pipeline_run(run_id) is not None:
                    print(f"  DONE in {el}s + persisted — stats: {stats}")
                    return
                time.sleep(5)
            print(f"  DONE in {el}s but NOT persisted after 120s — stats: {stats}")
            return
        if status == "error":
            with _RUNS_LOCK:
                print("  ERROR:", _RUNS.get(run_id, {}).get("error"))
            return
        if el > 1500:
            print("  TIMEOUT (kept running in background)")
            return


def main() -> None:
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    targets = DEMOS if which == "all" else [d for d in DEMOS if d["id"] == which]
    if not targets:
        print(f"no demo matching {which!r}; valid: {[d['id'] for d in DEMOS]}")
        sys.exit(1)
    for d in targets:
        run_one(d)


if __name__ == "__main__":
    main()
