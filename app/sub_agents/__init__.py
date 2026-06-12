"""Sub-agents for the Curator regulatory-change-intelligence chain.

Each module here exposes:
  * ``agent``  — an ADK ``Agent`` instance with a real instruction prompt.
  * ``stub``   — a deterministic Python function that produces
    schema-valid output for the same task. Used by the offline smoke
    runner and the Stage-1 eval harness so the chain executes end-to-end
    without GCP credentials.

Stage 2 replaces the stubs with real LLM-driven tool calls.
"""

from app.sub_agents import decompose, diff, judge, map_, qna

__all__ = ["decompose", "map_", "diff", "judge", "qna"]
