# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Curator root agent — regulatory-change-intelligence orchestrator.

Stage 1: builds the ADK agent graph (orchestrator + five sub-agents).
The LLM-driven path runs under ``adk run`` / ``agents-cli playground``
once GCP credentials are configured.

A deterministic offline path lives in :mod:`app.chain` — the same
graph executed against the stub functions of each sub-agent. The
offline path is what the Stage-1 eval set and the smoke test run.

Stage 2 replaces every sub-agent's stub with a real LLM tool/return,
wires Vertex AI RAG Engine for grounding, and exposes the orchestrator
over A2A for remote discovery.
"""

import os

from app.sub_agents import decompose, diff, judge, map_, qna

LLM_LOCATION = "global"
LOCATION = "us-central1"
LLM = "gemini-flash-latest"

ORCHESTRATOR_INSTRUCTION = """You are Curator — a regulatory-change-intelligence
orchestrator for Indian banks.

Inputs you receive:
  * An RBI amendment notification.
  * A pointer to the revised Master Direction it amends.
  * The bank's internal policies and SOPs.

Your job is to run the change-analysis chain in order:

  1. decompose_agent — Break each amended clause into atomic obligations.
                       One clause can yield several obligations with
                       different owners and timelines. Fan-out matters.
  2. map_agent       — Map each obligation to the bank's policy sections.
                       Label coverage (full/partial/missing/stale/
                       contradicts) and assign a confidence.
  3. diff_agent      — Draft concrete suggested edits for every
                       partial/missing/stale/contradicts match.
                       These are *proposals* — never autonomously applied.
  4. judge_agent     — Score impact and priority, list affected
                       departments, surface non-obvious downstream
                       effects (ICAAP, capital plan, disclosures,
                       training, board reporting).
  5. qna_agent       — Answer follow-up questions over the package
                       with citations.

Safety constraints (enterprise B2B):
  * You only *propose*. A human reviewer approves every change.
  * No external actions. No emails. No DB writes outside the session
    blackboard.
  * If you are uncertain, say so. Better to flag a missing coverage
    than to invent compliance.
"""


def _build_root_agent():  # type: ignore[no-untyped-def]
    """Build the ADK root agent. Imports vertexai lazily so the rest of
    the package — models, grounding, stubs, eval harness — can be
    imported without GCP credentials in scope.
    """
    import google
    import vertexai
    from google.adk.agents import Agent
    from google.adk.apps import App
    from google.adk.models import Gemini
    from google.genai import types

    credentials, project_id = google.auth.default()
    os.environ["GOOGLE_CLOUD_PROJECT"] = project_id
    os.environ["GOOGLE_CLOUD_LOCATION"] = LLM_LOCATION
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
    vertexai.init(project=project_id, location=LOCATION)

    sub_agents = [
        decompose.build_agent(),
        map_.build_agent(),
        diff.build_agent(),
        judge.build_agent(),
        qna.build_agent(),
    ]

    root = Agent(
        name="root_agent",
        model=Gemini(
            model=LLM,
            retry_options=types.HttpRetryOptions(attempts=3),
        ),
        instruction=ORCHESTRATOR_INSTRUCTION,
        description=(
            "Curator orchestrator — decompose → map → diff → judge → qna "
            "for RBI regulatory amendments."
        ),
        sub_agents=sub_agents,
    )
    return App(root_agent=root, name="app")


# Top-level export expected by ``adk run`` / agents-cli playground.
# Constructed lazily on first access so importing this module does not
# require GCP auth — the Stage-1 offline chain and the eval harness
# never trigger this path.
_app = None
_root_agent = None


def __getattr__(name: str):  # PEP 562 module-level lazy attr.
    global _app, _root_agent
    if name in {"app", "root_agent"}:
        if _app is None:
            _app = _build_root_agent()
            _root_agent = _app.root_agent
        return _app if name == "app" else _root_agent
    raise AttributeError(name)
