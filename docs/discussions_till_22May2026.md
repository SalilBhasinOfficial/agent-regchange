On the participant list
That's expected and not a bug. Google's webinar platform (and most webinar tools — Zoom Webinars, Google Meet in webinar mode, BrightTALK) hide the attendee list from attendees by default. You see yourself + the hosts/panelists, and that's it. You're not seeing only your organization — you're seeing only yourself. Other registrants exist; they're just not exposed to you. This is standard for B2B webinars: organizers don't want attendees scraping each other for sales prospecting, and attendees usually prefer the privacy. Don't worry — the room won't be empty.
If you want, paste a paragraph about what Aidni actually does (domain, current product, type of data in the KB) and I'll re-cut the architecture and the webinar questions to your specifics.You said: Need practical questions around the later un tested part of the project.SalilBhasinOfficial/bbbmasterGITHUBNeed practical questions around the later un tested part of the project. currently working on knowledge base creation only. once knowledge base is ready, how do we automate research jobs over the knowledge base and save the results overtime and itterate without any set pattern to help get the best results without hard boundaries. Also once BFSI client is onboarded, the agents should run knowlege base and BFSI entity internal policy sop manuals processes comparative for gap analysis, change management, etc. Also one line in a rbi direction can trigger multiple processes to comply which requires splitting the line into different requirements all together. how agents and agentic framework can help in orchestrating such agents. also cost of always running agents may sky rocket. what are cost control measures in place and how agents learnes over time from the tasks completed so far?May 14Claude responded: Okay — context fully changes now.Architected agentic layer patterns for autonomous research, comparative analysis, cost optimization, and continuous learningArchitected agentic layer patterns for autonomous research, comparative analysis, cost optimization, and continuous learningOkay — context fully changes now. You're not building from zero. You already have the pipeline (14 stages, GPU-native, deontic-aware), the graph (322K nodes), the orchestrator (Bija on LangGraph), and the MCP surface (28–44 tools). The question is the agentic layer that sits on top, and that's a meaningfully different design problem from "build a GraphRAG agent." Let me address each of your five questions concretely, then come back to what Google's new stack actually adds for you (vs. duplicates) and revise your webinar questions.

1. Automating research jobs over the KB, persisting results, iterating without rigid patterns
What you want is a research loop — long-running, self-directed, with no fixed playbook. The pattern that works in practice:

Research jobs as first-class graph citizens. Every research run is a node — (:ResearchRun {goal, hypothesis, plan, started_at, status}) — with edges to the source Rule/Clause/DocSection nodes it consumed and the artifacts it produced. This means your KB and your research outputs live in the same graph; future agents traverse both. Three months in, an agent asking "what did we already learn about green-deposit obligations across RBI + SEBI?" hits prior research nodes, not just primary sources.
Two trigger modes, not one. Reactive (your existing 15-min circular-watcher fires research on every new high-impact ingest) and proactive (a scheduler runs standing research questions weekly — "any new IRDAI guidance on cyber resilience this week?"). Both write to the same artifact schema.
Plans that mutate. Don't pre-define research workflows. Let the planner agent emit a plan, execute it via your MCP tools, observe results, and replan if confidence < threshold. Store every plan iteration. This is where LangGraph's checkpointer earns its keep — you get free time-travel debugging.
Evaluation built-in from day one. Use your synthetic queries (already generated during enrichment — Phase 3 reasoning traces) as the regression set. Every research output gets scored against (a) groundedness in cited sources, (b) deontic completeness, (c) cross-reference closure. Failed runs feed back as few-shot negative examples.
No hard pattern, but bounded freedom. The trap is unbounded freedom — agents that explore forever. Bound by: max tool calls per run, max graph hops, max tokens, max wall time. Inside those bounds, let the planner do whatever it wants. The bandit then learns which strategies work for which query shapes.


2. Tenant-KB comparative analysis for gap analysis and change management
You already have the seed (Circular → Policy pipeline with 0.70 similarity match). Productionising this for an onboarded BFSI tenant means three additions:

Mirror pipeline for tenant docs. Run the same 14-stage extraction on the tenant's policies, SOPs, control library, and board mandates. You get a tenant subgraph that's structurally identical to the external one — (:TenantRule), (:TenantPolicy), (:TenantControl). This is the table stakes; without it everything else is hand-wavy.
Bidirectional alignment edges with typed semantics. Not just "matches with similarity 0.78." Type the relationship: COVERS_FULLY, COVERS_PARTIALLY, CONTRADICTS, STALE (tenant rule aligned to an amended external rule), ORPHAN (tenant rule with no external driver — could be audit-finding-driven or just legacy cruft). A gap-analysis agent traverses the tenant graph looking for missing edges or STALE/ORPHAN patterns and generates a prioritised remediation queue.
Change-management as graph diffs. When an external rule node updates (your amendment classifier already does this — unchanged/modified/amended/substituted), an agent walks the downstream tenant subgraph and creates (:ChangeTicket) nodes for every impacted tenant artifact, with proposed deltas drafted. The compliance officer sees the blast radius before they read the amendment text. This is your Pillar 4 made autonomous rather than alert-driven.


3. Decomposing one RBI line into multiple compliance requirements
This is the right instinct and it's underbuilt in most regtech. A sentence like "Every regulated entity shall conduct customer due diligence at account opening and re-verify annually" carries (a) two distinct obligations with different temporal scope, (b) multiple process owners (operations vs. compliance), (c) multiple control types (system flag, periodic review, audit trail). Pattern:

Atomization agent. Takes a (:Rule) node, emits N (:Obligation) children with explicit deontic structure: {subject, action, object, condition, temporal_scope, modal_strength, triggering_event}. Each obligation is independently traceable, testable, and mappable. Your deontic classifier in Phase 3 is the bones of this — the new piece is structured fan-out.
Process-mapping agent (per-tenant). For each (:Obligation), identifies the tenant (:Process) nodes that should comply. One obligation → many processes is normal; one process → many obligations is also normal. Many-to-many edges with confidence scores.
Orchestration via DAG. This is exactly the use case the new ADK graph-based framework is pitched for. A decomposer → mapper → owner_router → drafter → reviewer DAG, where each node is an agent and the edges encode handoffs with explicit state. Your LangGraph already does this; the question (below) is whether ADK is worth migrating to.
Aggregation agent. Closes the loop — collects responses from process owners, identifies obligations with no acknowledgement after T days, escalates. This is where most regtech dies because it stops at "we flagged it."

The architectural insight: the unit of work isn't the document, the section, or the rule — it's the obligation. Rebuild your downstream around obligations as the canonical artifact and everything downstream (gap analysis, change management, audit packs) gets cleaner.

4. Cost control for always-running agents
Five concrete levers, in order of leverage:

