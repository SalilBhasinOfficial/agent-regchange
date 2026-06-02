"""Four-perspective decompose panel — the debate moment of the demo.

Each lens reads the same amended clause but with a stakeholder-specific
preamble, so the same fan-out is examined from four angles. The
Reconciler merges their four obligation lists into one deduplicated
final list, recording per-lens dissent in ``Obligation.missing_evidence``.

The four lenses are deliberately *human roles*, not regulatory artifacts:
they represent the four kinds of compliance reviewers who would
realistically read this amendment and notice different things. The
purpose is reasoning diversity, not classification:

  * banker_lens            — day-to-day banker / operations focus.
  * compliance_lens        — Chief Compliance Officer / RBI exposure focus.
  * auditor_lens           — internal auditor / evidence trail focus.
  * customer_protect_lens  — customer-protection / fair-treatment focus.

The lens prompts share the same DECOMPOSE_INSTRUCTION (so the output
schema and fan-out rules are identical) with a perspective preamble
prepended. Outputs land in distinct ``state`` keys so the Reconciler
can read all four.
"""

from __future__ import annotations

from app.models import Obligation
from app.sub_agents.decompose import DECOMPOSE_INSTRUCTION

LENS_NAMES = (
    "banker_lens",
    "compliance_lens",
    "auditor_lens",
    "customer_protect_lens",
)

LENS_STATE_KEYS = {
    "banker_lens": "banker_obligations",
    "compliance_lens": "compliance_obligations",
    "auditor_lens": "auditor_obligations",
    "customer_protect_lens": "customer_protect_obligations",
}

LENS_PREAMBLES: dict[str, str] = {
    "banker_lens": """You are a senior **banker** at an Indian commercial bank. You
read this amendment with the eye of someone responsible for day-to-day
operations: capital deployment, balance-sheet ratios, branch operations,
loan origination, and P&L impact. You notice obligations that change
*how the bank operates*. Tilt toward operational, capital, and pricing
obligations; tilt away from purely procedural/disclosure obligations
(other lenses will catch those).""",
    "compliance_lens": """You are the **Chief Compliance Officer** at an Indian
commercial bank. You read this amendment with the eye of someone whose
job is to keep the bank out of RBI penalty. You notice obligations
about regulatory exposure, audit trail, board reporting cadence,
RMC standing agenda, ICAAP recalibration, Pillar 3 disclosure templates,
and supervisory-review touchpoints. Tilt toward procedural, reporting,
and governance obligations; tilt toward downstream-effect obligations
that a junior reviewer would miss.""",
    "auditor_lens": """You are an **internal auditor** at an Indian commercial bank.
You read this amendment with the eye of someone who must later prove,
via documentation and evidence, that the bank complied. You notice
obligations that *require an evidence trail*: documentation,
record-keeping, internal control attestations, sign-offs, exception
logs, model validation, and the audit-committee touchpoints. Tilt
toward obligations that imply new audit artefacts or attestation
cadences; flag ambiguity in *who* must produce *what* evidence by
*when*.""",
    "customer_protect_lens": """You are a **customer-protection officer** at an
Indian commercial bank — the role responsible for fair treatment of
retail and small-business customers. You read this amendment with the
eye of someone who must ensure customer-facing impacts are surfaced
and that disclosure obligations to end-customers are met. You notice
obligations that change how products are priced, disclosed, sold, or
serviced to customers; mandatory KFS / disclosure-document updates;
grievance-redressal cadence changes; vulnerable-customer carve-outs.
Tilt toward obligations with customer-facing externalities; flag if
the amendment *appears* internal but ripples into customer disclosure.""",
}


def _lens_instruction(lens_name: str) -> str:
    """Compose a lens-specific instruction by prepending the perspective preamble."""
    if lens_name not in LENS_PREAMBLES:
        raise ValueError(f"unknown lens: {lens_name}")
    return (
        f"{LENS_PREAMBLES[lens_name]}\n\n"
        f"---\n\n"
        f"{DECOMPOSE_INSTRUCTION}\n\n"
        f"Important: stay in your perspective. If a clause has obligations\n"
        f"that fall outside your lens, you may still emit them (extraction\n"
        f"completeness matters), but set their confidence lower and add a\n"
        f"missing_evidence entry naming the lens you would have wanted to\n"
        f"consult (e.g. 'compliance_lens_review_needed').\n"
    )


def build_lens_agent(lens_name: str):  # type: ignore[no-untyped-def]
    """Construct a single lens ADK Agent. Lazy import keeps import-time GCP-free."""
    from google.adk.agents import Agent
    from google.adk.models import Gemini

    return Agent(
        name=lens_name,
        model=Gemini(model="gemini-flash-latest"),
        instruction=_lens_instruction(lens_name),
        description=(
            f"Decomposes amended clauses from the {lens_name.replace('_', ' ')} "
            f"perspective. One of four panel members in the debate-panel decompose."
        ),
        output_schema=list[Obligation],
        output_key=LENS_STATE_KEYS[lens_name],
    )


def build_all_lens_agents() -> list:
    """Construct all 4 lens agents. Used by the ParallelAgent panel and
    by the asyncio.gather-based path in ``real_decompose``."""
    return [build_lens_agent(name) for name in LENS_NAMES]
