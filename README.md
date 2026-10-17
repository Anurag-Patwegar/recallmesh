# RecallMesh

RecallMesh is a hackathon MVP for the **Agent Memory and Coordination** track. It gives multiple deterministic agents durable, tenant-isolated memory and observable handoffs using FalkorDB as the source of truth.

## Problem and solution

AI agents lose useful context between conversations, cannot reliably share tenant knowledge, and often hide delegation inside application state. RecallMesh persists sessions, turns, memories, tasks, handoffs, results, status events, and relationships in FalkorDB. A coordinator retrieves graph context, creates a task and handoff, routes work to a workflow specialist, and records the result. The UI shows the evidence and timeline.

## Architecture

```text
Streamlit UI
  ├── Chat & Recall ─┐
  ├── Memory Explorer │
  ├── Agent Coordination ── Deterministic agents
  ├── Graph View      │         ├── Coordinator
  ├── Isolation/Test  │         ├── Memory Agent
  └── System Health ──┘         └── Workflow Specialist
                             │
                      GraphStore repository
                             │ official falkordb client
                             ▼
              FalkorDB graph per tenant/workspace
```

No SQLite, local file, or Python dictionary is used as durable application state.

## Memory behavior

- **Episodic**: events and conversation experiences.
- **Semantic**: durable facts, preferences, and learned knowledge; fact updates create an inactive prior version and a `SUPERSEDES` edge.
- **Procedural**: instructions, workflows, and ways to complete tasks.

Personal memories require the matching `user_id`. Shared memories are visible only inside the current tenant graph. Tenant graphs are selected as `recallmesh_<validated-tenant>`.

## Graph data model

```text
(Session)-[:HAS_TURN]->(Turn)
(Session)-[:HAS_MEMORY]->(Memory)
(Memory)-[:SUPERSEDES]->(Memory)
(Task)-[:ASSIGNED_TO]->(Agent)
(Task)-[:HAS_HANDOFF]->(Handoff)-[:FROM_AGENT]->(Agent)
(Handoff)-[:TO_AGENT]->(Agent)
(Task)-[:USES_MEMORY]->(Memory)
(Task)-[:HAS_EVENT]->(CoordinationEvent)
```

Nodes include `Session`, `Turn`, `Memory`, `Agent`, `Task`, `Handoff`, and `CoordinationEvent`. Task and handoff statuses are `pending`, `in_progress`, `completed`, or `failed`, with timestamps and results/errors.

## Prerequisites and exact startup

Requirements: Python 3.11+, Docker, and a running FalkorDB container.

```bash
cd /home/Anurag/hackathon
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
docker run -d --name recallmesh-db -p 6379:6379 falkordb/falkordb:latest
python scripts/seed_demo.py --reset
streamlit run app.py
```

If the container already exists, use `docker start recallmesh-db`. With Compose instead: `docker compose up -d falkordb`.

The exact application command is `streamlit run app.py`.

## Configuration

`.env.example` defines `FALKORDB_HOST`, `FALKORDB_PORT`, optional `FALKORDB_USERNAME`, optional `FALKORDB_PASSWORD`, `FALKORDB_GRAPH_PREFIX`, and optional `LLM_API_KEY` or `OPENAI_API_KEY`. The current response path is deterministic and needs no API key. FalkorDB connectivity errors are shown in the UI and the seed command exits non-zero instead of pretending to persist.

## Demo flow

1. Open **Chat & Recall** in workspace `acme-demo`, user `maya`.
2. Send: `My preferred stack is Python, FastAPI and FalkorDB.`
3. Click **New Session**.
4. Ask: `What is my preferred stack?` and inspect the `semantic` source memory evidence.
5. Ask: `What is our release process?` and inspect the procedural memory plus the persisted task/handoff timeline.
6. Open **Agent Coordination** to see source coordinator, destination workflow specialist, handoff context, status, and result.
7. Switch to `beta-demo` or user `leo`; `maya`'s personal memory is not returned.
8. Open **Isolation & Concurrency** and run **Run Concurrent Memory Test**.
9. Open **Graph View** and **System Health** to inspect live nodes, relationships, and counts.

The seed creates only synthetic records in the dedicated `acme-demo` workspace. Re-running is idempotent for fixed IDs; `--reset` clears only that exact demo graph before reseeding.

## Actual graph operations

All application Cypher is kept in named repository methods in `memory/graph_store.py`. Representative queries are also in `queries.cypher`. They include parameterized `MATCH`, `CREATE`, `MERGE`, `SET`, the explicit demo-only `DETACH DELETE` reset, relationship creation, filtered retrieval, status transitions, exact concurrent verification, and `SUPERSEDES` updates.

## Tests and validation

```bash
source .venv/bin/activate
python -m pytest -q
python -m compileall -q app.py memory agents tests scripts
```

The suite covers connection-backed memory lifecycle, cross-session persistence, restart-like fresh clients, personal/shared/tenant isolation, fact supersession, agent task/handoff completion, concurrent writes and concurrent reads.

## Known limitations and security

- The demo user selector is logical isolation, not authentication or authorization.
- The fallback classifier and response synthesis are deterministic; no LLM provider is required.
- Production deployments still need network controls, secret management, TLS, authentication, rate limits, and a real identity provider.
- The UI is a local hackathon interface, not a hardened multi-user service.
- Concurrent verification is an application-level demonstration, not a benchmark or transactional workflow engine.
- Graph visualization limits displayed nodes/edges for responsiveness, while sourcing every displayed item from FalkorDB.

## Troubleshooting

- **Unavailable**: check `docker ps`, `FALKORDB_HOST`, `FALKORDB_PORT`, and port `6379`.
- **Existing container name**: run `docker start recallmesh-db`.
- **Empty workspace**: run `python scripts/seed_demo.py --reset` and refresh Streamlit.
- **No memory for another user**: expected for `personal`; use `shared` for tenant-wide knowledge.
- **Failed test**: ensure FalkorDB is running and rerun `python -m pytest -q`.

## Disclosure

AI coding assistants were used during implementation and validation. Claims in this document are based on the checked-in code and commands actually run.

## Final verification checklist

- [x] FalkorDB is the persistent source of truth.
- [x] Tenant graphs and user-scoped personal memory are enforced.
- [x] Cross-session and fresh-client persistence are tested.
- [x] Memory updates preserve history with `SUPERSEDES`.
- [x] Real coordinator handoffs and status/result persistence are tested.
- [x] Concurrent writes and reads are verified with UUID records.
- [x] Six judge-facing UI views exist.
- [x] Synthetic demo seed is repeatable and reset-scoped.
- [x] Startup, test, troubleshooting, limitations, and recording guidance are documented.

## 2–3 minute demo recording plan

1. **0:00–0:20** — Show `acme-demo`, `maya`, FalkorDB connected, and explain graph-per-tenant isolation.
2. **0:20–0:55** — Save the preferred-stack sentence, click **New Session**, ask the question, and point to the semantic FalkorDB source memory.
3. **0:55–1:30** — Ask the release-process question; show coordinator → workflow specialist, memory references, completed status, result, and persisted timeline.
4. **1:30–1:55** — Switch to `beta-demo` and `leo`; show the personal memory is absent, then return to `acme-demo`/`maya`.
5. **1:55–2:20** — Run the concurrent memory test and show attempted, successful, failed, and verification counts.
6. **2:20–2:45** — Show Graph View and System Health, then mention the tests and deterministic no-key fallback.
