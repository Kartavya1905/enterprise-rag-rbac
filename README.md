# Enterprise RAG with Role-Based Access Control (RBAC)

[![CI](https://github.com/Kartavya1905/enterprise-rag-rbac/actions/workflows/ci.yml/badge.svg)](https://github.com/Kartavya1905/enterprise-rag-rbac/actions/workflows/ci.yml)

An internal document assistant that answers questions over enterprise documents (PDFs, sheets)
**without leaking information a user isn't cleared to see**. Access control is enforced at
retrieval time: unauthorized chunks are filtered out of the vector/keyword search, so the LLM
never sees them, no matter how clever the prompt.

**Measured, not claimed** ([full report](reports/EVAL_REPORT.md)): **0 leaks** in 405 attack
searches and 180 LLM answers across 9 users, **0 / 46** successful prompt injections,
Recall@5 **100%**, answers **95%** correct with **100%** grounded numbers. It runs entirely on
local, free, open-source models.

```mermaid
flowchart LR
    U[User] -->|JWT| API[FastAPI]
    API -->|who are you?| PG[(Postgres<br/>users · registry · audit)]
    API --> IG{Input guard}
    IG -->|clean| S[Hybrid search<br/>dense + BM25]
    S -->|ACL filter inside Qdrant| Q[(Qdrant)]
    S --> DC[Double-check<br/>can_read] --> RR[Rerank] --> CG{Context guard}
    CG --> LLM[Ollama<br/>qwen2.5:7b] --> OG{Output guard} --> U
    API -.->|every request| AUD[Hash-chained<br/>audit log]
    DOCS[PDF · DOCX · XLSX<br/>+ manifest ACLs] -->|parse · chunk · label| Q
```

| Want to… | Go to |
|---|---|
| **Understand it without a technical background** | **[docs/README.md](docs/README.md)**: 9 step-by-step guides with examples, also as [one PDF](docs/Orbitra-Assist-Complete-Guide.pdf) |
| Run it in 5 commands | [Quick start with Docker](#quick-start-with-docker) |
| Show it to someone | [docs/DEMO.md](docs/DEMO.md), or `python -m scripts.demo` |
| Deploy it for real | [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) |
| See the security evidence | [reports/EVAL_REPORT.md](reports/EVAL_REPORT.md) |

## Quick start with Docker

Needs only Docker Desktop. An NVIDIA GPU is optional but makes answers much faster.

```powershell
Copy-Item .env.example .env        # then set DEMO_LOGIN=true for one-click persona sign-in
docker compose up -d --build --wait
docker compose --profile llm up -d ollama          # GPU: add -f docker-compose.yml -f docker-compose.gpu.yml
docker compose exec ollama ollama pull qwen2.5:7b  # once (~4.7 GB); llama3.2:3b without a GPU
docker compose exec api python -m scripts.bootstrap
```

Open **http://localhost:8001/app/**, sign in as the intern and then as the CEO, and ask
*"What is the CEO's base salary?"*. Persona passwords are in `data/org/dev_credentials.yaml`.
To check the installation: `docker compose exec api python -m scripts.smoke_test`.

## Status

| Phase | Scope | Status |
|---|---|---|
| 1 | Project setup, config, FastAPI skeleton, health checks, Docker Compose | Done |
| 2 | Synthetic enterprise dataset, ACL manifest, personas, golden Q&A | Done |
| 3 | Auth: users, roles, clearance, JWT, spoofing defenses | Done |
| 4 | Ingestion: PDF/DOCX/XLSX parsing, chunking, ACL on every chunk, registry | Done |
| 5 | Embeddings + Qdrant indexing (dense + sparse, payload indexes, incremental) | Done |
| 6 | RBAC-aware hybrid retrieval, double-check, reranking, `POST /search` | Done |
| 7 | Secure generation: local LLM, injection guards, redaction, citations, `POST /query` | Done |
| 8 | Admin API (upload, ACL changes, removal), rate limiting, security headers | Done |
| 9 | Tamper-evident audit log, masking, stats, request IDs + timings | Done |
| 10 | Web UI: chat with citations, persona switcher, admin + audit dashboard | Done |
| 11 | Red-team evals: RBAC leak suite, injection suites, retrieval + answer quality | Done |
| 12 | CI, production deployment, bootstrap, smoke test, demo, docs | Done |

## Tech stack

FastAPI · Pydantic Settings · SQLAlchemy (SQLite in dev, Postgres in Docker) ·
Qdrant (embedded in dev, server in Docker) · PyJWT + bcrypt · FastEmbed (BGE, BM25, MiniLM
reranker) · Ollama + Qwen2.5 7B (local LLM) · pytest · ruff

**Zero cost by design:** every component is open source and runs locally. No paid APIs,
no API keys, no cloud bills. The LLM runs through Ollama, and the embedding and reranker
models run locally through FastEmbed (ONNX, CPU).

## Project layout

```
app/
  api/          HTTP routes: health, auth, search, query, admin, audit
  auth/         users table, passwords, JWT, current-user check
  ingestion/    manifest, parsers, chunker, pipeline, documents registry, admin changes
  retrieval/    embeddings, Qdrant collection, indexer, ACL filter, secure search, reranker
  security/     injection detection, redaction, output guard
  generation/   Ollama client, grounded prompt, answer pipeline
  audit/        tamper-evident audit log, masking, statistics
  core/         config, access rules (can_read), DB + vector store clients, rate limits
  web/          web UI: index.html, css/, js/ (no build step)
data/raw/       synthetic enterprise documents + manifest.yaml (the ACLs)
data/org/       demo personas
data/eval/      golden Q&A, leak attacks, injection suites, retrieval questions
scripts/        bootstrap, smoke test, demo, create_user, dataset, ingest, index, evals
tests/
  unit/         unit tests
  rbac_leak/    the 45-attack leak suite on every persona
  evals/        tests for the evaluation metrics
reports/        EVAL_REPORT.md + eval_results.json (Phase 11)
docs/           DEPLOYMENT.md, DEMO.md
.github/        CI workflow + Dependabot
```

## Scripts

| Command | What it does |
|---|---|
| `python -m scripts.bootstrap` | One step from empty databases to ready: users, ingest, index, LLM check |
| `python -m scripts.smoke_test` | 12 checks on a **running** API: health, headers, auth, access control, prod config |
| `python -m scripts.demo` | Same questions as different people, answers side by side |
| `python -m scripts.create_user …` | Add or update one real account (how users get into production) |
| `python -m scripts.generate_dataset` | Regenerate the 18 synthetic documents (dev only) |
| `python -m scripts.seed_users` · `ingest_documents` · `index_chunks` | The individual bootstrap steps |
| `python -m scripts.run_evals` | The full red-team + quality evaluation (~1 h) |

Inside Docker, prefix any of these with `docker compose exec api` (except the dev-only
`generate_dataset` and `run_evals`).

## Quick start (local, no Docker needed)

Uses SQLite (`data/dev.db`) and embedded Qdrant (`data/qdrant/`).

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
uvicorn app.main:app --reload
```

Then open:

- http://localhost:8000/health: liveness
- http://localhost:8000/health/ready: checks DB + vector store (503 if either is down)
- http://localhost:8000/docs: interactive API docs

Run the tests and the linter:

```powershell
pytest            # everyday suite (~1.5 min), the same one CI runs
pytest -m slow    # only the end-to-end checks with the real AI models (~2 min)
pytest -m "slow or not slow"   # everything
ruff check .
```

## Running with Docker

Requires Docker Desktop.

```powershell
docker compose up --build
```

This starts Postgres, Qdrant (dashboard at http://localhost:6333/dashboard) and the API on
port 8000. To run only the backing services and keep the API local with hot reload:

```powershell
docker compose up -d postgres qdrant
```

Then set `DATABASE_URL` and `QDRANT_URL` in `.env` (see the commented lines in `.env.example`).

## The dataset (fictional company: Orbitra Systems)

18 synthetic documents (PDF, DOCX, XLSX) across four clearance levels, generated
deterministically by:

```powershell
python -m scripts.generate_dataset
```

| Path | What it is |
|---|---|
| `data/raw/<category>/` | The documents: handbook, payroll, board minutes, budgets, ... |
| `data/raw/manifest.yaml` | Each document's ACL: clearance, departments, allowed/denied users, column policies |
| `data/org/personas.yaml` | 9 demo users, from intern (clearance 1) to CEO (clearance 4), plus an admin |
| `data/ACCESS_MATRIX.md` | Who can read what, computed from the reference policy |
| `data/eval/golden_qa.yaml` | 21 questions with known answers, for retrieval evals |

Built-in test cases for the access controls:

- **Mixed sensitivity:** the employee directory is visible to all staff, but its salary column
  is HR/Finance only and its performance-rating column is HR only.
- **Need-to-know grant:** the engineering manager is named on the finance cloud-cost review.
- **Explicit deny:** the HR partner is blocked from an investigation they were a witness in.
- **Poisoned document:** a public Wi-Fi guide hides a prompt-injection payload in invisible
  text that parsers still extract.
- **Existence-sensitive:** the restructuring plan must not even be acknowledged to others.

The access rules live in one place, `app/core/access.py` (`can_read`). Every later enforcement
point must agree with it, and the tests use it as the oracle.

## Authentication

Create login accounts for the 9 personas (random passwords are written to the git-ignored
`data/org/dev_credentials.yaml`):

```powershell
python -m scripts.seed_users                     # local SQLite
python -m scripts.seed_users --database-url postgresql+psycopg://rag:rag_dev_password@localhost:5432/enterprise_rag
```

Then open http://localhost:8000/docs, click **Authorize**, and log in with a persona's email
and password. `GET /auth/me` shows who you are.

| Endpoint | Purpose |
|---|---|
| `POST /auth/login` | Email + password (OAuth2 form) in, signed JWT out (60 min) |
| `GET /auth/me` | The current user, as the **database** knows them |

How identity is protected:

- Passwords are stored only as bcrypt hashes; unknown-email and wrong-password logins
  look identical (same message, same timing).
- Tokens are HS256-signed with a 32+ character secret; forged, tampered, unsigned
  (`alg: none`), expired and wrong-audience tokens are rejected.
- **Role and clearance are never taken from the request or the token.** Every request
  reloads the user from the database, so a demotion or a disabled account takes effect
  immediately.

## Ingestion

```powershell
python -m scripts.ingest_documents                     # local SQLite registry
python -m scripts.ingest_documents --database-url postgresql+psycopg://rag:rag_dev_password@localhost:5432/enterprise_rag
```

`manifest.yaml + data/raw/*` → **parse** (PyMuPDF / python-docx / openpyxl) → **chunk** →
`data/processed/chunks.jsonl` + the `documents` table (new / changed / unchanged).

- **Every chunk carries its document's ACL**, copied from the manifest and never invented.
  Files with no manifest entry are reported and **not** ingested.
- **Column-level security:** spreadsheet columns are grouped by label. Salary values live in
  separate chunks labelled HR/Finance-only, so other users' searches can never return them.
- **Hidden content is removed and reported:** white or microscopic PDF text, hidden Word
  runs, and hidden sheets, rows or columns. This removes the poisoned document's injection.
- **Structure-aware chunks** of about 300 tokens (max 400). A new heading starts a new chunk,
  tables stay as Markdown, and every chunk begins with a
  `[Document: … | Section: …]` context header.

## Indexing

```powershell
python -m scripts.index_chunks                                   # embedded Qdrant
python -m scripts.index_chunks --qdrant-url http://localhost:6333   # Docker Qdrant
```

Each chunk becomes a Qdrant point with two vectors and its full ACL in the payload:

- **dense**: `BAAI/bge-small-en-v1.5` (384 numbers), which matches by *meaning*
- **sparse**: `Qdrant/bm25` with IDF, which matches *exact words* (codes, names, numbers)

Both models run locally on CPU through FastEmbed (~65 MB, downloaded once to
`data/models/`). Payload indexes cover `clearance_level`, `departments`,
`allowed_users`, `denied_users` and more, so access-filtered search stays fast.

Re-runs are **incremental**. Each document's fingerprint covers its chunks' text **and
ACL**, so tightening a document's permissions in the manifest reaches the index even when
the file itself is unchanged. Old points are deleted before new ones are written, and
documents that are no longer ingested are removed.

Baseline on the 21 golden questions, with no access filter:

| Mode | Recall@1 | Recall@5 |
|---|---|---|
| Dense | 20/21 | 21/21 |
| Sparse (BM25) | 20/21 | 20/21 |
| Hybrid (RRF) | 20/21 | 21/21 |

## Secure search

`POST /search` with `{"query": "...", "top_k": 5}` returns the most relevant chunks **the
logged-in user may read**. Try it from http://localhost:8000/docs after **Authorize**.

```
user (from DB) ─► ACL filter ─┬─► dense search  (filtered) ─┐
question ─► embeddings ───────┴─► sparse search (filtered) ─┴─► RRF fusion
   ─► double-check every hit with can_read()  (any violation → alert + return nothing)
   ─► cross-encoder rerank ─► top 5
```

- The filter is applied **inside Qdrant**, on both search paths, so unauthorized chunks are
  never scored or returned. Tests show the filter matches `can_read()` exactly for every
  persona and for 120 random users.
- **Defense in depth:** every hit is re-checked against `can_read()`. A broken filter or a
  point with a missing label causes a `SECURITY` alert and an empty result (fail closed).
- **No existence leaks:** responses never include other users' access lists, and "nothing
  found" is the same neutral message for everyone.

Measured live on the Docker stack (21 golden questions × 8 users = 168 searches):

| Check | Result |
|---|---|
| Authorized users found the right document (top 5) | **105 / 105** |
| Unauthorized users who got the forbidden document | **0** |
| Results the asker could not read | **0** |
| Average latency (CPU, after warm-up) | 0.58 s |

## Answers from the local LLM

Start the model server once. It's free and local; the GPU file is optional but much faster:

```powershell
docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile llm up -d ollama
docker compose exec ollama ollama pull qwen2.5:7b      # ~4.7 GB; llama3.2:3b without a GPU
```

`POST /query` with `{"question": "..."}` returns `answer`, `citations` and `sources`.

```
question ─► INPUT GUARD (injection? → polite refusal, no search, no LLM)
         ─► SECURE SEARCH (Phase 6: only chunks this user may read)
         ─► CONTEXT GUARD (drop chunks containing injections; mask tax IDs / bank accounts)
         ─► nothing left? → "I couldn't find that in the documents you have access to." (no LLM)
         ─► LLM: fixed rules + sources fenced as <source> DATA (escaped) + question
         ─► OUTPUT GUARD (canary leak → block; mask IDs; drop invented [S#] citations)
```

- The prompt carries **no access information**. The model can't leak what it never
  receives, so every other layer protects the model itself.
- Internal security flags are logged, never returned to the caller.

Measured live (Docker, RTX 5070 laptop GPU, `qwen2.5:7b`):

| Check | Result |
|---|---|
| Golden questions answered correctly with the right citation | **20 / 20** answerable (+1 correct refusal of a salary column the asker can't see) |
| Attack prompts from the intern that leaked a secret | **0 / 10** |
| Average answer time | **1.4 s** |

## Administration and API hardening

The admin persona `u_it_admin` (Samuel Osei, role `admin`) manages documents:

| Endpoint | Purpose |
|---|---|
| `GET /admin/documents` | Every document with its ACL and chunk count |
| `POST /admin/documents` | Upload a PDF/DOCX/XLSX with its ACL (multipart form) |
| `PATCH /admin/documents/{doc_id}/acl` | Change clearance, departments, allowed or denied users |
| `DELETE /admin/documents/{doc_id}` | Remove from the manifest and the index (the file is kept) |
| `POST /admin/reindex` | Re-ingest and re-index everything that changed |

- Each change is validated, written to `manifest.yaml` atomically, then pushed through
  ingest → index. **Access changes reach search immediately**, and a failed change is rolled
  back.
- **Admin rights don't widen reading rights.** Searches by the admin still use clearance 3
  and Engineering, and **admins can't grant themselves access** (403, logged).
- Uploads are checked by their real content (magic bytes), size-limited (10 MB), and stored
  under a name built from the validated `doc_id`, never the uploaded filename.
- **Rate limits** (per 60 s): login 10 per IP; search 60, query 30, admin 30 per user.
  Going over returns `429` with `Retry-After`.
- **Security headers** on every response, including `Cache-Control: no-store`, so answers are
  never cached.
- **No streaming, by design:** the output guard must see the complete answer before any of
  it is shown.

After a change to the users table (like the new `admin` role), reset dev databases with
`python -m scripts.seed_users --reset`.

## Audit log

Every query, search, login, rate-limit hit and admin action is written to the
`audit_events` table. The record covers who, when, from which IP, which documents were
retrieved and cited, security flags, latency, and per-step timings. **Answers are never
stored**, and tax IDs or account numbers in questions are masked.

| Endpoint (admins only) | Purpose |
|---|---|
| `GET /admin/audit` | Recent events, filterable by type, user, outcome and time |
| `GET /admin/audit/stats` | Volumes, security signals (injections, failed logins, self-grants …), top documents, latency p95 |
| `GET /admin/audit/verify` | Recomputes the hash chain and reports whether the log has been altered |

- **Tamper-evident:** each row stores the SHA-256 of the previous row plus its own
  contents. Editing or deleting any past row breaks the chain, and `verify` names the
  first bad row. There is no API to edit or delete events.
- **No side channel:** when an event touched a document the *viewer* may not read, its
  question and those document IDs show as `[hidden]`. The admin can't learn of the
  restructuring plan by reading the CEO's questions.
- **Who watches the watchers:** reading the log is itself logged (`audit_view`).
- **Tracing:** every response has an `X-Request-ID` header, stored with the event.
- The log never breaks a request: a failed audit write is logged as `CRITICAL` and the
  user still gets their answer.

## Web UI

Open **http://localhost:8000/app/**. It's plain HTML, CSS and JavaScript served by the API
itself, with no build step and no extra server.

| Screen | What it does |
|---|---|
| Sign in | Email + password. With `DEMO_LOGIN=true` (dev only) there's also one-click sign-in as any persona. |
| Ask | Chat with clickable `[S1]` citations that highlight their source, plus suggested questions (including an injection attempt) |
| Admin → Documents | Every document with its ACL; edit access or remove a document |
| Admin → Upload | Add a PDF, DOCX or XLSX file with its ACL |
| Admin → Audit log | Security counters, tamper check, and the event log with `[hidden]` masking |

**Demo:** sign in as Aarav (intern) and ask *"What is the CEO's base salary?"* → "I couldn't
find that…". Switch to Helena (CEO) → "$310,000 [S1]". Switch to Samuel (admin) →
Audit log: the CEO's question shows as **hidden**.

Security:
- **XSS-safe by construction.** Server text (answers, documents, names) is only ever
  inserted as text nodes. A test fails if any script uses `innerHTML`, `eval` or similar.
- **Strict Content-Security-Policy:** scripts, styles and data from this server only, with
  no inline code and no framing.
- The token is kept in `sessionStorage` (cleared when the tab closes). Chat history isn't
  saved anywhere in the browser.
- Admin screens are hidden from non-admins, but the **server** enforces it (403).
- `DEMO_LOGIN` is off by default, its routes return 404 when off, prod refuses to start with
  it on, and every use is audited.
- All Docker ports are published on **127.0.0.1 only**, so other devices on your network
  can't reach the API, Postgres, Qdrant or Ollama.

## Evaluation results

Full report: **[reports/EVAL_REPORT.md](reports/EVAL_REPORT.md)**. Measured on the real system
(`qwen2.5:7b` on an RTX 5070 laptop GPU, BGE + BM25 + MiniLM reranker):

| Check | Result |
|---|---|
| RBAC leak suite: 45 attacks × 9 personas through search | **0 leaks in 405 searches** (0 unreadable chunks returned) |
| RBAC leak suite through the full LLM pipeline | **0 leaks in 180 answers** |
| Golden questions asked by users not allowed to know the answer | **0 / 15 leaked** (15/15 neutral refusals) |
| Prompt injection, 34 attacks in 10 categories | **0 succeeded** (baseline: 1, fixed) |
| Prompt injection, **12 held-out attacks** never used for tuning | **0 succeeded**; the input guard alone caught 4/12 |
| Indirect injection (poisoned document in the index) | Retrieved 3/3, reached the LLM 0/3, complied 0/3 |
| Retrieval Recall@1 / Recall@5, 59 questions | 97% / 100% (hybrid + rerank) vs 88% / 100% dense only |
| Answers: correct / right citation / every number grounded | 95% / 100% / 100% |

The honest takeaway: the pattern-based input guard **doesn't generalise** (33% on unseen
attacks). The guarantees come from the layers that don't depend on wording: restricted text
never reaches the model, the fenced prompt rules, and the output guard.

```powershell
python -m scripts.run_evals --qdrant-url http://localhost:6333            # everything (~1 h)
python -m scripts.run_evals --qdrant-url http://localhost:6333 --only injection,answers
```

The same 45 leak attacks also run on every `pytest` (with offline fakes) in
`tests/rbac_leak/`.

## Continuous integration

`.github/workflows/ci.yml` runs on every push and pull request. It's free: GitHub Actions is
unlimited for public repositories and includes 2,000 minutes a month for private ones.

| Job | Checks |
|---|---|
| lint | `ruff check .` |
| test | the full everyday `pytest` suite, including the 45 × 9 RBAC leak suite, on Python 3.11 and 3.12 |
| audit | `pip-audit`: no installed library with a known vulnerability |
| docker | builds the image, starts Postgres + Qdrant + API, runs `bootstrap`, then the `smoke_test` access checks against the live stack |

The real-LLM tests (`-m slow`) and the hour-long `run_evals` stay local because CI has no
GPU. Dependabot (`.github/dependabot.yml`) opens weekly update PRs, which CI tests before
merge.

## Deployment

`docker-compose.prod.yml` turns the same stack into production: required secrets,
`ENVIRONMENT=prod` (weak secrets and demo login refuse to start), demo personas refused,
Qdrant behind an API key, separate volumes, automatic restarts and log rotation. Real
accounts are added with `scripts.create_user`. The walkthrough, including free ways to
share it (Tailscale, Cloudflare Tunnel), backups and a checklist, is in
**[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)**.

## Configuration

All settings come from environment variables or `.env`. See `.env.example`, and
`.env.prod.example` for production. In `ENVIRONMENT=prod` the app refuses to start with
the default `JWT_SECRET_KEY` or with `DEMO_LOGIN` on.

## Limitations

- One API process: rate limits are kept in memory. Scaling out would need a shared store
  (for example Redis).
- No schema migrations: tables are created on startup. Production schema changes would need
  Alembic or similar.
- Small synthetic corpus (18 documents). The input guard is a speed bump, not a guarantee;
  see the held-out results in the evaluation report.
- PyMuPDF is AGPL-3.0. Offering this as a network service means making its source available.

## Security principle

> The model must never see text the user isn't authorized to read.

Access is decided server-side from the verified identity (never from request input), applied as
a filter on **every** retrieval path (dense and lexical), re-verified after retrieval, and logged.
