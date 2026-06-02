# Google Cloud Credits & Resource Optimization Guide

This guide analyzes the terms of the `Marketing- AI Agents Challenge` promotional credits and provides an architectural blueprint to optimize resource usage inside the Bija-Banyan-BeatSync (BBB) project to maximize utility while minimizing costs.

---

## 1. Credit Terms & Analysis

*   **Billing Account Name:** `My Billing Account` (ID: `015894-FFA17E-7F9806`)
*   **Active Promotion:** `Marketing- AI Agents Challenge- jesshuang- 499056416`
*   **Promotional Promo Code:** `7H3BMV23QBTW54RH`
*   **Balance Details:**
    *   **Original Value:** ₹47,275.01 (approx. $500 USD)
    *   **Current Available:** ₹45,269.54 (96% remaining)
    *   **List Pricing:** Applicable for all utilized services.
*   **Validity Period:** 15 May 2026 to 14 July 2026 (One-time credit, no extensions).

---

## 2. Eligible Google Cloud Services

The promotion applies to standard Google Cloud infrastructure and API billing. To target the AI Agents Challenge, we will prioritize services that directly support agent development:

| Service Category | Google Cloud Product | Best Application in BBB |
|---|---|---|
| **AI & LLM Services** | **Vertex AI (Gemini 2.5 Flash / Pro)** | Model reasoning, SFT data generation, structured compliance extraction, policy diffing. |
| **Agent Runtimes** | **Vertex AI Agent Engine** (Reasoning Engine) | Managed runtime for ADK agents, auto-scaling to zero when idle. |
| **Serverless Compute** | **Google Cloud Run & Cloud Run Jobs** | Hosting Banyan API gateways, running Playwright scrapers on schedules, batch document parsing. |
| **Vector Search** | **Vertex AI Vector Search** (Matching Engine) | Hosting semantic embeddings (Qwen3 or Google Multimodal) for regulatory paragraph matching. |
| **Managed Databases** | **Cloud Firestore** & **Cloud SQL** | Storing agent session history, conversation memory, and relational indices (`ingested_regulatory_knowledge`). |
| **Object Storage** | **Google Cloud Storage (GCS)** | Landing bucket for PDFs, parser outputs, and model training weights. |

---

## 3. Cost Estimations (List Pricing)

With a total budget of ₹45,269.54 over two months, we must budget our API calls and infrastructure strategically:

### 1. LLM Calls (Vertex AI Gemini 2.5)
*   **Gemini 2.5 Flash:** ~$0.075 / 1M Input Tokens, ~$0.30 / 1M Output Tokens.
*   **Gemini 2.5 Pro:** ~$1.25 / 1M Input Tokens, ~$5.00 / 1M Output Tokens.
*   *Budget Allocation:* **₹15,000**. This enables ~200 million input tokens on Flash and ~10 million input tokens on Pro, more than sufficient for agent debate cycles.

### 2. Compute (Cloud Run)
*   **Tier 1 CPU/Memory:** ~$0.00002400 / vCPU-second, ~$0.00000250 / GB-second.
*   *Scale-to-Zero Advantage:* Under idle conditions, Cloud Run drops instances to zero.
*   *Budget Allocation:* **₹10,000**. Supports running Banyan backend services and periodic scraper scripts.

### 3. Vector Database (Vertex AI Vector Search)
*   Standard index query costs depend on the number of deployed nodes.
*   *Alternative:* For development, we can store small indices (under 100K items) in a serverless library (like FAISS or LanceDB) stored directly on GCS and loaded in-memory on Cloud Run.
*   *Budget Allocation:* **₹5,000**.

### 4. Storage & Relational DB (GCS & Firestore)
*   **GCS standard storage:** ~₹1.80 ($0.02) / GB per month.
*   **Firestore operations:** Generous free tier, ₹5.00 ($0.06) / 100,000 document reads.
*   *Budget Allocation:* **₹5,000**.

---

## 4. Architectural Optimization Blueprint

To prevent running out of credits or accumulating billable overages after July 14, 2026, the following architectural choices are recommended:

```
                  ┌───────────────────────────────────────────────┐
                  │          Google Cloud Storage (GCS)           │
                  │  - Standard Bucket: gs://curator-research     │
                  │  - Stores PDF files and vector index files    │
                  └───────────────────────┬───────────────────────┘
                                          │
                                          ▼
  ┌───────────────────────────────────────────────────────────────────────────────┐
  │                           Google Cloud Run Jobs                               │
  │  - Triggered on-demand or by Cloud Scheduler                                  │
  │  - Runs Playwright scrapers and Docling PDF parsers                           │
  │  - Shuts down immediately upon completion (Cost = zero when idle)             │
  └───────────────────────────────────────┬───────────────────────────────────────┘
                                          │
                                          ▼
  ┌───────────────────────────────────────────────────────────────────────────────┐
  │                          Vertex AI Agent Engine                               │
  │  - Deployed via Agent Development Kit (ADK)                                   │
  │  - Queries Gemini 2.5 Pro (enterprise = True)                                 │
  │  - Records conversational session memory in serverless Firestore              │
  └───────────────────────────────────────────────────────────────────────────────┘
```

### Action Items for Credit Protection:
1. **Never run 24/7 Compute Engine (VM) instances:** Standard GCE instances accumulate charges continuously. Use serverless runtimes (Cloud Run and Agent Engine) which are billed only per execution millisecond.
2. **Setup Budget Alerts:** Navigate to GCP Billing, select `015894-FFA17E-7F9806`, and create a budget alert at **₹35,000 (80%)** and **₹42,000 (90%)** of the promo credit value.
3. **Use the `enterprise=True` API Client:** Ensure the Python scripts use:
   ```python
   client = genai.Client(enterprise=True, project="curator-research")
   ```
   If `enterprise=True` is omitted, the API routing defaults to AI Studio, which requires a separate `GEMINI_API_KEY` and does not draw from your GCP billing credit account.
4. **Deploy GCS Life Cycle Policies:** Set transition policies on `gs://curator-research` to automatically delete raw crawl PDFs after 30 days, keeping only metadata indices in Firestore to save storage costs.
