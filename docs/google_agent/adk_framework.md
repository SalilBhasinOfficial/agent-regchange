# Google Agent Development Kit (ADK) — Framework Guide

The **Agent Development Kit (ADK)** is Google's modular, developer-friendly framework for constructing intelligent agents. It provides standardized abstractions to bridge local code compilation with Vertex AI's managed production runtimes.

---

## 1. Core Abstractions

An ADK agent contains three fundamental architectural pillars:

```
  ┌──────────────────────────────────────────────────────────┐
  │                        1. AGENT                          │
  │  Stores system instructions, LLM config, and toolset.    │
  └────────────────────────────┬─────────────────────────────┘
                               ▼
  ┌──────────────────────────────────────────────────────────┐
  │                       2. SESSION                         │
  │  Handles conversational memory, chat logs, and context   │
  │  preservation. Supports Redis/Spanner/Firestore stores.   │
  └────────────────────────────┬─────────────────────────────┘
                               ▼
  ┌──────────────────────────────────────────────────────────┐
  │                        3. RUNNER                         │
  │  Executes the reasoning loop. Determines when to invoke  │
  │  tools, call the LLM, and return values to the user.     │
  └──────────────────────────────────────────────────────────┘
```

---

## 2. Implementing Custom Tools

The ADK simplifies tool definition. Any Python function with clear type hints and a docstring is automatically converted into a structured tool Schema that the Gemini model can call.

### Code Pattern: Define Custom Tools
```python
def retrieve_regulatory_circular(circular_id: str) -> str:
    """
    Fetches the full text of an Indian regulatory circular (RBI/SEBI) from the Database.

    Args:
        circular_id: The unique alphanumeric code of the circular (e.g., 'RBI-2026-104').

    Returns:
        The text content of the circular, or an error message if not found.
    """
    # Import inside tool to keep deployment packaging lightweight
    import psycopg2
    
    conn = psycopg2.connect("postgresql://user:pass@host:port/db")
    cursor = conn.cursor()
    cursor.execute("SELECT text FROM ingested_regulatory_knowledge WHERE doc_id = %s", (circular_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return row[0]
    return f"Circular {circular_id} not found."
```

---

## 3. Creating an ADK Application (`AdkApp`)

The `AdkApp` class is the entry point that groups your agent logic, memory templates, and registered tools, preparing them for the serverless deployment engine.

### Code Pattern: Bootstrap Agent
```python
from google.adk.agents import Agent
from vertexai.agent_engines import AdkApp

# 1. Define the agent instance
compliance_agent = Agent(
    name="compliance_officer",
    model="gemini-2.5-flash",
    instructions=(
        "You are an Indian BFSI Compliance Auditor. Use the registered database "
        "tools to search for circulars and write audit compliance checklists."
    ),
    tools=[retrieve_regulatory_circular]
)

# 2. Package into AdkApp
app = AdkApp(agent=compliance_agent)

# Test agent reasoning locally before deployment
if __name__ == "__main__":
    response = app.run(
        user_query="Has there been any recent circular on KYC onboarding? Check RBI-2026-104."
    )
    print("Local Test Output:", response)
```

---

## 4. Deploying to Vertex AI Agent Engine

Once tested locally, you deploy the agent. Behind the scenes, the SDK packages your code directory, extracts dependencies from `requirements.txt`, serializes (pickles) the agent configuration, uploads them to Google Cloud Storage (GCS), and spins up a serverless API Endpoint.

### Method 1: Programmatic Deployment via Python SDK
```python
import vertexai
from vertexai.preview import reasoning_engines

# Initialize Vertex AI Context
vertexai.init(
    project="curator-research",
    location="asia-south1",          # Deploy close to local services
    staging_bucket="gs://curator-research-staging"
)

# Remote compilation and deployment
remote_agent = reasoning_engines.ReasoningEngine.create(
    app,
    display_name="BFSI Compliance Assistant",
    description="Automated auditing agent for RBI and SEBI regulations",
    requirements=[
        "psycopg2-binary==2.9.9",
        "google-genai==0.1.0",
    ],
    extra_packages=["./libs"] # Inject shared utilities directly
)

print(f"Agent successfully deployed! Resource URI: {remote_agent.resource_name}")
```

### Method 2: Command Line Interface (ADK CLI)
If your directory is organized as a standalone package with `agent.py` and `requirements.txt`:
```bash
# 1. Install ADK CLI
pip install google-cloud-adk

# 2. Initialize project context
gcloud config set project curator-research

# 3. Deploy the agent code directory
adk deploy agent_engine \
  --agent_folder ./my_agent_src_directory \
  --display_name "BFSI-Compliance-Engine"
```

---

## 5. Agent-to-Agent (A2A) Workflows

The ADK supports native agent-to-agent communication, allowing modular agents to hand off sub-tasks cleanly.

```python
from google.adk.agents import Agent
from google.adk.workflows import AgentRouter

# 1. Define Specialist Agents
financial_analyst = Agent(
    name="finance_analyst",
    model="gemini-2.5-flash",
    instructions="Analyze balance sheets and compute debt-to-equity ratios."
)

legal_advisor = Agent(
    name="legal_advisor",
    model="gemini-2.5-flash",
    instructions="Inspect contracts and identify potential liability clauses."
)

# 2. Create the Router Agent
router_app = AgentRouter(
    agents=[financial_analyst, legal_advisor],
    routing_instruction="Route financial analysis questions to the finance_analyst and legal clauses to the legal_advisor."
)
```
This multi-agent graph isolates duties, maintaining security parameters while reducing prompt pollution on complex reasoning queries.