Cascade by model tier. Cheap classifier first (Gemini 3.1 Flash, Gemma-2B local, or a fine-tuned BERT) decides whether the expensive Gemma3/4-27B run is justified. Pre-screening kills 60–80% of low-signal triggers. You already have an online-learned router — extend it to model-tier selection, not just retrieval-strategy selection.
Context caching. Vertex AI now supports prompt caching (similar to Anthropic's). For your standing prompts and frequently-accessed KB chunks, this drops repeat-query cost by 70–90%. Worth designing your agent prompts to maximise cache hits from day one (stable prefix, variable suffix).
Hard budgets, per tenant and per agent type. Track tokens per (tenant_id, agent_type, task_class). Set per-day caps. Agents check budget before expensive operations and degrade gracefully (e.g., fall back to Flash, or queue for batch).
Async + batched by default; sync is the exception. Most regulatory research doesn't need to be real-time. Your 15-min watcher is the only thing that has to be near-real-time. Everything else — gap analysis, periodic deep research, policy proposals — can run nightly via batch APIs at 50% cost.
Sleep/wake on idle. Long-running agents should checkpoint state and tear down compute. LangGraph's checkpointer plus a queue-driven wake-up gets you to "agents that look always-on but cost like cron jobs."

The trap to avoid: don't optimise costs by lowering quality at scale. Optimise by routing the right work to the right tier. A wrongly-decomposed RBI rule costs 1000x more in compliance failure than the LLM tokens saved.

5. Learning over time
The substrate is what I described in Q1 — every run is a graph artifact with provenance. On top of that:

Episodic memory with retrieval, not memory walls. When a new task arrives, the planner queries past (:ResearchRun) nodes for similar goals, fetches their plans and outcomes, and conditions its plan accordingly. Cheap, no fine-tuning needed, immediately useful.
Failure mining. Cluster failed runs by failure mode (wrong tool, wrong graph hop, hallucinated entity). Auto-generate new few-shot exemplars from the closest successful runs in the same cluster and inject into the system prompt. This is the "improve without retraining" loop.
Human-in-loop is the highest-signal data. Every time a compliance officer edits an agent-drafted policy proposal, the diff is gold. Log it. Cluster the diffs. They reveal the systematic gaps between agent output and ground truth — and they're rare and expensive, so treat them as the most valuable signal you generate.
Distillation, eventually. Once you have ~10K labelled (input, plan, output, human-edit-diff) tuples, fine-tune a small Gemma router. Don't do this for at least 6 months post-beta — the data isn't stable enough yet.
Agent Optimizer (Google's new tool) is essentially this pattern packaged. Worth evaluating against your roll-your-own — the answer is probably "use it for evaluation/diagnostics, keep your own loops for the BFSI-specific failure modes it won't understand."


What Google's new stack actually adds for you (honest read)
You don't need most of it. You have Bija + LangGraph + Milvus + Neo4j + MCP + online-learned router. The ADK and Agent Studio largely duplicate what you've built. What does Google add that you can't trivially replicate:
Google pieceWorth it for Aidni?WhyADK (graph-based)Probably not, unless distribution requires it.LangGraph does what you need. ADK is interesting only if Marketplace listing requires it.Agent StudioNo.You're past low-code stage.Agent SimulationYes, evaluate.Synthetic eval generation is hard to do well; worth a try.Agent OptimizerYes, evaluate.Failure analysis tooling; lower investment than building yours.Knowledge CatalogMaybe.Your Neo4j ontology already encodes business semantics. Useful if it integrates with BigQuery for analytics workloads.Gemini Enterprise Marketplace listingYes — strategic.This is the one thing you can't replicate. Distribution to enterprise buyers.Vertex AI Vector SearchNo.Milvus is more flexible for your hybrid + Matryoshka pattern.Context caching (Vertex)Yes, integrate.Direct cost win on repeat KB queries.Gemini 3.1 Pro/FlashYes for routing/agentic; keep Gemma for enrichment.Use Gemini for orchestration where its tool-use is strong; keep your fine-tuned Gemma pipeline for the deontic-heavy enrichment where you've invested.
So your real opportunity in the hackathon is Track 3 (refactor a business-ready agent for enterprise distribution) — package a Curator-on-Google reference deployment that can be listed in the Gemini Enterprise Agent Marketplace. That's the only thing the hackathon offers that you can't build yourself, and it's potentially worth more than the $90K prize pool.

Revised webinar questions, calibrated to where you actually are
Drop the introductory ones from my earlier list. Ask these:

"For a startup with an existing LangGraph multi-agent stack and Neo4j + Milvus, what's the minimum-viable integration with Gemini Enterprise Agent Platform that qualifies for Track 3 (Marketplace distribution)? Do we need to migrate orchestration to ADK, or is MCP-based interop sufficient?"
"How does Agent Optimizer handle agents whose failure modes are domain-specific (deontic logic misclassification, wrong graph traversal, entity-resolution ambiguity)? Can we plug in custom evaluators, or is it tied to Google's default eval set?"
"Vertex AI context caching — what's the practical ceiling on cached prefix size, and what's the cache TTL? We have stable system prompts of ~30K tokens that we'd want cached across millions of agent calls."
"For BFSI in India — regulated data must stay in India. Does Gemini Enterprise Agent Platform support full asia-south1 residency for both inference and agent state, or does any control-plane data egress? This is a hard blocker for our buyers."
"Agent Marketplace listing — what's the path from hackathon submission to actually being listed in the Gemini Enterprise Agent Gallery? Is winning Track 3 a fast-track, or a separate partner onboarding process? Who is the right Google contact for an India-based startup with a BFSI-vertical agent?"
"We use Gemma3-27B fine-tuned for our extraction pipeline and would want to keep it. Can Vertex AI host custom Gemma checkpoints, or are we restricted to first-party Gemini models for the agent path?"

Question 1, 4, and 5 are the ones where Google staff have agency to actually move something for you. Lead with those.You said: what was track 3?what was track 3? 3 tracks one line each?May 14Claude responded: Track 1 — Build new: Start from scratch and build a brand-new agent on Gemini Enterprise Agent Platform.Track 1 — Build new: Start from scratch and build a brand-new agent on Gemini Enterprise Agent Platform.
Track 2 — Optimize prototype: Take an existing agent prototype and harden it for production reliability (evals, guardrails, scale).
Track 3 — Refactor for enterprise distribution: Take a business-ready agent and package it for listing on Google Cloud Marketplace and the Gemini Enterprise Agent Gallery.You said: brief in few lines about aidni curator research (2 lines max)brief in few lines about aidni curator research (2 lines max)May 14Claude responded: Curator Research by Aidni is an AI-native regulatory intelligence platform for Indian BFSI that ingests every publication from RBI, SEBI, IRDAI, MCA, and other…Curator Research by Aidni is an AI-native regulatory intelligence platform for Indian BFSI that ingests every publication from RBI, SEBI, IRDAI, MCA, and other regulators through a 14-stage GPU pipeline, extracting rules, entities, and cross-references into a 322K-node knowledge graph. It then maps every external regulatory change to each tenant's internal policies, SOPs, and board mandates — so risk, compliance, and CXO teams act on regulatory signals in minutes instead of months.You said: can we keep these questions short and sharp?can we keep these questions short and sharp?  (Curator Research by Aidni is an AI-native regulatory intelligence platform for Indian BFSI that ingests every publication from RBI, SEBI, IRDAI, MCA, and other regulators through a 14-stage GPU pipeline, extracting rules, entities, and cross-references into a 322K-node knowledge graph. It then maps every external regulatory change to each tenant's internal policies, SOPs, and board mandates — so risk, compliance, and CXO teams act on regulatory signals in minutes instead of months.
Questions:
1. For a startup with an existing LangGraph multi-agent stack and Neo4j + Milvus, what's the minimum-viable integration with Gemini Enterprise Agent Platform that qualifies for Track 3 (Marketplace distribution)? Do we need to migrate orchestration to ADK, or is MCP-based interop sufficient?
2. How does Agent Optimizer handle agents whose failure modes are domain-specific (deontic logic misclassification, wrong graph traversal, entity-resolution ambiguity)? Can we plug in custom evaluators, or is it tied to Google's default eval set?"
"Vertex AI context caching — what's the practical ceiling on cached prefix size, and what's the cache TTL? We have stable system prompts of ~30K tokens that we'd want cached across millions of agent calls.
3. For BFSI in India — regulated data must stay in India. Does Gemini Enterprise Agent Platform support full asia-south1 residency for both inference and agent state, or does any control-plane data egress? This is a hard blocker for our buyers.
4. Agent Marketplace listing — what's the path from hackathon submission to actually being listed in the Gemini Enterprise Agent Gallery? Is winning Track 3 a fast-track, or a separate partner onboarding process? Who is the right Google contact for an India-based startup with a BFSI-vertical agent?
5. We use Gemma3-27B fine-tuned for our extraction pipeline and would want to keep it. Can Vertex AI host custom Gemma checkpoints, or are we restricted to first-party Gemini models for the agent path?). keep same text formatting.Show moreMay 14Claude responded: Curator Research by Aidni is an AI-native regulatory intelligence platform for Indian BFSI that ingests every publication from RBI, SEBI, IRDAI, MCA, and other…Curator Research by Aidni is an AI-native regulatory intelligence platform for Indian BFSI that ingests every publication from RBI, SEBI, IRDAI, MCA, and other regulators through a 14-stage GPU pipeline, extracting rules, entities, and cross-references into a 322K-node knowledge graph. It then maps every external regulatory change to each tenant's internal policies, SOPs, and board mandates — so risk, compliance, and CXO teams act on regulatory signals in minutes instead of months.
Questions:

We have a LangGraph + Neo4j + Milvus stack. Minimum-viable integration to qualify for Track 3 — do we migrate orchestration to ADK, or is MCP interop enough?
Can Agent Optimizer plug in custom evaluators for domain-specific failure modes (deontic misclassification, wrong graph traversal, entity ambiguity), or is it tied to Google's default eval set?
Vertex AI context caching — practical ceiling on cached prefix size and TTL? We have ~30K-token stable system prompts hit across millions of agent calls.
BFSI in India requires full data residency. Does Gemini Enterprise Agent Platform keep both inference and agent state in asia-south1, or does any control-plane data egress?
Path from Track 3 win to actual Gemini Enterprise Agent Gallery listing — fast-track or separate partner onboarding? Who's the right Google contact for an India-based BFSI-vertical agent?
Can Vertex AI host our fine-tuned Gemma3-27B checkpoint on the agent path, or are we restricted to first-party Gemini models?
You said: similar short question regarding (In the AI world, your only real moat is iteration speed.similar short question regarding (In the AI world, your only real moat is iteration speed. Logan Kilpatrick and founders from the front lines share their "recipe" for moving fast without breaking the model. We’ll look at real workflows using Google DeepMind's models, the technical trade-offs of multimodality, and how to stay ahead of the next model release..)  panel (Agenda - Asia-Pacific
May 14
Time
arrow_drop_down
Title
8:35 AM  - 8:50 AM  GMT+5:30
The future of AI: How startups build competitive moats
As the future of AI takes shape, startups are making big bets on what will matter long-term. Join leading founders for a real conversation about how they’re building moats beyond the model—what decisions paid off, which ones didn’t, and how they’re thinking about architecture, data, cost, and product today.
link
Copy link to share session
event
Add to calendar
Scott Barneson
Managing Director
North America Startups
Simon Hørup Eskildsen
Founder & CEO
Turbopuffer
Mukund Jha
Founder & CEO
Emergent
Felipe Moreno
CEO
Jusbrasil
youtube_live
Watch live
8:50 AM  - 9:05 AM  GMT+5:30
Startups shipping at scale with Google DeepMind
In the AI world, your only real moat is iteration speed. Logan Kilpatrick and founders from the front lines share their "recipe" for moving fast without breaking the model. We’ll look at real workflows using Google DeepMind's models, the technical trade-offs of multimodality, and how to stay ahead of the next model release.
link
Copy link to share session
event
Add to calendar
Logan Kilpatrick
Group Product Manager
Google DeepMind
Michele Catasta
President & Head of AI
Replit
Eno Reyes
CTO & Co-Founder
Factory
Bianca Rangecroft
Founder & CEO
Whering
Jay Wu
Co-Founder & CTO
Opus Clip
9:05 AM  - 9:20 AM  GMT+5:30
Multimodal startups: Building AI that sees, speaks & creates
The future of AI is multimodal and generative. Startup founders will discuss how they combine vision, speech, and language with tools like Imagen, Chirp, Veo, Lyria, and Gemini Live to build human-like experiences, prototype fast, scale production, and turn AI-driven creativity into real products.
link
Copy link to share session
event
Add to calendar
Arthur Soroken
Co-Founder
AI Futures Fund & Growth Hacking Lead
Bin Liu
VP of Product Engineering
HeyGen
Ben Budde
VP of Revenue
ElevenLabs
Matt Rouif
CEO & Co-Founder
Photoroom
9:20 AM  - 9:35 AM  GMT+5:30
From prompts to production: Startup multi-agent workflows
Autonomous multi-agent systems are speeding up how startups build and scale. Founders share how they use frameworks like ADK, A2A, and MCP to orchestrate complex workflows, prototype faster, and deliver reliable next-gen AI solutions.
link
Copy link to share session
event
Add to calendar
Jamie de Guerre
Senior Director, Outbound Product Management
Cloud AI
Akash Sharma
CEO
Vellum AI
Maxim Fateev
CTO
Temporal
George Kichukov
Field CTO
GitLab
9:35 AM  - 10:05 AM  GMT+5:30
Expert insights: Live Q&A with Google Cloud experts
Bring your questions and join the conversation. As our experts walk through the highlights, ask anything that comes up and get real-time insights on new launches, AI adoption, and business impact.
link
Copy link to share session
event
Add to calendar
Mirabel Tukiman
Customer Engineer
Google Cloud
Gia Lim
Customer Engineer, Infrastructure Modernization, Digital Natives
Google Cloud
Yuan Liu
Customer Engineer, Applied & Generative AI
Google Cloud
Yazan Mughrabi
Security Practice Lead
AuNZ
10:05 AM  - 10:10 AM  GMT+5:30
Closing remarks
link
Copy link to share session
event
Add to calendar
Darren Mowry
Vice President
Global Startups
Welcome & Keynote
Join Darren Mowry, VP of Global Startups at Google Cloud, as he kicks things off with an exclusive recap of key announcements and innovations directly from the Startup Hub at Google Cloud Next, highlighting the most impactful trends shaping the future of AI.
5 Minutes
link
Copy link to share session
Darren Mowry
Vice President
Global Startups) 2 questions specific to us.Show moreMay 14Claude responded: Iteration speed vs.
Iteration speed vs. moat depth — our moat is a deeply specialised 14-stage GPU pipeline (deontic logic, paragraph-level amendment diffs, Indian regulatory ontology) that takes weeks to evolve. How do you balance "ship fast against the next model release" with vertical depth that can't be re-architected every quarter?
Every Gemini release shifts behaviour on our extraction prompts. What's the recommended pattern for regression-testing 30K-token system prompts and fine-tuned Gemma checkpoints against new Gemini versions before rolling forward in production?
You said: again 2 questions (Startups shipping at scale with Google DeepMindagain 2 questions (Startups shipping at scale with Google DeepMind
8:50 AM - 9:05 AM
Logan KilpatrickMichele CatastaEno ReyesBianca RangecroftJay Wu
In the AI world, your only real moat is iteration speed. Logan Kilpatrick and founders from the front lines share their "recipe" for moving fast without breaking the model. We’ll look at real workflows using Google DeepMind's models, the technical trade-offs of multimodality, and how to stay ahead of the next model release.
SHOW LESS)(Agenda - Asia-Pacific
May 14
Time
arrow_drop_down
Title
8:50 AM
-
9:05 AM
GMT+5:30
Startups shipping at scale with Google DeepMind
In the AI world, your only real moat is iteration speed. Logan Kilpatrick and founders from the front lines share their "recipe" for moving fast without breaking the model. We’ll look at real workflows using Google DeepMind's models, the technical trade-offs of multimodality, and how to stay ahead of the next model release.
linkCopy link to share session
eventAdd to calendar
Logan Kilpatrick
Group Product Manager
Google DeepMind
Michele Catasta
President & Head of AI
Replit
Eno Reyes
CTO & Co-Founder
Factory
Bianca Rangecroft
Founder & CEO
Whering
Jay Wu
Co-Founder & CTO
Opus Clip
[youtube_liveWatch live](https://cloudonair.withgoogle.com/events/best-of-next-for-startups/watch?talk=talk-apac3)
9:05 AM
-
9:20 AM
GMT+5:30
Multimodal startups: Building AI that sees, speaks & creates
The future of AI is multimodal and generative. Startup founders will discuss how they combine vision, speech, and language with tools like Imagen, Chirp, Veo, Lyria, and Gemini Live to build human-like experiences, prototype fast, scale production, and turn AI-driven creativity into real products.
linkCopy link to share session
eventAdd to calendar
Arthur Soroken
Co-Founder
AI Futures Fund & Growth Hacking Lead
Bin Liu
VP of Product Engineering
HeyGen
Ben Budde
VP of Revenue
ElevenLabs
Matt Rouif
CEO & Co-Founder
Photoroom
9:20 AM
-
9:35 AM
GMT+5:30
From prompts to production: Startup multi-agent workflows
Autonomous multi-agent systems are speeding up how startups build and scale. Founders share how they use frameworks like ADK, A2A, and MCP to orchestrate complex workflows, prototype faster, and deliver reliable next-gen AI solutions.
linkCopy link to share session
eventAdd to calendar
Jamie de Guerre
Senior Director, Outbound Product Management
Cloud AI
Akash Sharma
CEO
Vellum AI
Maxim Fateev
CTO
Temporal
George Kichukov
Field CTO
GitLab
9:35 AM
-
10:05 AM
GMT+5:30
Expert insights: Live Q&A with Google Cloud experts
Bring your questions and join the conversation. As our experts walk through the highlights, ask anything that comes up and get real-time insights on new launches, AI adoption, and business impact.
linkCopy link to share session
eventAdd to calendar
Mirabel Tukiman
Customer Engineer
Google Cloud
Gia Lim
Customer Engineer, Infrastructure Modernization, Digital Natives
Google Cloud
Yuan Liu
Customer Engineer, Applied & Generative AI
Google Cloud
Yazan Mughrabi
Security Practice Lead
AuNZ
10:05 AM
-
10:10 AM
GMT+5:30
Closing remarks
linkCopy link to share session
eventAdd to calendar
Darren Mowry
Vice President
Global Startups
Welcome & Keynote
Join Darren Mowry, VP of Global Startups at Google Cloud, as he kicks things off with an exclusive recap of key announcements and innovations directly from the Startup Hub at Google Cloud Next, highlighting the most impactful trends shaping the future of AI.
5 Minutes
linkCopy link to share session
Darren Mowry
Vice President
Global Startups
The future of AI: How startups build competitive moats
As the future of AI takes shape, startups are making big bets on what will matter long-term. Join leading founders for a real conversation about how they’re building moats beyond the model—what decisions paid off, which ones didn’t, and how they’re thinking about architecture, data, cost, and product today.
15 Minutes
linkCopy link to share session
Scott Barneson
Managing Director
North America Startups
Simon Hørup Eskildsen
Founder & CEO
Turbopuffer
Mukund Jha
Founder & CEO
Emergent
Felipe Moreno
CEO
Jusbrasil)Show moreMay 14Claude responded: We built a 322K-node graph because context windows died on 400-page Master Directions.Synthesized panel context and crafted two targeted questionsSynthesized panel context and crafted two targeted questions
We built a 322K-node graph because context windows died on 400-page Master Directions. With Gemini 3.1 Pro's long context, when does long-context-over-everything beat structured retrieval for accuracy on regulatory-grade outputs — and how do you decide where to draw that line as context windows keep growing?
We fine-tuned Gemma3-27B for deontic extraction because frontier models miss obligation density on dense regulatory prose. For a specialised vertical, is the iteration-speed-optimal bet to keep investing in fine-tuned smaller models, or to migrate to frontier Gemini with prompt engineering as it gets cheaper and smarter each release?
You said: (Agenda - Asia-Pacific(Agenda - Asia-Pacific
May 14
Time
arrow_drop_down
Title
9:05 AM
-
9:20 AM
GMT+5:30
Multimodal startups: Building AI that sees, speaks & creates
The future of AI is multimodal and generative. Startup founders will discuss how they combine vision, speech, and language with tools like Imagen, Chirp, Veo, Lyria, and Gemini Live to build human-like experiences, prototype fast, scale production, and turn AI-driven creativity into real products.
linkCopy link to share session
eventAdd to calendar
Arthur Soroken
Co-Founder
AI Futures Fund & Growth Hacking Lead
Bin Liu
VP of Product Engineering
HeyGen
Ben Budde
VP of Revenue
ElevenLabs
Matt Rouif
CEO & Co-Founder
Photoroom
[youtube_liveWatch live](https://cloudonair.withgoogle.com/events/best-of-next-for-startups/watch?talk=talk-apac4)
9:20 AM
-
9:35 AM
GMT+5:30
From prompts to production: Startup multi-agent workflows
Autonomous multi-agent systems are speeding up how startups build and scale. Founders share how they use frameworks like ADK, A2A, and MCP to orchestrate complex workflows, prototype faster, and deliver reliable next-gen AI solutions.
linkCopy link to share session
eventAdd to calendar
Jamie de Guerre
Senior Director, Outbound Product Management
Cloud AI
Akash Sharma
CEO
Vellum AI
Maxim Fateev
CTO
Temporal
George Kichukov
Field CTO
GitLab
9:35 AM
-
10:05 AM
GMT+5:30
Expert insights: Live Q&A with Google Cloud experts
Bring your questions and join the conversation. As our experts walk through the highlights, ask anything that comes up and get real-time insights on new launches, AI adoption, and business impact.
linkCopy link to share session
eventAdd to calendar
Mirabel Tukiman
Customer Engineer
Google Cloud
Gia Lim
Customer Engineer, Infrastructure Modernization, Digital Natives
Google Cloud
Yuan Liu
Customer Engineer, Applied & Generative AI
Google Cloud
Yazan Mughrabi
Security Practice Lead
AuNZ
10:05 AM
-
10:10 AM
GMT+5:30
Closing remarks
linkCopy link to share session
eventAdd to calendar
Darren Mowry
Vice President
Global Startups
Welcome & Keynote
Join Darren Mowry, VP of Global Startups at Google Cloud, as he kicks things off with an exclusive recap of key announcements and innovations directly from the Startup Hub at Google Cloud Next, highlighting the most impactful trends shaping the future of AI.
5 Minutes
linkCopy link to share session
Darren Mowry
Vice President
Global Startups
The future of AI: How startups build competitive moats
As the future of AI takes shape, startups are making big bets on what will matter long-term. Join leading founders for a real conversation about how they’re building moats beyond the model—what decisions paid off, which ones didn’t, and how they’re thinking about architecture, data, cost, and product today.
15 Minutes
linkCopy link to share session
Scott Barneson
Managing Director
North America Startups
Simon Hørup Eskildsen
Founder & CEO
Turbopuffer
Mukund Jha
Founder & CEO
Emergent
Felipe Moreno
CEO
Jusbrasil
Startups shipping at scale with Google DeepMind
In the AI world, your only real moat is iteration speed. Logan Kilpatrick and founders from the front lines share their "recipe" for moving fast without breaking the model. We’ll look at real workflows using Google DeepMind's models, the technical trade-offs of multimodality, and how to stay ahead of the next model release.
15 Minutes
linkCopy link to share session
Logan Kilpatrick
Group Product Manager
Google DeepMind
Michele Catasta
President & Head of AI
Replit
Eno Reyes
CTO & Co-Founder
Factory
Bianca Rangecroft
Founder & CEO
Whering
Jay Wu
Co-Founder & CTO
Opus Clip
Share
[About Google](https://www.google.com/about/)[Google products](https://www.google.com/about/products/)[Privacy](https://policies.google.com/privacy)[Terms](https://policies.google.com/terms)[Code of Conduct](https://cloudonair.withgoogle.com/code-of-conduct))(Multimodal startups: Building AI that sees, speaks & creates
9:05 AM - 9:20 AM
__Arthur SorokenBin LiuBen BuddeMatt Rouif__
The future of AI is multimodal and generative. Startup founders will discuss how they combine vision, speech, and language with tools like Imagen, Chirp, Veo, Lyria, and Gemini Live to)Show moreMay 14Claude responded: We process 400-page regulatory PDFs with dense tables, LaTeX formulas, and footnoted cross-references — currently via a specialist parser (Docling).Synthesized document-focused multimodal angles for regulatory startup panelSynthesized document-focused multimodal angles for regulatory startup panel
We process 400-page regulatory PDFs with dense tables, LaTeX formulas, and footnoted cross-references — currently via a specialist parser (Docling). When does Gemini's native multimodal document understanding beat specialist parsers for regulated-data accuracy, and what's the failure mode you'd warn us about?
We want CXOs and boards to consume regulatory briefings as voice and short video, not text walls. What's the realistic accuracy bar for Chirp + Veo + Gemini Live on dense financial-legal terminology where one mispronunciation or visual misrender breaks buyer trust?
You said: list all question (same text) and provide.list all question (same text) and provide.May 14Claude responded: Curator Research by Aidni is an AI-native regulatory intelligence platform for Indian BFSI that ingests every publication from RBI, SEBI, IRDAI, MCA, and other…Curator Research by Aidni is an AI-native regulatory intelligence platform for Indian BFSI that ingests every publication from RBI, SEBI, IRDAI, MCA, and other regulators through a 14-stage GPU pipeline, extracting rules, entities, and cross-references into a 322K-node knowledge graph. It then maps every external regulatory change to each tenant's internal policies, SOPs, and board mandates — so risk, compliance, and CXO teams act on regulatory signals in minutes instead of months.

The future of AI: How startups build competitive moats (8:35–8:50 AM)

Iteration speed vs. moat depth — our moat is a deeply specialised 14-stage GPU pipeline (deontic logic, paragraph-level amendment diffs, Indian regulatory ontology) that takes weeks to evolve. How do you balance "ship fast against the next model release" with vertical depth that can't be re-architected every quarter?
Every Gemini release shifts behaviour on our extraction prompts. What's the recommended pattern for regression-testing 30K-token system prompts and fine-tuned Gemma checkpoints against new Gemini versions before rolling forward in production?


Startups shipping at scale with Google DeepMind (8:50–9:05 AM)

We built a 322K-node graph because context windows died on 400-page Master Directions. With Gemini 3.1 Pro's long context, when does long-context-over-everything beat structured retrieval for accuracy on regulatory-grade outputs — and how do you decide where to draw that line as context windows keep growing?
We fine-tuned Gemma3-27B for deontic extraction because frontier models miss obligation density on dense regulatory prose. For a specialised vertical, is the iteration-speed-optimal bet to keep investing in fine-tuned smaller models, or to migrate to frontier Gemini with prompt engineering as it gets cheaper and smarter each release?


Multimodal startups: Building AI that sees, speaks & creates (9:05–9:20 AM)

We process 400-page regulatory PDFs with dense tables, LaTeX formulas, and footnoted cross-references — currently via a specialist parser (Docling). When does Gemini's native multimodal document understanding beat specialist parsers for regulated-data accuracy, and what's the failure mode you'd warn us about?
We want CXOs and boards to consume regulatory briefings as voice and short video, not text walls. What's the realistic accuracy bar for Chirp + Veo + Gemini Live on dense financial-legal terminology where one mispronunciation or visual misrender breaks buyer trust?


From prompts to production: Startup multi-agent workflows (9:20–9:35 AM)

We have a LangGraph + Neo4j + Milvus stack. Minimum-viable integration to qualify for Track 3 — do we migrate orchestration to ADK, or is MCP interop enough?
Can Agent Optimizer plug in custom evaluators for domain-specific failure modes (deontic misclassification, wrong graph traversal, entity ambiguity), or is it tied to Google's default eval set?


Expert insights: Live Q&A with Google Cloud experts (9:35–10:05 AM)

Vertex AI context caching — practical ceiling on cached prefix size and TTL? We have ~30K-token stable system prompts hit across millions of agent calls.
BFSI in India requires full data residency. Does Gemini Enterprise Agent Platform keep both inference and agent state in asia-south1, or does any control-plane data egress?
Path from Track 3 win to actual Gemini Enterprise Agent Gallery listing — fast-track or separate partner onboarding? Who's the right Google contact for an India-based BFSI-vertical agent?
Can Vertex AI host our fine-tuned Gemma3-27B checkpoint on the agent path, or are we restricted to first-party Gemini models?
You said: only few critical once (Expert insights: Live Q&A with Google Cloud expertsonly few critical once (Expert insights: Live Q&A with Google Cloud experts
9:35 AM - 10:05 AM
Mirabel TukimanGia LimYuan LiuYazan Mughrabi
Bring your questions and join the conversation. As our experts walk through the highlights, ask anything that comes up and get real-time insights on new launches, AI adoption, and business impact.
M
SHOW MORE)May 14Claude responded: The 4 critical ones to ask the Google Cloud experts:The 4 critical ones to ask the Google Cloud experts:

BFSI in India requires full data residency. Does Gemini Enterprise Agent Platform keep both inference and agent state in asia-south1, or does any control-plane data egress?
Path from Track 3 win to actual Gemini Enterprise Agent Gallery listing — fast-track or separate partner onboarding? Who's the right Google contact for an India-based BFSI-vertical agent?
Can Vertex AI host our fine-tuned Gemma3-27B checkpoint on the agent path, or are we restricted to first-party Gemini models?
Vertex AI context caching — practical ceiling on cached prefix size and TTL? We have ~30K-token stable system prompts hit across millions of agent calls.

Question 1 and 2 are the highest-leverage — they unlock buyers and distribution. Lead with those.You said: our question got taken.our question got taken. 1. golden data set and matrix to compare model in built context vs graph rag (cost and all). 2. some fine-tuning always helpful. tuning cheaper model first on specialized tasks.May 14Claude responded: Got it — your two questions got answered already.Got it — your two questions got answered already. These are the takeaways from the panel:

Build a golden dataset and metrics to compare in-built long context vs. GraphRAG — measure across accuracy, cost, and latency before committing to either side. Don't pick on vibes; pick on numbers.
Fine-tuning still earns its keep — start by tuning a smaller, cheaper model on the specialised task before reaching for frontier models. The economics and iteration speed favour small-and-tuned over large-and-prompted for narrow verticals.

Both directly validate what you're already doing with Aidni — your Gemma3-27B fine-tune on deontic extraction is the right shape of bet, and your next move is formalising the golden eval set so every Gemini release can be measured against your structured retrieval stack on actual numbers.
Want me to sketch what that golden dataset should look like for Aidni (size, composition, metrics, refresh cadence)?You said: Create list of people in sessions and create simple table with full meatadata and csv for me to download.Create list of people in sessions and create simple table with full meatadata and csv for me to download. also add the the webinar name at the top.May 14Claude responded: Best of Next '26 for Startups — Asia-PacificOrchestrated webinar data into structured CSV format with metadataOrchestrated webinar data into structured CSV format with metadataBest of Next '26 for Startups — Asia-Pacific
May 14, 2026 · 11:00 AM–12:40 PM GMT+8 (08:30–10:10 GMT+5:30)
SessionTime (IST)NameTitleOrganizationRoleWelcome & Keynote08:30–08:35Darren MowryVP, Global StartupsGoogle CloudHostCompetitive moats08:35–08:50Scott BarnesonMD, North America StartupsGoogle CloudModeratorCompetitive moats08:35–08:50Simon Hørup EskildsenFounder & CEOTurbopufferPanelistCompetitive moats08:35–08:50Mukund JhaFounder & CEOEmergentPanelistCompetitive moats08:35–08:50Felipe MorenoCEOJusbrasilPanelistShipping w/ DeepMind08:50–09:05Logan KilpatrickGroup Product ManagerGoogle DeepMindModeratorShipping w/ DeepMind08:50–09:05Michele CatastaPresident & Head of AIReplitPanelistShipping w/ DeepMind08:50–09:05Eno ReyesCTO & Co-FounderFactoryPanelistShipping w/ DeepMind08:50–09:05Bianca RangecroftFounder & CEOWheringPanelistShipping w/ DeepMind08:50–09:05Jay WuCo-Founder & CTOOpus ClipPanelistMultimodal startups09:05–09:20Arthur SorokenCo-Founder; Growth Hacking LeadAI Futures FundModeratorMultimodal startups09:05–09:20Bin LiuVP of Product EngineeringHeyGenPanelistMultimodal startups09:05–09:20Ben BuddeVP of RevenueElevenLabsPanelistMultimodal startups09:05–09:20Matt RouifCEO & Co-FounderPhotoroomPanelistMulti-agent workflows09:20–09:35Jamie de GuerreSenior Director, Cloud AI Outbound PMGoogle CloudModeratorMulti-agent workflows09:20–09:35Akash SharmaCEOVellum AIPanelistMulti-agent workflows09:20–09:35Maxim FateevCTOTemporalPanelistMulti-agent workflows09:20–09:35George KichukovField CTOGitLabPanelistExpert Q&A09:35–10:05Mirabel TukimanCustomer EngineerGoogle CloudExpertExpert Q&A09:35–10:05Gia LimCE, Infrastructure Modernization (Digital Natives)Google CloudExpertExpert Q&A09:35–10:05Yuan LiuCE, Applied & Generative AIGoogle CloudExpertExpert Q&A09:35–10:05Yazan MughrabiSecurity Practice Lead, AuNZGoogle CloudExpertClosing remarks10:05–10:10Darren MowryVP, Global StartupsGoogle CloudHost
23 entries · 22 unique people (Darren Mowry hosts both Welcome and Closing).Presented filePresented fileCSV includes both GMT+5:30 and GMT+8 columns so you can open it in any of: Excel, Google Sheets, Numbers, or pipe it straight into CRM/outreach tooling.Best of next 26 apac speakersTable · CSV DownloadYou said: should i have my actual image in google hackethon?should i have my actual image in google hackethon? (Who are you?
Help make it easier for your colleagues to find you to collaborate on projects
Photo
JPG, PNG format
5MB maximum
First name *
Salil
Last name *
Bhasin
What is your specialty? *
Business
What are your skills? *
pythonsqldevops
Location *
India
)?Show moreMay 14Claude responded: Yes, use a real photo — but understand what this screen is.Yes, use a real photo — but understand what this screen is. The copy ("help your colleagues find you to collaborate") tells you this is your Devpost participant profile, used for team-building and networking, not a judged part of your submission. Judges score your project, not your profile picture.
That said, a real headshot is the right call for three practical reasons: it makes you credible to potential teammates if you ever want to collaborate, it's the face Google's startup team and Customer Engineers see if they look you up after the webinar, and a profile with a real photo simply gets taken more seriously than a blank avatar or a logo. For a solo founder using this challenge partly as a distribution and relationship play, that small credibility signal is worth it.
Use a clean, professional headshot — plain background, good lighting, just you, dressed how you'd show up to a customer meeting. Not the Aidni logo (there's a separate place for that when you create the project), not a casual or group photo. The same image you'd use on LinkedIn is exactly right.
One note since you care about privacy given the BFSI context: a Devpost profile photo is reasonably public. That's normal and fine for a founder — you're already putting your name, email, and phone on pitch decks — but if you'd rather not, it's genuinely optional and won't affect your submission or judging. The fields marked with asterisks (name, specialty, skills, location) are the required ones; photo isn't.You said: Is this ok or should we trim it?Is this ok or should we trim it?May 14Claude responded: This works well as-is — you don't need to trim it.This works well as-is — you don't need to trim it.
It's already a strong profile photo: clean white background, even lighting, professional attire (navy blazer, light shirt), neutral friendly expression, and you're well-centered. That's exactly the standard for a Devpost profile or any professional platform.
The only minor thing: there's a bit more headroom (space above your head) than a typical tight headshot crop. If you want it to look slightly more polished, you could crop a little off the top and sides so your face fills a bit more of the frame — most profile photos are framed from roughly mid-chest up with minimal headroom. But this is optional and cosmetic.
One practical note: Devpost displays profile photos as small circles. With your current framing, the circular crop will still land cleanly on your face, so even uncropped it'll render fine. If you do crop, just keep it square (1:1) so it doesn't get distorted when the platform makes it circular.
Bottom line: usable right now, light crop only if you feel like optimizing. Not worth losing any time over.You said: crop and provide.crop and provide. keep space above head so face is in middle.May 14Claude responded: Done.Ran 2 commands, viewed 2 filesRan 2 commands, viewed 2 filesDone. Square 1:1 crop (800×800), face centered with headroom above, white background intact.Presented filePresented fileIt's square (so it won't distort when Devpost makes it circular), face sits in the middle with space above your head as you asked, and at 800×800 it's crisp but well under the 5MB limit. Ready to upload.Salil bhasin profileImage · JPG DownloadYou said: give a prompt to get full information from this page as downloaded csv file and interpreting which track gives us best chance to win atleast regional, get unde…give a prompt to get full information from this page as downloaded csv file and interpreting which track gives us best chance to win atleast regional, get understanding on the projects other has posted (download them all with names of team and all to analyse further). for ref (All eligible startups will receive $500 in credits and a chance to win a share of a $90,000 prize pool!
The Challenge: From Prototype to Production
Ready to build an autonomous system that drives real business results for your startup? The Google for Startups AI Agents Challenge is your fast-track from prototype to deployment. Get hands-on with Gemini, the recently upgraded Agent Development Kit (ADK), and a complete toolchain to rapidly build, optimize, and manage the entire agent lifecycle.
This challenge gives you the sandbox and resources to build for reliability before pushing to production. Whether you are architecting a net-new system from scratch or hardening an existing system, choose one of our three tracks to build an agent that doesn't just respond, but acts.
Challenge Tracks
Track 1: Build (Net-New Agents)
Start with a blank canvas and a complex business problem. In this track, you will leverage the Agent Development Kit (ADK)—or your preferred open-source framework like LangChain or CrewAI—to architect a net-new autonomous agent. Your goal is to move from static code to declarative intent. Show us how your agent uses the Model Context Protocol (MCP) to securely connect to external tools, gather context, and execute tasks autonomously.
Track 2: Optimize (Existing Agents)
Got an agent that works in a sandbox but struggles with the edge cases of the real world? This track is about treating AI quality as a rigorous engineering discipline. Bring your existing experimental agent and use our new optimization tools. You will stress-test multi-step reasoning, debug stalled logic, and programmatically refine your system instructions to achieve production-grade reliability and enterprise scale.
Track 3: Refactor for Google Cloud Marketplace & Gemini Enterprise
Got an existing agent that is ready for prime time? This track is dedicated to taking your current, functional agents and refactoring their architecture to meet the requirements of the Google Cloud ecosystem. This is your opportunity to transform an MVP into a scalable, monetizable asset prepped for listing on the Google Cloud Marketplace and within Gemini Enterprise.
Prize Pool
$60,000 in cash prizes
$37,500 in Google Cloud credits
Virtual coffee with Addy Osmani and other Google Cloud and DeepMind experts'
VIP tickets to Google event in the Bay Area
Social promo on Google social channels
Submission Deadline
Projects are due by 5:00 PM PT on June 5th, 2026.
Questions
For any challenge questions please reach out to laurel@devpost.com
Project requirements
Idea pitch or technical demo
Project categories
Theme
Build (Net-New Agents)
Optimize (Existing Agents)
Refactor for Google Cloud Marketplace & Gemini Enterprise
Criteria
Technical Implementation (30%)
Business Case (30%)
Innovation & Creativity (20%)
Demo and Presentation (20%)
Awards
Overall Grand Prize
Top scoring project.
1 winner
• $15,000 in USD • $10,000 in Google Cloud Credits for use with a Cloud Billing Account • Virtual Coffee with Addy Osmani and Google Cloud experts • VIP tickets to Google event in the Bay Area • Social Promo on Google social channels
Best of each Theme
Top Scoring Project in each of the themes (Build, Optimize, Refactor)
3 winners
• $10,000 in USD • $7,500 in Google Cloud Credits for use with a Cloud Billing Account • Virtual Coffee with Google Cloud experts • VIP tickets to Google event in the Bay Area • Social Promo on Google social channels
Regional Winners
Top Scoring Project in each region (APAC & EMEA)
2 winners
• $5,000 in USD • $2,500 in Google Cloud Credits for use with a Cloud Billing Account • Virtual Coffee with Google Cloud Experts • Social Promo on Google social channels
Announcements
RSVP: Google for Startups AI Agents Kickoff Call (Tomorrow)
Additional details
Track 1
Track 2
Track 3
Key Considerations for Participants
Mandatory Technologies
Resources
﻿Official Rules
Additional Questions
Registered!
Unregister
3 registration questionsEdit answers
Organizers
Jess Huang
Schedule
Timezone: IST
Apr 22, 2026
09:30pm    
Submissions open
May 15, 2026
01:30am    
Challenge kickoff
Intro session hosted by Addy Osmani
Jun 06, 2026
05:30am    
Submissions deadline
Jun 08, 2026
09:30pm    
Judging Prep
Jun 11, 2026
09:30pm    
Judging Period Begins
Jun 19, 2026
05:30am    
Judging Period Ends
Jun 23, 2026
02:30am    
Winners announced!
Projects
People
Search projects
Filter
382 results
Status
Title
Team
Team Building
project thumbnail
idea
key account intelligence
user avatar image
CLOSED
project thumbnail
idea
Sukhi : Unified Health Intelligence Layer
user avatar image
CLOSED
project thumbnail
idea
Ai assistance for Student.
user avatar image
CLOSED
project thumbnail
idea
Finance agent for one-person company
user avatar image
OPEN
project thumbnail
idea
DocPod Enterprise: Accessible AI Learning Orchestrator
user avatar image
CLOSED
project thumbnail
idea
Charles' project
user avatar image
OPEN
project thumbnail
idea
Lumicoria
user avatar image
OPEN
project thumbnail
idea
SmartDev Agent
user avatar image
OPEN
project thumbnail
idea
SabiRight
user avatar image
OPEN
) i will run your provided prompt in claude in chrome.Show moreMay 14Claude responded: Here's a prompt to run in Claude in Chrome on the Devpost challenge page.Here's a prompt to run in Claude in Chrome on the Devpost challenge page. It's structured in two phases because the data you want spans multiple pages.

Prompt to paste into Claude in Chrome:
You are on the Devpost page for the "Google for Startups AI Agents Challenge."
I need you to do two things: extract all submitted projects into a CSV, and
analyze which track gives me the best chance of winning.

PHASE 1 — SCRAPE ALL PROJECTS
Go to the "Projects" tab. There are ~382 projects across multiple pages.
For EVERY project on EVERY page (paginate through all of them — do not stop
at page 1), collect:
- Project name
- Team name / member names
- Status (Open / Closed for team building)
- Project type (idea / demo / etc.)
- Track/theme if shown (Build / Optimize / Refactor)
- Short tagline or description if visible
- Project URL

Compile into a single CSV with one row per project. Use these exact column
headers: project_name, team, status, type, track, description, url
If a field isn't available for a project, leave it blank — do not skip the row.
Output the CSV in a code block so I can copy it, and also give me a count
confirming how many projects you captured vs the 382 total.

PHASE 2 — ANALYSIS
After the CSV, give me a written analysis covering:
1. Track distribution — how many projects in each of the 3 tracks (Build /
   Optimize / Refactor), and which track is least crowded.
2. Theme patterns — what problem areas are most common (e.g. coding agents,
   health, finance, student/edu, sales). Note saturated categories.
3. Maturity — rough split of "idea" vs working-demo submissions.
4. Given the judging criteria (Technical Implementation 30%, Business Case
   30%, Innovation & Creativity 20%, Demo & Presentation 20%) and the award
   structure (Overall Grand Prize, Best of each Theme x3, Regional Winner
   APAC x1), tell me: for an APAC-based, production-grade vertical AI product
   (regulatory-intelligence platform for Indian BFSI — existing system with a
   322K-node knowledge graph, multi-agent stack, already functional), which
   of the 3 tracks gives the best realistic chance at (a) Best of Theme and
   (b) APAC Regional Winner. Factor in how crowded each track is and how my
   maturity level compares to other submissions in that track.
5. Name the specific competing projects (from the data you scraped) that
   would be my closest rivals in the recommended track.

Be concrete and quantitative wherever possible. Don't pad.

Two practical notes before you run it:
The scrape may need nudging — Devpost paginates and sometimes lazy-loads. If Claude stops early, follow up with "continue from page X" or "you only got 60, keep going through all pages." Browser agents are reliable but can lose patience on long pagination loops, so verify the final count lands near 382.
On the analysis itself: you may already know the answer. Track 3 (Refactor for Marketplace) is almost certainly your best shot — it's the least crowded because most hackathon entrants don't have a production-ready system, and your maturity level is the differentiator there rather than something you'd have to fake. The prompt asks Claude to confirm this against real data rather than assume it, which is what you want. But if the scrape shows Track 3 is unexpectedly crowded with serious teams, that's exactly the intelligence you need before committing — so let the data talk.
If Claude in Chrome struggles to export a clean CSV inline, add: "save the CSV as a downloadable file" — though copying from a code block into a file is usually faster and less error-prone.You said: event date in ist ?Additional details
Examples

﻿

To help visualize what you can build for the challenge, imagine tackling complex, multi-step workflows, some where multiple specialized agents collaborate.

To improve hiring practices, you could build an Automated Talent Sourcing Agent that screens inbound resumes agpastedevent date in ist ? should i attend ? (05/14/2026 at 01:39am
RSVP: Google for Startups AI Agents Kickoff Call (Tomorrow)
Mark your calendar. We're hosting the official kickoff for the Google for Startups AI Agents Challenge TOMORROW and we'd love for you to be there!Addy Osmani, Director of Google Cloud AI, will walk through the Gemini Enterprise Agent Platform, demo each of the three tracks, and leave time at the end for a Q&A.AI Agents Challenge: Kickoff Call and Q&A
Thursday, May 14 · 1:00 to 1:30 PM PT
Register through this form and we'll send you a Calendar invite here: __https://forms.gle/aMGsQAzA4gMd3hS2A__Space is limited, so don't miss it. See you Thursday!The Google for Startups AI Agents Challenge Team)Show moreMay 14Claude responded: IST conversion: Thursday, May 14, 1:00 PM PT = Friday, May 15, 1:30 AM IST (PT is 12.IST conversion: Thursday, May 14, 1:00 PM PT = Friday, May 15, 1:30 AM IST (PT is 12.5 hours behind IST). This matches the Devpost schedule you pasted earlier — it lists "May 15, 01:30am — Challenge kickoff, intro session hosted by Addy Osmani." Same event.
Should you attend? Yes — and here's the honest cost-benefit.
The case for attending live: it's the same Addy Osmani who's the Grand Prize "virtual coffee," so face time matters. He's demoing each of the three tracks and — most importantly for you — walking through the Gemini Enterprise Agent Platform in detail. Given your Track 3 questions (A2A protocol, Marketplace listing path, data residency, custom Gemma checkpoints), the live Q&A is your single best shot at answers from someone with actual authority. And it's only 30 minutes.
The case against: it's 1:30 AM IST. You'll have just attended the Best of Next webinar earlier the same day. Two AI events in one day, one in the dead of night.
My recommendation: Register either way (the form just sends a calendar invite — costs nothing, and registration may itself be a signal Google tracks). Then decide based on one thing: whether you'll have a Track 3 question ready to ask live. If yes, attend — the Q&A is worth losing sleep over. If you're too foggy to ask something sharp, let the recording cover it; kickoff calls are almost always recorded and the demo content will be in the resource guide anyway. The Q&A is the only part that doesn't reproduce.
One thing worth noting from the document you just shared — Track 3 now has hard architectural mandates, not just vibes:

B2B focus — Curator qualifies cleanly.
Cloud-native runtime — you must migrate the agent runtime natively to Cloud Run or GKE. Your stack is currently Azure/GCP-federated via Tailscale, so this is real migration work.
Gemini-powered intelligence — the reasoning engine must run on Gemini, or a third-party LLM deployed exclusively through Agent Platform. This is the big one: your fine-tuned Gemma3-27B enrichment pipeline would need to either move onto Agent Platform or be scoped out of the "agent" boundary. This is now your most important webinar question.
A2A interoperability — your agent's comms layer must use the A2A protocol so other enterprise agents can discover it.

So Track 3 is still your best strategic fit, but it's not a light refactor — it's a genuine architecture migration. That actually sharpens why the kickoff Q&A matters: you need to know how strict "exclusively through Agent Platform" is before you commit a month of solo founder time. Add this to your list:
"Track 3 mandates the reasoning engine run on Gemini or a third-party LLM exclusively via Agent Platform. We run a fine-tuned Gemma3-27B for domain-specific extraction. Can a custom Gemma checkpoint served through Agent Platform satisfy this, or does the extraction layer need to sit outside the 'agent' boundary to comply?"
That's the question that determines whether Track 3 is viable for you. Ask it live if you attend; post it in the challenge forum if you don't.You said: form is asking question or query.form is asking question or query. give a single question to ask.May 14Claude responded: For an existing production multi-agent system that uses a fine-tuned open-source model (Gemma3-27B) for domain-specific extraction, does Track 3's "third-party…For an existing production multi-agent system that uses a fine-tuned open-source model (Gemma3-27B) for domain-specific extraction, does Track 3's "third-party LLM deployed exclusively through Agent Platform" mandate allow a custom Gemma checkpoint served via Agent Platform, or must the reasoning engine be swapped entirely to Gemini?You said: but we dont have the fine tuned model right now.but we dont have the fine tuned model right now. it way forward in our plan. any better one?May 14Claude responded: Got it — then don't anchor the question to something you haven't built.Got it — then don't anchor the question to something you haven't built. Ask the one that actually unblocks your decision right now:
For an existing production multi-agent system (LangGraph orchestration, Neo4j + Milvus retrieval) that already runs partly on GCP, what's the realistic scope of Track 3's "migrate runtime natively to Cloud Run/GKE" and "A2A interoperability" mandates — is this a light refactor or a full re-architecture, and is it achievable solo within the submission window?
That's the question whose answer changes what you do next. It tells you whether Track 3 is viable for a solo founder in the time available, which is the real thing you're trying to find out.You said: Lets analyse the data carefully.devpost_google_ai_agents_SUBMITTED_ONLY.csvcsvdevpost_google_ai_agents_RICH_IDEAS.csvcsvdevpost_google_ai_agents_all_projects_FULL.csvcsvcompetitive_intelligence_full_report.mdmddevpost_google_ai_agents_all_projects_FULL.jsonjsondevpost_google_ai_agents_challenge_projects.csvcsvcompetitive_analysis_rivals.txt118 linestxtLets analyse the data carefully. Lets also identify if we can re-purpose anything from our git project bbb for this submission. Target is to win the hackethon so analyse fully and provide next steps. if you can not access my git bbb repo, let me know and i will attach key dirs or you can give a prompt to run on claude code cli to get the information.May 14Claude responded: I've gone through all seven files — the scrape, the rich-ideas subset, the submitted-only set, and your competitive intel report.Ran 7 commands, viewed a fileRan 7 commands, viewed a fileI've gone through all seven files — the scrape, the rich-ideas subset, the submitted-only set, and your competitive intel report. Here's the full read.
What the data actually says
Your scrape captured 383 projects. The submission picture (using the real submission flag, not the team-building open/closed status):
TrackRegisteredSubmittedSubmitted with a real descriptionBuild (Net-New)1782722Optimize (Existing)401211Refactor (Marketplace)1311No track yet1520—
Two facts jump out. First, 38 of 40 submitters are solo — being a sole founder is the norm here, not a disadvantage. Second, Refactor is nearly empty and the one submitted entry is unrelated to you (Dimona's project — a code-review/security agent).
Who actually threatens you
I pulled every regulatory / compliance / finance / knowledge-graph project across all 383 — there are 24. Most are generic. The ones that matter:
ARIA — Automated Regulatory Intelligence Agent [15965] is your only true domain rival: Indian BFSI, regulatory, SEBI-focused. But look closely — it's KYC onboarding for PMS firms (6 sub-agents, document intake → risk scoring → human decision). That's a narrow workflow, not a regulatory-corpus intelligence platform. It's in Build, still Idea stage, solo founder. Different wedge, different track, far less system depth than Curator. It's the one to watch, not fear.
The rest are adjacent, not competing: Clausely AI (legal drafting), A.I.G.F. Governance Guardian (EU AI Act / AI-governance compliance — submitted, but different domain), NexClinicalMind (FDA clinical-trial compliance — pharma), WorkorAI (self-hosted hiring — but note it's a Refactor entry with a data-residency angle, so architecturally instructive). QLD2032 (Australian construction procurement) is your closest architectural analog — solo founder, vertical, data-heavy, "Agentic Data Cloud pattern" — but wrong domain and geography.
Bottom line: nobody is building what you're building. The regulatory vertical has 24 names but only ARIA is in your lane, and ARIA is a thinner system in a different track.
Track recommendation: Refactor — and not just because it's empty
Your intel report concludes Refactor; I agree, but the reason matters more than the emptiness. Refactor has hard entry mandates — B2B focus, runtime migrated natively to Cloud Run/GKE, Gemini-powered reasoning (or third-party LLM exclusively via Agent Platform), A2A protocol. Those mandates are a filter that screens out everyone without a real production system. 178 people picked Build because you can enter Build with a weekend prototype. Almost nobody can credibly enter Refactor — and you're one of the few who can. The barrier is the moat.
Honest counterpoints you should weigh:

It's the most actual work. Your stack is Azure/GCP-federated over Tailscale. "Migrate runtime natively to Cloud Run/GKE" plus implementing A2A is real engineering, not a reskin.
Thin fields attract late floods. 13 registered today; June 5 is weeks away. Don't assume it stays this empty.
The cross-track prizes are where ARIA still meets you. APAC Regional ($5K) and Grand Prize ($15K) are cross-track. Even in Refactor, you're compared against ARIA and QLD2032 for those. Your edge there is system depth — Curator is a far bigger build than ARIA's onboarding flow — but only if the demo shows that depth.

Net: Refactor for Best-of-Theme (very winnable — 1 unrelated rival), and your production maturity is the wedge for APAC Regional regardless of track.
What to repurpose from bbb — and what not to
I can't see your repo. But from your three decks I know the architecture, and the key strategic point is this: do not try to refactor the whole 14-stage pipeline. That's a trap — it's too much, and most of it (Docling parsing, GPU enrichment, RAPTOR) isn't "the agent." For a Refactor submission you carve out one agent workflow, migrate that slice cleanly, and demo it.
Likely reusable as-is or with light work:

The unified MCP server (28–44 tools) — this is your single biggest asset for the Refactor mandate. MCP interop is half the A2A story; you've already built it.
Bija orchestrator (LangGraph) — ADK explicitly allows supported open-source frameworks, so LangGraph likely stays. Confirm at the kickoff Q&A.
A slice of the Neo4j graph — for grounding the demo. Not all 322K nodes; a coherent subgraph.
One vertical workflow — the Circular → Policy gap-analysis loop is the obvious demo candidate: it's visual, it "acts," and it shows multi-agent collaboration.

Likely not reusable for the submission boundary:

The GPU enrichment pipeline (Gemma3-27B, vLLM, Triton) — keep it running your product, but it sits outside the "agent" you submit. The submitted agent's reasoning runs on Gemini.
Azure-pinned infra, Tailscale mesh, supervisord process orchestration.

To advise precisely, I need to see the repo's shape. Run this in Claude Code CLI at the bbb root and paste me the output:
Analyze this repo and produce a concise inventory for a hackathon-submission planning task. I need:

1. TOP-LEVEL STRUCTURE: tree of directories 2 levels deep, with a one-line purpose for each major dir.

2. THE AGENT/ORCHESTRATION LAYER: locate the Bija orchestrator and any LangGraph code. List the files, the graph/state-machine definitions, and how agents are defined and invoked. How many distinct agents/nodes exist?

3. THE MCP SERVER: locate it. List every tool it exposes (names + one-line purpose). Note how routing works. Roughly how many LOC, and what are its external dependencies?

4. DEPLOYMENT & RUNTIME: find all Dockerfiles, compose files, deploy scripts, supervisord configs. For each service, note: what it runs, what cloud/infra it's pinned to, and whether it's stateless enough to run on Cloud Run.

5. GCP vs AZURE COUPLING: grep for anything Azure-specific, Tailscale-specific, or hard-coded infra. Flag what would break if moved to a clean GCP-native deployment.

6. THE CIRCULAR-TO-POLICY WORKFLOW: locate the code for the circular-watcher → tenant Milvus hybrid-search → policy-proposal pipeline. List the files and trace the call path end to end.

7. MODEL CALLS: grep for every LLM call site. Which use Gemma/vLLM, which use Gemini, which use Claude/Anthropic. Note the file and purpose of each.

Output as a structured markdown report. Do not modify any files. Be concise — purpose lines, not full code dumps.
That tells me exactly what's liftable, what's a migration cost, and which workflow makes the cleanest demo.
Next steps, in order

Tonight/tomorrow: Register for the kickoff call (Fri May 15, 1:30 AM IST) or plan to watch the recording. Submit your one Refactor-scoping question.
Run the Claude Code inventory prompt above and send me the output.
Lock the track to Refactor on Devpost — but don't over-commit publicly until step 4.
Pick the one workflow to refactor. My prior: the Circular → Policy gap-analysis loop. We confirm once I see the repo.
Scope the migration honestly — once I see the Azure/Tailscale coupling, we'll know if Cloud Run migration of that one slice is a weekend or three weeks. That determines whether Refactor is realistic solo by June 5, or whether Optimize is the safer medal.
Watch ARIA [15965]. If it converts from Idea to a strong submission, it's your cross-track rival for APAC Regional. Your counter is depth — make the demo show Curator is a platform, not a workflow.

Send me the repo inventory and I'll turn this into a concrete build plan with the migration scoped.● 3 Explore agents finished (ctrl+o to expand)
   ├ Inventory structure, Bija orchestrator, MCP server · 40 tool uses
      · 73.4k tokens
   │ ⎿  Done                                                    
   ├ Deployment runtime and GCP/Azure coupling · 30 tool uses · 65.8k 
     tokens
   │ ⎿  Done pastedMay 14Claude responded: This is exactly what I needed.This is exactly what I needed. The inventory changes the plan from "vague ambition" to "specific, scoped, and — with one key decision — actually feasible solo by June 5." Here's the full read.
The headline: don't refactor BBB. Carve out one agent.
A full Track 3 refactor of BBB is a trap, and the inventory proves it. Section 5 lists the killers: Tailscale 100.x IPs hardcoded across 15+ scripts, AWS IAM-role S3 client, Azure VM control scripts, stateful DBs that can't run on Cloud Run, a services registry that assumes the mesh. That's months of cross-cloud migration work. You cannot do it solo in three weeks and you shouldn't try.
But Track 3 never asked you to. It asks you to submit one agent that is B2B, Cloud-Run-native, Gemini-reasoned, and A2A-speaking. So the entire strategy is choosing the right agent to carve out — and the inventory makes the choice obvious.
The submission: the Circular → Policy Agent
Section 6 hands you the answer. The Circular→Policy workflow is 80% built, and the missing 20% — the diff-generator agent — is real work that you need for the product anyway. That's the perfect hackathon artifact: a genuine build, not a reskin, with scaffolding already in place (self_improvement.OntologyProposal, RelationshipProposal).
Why this carve-out is the right one:

It "acts." The judges' examples (energy agent, IT incident agent) all take action. "RBI publishes a circular → agent decomposes the obligations → maps each to tenant SOPs → generates the policy diff and impact analysis → routes to the owner" is a textbook agentic workflow and a killer 3-minute demo.
The model mandate solves itself. The diff-generator doesn't exist yet — so you build it fresh on Gemini. You never have to rip Gemma4 out of your enrichment pipeline, because enrichment is upstream of this agent. The agent consumes already-enriched data. Gemma stays in your product; the submitted agent is 100% Gemini reasoning by construction.
The stateful layer becomes "grounding," not a migration problem. Track 3's key considerations explicitly say to "employ Grounding... with private data" and RAG. Your Neo4j graph and Milvus collections are the grounding source — accessed as tools, not refactored. The thing that has to be Cloud-Run-native is just the agent's orchestration logic, which is genuinely stateless.
One competitor, unrelated. Refactor has 1 submitted entry (Dimona — code review). ARIA is Build-track, Idea-stage, and a narrow KYC-onboarding flow — not corpus intelligence. Nobody is near you here.

How the four Track 3 mandates get satisfied
MandateHow you meet itWork requiredB2B focusCurator serves BFSI compliance teamsNone — already trueCloud-native runtimeDeploy only the agent logic on Cloud Run. Stateful DBs stay off-Cloud-Run as grounding backendsMedium — see the data-layer decision belowGemini reasoningBuild the diff-generator fresh on Gemini; gemini_router.py + gemini_sdk_client.py already existLow — by constructionA2A interoperabilityWrap the agent so it's discoverable and can coordinate (e.g., hand off to a downstream "audit-pack agent")Medium — unfamiliar, this is your real risk
The one decision that makes this feasible: managed data backends
Your single biggest blocker is Tailscale — the Cloud Run agent can't reach a mesh-pinned Milvus/Neo4j. Don't solve this by de-meshing BBB. Solve it for the submission only: stand up Neo4j Aura and Zilliz Cloud (managed Milvus), both with GCP-region options, loaded with a coherent subset of your regulatory graph and the Matryoshka collections. The Cloud Run agent hits those over authenticated endpoints — zero Tailscale, zero AWS IAM, clean.
Your real product keeps its mesh. The submission gets a clean, demoable, fully-GCP data path. This decision converts the infra work from "impossible" to "a few days."
What to reuse, drop, and build
Reuse directly:

The Bija LangGraph pattern (orchestrator.py, StateGraph) — the diff-agent is a new graph in the same idiom. Don't rewrite in ADK unless the kickoff says you must.
The 6-agent proposer/judge pattern — repurpose it: instead of optimist-vs-skeptic debating a feature, agents decompose a circular line into multiple requirements, match against tenant policies, diff, and a judge scores impact. That directly answers your earlier "one RBI line → multiple requirements" question.
circular_watcher.py steps 1–4 (watch → embed → hybrid-search → proposal) — these work.
self_improvement.py scaffolding — OntologyProposal.propose_changes() is your diff-agent skeleton.
The product-relevant MCP tools only: query_milvus, get_neo4j_node_count, parse_document, parse_structure, the vector_graph_tools module.

Drop from the submission entirely:

The 56-tool MCP server as-is. Critical realization: ~48 of those 56 tools are internal devops (service_status, query_tsdb, search_code, remote_exec...). Ship a small clean MCP surface of just the 6–8 grounding tools the agent needs. The big MCP server is product infrastructure, not a submission asset.
The supervisord mesh, Azure VM scripts, Tailscale routing, exec-api, the AWS-IAM S3 client (libs/object_store/client.py — use GCS for the submission).
The Gemma4/vLLM enrichment pipeline — upstream, out of scope.

Build fresh (this is the hackathon work):

The diff-generator agent — Gemini-powered, the core IP. Decomposes obligations, maps to tenant policy nodes, generates diff + impact. Scaffolding exists.
A2A wrapper — discoverable agent endpoint.
Clean Cloud Run deployment of just the agent.
Managed data layer — Neo4j Aura + Zilliz Cloud with a scoped data subset.

Three-week plan
Week 1 — the agent. Build the diff-generator on Gemini, reusing the Bija graph pattern and self_improvement scaffolding. Wire it into steps 1–4 of circular_watcher locally. Goal: end-to-end working against your existing data, mesh-side. This is the highest-value week and it's pure product work — valuable even if you pivot off Track 3.
Week 2 — the infra. Stand up Neo4j Aura + Zilliz Cloud, load the subset. Containerize just the agent, deploy to Cloud Run (asia-south1 — you already have workers/cloudrun/deploy.sh as a starting point). Repoint the agent's grounding tools at the managed backends. Add the A2A wrapper.
Week 3 — the submission. 3-minute demo video (circular lands → decomposition → mapping → diff → owner routing), the write-up, architecture diagram, repo cleanup with an open-source license. Buffer for what slips.
Open risks and kickoff questions
Three things you must confirm on the Friday kickoff call before going all-in:

"Does LangGraph count as a supported framework, or must orchestration be ADK?" The rules say "LangChain, CrewAI" — LangGraph is LangChain's, so likely yes. If yes, you keep Bija's architecture and save a week. If no, the plan needs rework. This is your single most important question.
"What's the minimum viable A2A implementation?" — Is it a protocol wrapper, or does it require Agent Engine deployment? This determines whether Week 2's A2A work is two days or two weeks.
"Can grounding backends live outside Google Cloud (managed Neo4j Aura / Zilliz), or must private data sit in Vertex AI Search / GCP?" If they mandate GCP-resident grounding, you'd use Vertex AI Search or a GCP-hosted vector store instead — workable, but changes Week 2.

Honest go/no-go
Track 3 is the right call if the kickoff answers on LangGraph and A2A come back favorable. The carve-out makes it feasible; the managed-backend decision makes it feasible; the diff-agent is real product value regardless. Your production maturity is a genuine moat in a near-empty field.
The fallback, if A2A turns out to be a multi-week rebuild: Track 2 with the Bija brainstorm orchestrator — it's already a mature 6-node multi-agent system, Track 2 has no Cloud Run or A2A mandate, and "harden a multi-agent regulatory-analysis system with Agent Simulation + Optimizer" is a legitimate submission. Weaker field position than Refactor (11 real competitors) but far less infra risk.
Start Week 1 now — the diff-agent is needed either way. Decide Track 2 vs 3 the moment the kickoff Q&A ends. Want me to draft the diff-generator agent's graph design — node structure, state schema, and how the "one circular line → N requirements" decomposition flows through it?You said: If i understand right, we will take few circulars and ammendment data from our project to gcp vm (tsdb, neo4j, milvus) and setup basic small vm for hosting the…If i understand right, we will take few circulars and ammendment data from our project to gcp vm (tsdb, neo4j, milvus) and setup basic small vm for hosting these, then we will create bank policy and sop using an older version of RBI direction and keep them mapped and reviewed against each other, new amendment comes in along with revised full master direction, we run it through the agent to find change requirement and suggest changes and also qna later. one example for demo video right? or should it be working end to end with latest updated knowledge base for actual bfsi to come to google market place and use it???May 14Claude responded: Your demo plan is right.Your demo plan is right. Your worry about the second option is the thing to correct.
Yes — one worked example, end to end
What you described is exactly the submission: a small GCP VM running TSDB + Neo4j + Milvus, seeded with a slice of real data — a handful of circulars, one Master Direction in two versions (old and amended), and a bank's policy/SOP set you author against the old version and keep mapped. Then the amendment lands, the agent runs, finds the change requirements, decomposes them, suggests policy edits, and answers follow-up Q&A. That's a complete, honest, end-to-end demo. It's the right scope.
The key word is vertical slice, not toy. End-to-end on narrow data — every stage real, just few documents. That beats broad-but-shallow every time with judges.
Where your thinking goes wrong: "actual BFSI to come to Google Marketplace"
You've conflated two different finish lines, and it's making the task feel impossibly big.
Finish line 1 — the hackathon submission (June 5). A working agent, demonstrated on a representative example, deployed on Cloud Run, architecturally meeting the Track 3 mandates. Judging is Technical Implementation, Business Case, Innovation, Demo — 30/30/20/20. Nothing in the rubric requires a live production system serving real banks. It requires proof the architecture is real and the agent works. Your one worked example is the proof.
Finish line 2 — an actual Marketplace listing serving real BFSI tenants. That's a months-long path: Google partner onboarding, security review, real tenant data, data-residency compliance, SLAs, contracts. It does not happen by June 5, and the hackathon doesn't ask it to. Track 3's name — "Refactor for Marketplace & Gemini Enterprise" — means architecturally prepared for, not already listed on. You're demonstrating Marketplace-readiness, not Marketplace presence.
So: don't try to run the latest full knowledge base for real banks. That's not a bigger version of the submission — it's a different project on a different timeline. Trying to reach finish line 2 by June 5 is how you end up with nothing to submit.
One sharpening of your plan
Your instinct to keep a real version-pair is good — make sure the amendment you pick genuinely produces multiple downstream policy changes from a single clause. That's your innovation showcase: the "one RBI line → N requirements" decomposition. If the amendment is too simple (one line → one change), the agent looks like find-and-replace. Pick the version-pair deliberately so the demo shows fan-out — one amended clause cascading into several SOP edits across different process owners. That's the moment that wins the Innovation score.
Also: seed the data so the demo has a clean "wow" beat — a non-obvious downstream impact a human reviewer would plausibly miss. That's what makes judges remember it.
What this means for scope
It shrinks the job to exactly what's feasible solo in three weeks:

Small GCP VM, three databases, a curated data subset — not the full corpus.
One bank's policy/SOP set, hand-authored against the old Master Direction — you control this, so make it realistic but compact.
One amendment event, chosen for fan-out.
The agent: decompose → map → diff → suggest → Q&A.
Cloud Run deployment of the agent logic, managed/hosted data backends, A2A wrapper.
A 3-minute video of that one example running end to end.

In the write-up you describe the path to a real Marketplace listing — that's your Business Case section, and saying "here's the architecture, here's what production onboarding looks like next" is exactly what they want there. You explain finish line 2; you don't build it.
Build the one example. Make it real, make it deep, make it show fan-out. That's the winning submission.
Want me to design the diff-generator agent's graph — node structure, state schema, and how the one-clause-to-many-requirements decomposition flows through it?You said: lets build the project in hackethon website first.lets build the project in hackethon website first. Refractor right?May 14Claude responded: Yes — Track 3, Refactor for Google Cloud Marketplace & Gemini Enterprise.Yes — Track 3, Refactor for Google Cloud Marketplace & Gemini Enterprise.
One caveat before you commit it as final: that Friday kickoff call (1:30 AM IST) is where you confirm the two things that could change the plan — whether LangGraph counts as a supported framework, and what minimum-viable A2A actually requires. But on Devpost the track selection isn't a binding contract; you can change it later if the kickoff reveals a blocker. So selecting Refactor now is the right move — it commits you directionally without locking you in.
Now, the Devpost project setup itself. You're not filling in the final submission today — you're creating the project shell. Devpost lets you create a project in draft and edit it freely until the June 5 deadline, so the goal right now is just to get it registered under the right track with a clean foundation.
What you'll set up:
Project name — go with something clear over clever. "Curator Research — Regulatory Change Intelligence Agent" or similar. It should say what it does; judges skim hundreds of these.
Track/theme — select Refactor for Google Cloud Marketplace & Gemini Enterprise.
The elevator pitch / tagline — one line. Something like: "An autonomous agent that decomposes RBI regulatory amendments into specific policy-change requirements and maps them to a bank's internal SOPs."
The "Problem to solve" and "Our solution" fields — you can drop in a tight version now and refine later. Don't leave them as the default placeholder text — a surprising number of your competitors did exactly that (you saw it in the scrape: half the Refactor entries still say "[What's the problem you want to solve?]"). Even a rough real answer puts you ahead.
Team — just you, solo. That's the norm here; 38 of 40 submitters are solo.
Everything else — repo link, demo video, screenshots, full description — leave blank or draft. That's the next three weeks of work.
The thing to get right today is just: correct track, real name, real pitch text instead of placeholders. Everything else is iterative.
Want me to draft the "Problem to solve" and "Our solution" text — sized to fit Devpost's fields, written to hit the Business Case and Innovation criteria — so you can paste them in now and sharpen later?You said: ok.ok. we can wait overnight but itss asking me this (Your project is visible but not yet submitted!
Your working project is now visible to other participants, but not yet officially submitted. Give it a title and description to help others understand your idea!
Project for__[Google for Startups AI Agents Challenge](https://devpost.team/google-cloud-for-startups/hackathons/3197)__
Salil's project
15/60
Project assets
Link
[Video*](https://devpost.team/google-cloud-for-startups/projects/16636/edit)
[Link](https://devpost.team/google-cloud-for-startups/projects/16636/edit#)
[Code*](https://devpost.team/google-cloud-for-startups/projects/16636/edit)
[Link](https://devpost.team/google-cloud-for-startups/projects/16636/edit#)
[Testing access: link/demo/test build, with login if private*](https://devpost.team/google-cloud-for-startups/projects/16636/edit)
[Link](https://devpost.team/google-cloud-for-startups/projects/16636/edit#)
[Architecture diagram*](https://devpost.team/google-cloud-for-startups/projects/16636/edit)
[Link](https://devpost.team/google-cloud-for-startups/projects/16636/edit#)
[Add](https://devpost.team/google-cloud-for-startups/projects/16636/edit#)
Description
Ready to start building? Check out this __[guide](https://services.google.com/fh/files/misc/ai_agents_challenge_designed_guide.pdf)__ for next steps.
Problem to solve
[What's the problem you want to solve?]
Our solution
[What are you building? Summarize the key features and how your agent functions.]
Technologies used
[List the Google Cloud and other technologies powering your project — e.g., Gemini, ADK, Vertex AI, Cloud Run, GKE, MCP, A2A, LangChain, CrewAI, etc.]
Data sources
[List any data sources, APIs, or knowledge bases your agent connects to or relies on.]
Findings and learnings
[What did you discover while building this? Any surprises, challenges, or insights worth sharing?]
Third-party integrations (if applicable)
[List any third-party SDKs, APIs, data, or content used, and confirm you have rights/authorization to use them.]
Submission questions
Only visible to hackathon organizers & judges
On a scale from 1-5, how familiar are you with Google Cloud products? (1=none, 5=expert)
*
[Answer](https://devpost.team/google-cloud-for-startups/projects/16636/edit#)
On a scale from 1-5, how familiar are you with Google AI Studio? (1=none, 5=expert)*
[Answer](https://devpost.team/google-cloud-for-startups/projects/16636/edit#)
Describe the readiness of your project for launch.
*
[Answer](https://devpost.team/google-cloud-for-startups/projects/16636/edit#)
Which specific feature of Agent Platform was most critical to your project's impact, and what is one thing it’s currently missing?"
*
[Answer](https://devpost.team/google-cloud-for-startups/projects/16636/edit#)
If you could add one specific API capability or integration that would have saved you 2+ hours of work, what would it be?
*
[Answer](https://devpost.team/google-cloud-for-startups/projects/16636/edit#)
[Comments](https://devpost.team/google-cloud-for-startups/projects/16636/edit#)[Image](https://devpost.team/google-cloud-for-startups/projects/16636/edit#)Joined!
__[Leave project](https://devpost.team/google-cloud-for-startups/projects/16636/edit#)__
Project details
Created
May 14, 2026
Status
idea
Theme
Refactor for Google Cloud Marketplace & Gemini Enterprise
Team
Team building
[Open](https://devpost.team/google-cloud-for-startups/projects/16636/edit#)
[Closed](https://devpost.team/google-cloud-for-startups/projects/16636/edit#)
Teammates neededAnyone can join
Any skill set
[Teammate needed](https://devpost.team/google-cloud-for-startups/projects/16636/edit#)
Current members__[Salil Bhasin](https://devpost.team/google-cloud-for-startups/users/40877/profile)__(guest)
Business / India
[Invite teammate](https://devpost.team/google-cloud-for-startups/projects/16636/edit#)
Hackathons[Create hackathon](https://devpost.team/google-cloud-for-startups/templates#t=custom)[My hackathons](https://devpost.team/google-cloud-for-startups/hackathons?my_hackathons=%E2%9C%93)[Browse all hackathons](https://devpost.team/google-cloud-for-startups/hackathons)
Projects[My projects](https://devpost.team/google-cloud-for-startups/projects?my_projects=%E2%9C%93)[Browse all projects](https://devpost.team/google-cloud-for-startups/projects)
People[Find teammates](https://devpost.team/google-cloud-for-startups/people)
Devpost for Teams[Help docs](https://help.devpost.team/)[Contact](mailto:help@devpost.team)) should we keep it ready? how will i get the credits on gcp and a2a serverless?  also it says visible so we should complete the form pending few items like post completion demo and all.Show moreMay 14Claude responded: Good — you've got the project shell created (#16636), correctly under the Refactor theme.Good — you've got the project shell created (#16636), correctly under the Refactor theme. Let me answer your three questions in order, then tell you what to actually do tonight.
Should you fill the form tonight?
Partially. Here's the split:
Fill tonight — the fields you can answer truthfully right now without having built anything:

Title (currently "Salil's project") — change it. Use something clear like "Curator — Regulatory Change Intelligence Agent."
Problem to solve and Our solution — replace the [placeholder] text. Even a rough real version beats placeholders, and "visible to other participants" means rivals can see your project page now. No reason to show them placeholder text.
Technologies used / Data sources — you know these already (Gemini, Cloud Run, LangGraph, MCP, A2A, Neo4j, Milvus, RBI corpus).

Leave for later — anything that requires the work to exist:

Video, Code link, Testing access, Architecture diagram (the four assets marked *)
Findings and learnings
The 5 submission questions, especially "Describe the readiness of your project" and the two Agent Platform questions — those need you to have used Agent Platform first. Answering them now would be guessing.

So: clean up the public-facing description tonight, leave the build-dependent fields blank. The form saves as draft and stays editable until June 5. "Visible but not submitted" is the correct state to be in — don't rush to "submitted."
One thing to note: the four asset fields and the five submission questions are marked required (*). You cannot officially submit until those are filled. That's fine — that's literally the next three weeks of work. Don't let the asterisks pressure you.
How you get the GCP credits
The $500 in credits comes through the challenge itself — registered participants get them; it's not something you compete for. The exact mechanism (a coupon code, or credits applied to a billing account) almost always gets sent by email to registered participants or announced at the kickoff call. You haven't missed anything — it typically lands around or just after kickoff. Watch for it at Friday's kickoff call and in challenge emails from Devpost. If it hasn't arrived by a day after kickoff, email laurel@devpost.com (the contact listed on the challenge page).
Important reality check: $500 is not much. A small always-on GCP VM running Neo4j + Milvus + TSDB plus Cloud Run plus Gemini API calls will eat that quickly over three weeks. Two things to do:

Apply separately to the Google for Startups Cloud Program (cloud.google.com/startup) — that's the up-to-$350K credits track, completely separate from the hackathon's $500. Aidni is a registered MSME, so you likely qualify. This is the one that actually funds your build.
Keep the demo VM small and shut it down when you're not actively working. You don't need it always-on until the final demo recording.

A2A "serverless" — clearing up the concept
A2A (Agent-to-Agent protocol) isn't itself a serverless product — it's a communication protocol that lets agents discover and talk to each other. The "serverless" part is where you run the agent that speaks A2A: you deploy your agent on Cloud Run (serverless — scales to zero, you pay per request, no VM to manage), and that agent exposes an A2A-compliant interface so other enterprise agents can find and coordinate with it.
So the architecture is: your agent logic runs serverless on Cloud Run, speaks A2A outward, and reaches back to your data backends (Neo4j/Milvus) as grounding tools. The stateful databases are not serverless — they run on that small VM or on managed services (Neo4j Aura, Zilliz). Only the agent is serverless.
But — exactly how you're expected to implement A2A (a protocol wrapper you write yourself? a feature of Agent Engine? something ADK gives you?) is one of the two open questions I flagged. That's a kickoff-call question. Don't guess at it tonight.
What to actually do tonight

Rename the project from "Salil's project" to a real title.
Paste real Problem/Solution/Technologies/Data-sources text (I can draft these now — sized to Devpost's fields).
Leave the four asset fields and five submission questions blank.
Set team status — since you're going solo, set it to Closed for team building unless you actually want a teammate. Right now it appears open to "anyone can join."
Friday kickoff call: get the credit-distribution mechanism, ask the LangGraph question, ask the A2A-implementation question.

Want me to draft the Problem to solve, Our solution, Technologies used, and Data sources text right now so you can paste them in and close the laptop?You said: something better than this (Curator — Regulatory Change Intelligence Agent.something better than this (Curator — Regulatory Change Intelligence Agent.)? or its fine? provide filled text for this, just a basic to start with as other participants can see it. we will finalise it overtime (Ready to start building? Check out this __[guide](https://services.google.com/fh/files/misc/ai_agents_challenge_designed_guide.pdf)__ for next steps.
Problem to solve
[What's the problem you want to solve?]
Our solution
[What are you building? Summarize the key features and how your agent functions.]
Technologies used
[List the Google Cloud and other technologies powering your project — e.g., Gemini, ADK, Vertex AI, Cloud Run, GKE, MCP, A2A, LangChain, CrewAI, etc.]
Data sources
[List any data sources, APIs, or knowledge bases your agent connects to or relies on.]
Findings and learnings
[What did you discover while building this? Any surprises, challenges, or insights worth sharing?]
Third-party integrations (if applicable)
[List any third-party SDKs, APIs, data, or content used, and confirm you have rights/authorization to use them.])Show moreMay 14Claude responded: Your name is fine — "Curator — Regulatory Change Intelligence Agent" is clear, accurate, and judges will instantly get it.Your name is fine — "Curator — Regulatory Change Intelligence Agent" is clear, accurate, and judges will instantly get it. If you want something marginally sharper, "Curator — Regulatory Amendment-to-Policy Agent" says the actual mechanism out loud, but it's a marginal call. Keep yours; don't spend time here.
Here's starter text for each field — real, credible, but light enough to refine later. Copy-paste each block.

Problem to solve
Indian BFSI institutions operate under a constant stream of regulatory change from the RBI, SEBI, IRDAI and other regulators. When a regulator issues an amendment or a revised Master Direction, compliance teams must manually read it, work out which of their internal policies, SOPs and process manuals are affected, and rewrite them — a slow, error-prone process where a single amended clause can quietly trigger several distinct policy changes across different teams. The result is compliance lag, missed obligations, and audit risk.
Our solution
Curator is an autonomous agent that turns a regulatory amendment into a concrete set of internal policy-change requirements. When a new RBI amendment or revised Master Direction is published, the agent decomposes it clause by clause, identifies every distinct obligation, maps each one against the institution's existing internal policies and SOPs, and generates specific suggested edits with an impact summary — then supports follow-up Q&A so a compliance officer can interrogate the reasoning. It is built to be deployed as a B2B agent on Google Cloud, discoverable and interoperable with other enterprise agents.
Technologies used
Google Cloud: Gemini (agent reasoning), Cloud Run (serverless agent runtime), Agent-to-Agent (A2A) protocol for interoperability. Orchestration via a multi-agent graph (LangGraph) with a Model Context Protocol (MCP) tool layer for grounding. Knowledge backend: Neo4j (regulatory knowledge graph) and Milvus (vector search) for retrieval-augmented grounding against the regulatory corpus.
Data sources
RBI circulars, amendments and Master Directions (public regulatory corpus), structured into a regulatory knowledge graph. Tenant-side inputs: an institution's internal policies, SOPs and process manuals, mapped against the external regulatory graph. Demo uses a representative subset — a Master Direction in two versions (original and amended) and a sample bank policy/SOP set authored against the original.
Findings and learnings
To be updated through the build. Early focus: how a single amended clause fans out into multiple downstream policy-change requirements across different process owners, and how to deploy an existing production-grade multi-agent system cleanly onto Google Cloud's serverless, A2A-interoperable architecture.
Third-party integrations
Neo4j (knowledge graph database) and Milvus (vector database) — both open-source / standard commercial offerings, used with appropriate rights. All regulatory source data is from publicly available regulator publications. Sample internal bank policies used in the demo are synthetic, authored for demonstration purposes.

That's enough to look serious to anyone browsing. Rename the project, paste these six blocks, set team-building to Closed, and you're done for tonight. The asset fields and submission questions wait for the kickoff call and the build.You said: are we giving too much information ?are we giving too much information ? or is this good balance?May 14Claude responded: Good balance — lean toward keeping it.Good balance — lean toward keeping it. Here's the reasoning.
What you're showing isn't sensitive. It's a problem statement, an approach, and a tech stack. Every serious team's page has exactly this. The thing that's actually your moat — the 14-stage GPU pipeline, the deontic extraction, the 322K-node graph you've already built, the founder domain expertise — none of that is in this text, and it shouldn't be. What's on the page is the idea; what wins is the execution and the demo. Ideas aren't the scarce thing in a 383-project field. Nobody is going to read your Devpost page and replicate Curator — and if they could, they'd have done it already.
There's also an asymmetry worth noting. The downside of "too much info" is vague and unlikely — a competitor would need your domain background, your existing infrastructure, and three weeks they don't have. The downside of "too little" is concrete and immediate: a thin or placeholder page reads as a weak entry, and you saw from the scrape that half the Refactor field still has literal [placeholder] text. A complete, confident page signals you're a real contender — to other participants deciding whether to bother competing near you, and to anyone from Google browsing.
The one place I'd actually tighten isn't competitive paranoia, it's positioning. Two small edits:
The demo data sentence ("a Master Direction in two versions... sample bank policy/SOP set") — that's fine to keep, but it's the one detail that slightly undersells you by making the project sound like it starts from a toy dataset. You could trim it to just "Demo uses a representative subset of the regulatory corpus" and save the version-pair detail for the final write-up where you control the framing.
And "existing production-grade multi-agent system" in Findings — that's a strength worth keeping, because Track 3 rewards exactly that maturity, but make sure your eventual demo backs it up. Don't claim production-grade and show a prototype.
Net: this is the right amount. Don't trim for secrecy — there's no secret here a rival could use. Trim only for sharper positioning. Paste it, rename the project, set team-building to Closed, close the laptop.You said: Should we start creating source data now or should i set up a separate project for this submission?Should we start creating source data now or should i set up a separate project for this submission? suggest. also refer earlier messages, can we borrow functionalities from bbb to copy them to this new project and build upon that? we can also get 2 master directions and 1 related amendment notification to start with (we can have its structural extract, copied milvus embedding to separate collection, copied related rows in tsdb table to new table and copied neo4j entities nodes and all with different lable.May 14Claude responded: Set up a separate project.Set up a separate project. Don't build this inside bbb. Three reasons, and they're decisive:
The Track 3 mandate is a clean Cloud-Run-native, Gemini-reasoned, A2A-speaking agent. bbb is the opposite — mesh-pinned, Azure/AWS-coupled, 16 services. If you build inside it, you spend the whole three weeks fighting Tailscale IPs and IAM roles instead of building the agent. A fresh repo means the judges (and you) see exactly the submitted artifact with nothing to untangle. Second, you don't want your production system's git history, infra scripts, and 56-tool MCP server in a repo you're making public with an open-source license for the hackathon — the submission repo should contain only what you're submitting. Third, a clean repo is its own forcing function: it stops you from quietly depending on mesh services that won't exist on Cloud Run.
So: new repo, new GCP project. Call it something like curator-agent or aidni-hackathon.
Yes, borrow heavily from bbb — but copy, don't link. This is lift-and-adapt, not import. From the inventory, the specific things worth copying into the new repo:

The Bija LangGraph pattern — orchestrator.py's StateGraph construction, models.py's SharedState/GraphContext schemas, the agents.py provider-typed agent creation. You're rewriting the nodes (decompose → map → diff → judge instead of the brainstorm roles), but the graph scaffolding, checkpointing, and state model transfer directly. This is your single biggest time-saver.
A trimmed MCP tool layer — not the 56-tool server. Copy just the grounding tools: query_milvus, get_neo4j_node_count, the vector_graph_tools module, maybe parse_structure. Six to eight tools, clean server, no devops tooling.
The self_improvement.py diff scaffolding — OntologyProposal / RelationshipProposal as the skeleton for your diff-generator agent.
Steps 1–4 of circular_watcher.py — the watch/embed/hybrid-search/proposal-creation logic, adapted to hit managed backends instead of mesh ones.
The schema definitions — milvus_collections.yaml and the relevant TSDB/Neo4j schemas, so your copied data lands in a structure the agent already understands.

What you do not copy: supervisord configs, Azure/AWS deploy scripts, the object-store IAM client, the enrichment/vLLM pipeline, anything Tailscale.
On the data — yes, start now, and your instinct is exactly right. Picking 2 Master Directions + 1 amendment and copying a scoped slice across all three stores into separate collections/tables/labels is precisely the move. A few refinements:
Pick the documents for fan-out first. Before you copy anything, find an amendment where one clause genuinely cascades into multiple SOP changes across different process owners — that's your Innovation showcase. If the amendment is one-line-one-change, the agent looks like find-and-replace. Choose the version-pair deliberately.
Namespace everything with a clear prefix — hackathon_ or demo_ on the Milvus collections, TSDB tables, and Neo4j labels. This keeps the slice unambiguous and makes it trivial to point the agent's tools at exactly the demo data.
Authored bank policies are yours to create — and the most important data you'll make. Hand-author a compact but realistic policy/SOP set against the original Master Direction. This is where you control the demo's quality: build in the non-obvious downstream impact a human reviewer would miss. That's the "wow" beat.
But — one sequencing caution. Do the data work in parallel with, not ahead of, the Friday kickoff. Don't copy data into a specific backend architecture until you've confirmed the two open questions: whether grounding backends can live on a plain VM / Neo4j Aura / Zilliz (vs. mandated Vertex AI Search), and whether LangGraph counts. The document selection and the authored bank policies are safe to start tonight — those are architecture-independent. The where it gets copied to should wait ~36 hours for the kickoff answers. Don't stand up the GCP VM and load three databases until Friday.
So tonight and tomorrow: create the new repo, pick the 2 MDs + 1 amendment for fan-out, start hand-authoring the bank policy/SOP set. Right after kickoff: lock the backend architecture, then copy the scoped slices in with hackathon_ namespacing, and start lifting the Bija graph pattern into the clean repo.
Want me to design the diff-generator agent's graph now — node structure, state schema, and the one-clause-to-many-requirements decomposition flow? That's the piece you can start building the moment the repo exists, and it's architecture-independent.You said: Provide a comprehensive prompt for agent (which is currently in BBB project) to set it up end to end in ~/bs/agent/ directory.Provide a comprehensive prompt for agent (which is currently in BBB project) to set it up end to end in ~/bs/agent/ directory. Foresee all thats required like venv installations and all carefully to design project structure and full code base implementation. if required share an artifact to copy to new project for agent to work in a systematic way.May 14Claude responded: Before I write a 5,000-word build prompt — I want to flag something, because getting this wrong costs you days.Before I write a 5,000-word build prompt — I want to flag something, because getting this wrong costs you days.
That prompt would have to hard-code answers to the two questions Friday's kickoff exists to answer: whether LangGraph counts as a supported framework, and whether your grounding backends can live on a plain VM / Neo4j Aura / Zilliz versus being mandated onto Vertex AI Search. If I bake in "use LangGraph, use self-hosted Neo4j" and the kickoff says "ADK required, Vertex AI Search required," your agent rebuilds the project scaffolding and dependency tree on a foundation you'll tear up 36 hours later. The expensive part of a scaffold isn't writing it — it's unwinding it.
So the right move is a two-stage prompt. Stage 1 is 100% architecture-independent and you can run it tonight — it builds everything that's true regardless of the kickoff answers. Stage 2 is the agent graph and backend wiring, and I'll give it to you Friday with the two answers filled in. This isn't delay; Stage 1 is genuinely a day of work and it's all reusable.
Here's the Stage 1 prompt. It's designed to be pasted into Claude Code running in your bbb project, and it reads from bbb to copy patterns but writes only to ~/bs/agent/.

You are setting up a NEW, CLEAN project at ~/bs/agent/ for a Google hackathon
submission. It is SEPARATE from the bbb project you are currently in. You may
READ from the current bbb repo to copy and adapt patterns, but you must WRITE
only to ~/bs/agent/. Do not modify anything in bbb.

CONTEXT
The project is "Curator — Regulatory Change Intelligence Agent." It is an
autonomous agent that takes an RBI regulatory amendment, decomposes it clause
by clause into distinct obligations, maps each obligation against a bank's
internal policies/SOPs, generates suggested policy edits with an impact
summary, and supports follow-up Q&A. Target deployment is Google Cloud Run,
reasoning on Gemini, with an A2A-compatible interface.

IMPORTANT CONSTRAINT
This is STAGE 1 of a two-stage build: scaffold + architecture-independent
foundations ONLY. Do NOT yet build the LangGraph/ADK agent graph itself, and
do NOT wire concrete database backends. Two architecture decisions are pending
(orchestration framework choice; whether grounding backends are self-hosted vs
Vertex AI Search). Your job is to build everything that is TRUE REGARDLESS of
those two decisions, and to leave clean, well-documented seams where Stage 2
will plug in. Wherever you would otherwise hard-code one of those choices,
instead define an interface/abstract base class and a TODO(stage-2) marker.

WHAT TO BUILD

1. PROJECT STRUCTURE — create this layout:
   ~/bs/agent/
   ├── README.md                  # project overview, setup, run instructions
   ├── pyproject.toml              # deps, tooling config (prefer over bare requirements.txt)
   ├── .python-version             # pin 3.11
   ├── .env.example                # every env var the project will need, documented
   ├── .gitignore                  # python, venv, .env, IDE, OS junk
   ├── Makefile                    # setup / test / lint / run / deploy targets
   ├── Dockerfile                  # Cloud Run-ready container (python:3.11-slim base)
   ├── .dockerignore
   ├── src/curator_agent/
   │   ├── __init__.py
   │   ├── config.py               # pydantic-settings config loaded from env
   │   ├── models.py               # ALL pydantic schemas: AmendmentInput, Obligation,
   │   │                           #   PolicyMatch, PolicyDiff, ImpactSummary, AgentState
   │   ├── grounding/
   │   │   ├── __init__.py
   │   │   ├── base.py             # ABC: GroundingBackend (vector_search, graph_query,
   │   │   │                       #   get_document) — TODO(stage-2): concrete impls
   │   │   └── mock.py             # in-memory mock impl using local fixture files,
   │   │                           #   so the whole pipeline is testable NOW
   │   ├── orchestration/
   │   │   ├── __init__.py
   │   │   └── base.py             # ABC: Orchestrator — defines the node contract
   │   │                           #   (decompose, map, diff, judge, qna) abstractly.
   │   │                           #   TODO(stage-2): LangGraph or ADK concrete impl
   │   ├── tools/
   │   │   ├── __init__.py
   │   │   └── grounding_tools.py  # thin MCP-style tool wrappers over GroundingBackend
   │   ├── llm/
   │   │   ├── __init__.py
   │   │   └── gemini_client.py    # Gemini API wrapper: structured-output calls,
   │   │                           #   retry/backoff, token accounting. Adapt the
   │   │                           #   pattern from bbb's libs/llm/gemini_sdk_client.py
   │   ├── api/
   │   │   ├── __init__.py
   │   │   └── app.py              # FastAPI app, health endpoint, /run + /qna stubs
   │   │                           #   that call the Orchestrator ABC
   │   └── cli.py                  # local dev entrypoint: run the pipeline on a
   │                               #   fixture amendment end-to-end via mock backend
   ├── data/
   │   ├── fixtures/               # sample amendment + master direction + bank policy
   │   │   └── README.md           # explains what goes here, expected formats
   │   └── schemas/                # copied/adapted schema yaml from bbb (milvus
   │                               #   collections, tsdb, neo4j) for Stage 2 reference
   ├── tests/
   │   ├── __init__.py
   │   ├── conftest.py             # fixtures: sample AmendmentInput, mock backend
   │   ├── test_models.py          # schema validation round-trips
   │   ├── test_grounding_mock.py  # mock backend behaves per the ABC contract
   │   ├── test_tools.py           # tool wrappers
   │   └── test_pipeline_e2e.py    # full pipeline on mock backend (will be wired
   │                               #   fully in stage 2; stub the orchestrator now)
   └── docs/
       ├── ARCHITECTURE.md         # the two-stage plan, the pending decisions,
       │                           #   the seams, and the data-flow diagram in text
       └── STAGE2_PLAN.md          # explicit checklist of what Stage 2 plugs in

2. ENVIRONMENT & TOOLING
   - Use Python 3.11. Create the venv at ~/bs/agent/.venv
   - Use pyproject.toml with these dependency groups:
     * core: pydantic, pydantic-settings, fastapi, uvicorn, google-genai,
       httpx, tenacity, structlog, python-dotenv
     * dev: pytest, pytest-asyncio, pytest-cov, ruff, mypy
   - Pin versions to currently-stable releases. Verify each package name is
     correct before adding it; do not invent package names.
   - After writing pyproject.toml, actually CREATE the venv, install both
     dependency groups, and confirm the install succeeds. Report any failures.
   - Makefile targets: `setup` (venv + install), `test` (pytest with coverage),
     `lint` (ruff + mypy), `run` (uvicorn local), `cli` (run cli.py on a
     fixture), `docker-build`, `docker-run`. Test that `make setup`, `make lint`,
     and `make test` all pass before finishing.

3. WHAT TO COPY/ADAPT FROM bbb (read-only from bbb, write to ~/bs/agent/)
   - The Gemini client pattern from libs/llm/gemini_sdk_client.py — adapt into
     a clean standalone llm/gemini_client.py with NO bbb-internal imports.
     Strip all mesh/router/queue coupling. It must work as a self-contained
     module with only the google-genai SDK + an API key from env.
   - The SharedState / GraphContext schema idea from bbb's
     services/bija/brainstorm/models.py — adapt the STATE-MODEL CONCEPT into
     models.py's AgentState. Do not copy bbb's brainstorm-specific fields;
     design AgentState for THIS pipeline (decompose→map→diff→judge→qna).
   - The grounding-tool shape from bbb's MCP vector_graph_tools — adapt into
     tools/grounding_tools.py as thin wrappers over the GroundingBackend ABC.
   - The relevant schema YAML from bbb's libs/schema (milvus collections, tsdb,
     neo4j) — COPY into data/schemas/ purely as reference material for Stage 2.
   CRITICAL: the new project must have ZERO imports from bbb. Everything copied
   must be fully self-contained. After building, grep the whole ~/bs/agent/
   tree to confirm no `bbb`, `tailscale`, `supervisord`, or bbb-internal module
   paths appear anywhere.

4. THE MOCK BACKEND — this is important
   Build grounding/mock.py as a fully working in-memory implementation of the
   GroundingBackend ABC, backed by the JSON/text fixture files in data/fixtures/.
   The point: the ENTIRE pipeline must be runnable and testable end-to-end on
   the mock backend RIGHT NOW, before any real database exists. cli.py should
   run a fixture amendment through (a stubbed) orchestrator using the mock
   backend and print structured output. This de-risks Stage 2 — when real
   backends get wired, the contract is already proven.

5. FIXTURES
   Create realistic-looking placeholder fixtures in data/fixtures/:
   - one sample "amendment" doc (a few clauses, JSON + raw text)
   - one sample "master direction" excerpt
   - one sample "bank policy/SOP" set authored against that master direction
   Keep them small but structurally realistic. Add a fixtures/README.md
   explaining the expected real-data format so they can be swapped later.

6. DOCUMENTATION
   - README.md: what this is, the two-stage build approach, how to set up and
     run, current status (Stage 1 complete / Stage 2 pending).
   - docs/ARCHITECTURE.md: the data flow (amendment → decompose → map → diff →
     judge → qna), the GroundingBackend and Orchestrator seams, and the two
     pending architecture decisions explicitly called out.
   - docs/STAGE2_PLAN.md: a concrete checklist — "plug LangGraph/ADK into
     orchestration/, plug real backends into grounding/, swap mock for real in
     config, wire circular-watcher ingestion, build A2A wrapper, Cloud Run
     deploy." Leave it as an actionable list.

DELIVERABLE
After building, give me:
- A tree view of the created ~/bs/agent/ structure
- Confirmation that venv created, deps installed, `make lint` and `make test`
  pass, and `make cli` runs the mock pipeline end-to-end
- The grep confirmation of zero bbb coupling
- A short "Stage 1 complete" summary and what's blocked on the kickoff answers

Work systematically. Build the structure first, then models, then the mock
backend and fixtures, then the ABCs, then the LLM client, then the API/CLI
stubs, then tests, then docs. Verify as you go. Do not skip the venv
creation and test run — I need to know it actually works.

A few notes on why it's shaped this way.
The mock backend is the most important instruction in there. It means by tomorrow you have a pipeline that runs end-to-end — provable, testable, demoable in skeleton — before a single database exists. When Stage 2 wiring happens, you're swapping implementations behind a proven contract, not integrating blind.
The ABCs for orchestration and grounding are the seams. Whatever Friday answers — LangGraph or ADK, self-hosted or Vertex — it plugs in behind an interface that already has passing tests. Nothing rebuilds.
The zero-bbb-coupling grep matters because the failure mode here is a module that quietly works in bbb because the mesh is there, then breaks on Cloud Run. Forcing self-containment now surfaces that immediately.
What this deliberately leaves out: the actual agent graph (the decompose→map→diff→judge nodes), the real backend wiring, the A2A wrapper, the Cloud Run deploy. That's Stage 2 — and the decompose-to-many-requirements node design is the part I'd most want to think through carefully with you anyway, because the fan-out logic is your Innovation score.
Run this tonight. Send me the deliverable summary plus the two kickoff answers Friday, and I'll write Stage 2 against a foundation that's already green.
Want me to design the agent graph — the node structure and the one-clause-to-many-obligations state flow — now as a separate artifact, so it's ready to drop into orchestration/ the moment the framework question is settled?You said: questions were not taken.questions were not taken. but lets use gcp ai search and native functionalities at final deployment and submission stage. no langgraph.  Lets use googles adk and agent cli fully for this project submission purpose. i have not run the initial prompt provided by you. research web around these to provide full prompt. also research newly launched agents studio, its features like observability and all to include all great features in our plan and final submission.May 15Claude responded: This is the right call — going all-in on Google's native stack (ADK, Agent Engine, Vertex AI Search, Agent Studio) is exactly what Track 3 rewards, and it remo…This is the right call — going all-in on Google's native stack (ADK, Agent Engine, Vertex AI Search, Agent Studio) is exactly what Track 3 rewards, and it removes the two open questions entirely. Let me research the current state of these tools before writing the prompt, because ADK and Agent Studio have moved fast and I don't want to scaffold against stale APIs.Searched the webSearched the webThat's the critical piece — the Agents CLI workflow. It's purpose-built for exactly what you're doing: you drive ADK through an AI coding tool (Claude Code, in your case) using natural-language prompts, and it scaffolds, evals, and deploys. Let me dig into Agent Studio and the observability/optimization tooling next.Searched the webSearched the webI have what I need. Let me also confirm the Vertex AI Search / RAG Engine specifics so the prompt grounds against the right service names.Searched the webSearched the webI have a clear picture of the current stack now. Before the prompt, one important correction to your plan based on what the research shows — it changes the prompt in a way that saves you significant time.
One thing to reconsider: don't hand-write the scaffold
You said "use Google's ADK and agent CLI fully." The research shows the Agents CLI workflow is itself designed to be driven by Claude Code — you don't write a giant prompt that hand-codes an ADK project; you give Claude Code a prompt that tells it to drive the Agents CLI, which scaffolds, evals, and deploys through Google's own skills (google-agents-cli-scaffold, google-agents-cli-eval, google-agents-cli-deploy). The CLI "encapsulates expert knowledge of ADK" — it writes the boilerplate, the DESIGN_SPEC.md, the test/eval sets, the deployment config.
So a 5,000-word hand-coding prompt would actually fight the tooling. The right prompt is shorter and tells Claude Code to use the Agents CLI as the engine, with your domain logic as the spec. That's the prompt below.
Also note one correction worth knowing: Vertex AI RAG Engine's managed DB runs on Spanner, and the Engine itself is region-limited (us-central1, us-east1, us-east4 on allowlist). That matters for your data-residency story later — but for the hackathon demo it's fine; just don't claim asia-south1 RAG residency in the submission without checking. The agent runtime on Cloud Run can be asia-south1; the RAG corpus may not be yet.
Why still Stage 1 / Stage 2
You haven't run the earlier prompt — good, because this replaces it. But the two-stage logic still holds, for a different reason now. Stage 1 is everything that's deterministic: environment, the Agents CLI bootstrap, the DESIGN_SPEC.md, the data fixtures, the eval set, a skeleton agent that runs on mock data. Stage 2 is wiring the real RAG corpus, the multi-agent decompose→map→diff→judge graph, A2A, and Cloud Run deploy — and that benefits from you having actually used the CLI once and from me designing the agent graph carefully with you. Splitting it isn't about the kickoff anymore; it's that scaffolding-then-logic is simply the right order, and the agent graph is your Innovation score — worth deliberate design, not a one-shot dump.

The Stage 1 prompt — paste into Claude Code at ~/bs/
Set up a new Google ADK agent project at ~/bs/agent/ for a hackathon submission.
This is a CLEAN, STANDALONE project. You are currently in the bbb repo — you may
READ bbb to copy domain data and reference patterns, but WRITE only to ~/bs/agent/.
Zero imports from bbb in the final project.

== WHAT THIS AGENT IS ==
"Curator — Regulatory Change Intelligence Agent." A multi-agent system that takes
an RBI regulatory amendment (plus the revised Master Direction), and:
  1. DECOMPOSES each amended clause into distinct atomic obligations (one clause
     can yield several obligations with different owners/timelines)
  2. MAPS each obligation against a bank's existing internal policies/SOPs
  3. DIFFS — generates specific suggested policy edits with an impact summary
  4. JUDGES — scores impact/priority and flags non-obvious downstream effects
  5. Q&A — answers follow-up questions about the analysis
Target: ADK multi-agent, Gemini reasoning, deployed to Cloud Run, grounded via
Vertex AI RAG Engine / Vertex AI Search, A2A-discoverable.

== STAGE 1 SCOPE (this prompt) ==
Scaffold + foundations + a runnable skeleton. NOT the full multi-agent graph,
NOT real RAG wiring, NOT A2A, NOT deployment. Those are Stage 2. Build everything
deterministic now and leave clean, documented seams (TODO(stage-2)) for the rest.

== STEP 1: ENVIRONMENT ==
- Python 3.11. Install `uv` if not present (the Agents CLI uses it).
- Create the project venv at ~/bs/agent/.venv
- Verify the Google Cloud SDK (`gcloud`) is installed and report auth status;
  if not authenticated, tell me the exact command to run — do not guess credentials.

== STEP 2: BOOTSTRAP VIA THE AGENTS CLI ==
Use Google's Agents CLI as the scaffolding engine (it encapsulates ADK best
practice). Run the Agents CLI setup via uvx, then drive it to scaffold the
project. When it asks clarifying questions, use these answers:
  - Project name: curator-agent
  - Purpose: the 5-step regulatory-change-intelligence workflow described above
  - Deployment target: Cloud Run
  - Model: Gemini (latest stable Gemini available in ADK; verify the exact model
    string from ADK docs rather than assuming)
  - Safety constraints: enterprise B2B, no autonomous external actions — the
    agent only proposes; a human approves
Let the CLI generate the DESIGN_SPEC.md, boilerplate agent code, tests, and
eval-set structure. Do NOT bypass it and hand-write the project layout.

== STEP 3: REVIEW & EXTEND WHAT THE CLI GENERATED ==
After the CLI scaffolds, read everything it produced and:
- Flesh out DESIGN_SPEC.md with the full 5-step workflow, the agent roles, and
  the data contracts (see Step 5 for the schemas).
- Confirm the project structure follows current ADK conventions (agents/, tools/,
  tests/eval/). If the CLI's layout differs from what you expect, trust the CLI.

== STEP 4: SKELETON MULTI-AGENT STRUCTURE (stubs, not full logic) ==
Define the agent hierarchy as ADK agents with clear instructions and docstrings,
but keep node logic as minimal stubs that pass typed data through:
  - root/orchestrator agent
  - decompose_agent, map_agent, diff_agent, judge_agent, qna_agent as sub-agents
Each sub-agent: real ADK Agent definition, real instruction prompt, but a stubbed
tool/return that produces schema-valid placeholder output. Mark the real logic
TODO(stage-2). The point: `adk run` / the dev UI should execute the full chain
end-to-end on placeholder data TODAY.

== STEP 5: DATA CONTRACTS (pydantic models) ==
Define and use throughout: AmendmentInput, AmendedClause, Obligation
(fields: id, source_clause_id, deontic_type, subject, action, condition,
temporal_scope, owner_hint), PolicyDocument, PolicyMatch (obligation_id,
policy_section_id, coverage: full|partial|missing|stale|contradicts, confidence),
PolicyDiff (policy_section_id, current_text, suggested_text, rationale),
ImpactSummary, AgentState (the shared state threaded through all agents).

== STEP 6: GROUNDING SEAM ==
Define a grounding interface with two implementations:
  - MockGroundingBackend: in-memory, backed by data/fixtures/ — works NOW
  - VertexRagBackend: stub only, TODO(stage-2) — will wrap Vertex AI RAG Engine
    (note in comments: RAG Engine managed DB = Spanner; region allowlist
    us-central1/us-east1/us-east4 — flag for Stage 2 residency review)
The skeleton runs on Mock today; Stage 2 swaps in Vertex.

== STEP 7: DOMAIN DATA FROM bbb ==
Read bbb to extract a SMALL real demo slice into ~/bs/agent/data/fixtures/:
  - 2 RBI Master Directions + 1 related amendment notification (structural
    extracts / text — whatever bbb has that's cleanest)
  - the corresponding schema definitions (Milvus collections, TSDB, Neo4j) copied
    into data/schemas/ as REFERENCE ONLY for Stage 2
Also create data/fixtures/sample_bank_policy/ — a small hand-authored bank
policy/SOP set written against the OLD version of one Master Direction (3-5 short
policy docs). Pick the amendment so one amended clause plausibly fans out into
MULTIPLE policy changes — that fan-out is the demo's key moment.
If bbb's data is hard to extract cleanly, tell me exactly what you found and what
format it's in rather than forcing it.

== STEP 8: EVAL SET ==
Using the Agents CLI eval skill, create tests/eval/ cases covering: clause
decomposition (one clause → N obligations), obligation→policy mapping accuracy,
diff quality, and the Q&A path. Configure LLM-as-judge criteria. These will be
thin in Stage 1 — that's expected — but the structure must be real.

== STEP 9: VERIFY ==
Confirm and report:
  - venv created, dependencies installed
  - Agents CLI ran and scaffolded successfully
  - `adk run` (or the CLI's local-run command) executes the full
    decompose→map→diff→judge→qna chain on fixture data without error
  - the eval set runs (even if cases are thin)
  - grep confirms zero bbb imports / zero tailscale / zero Azure refs
  - print the final project tree

== STEP 10: DOCS ==
Write README.md (what it is, setup, run, Stage 1 status) and docs/STAGE2_PLAN.md
(explicit checklist: full agent-node logic, Vertex AI RAG Engine wiring, A2A
interface, Cloud Run deploy, Agent Observability + Agent Simulation + Agent
Optimizer integration, Agent Registry listing).

== DELIVERABLE ==
Report each step's result, flag anything that surprised you or that you couldn't
do, and end with a "Stage 1 complete" summary plus what Stage 2 needs from me.

Work methodically. Verify as you go. Do not skip Step 2 (the Agents CLI) — driving
the CLI is the whole point; do not hand-roll the scaffold around it.

What I deliberately built into this
The Agents CLI does the scaffolding, not a hand-written layout — that's the correct use of Google's tooling and it's what Track 3 judges will expect to see. Hand-rolling an ADK project when the CLI exists would actually look naive.
The skeleton runs end-to-end on mock data from day one. Same de-risking logic as before — when Stage 2 wires real RAG, you're swapping behind a proven contract.
The fan-out instruction is in Step 7 because the demo data is the Innovation score. If you pick a boring amendment, no architecture saves the demo.
Observability / Simulation / Optimizer are explicitly Stage 2, in the STAGE2_PLAN.md. These are your highest-value submission features — Agent Observability gives you the Unified Trace Viewer showing the multi-agent reasoning path (gold for the Demo score), Agent Simulation stress-tests the decomposition logic, Agent Optimizer auto-refines the agent instructions. Built on ADK + deployed via Agent Runtime, you "instantly inherit Cloud Trace observability" — so these largely come for free once deployed, but wiring and showcasing them deliberately is Stage 2 work worth a dedicated pass.
After you run it
Send me the deliverable report — especially what the Agents CLI generated and what bbb data extracted cleanly. Then Stage 2, where the real work and the real scoring live, is two designed pieces:

The multi-agent graph — the decompose→map→diff→judge logic, especially how one clause fans out into N obligations routed to different owners. This is the prompt I want to write carefully with you, not one-shot.
The platform showcase — RAG Engine wiring, A2A, Cloud Run deploy, and deliberately surfacing Observability + Simulation + Optimizer so the submission visibly uses the full platform.

Run Stage 1, then let's design the agent graph together — that's the piece that wins or loses the Innovation and Technical scores.You said: also research web to find out when and how will we receive credits.also research web to find out when and how will we receive credits.May 15Claude responded: The official challenge announcement confirms the mechanics but is light on the exact delivery method.Searched the webSearched the webThe official challenge announcement confirms the mechanics but is light on the exact delivery method. Here's what the research establishes, and what it doesn't.
What's confirmed
The $500 is real and tied to the challenge itself. The Google for Startups AI Agents Challenge is open to anyone, runs for six weeks, and gives teams $500 in credits and the tools — like the new Gemini Enterprise Agent Platform — to build autonomous systems and compete for a share of a $90,000 prize pool. So eligible registered participants get it — it's not something you compete for. dev
What the research does not nail down
None of the official sources spell out the exact when and how of the $500 delivery — whether it's a coupon code emailed to registrants, credits applied to a billing account, or distributed at/after the kickoff. This is normal for hackathon credits; the delivery instruction almost always comes through a channel the public web doesn't index — a participant email from Devpost, or an announcement during the kickoff call. Two concrete things you can rely on:
The kickoff call is the most likely delivery moment or instruction point. That's Friday May 15, 1:30 AM IST, hosted by Addy Osmani. Credit instructions for hackathons are routinely given there or in the follow-up email. So attending — or at minimum watching for the recording and the post-kickoff email — is how you get the mechanism.
If nothing arrives, laurel@devpost.com is the contact on the challenge page (and dani@devpost.com appears on the additional-details section). One short email after kickoff resolves it.
A practical mechanics note from the broader Google credit docs: redeeming Google Cloud credits generally requires your 18-character Google Cloud billing account ID — you should have received your 18-character billing ID when you signed up for Google Cloud. So before kickoff, make sure you have a GCP billing account created and that ID handy — whatever the delivery method, you'll likely need it. YouTube
The more important finding: $500 is not your real funding
The research strongly reinforces what I flagged earlier — the $500 challenge credit is a starter, not a build budget. The actual money is the Google for Startups Cloud Program, and the numbers are significant: early stage startups can get up to $350,000 in Cloud credits through the Google for Startups Cloud Program, with the AI startup track — if AI is the core of the product and you're using tools like Vertex AI or Gemini — the ceiling rising to $350,000, where Year 1 can cover up to $250,000. DevpostCloud Run Hackathon
But there's a catch you should know now, because it's the thing that trips people up: the requirement that trips up most applicants is approved partner association — your startup must be associated with an approved accelerator, incubator, or venture capital firm that is part of Google's partner network. There's also a Start tier that's more accessible — ideate and iterate your MVP with $2,000 in credits with the Google for Startups Cloud Program — designed for startups under 5 years old that haven't taken institutional VC funding and have minimal prior Google Cloud credits. Aidni is a registered MSME with no external funding, so the Start tier ($2,000) is likely directly accessible to you without a partner; the larger AI track may need a partner affiliation. YouTube + 2
Two coverage caveats that matter for your architecture: the credits can be used for Google Cloud services such as BigQuery and Gemini Enterprise Agent Platform, but cannot be applied to any third-party services or offerings including those on Google Cloud Marketplace, and program credits cover Google's models like Gemini and Gemma, but third-party models are billed directly and are not covered. Good news for you — your plan is all-Google (Gemini, ADK, Vertex AI Search, Cloud Run), so it's fully covered. If you were still routing to Claude or other third-party models, that spend would fall outside credits. YouTubeGoogle Cloud
What to do, concretely
Tonight or before kickoff: confirm you have a GCP billing account and your 18-character billing ID. Apply to the Google for Startups Cloud Program Start tier at cloud.google.com/startup — that $2,000 is the realistic near-term funding and Aidni likely qualifies without a partner. At Friday's kickoff: get the exact $500 redemption mechanism, and watch the post-kickoff email. If it hasn't landed a day after kickoff, email laurel@devpost.com.
One cost-discipline point the research underscores hard: credits don't fix bad architecture — if your stack is over-provisioned or your team forgets to turn off GPUs, the credits will disappear and the bill will still arrive. For your demo VM running Neo4j/Milvus/TSDB — shut it down when you're not actively working. $500 plus $2,000 is plenty for this hackathon if you don't leave things running idle. Cloud Run HackathonYou said: what else do you require other than attachment?  Stage 1 complete — report                                                                                                   
                                                                                                                              
  Step-by-step results                   
    pastedwhat else do you require other than attachment?May 15Claude responded: Stage 1 came out clean — the fan-out is already visible offline (4 clauses → 6 obligations), zero bbb coupling, eval set structured.Stage 1 came out clean — the fan-out is already visible offline (4 clauses → 6 obligations), zero bbb coupling, eval set structured. Good foundation.
You asked what else I need beyond the attachment. The honest answer: the attachment tells me what the scaffold built, but not what's inside it. To write a Stage 2 prompt that's precise rather than generic, I need to see the actual generated code — otherwise I'm guessing at function signatures and file structure, and you'll get a prompt full of "adapt as needed" hand-waving.
What to attach — paste the actual file contents:

app/agent.py — the most important one. I need to see exactly how the 5 sub-agents are defined, how the agentic_rag template wired the root agent, what the instruction prompts currently say, and how the stub tools are shaped. Stage 2 is mostly rewriting this file.
app/models.py — the real pydantic schemas. I need exact field names to write node logic that threads AgentState correctly.
app/grounding.py — the ABC and both backends, so the Vertex wiring plugs into the real interface.
DESIGN_SPEC.md — what the CLI + the Stage-1 pass actually committed to.
docs/STAGE2_PLAN.md — you reference it; I need to see what's already checklisted so I extend rather than duplicate.
pyproject.toml — the real dependency set and the ADK version pinned.
tests/eval/evalsets/curator.evalset.json + eval_config.json — the 5 cases and rubrics, so Stage 2 expands them coherently.
The project tree — find ~/bs/agent -type f -not -path '*/.venv/*' -not -path '*/.git/*' so I see the real layout the agentic_rag template produced.

Four decisions I need from you (the Stage-1 report asked me, but these are yours to make — here's my recommendation on each so you can just confirm or override):

RAG residency — for the hackathon, use us-central1 with Vertex AI RAG Engine. It's the path the scaffold already chose, RAG Engine is the cleaner managed option, and the demo isn't real bank data so residency doesn't bite yet. Note the asia-south1 constraint in your submission write-up as "production roadmap." Don't contort Stage 2 to avoid us-central1.
Tenant model — shared corpus with per-tenant metadata filters. One-corpus-per-bank is the real-product answer but it's overhead you don't need for a one-bank demo. Filters demonstrate the same multi-tenant story at a fraction of the setup.
More amendments for Simulation — yes, but don't block Stage 2 on it. One amendment is enough to build and demo the chain. Agent Simulation generates synthetic interactions anyway — that's its whole point. Add 1–2 more real historical amendments if extraction from bbb is cheap; otherwise let Simulation do the stress-testing.
gcloud — just install and auth it before you run Stage 2. I don't need anything from you on this; the Stage-1 report's commands are correct. Only thing: tell me your GCP project ID so the Stage 2 prompt can reference it concretely instead of YOUR_GCP_PROJECT.

One thing I do not need: the fixture data files themselves (the RBI extracts, the bank policies). The report describes them well enough. If a specific schema question comes up I'll ask, but don't paste those — they're bulky and Stage 2 is about code, not data.
Paste those 8 items plus your project ID and the four confirmations, and I'll write you a Stage 2 prompt that's as concrete as the Stage 1 one was — real file names, real function signatures, real sequencing. Without the code, I can still write Stage 2, but it'll be 30% vaguer and you'll lose time translating.
One sequencing note while you gather that: install and auth gcloud now, before you paste. That way the moment you have the Stage 2 prompt, Claude Code can immediately run adk run app against the real LLM chain — you won't be blocked waiting on setup.You said: We want to make the agent useful with live demonstration such that users can upload two pdfs and get in depth comparison and change log along with actionable.We want to make the agent useful with live demonstration such that users can upload two pdfs and get in depth comparison and change log along with actionable. But i also dont want to disclose our curator research proprietary graph rag system stages and all. Research web on how to make use of gcp graph rag system with such documents and then our agent scope will be prompt and workflow driven rather than infra driven. Suggest if i am thinking in right direction and how should we proceed with this submission.May 18Claude responded: You're thinking in the right direction — and what you've just described is actually a better submission than the original plan.You're thinking in the right direction — and what you've just described is actually a better submission than the original plan. Let me say why, then research the GCP GraphRAG path, then give you the proceed plan.
Why this is the right call
The two-PDF live demo solves three problems at once. It makes the demo self-contained and reproducible — a judge can run it without your mesh, your corpus, or a seeded VM. It protects Curator's moat — you're not exposing the 14-stage pipeline, the deontic extraction, the 322K-node graph; you're showing an agent that ingests two documents live. And it matches what Track 3 actually scores — the rubric rewards the agent's reasoning, business case, and demo, not your ingestion infrastructure. "Prompt and workflow driven rather than infra driven" is exactly the right framing: the submission is the agent, and the agent is judged on what it does with two documents, not on the data lake behind your real product.
There's a strategic point too. The hackathon submission and Curator-the-product should not be the same artifact. The submission is a public, open-source-licensed, self-demonstrating agent that proves the concept. Curator is your proprietary platform. Keeping them separate isn't a compromise — it's how you compete hard and protect IP. The two-PDF agent is the public face; the graph pipeline stays private.
Let me research how GraphRAG actually works on GCP-native services so the agent can build a graph from two uploaded PDFs at runtime — without any of your infrastructure.Searched the webSearched the webThis confirms a clean GCP-native path. Let me check one more thing — how documents get parsed before graph construction, since regulatory PDFs are layout-heavy.Searched the webSearched the webI have the full GCP-native picture now. Here's the assessment and the plan.
You're thinking correctly — and there's a clean GCP-native path
Your instinct is right on both counts: the two-PDF live demo is the better submission, and "prompt-and-workflow driven, not infra driven" is exactly the correct framing. The research confirms there's a fully GCP-native way to do this that requires none of Curator's proprietary stack.
The key realization: Google has a published reference architecture for exactly this. A Cloud Run function builds a knowledge graph from input files using the Gemini API and LangChain's LLMGraphTransformer, and stores it in Spanner Graph. Spanner Graph then does GraphRAG by combining graph search for relationship context with vector search for semantic similarity. And Document AI's Layout Parser — which combines Google's OCR with Gemini — handles the messy regulatory-PDF problem: it understands tables, headers, lists, and the contextual relationships between them, solving the exact problem that standard OCR flattening creates for RAG.
So the runtime story for your submission is: user uploads two PDFs → Document AI Layout Parser extracts structured content → Gemini builds a knowledge graph from each → Spanner Graph stores both and runs GraphRAG queries → your ADK multi-agent chain (decompose → map → diff → judge) reasons over the graphs → out comes the in-depth comparison, change log, and actionable items.
Every piece is a managed GCP service. Nothing touches your 14-stage pipeline, your Milvus collections, your Neo4j, your deontic classifier, or your mesh. The GraphRAG "magic" lives in Spanner Graph + Gemini at runtime, built fresh from the two uploaded documents — which is genuinely different from Curator's pre-built persistent corpus graph. You're not hiding Curator; you're building a legitimately separate, smaller thing.
What this means for IP protection
This is cleaner than just "not disclosing." The submitted agent and Curator are now architecturally different systems:

Curator — a persistent, pre-ingested 322K-node graph over the entire regulatory corpus, built by a proprietary 14-stage GPU pipeline, queried by tenants continuously.
The submission — an ephemeral, two-document GraphRAG built at runtime on Spanner Graph from whatever the user uploads, reasoned over by an ADK agent.

You can describe the submission's architecture in full honesty in the Devpost write-up — it's all standard GCP services, nothing proprietary — because it genuinely isn't Curator. The pipeline stages, the deontic extraction methodology, the entity-resolution cascade, the Matryoshka embedding strategy — none of that appears, because the submission doesn't use them. It uses Gemini + LLMGraphTransformer + Spanner Graph. Your moat stays private not by redaction but by genuine separation.
One honest caveat to hold onto: a runtime two-PDF graph is shallower than Curator's corpus graph. That's fine — for two documents you don't need 14 stages. But don't let the demo over-claim. It shows the concept — regulatory change intelligence via GraphRAG — at two-document depth. The Business Case section is where you say "this scales to a full regulatory corpus" and point at the production vision.
How this revises the build
Good news: most of Stage 1 holds. Your 5-agent ADK skeleton (decompose/map/diff/judge/qna), your pydantic data contracts, your eval set — all still correct. What changes is the front of the pipeline and the grounding backend:

Before: seed a VM with circulars copied from bbb; agent queries a pre-loaded corpus.
Now: user uploads two PDFs at runtime → Layout Parser → Gemini graph construction → Spanner Graph → agent reasons.

Your Stage-1 GroundingBackend ABC was designed for exactly this swap. The VertexRagBackend stub becomes a SpannerGraphBackend. The MockGroundingBackend still works for offline tests. The agent chain on top is unchanged — it just reasons over a graph that was built 30 seconds ago instead of one seeded last week.
This also kills the Vertex AI RAG Engine residency problem you raised. You're not using RAG Engine's managed Spanner-in-us-central1. You're using Spanner Graph directly, which you provision in your own region. The residency question dissolves.
And it strengthens the Track 3 story. The judges' own examples are multi-step agentic workflows; "upload two regulatory documents, get a graph-grounded change analysis" is a textbook one, and it's visibly built on the newest GCP primitives — Spanner Graph, Document AI Layout Parser, ADK, Gemini. That's a strong Technical Implementation narrative.
The demo flow
The live demo a judge sees:

Upload two PDFs — e.g., RBI Master Direction v1 and the amended v2 (or a bank policy and a regulation).
Watch the agent work — Layout Parser extracts structure; Gemini builds a knowledge graph from each; ADK's trace view (Agent Observability) shows the decompose → map → diff → judge chain executing. That visible reasoning trace is gold for the Demo score.
Output — a structured, in-depth comparison: clause-level change log, each change decomposed into obligations, the fan-out moment (one amended clause → multiple downstream requirements), and an actionable list with priority/impact.
Q&A — judge asks a follow-up; the qna agent answers, grounded in the graph, with citations.

The fan-out moment is still your Innovation showcase — make sure at least one uploaded amendment produces the one-clause-to-many-obligations cascade.
How to proceed

This is a Stage-2 redirection, not a restart. Keep the Stage-1 scaffold. The change is: front-end PDF upload, Layout Parser ingestion, Gemini graph construction, Spanner Graph as the grounding backend.
Confirm two things before I write Stage 2: (a) Are the two PDFs always a version pair (v1 vs v2 of the same direction), or sometimes regulation vs internal policy? The agent's decompose/map logic differs slightly. My recommendation: support both, default to version-pair for the demo. (b) Provision Spanner Graph in your preferred region — asia-south1 works, which gives you a clean residency story for free.
Then I write the Stage-2 prompt — and it's now genuinely two designed pieces: the ingestion-to-graph front end (upload → Layout Parser → LLMGraphTransformer → Spanner Graph) and the agent reasoning chain over the two graphs. The agent graph design — especially the fan-out decomposition — is still the part I want to work through carefully with you.
For me to write a precise Stage 2, I still need the Stage-1 files I listed last message — app/agent.py, app/models.py, app/grounding.py, DESIGN_SPEC.md, STAGE2_PLAN.md, pyproject.toml, the eval JSON, and the project tree. The grounding-backend swap especially needs the real ABC code.

Net: yes, proceed exactly this way. It's a better, safer, more demoable submission than the seeded-corpus plan, and it's a redirection of Stage 2's front end — not lost work. Paste the Stage-1 files and confirm the two points above, and I'll write you the Stage-2 prompt: PDF-upload GraphRAG ingestion plus the agent reasoning chain, fully GCP-native, with your proprietary pipeline never entering the picture.You said: Existing files are added to this project via GitHub.Existing files are added to this project via GitHub. Will you be able to modify or add files in git repo, commit and push?May 18Claude responded: No — I can't reach your GitHub repo.No — I can't reach your GitHub repo. To be clear about what's actually happening:
When you say files are "added to this project via GitHub," that's the Claude Projects knowledge feature — it imports a snapshot of repo files so I can read them as context in our conversation. It's read-only, and it's a point-in-time copy, not a live connection. I have no ability to modify files, commit, push, open PRs, or otherwise write to your GitHub repo from here. I also can't browse it interactively — I only see whatever was synced into the project knowledge.
The reason it matters for our work: even reading isn't reliable enough for the Stage-2 prompt. Project-knowledge sync can be partial or stale, and for the grounding-backend swap I need the exact, current contents of app/agent.py, app/grounding.py, and app/models.py as they are right now on disk. So please still paste those files directly into chat, as I asked — don't assume the GitHub sync gave me the live versions.
The thing that can write to your repo is Claude Code. That's the whole model we've been using: I write you a precise prompt, you run it in Claude Code in your ~/bs/agent/ working tree, and Claude Code does the actual file creation, edits, git add, git commit, and git push. Claude Code has real filesystem and git access in your environment; I (here, in this chat) do not. That division is deliberate and it's working fine — I design, Claude Code executes.
So the flow stays exactly as planned:
You paste the current Stage-1 files into this chat (so my Stage-2 prompt is precise). I write the Stage-2 prompt. You run it in Claude Code, which modifies the repo and commits/pushes. If you want, the Stage-2 prompt can explicitly instruct Claude Code to commit at sensible checkpoints with good messages and push to a branch — just tell me your branch convention (e.g., work on stage-2 and PR into main, or commit straight to main) and I'll bake the git steps into the prompt.
One practical note: have Claude Code work on a branch, not main. Stage 2 is a substantial change — PDF-upload front end, Layout Parser, Spanner Graph backend swap. A branch means if something goes sideways mid-build, your last-known-good state is untouched. Tell me the branch name you want and I'll write the commit/push steps in.
So: paste the eight Stage-1 files, confirm the two questions from my last message (version-pair vs regulation-vs-policy; Spanner Graph region), tell me your branch preference, and I'll write Stage 2.You said: Ok research the attached files end to end.Ok research the attached files end to end. Research and think deep about our discussion and deliverables we need to submit in hackathon and provide fully formed plan till submission for claude code to run and deliver. The plan should be flexible enough for claude code to course correct, research independently and find better alternatives and take decisions accordingly. Plan should be downloadable Artefact so that i can share with claude code.  It should cover all research done in this conversation to ensure claude understands the context and once agent is completely build, claude should try to improve it overtime to target winning the top price.May 18Claude responded: Before I build this, two honest flags — they'll make the artifact actually usable rather than misleading.Before I build this, two honest flags — they'll make the artifact actually usable rather than misleading.
I've read the pitch decks and the Stage-1 report thoroughly, and I have the full conversation context. But the eight Stage-1 source files I asked for — app/agent.py, app/models.py, app/grounding.py, DESIGN_SPEC.md, STAGE2_PLAN.md, pyproject.toml, the eval JSON, the tree — were never pasted in. The project-knowledge sync gave me your decks, not the live agent code. So the plan I write must instruct Claude Code to first re-read its own Stage-1 codebase and reconcile before executing — which is good practice anyway, but I want you to know the plan is built on the Stage-1 report, not its actual code. I've designed the plan to handle that gap explicitly.
Second: you asked for a plan "till submission" that also keeps improving "to win top prize." I've built it as five phases with hard gates, because the realistic risk here isn't ambition — it's a solo founder running out of runway with an unsubmittable project. The plan front-loads a working submittable artifact and treats winning-grade polish as iterative layers on top of that floor. That's deliberate.
Let me write the artifact.Ran a command, created a file, read a fileRan a command, created a file, read a fileThe plan is ready to hand to Claude Code. Here's how it's built and how to use it.
Structure — five phases, each with a hard gate. Phase 0 reconcile and set up, Phase 1 real agent reasoning on mock data, Phase 2 runtime GraphRAG ingestion from two PDFs, Phase 3 deploy + A2A + demo (this is the submittable floor — Gate 3), Phase 4 submission assets, Phase 5 iterate to win. The gates are the safety mechanism: Claude Code can't move forward until each one passes, which guarantees a submittable artifact exists well before June 5 even if later work slips.
It carries the full conversation context so Claude Code understands why, not just what: the hackathon rules and judging weights, the competitive analysis (Refactor near-empty, ARIA the only adjacent rival), the Curator product background, the absolute IP boundary, the runtime-GraphRAG architecture decision with the GCP-native pipeline, and the Stage-1 state.
It's built to be flexible, as you asked. Section 0 and Section 4 explicitly instruct Claude Code to research independently, verify every API against current docs, find better alternatives, course-correct when the plan is wrong, and log decisions in docs/DECISIONS.md. The plan tells it to treat this as a plan, not a script.
It includes the win-it loop. Phase 5 runs from Gate 3 to the deadline — Agent Simulation, Agent Optimizer, deepening the fan-out, sharpening the demo — each as an independent low-risk improvement that must never break the submittable floor.
Three things to do before you hand it over:
The plan honestly flags that I built it from the Stage-1 report, not the live code — so Phase 0 makes Claude Code reconcile against its actual codebase first. That's handled, but it's why pasting the real Stage-1 files to me earlier would still help if you want me to refine anything.
The plan assumes the stage-2 branch and asks Claude Code to make the comparison-mode decision (version-pair vs. regulation-vs-policy) in Phase 0 with a default. If you have a strong preference on either, tell Claude Code directly when you hand it the plan.
Provision Spanner Graph in asia-south1 when Phase 2 starts — the plan says this, and it gives you the clean data-residency story for free.
Hand the markdown file to Claude Code and tell it to start at Phase 0. It will read its own codebase, reconcile, and proceed through the gates.Curator agent build planDocument · MD DownloadOpus 4.7 AdaptiveClaude is AI and can make mistakes. Please double-check responses.