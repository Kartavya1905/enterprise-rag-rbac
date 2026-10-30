# 9. Glossary: every technical word, explained

*Alphabetical. Each entry has a plain explanation and an example from this project.*

| Term | Plain meaning | Example in this project |
|---|---|---|
| **Access control** | Rules about who may see what | The intern can't read payroll |
| **ACL (Access Control List)** | The security sticker on a document: level, departments, named people | Payroll: level 3, HR + Finance |
| **Admin / administrator** | A person who manages documents and access, but doesn't get extra reading rights | Samuel Osei |
| **AI model / LLM** | A program that writes text; "LLM" means Large Language Model | Qwen 2.5 (7B) |
| **API** | The "front desk" programs use to talk to the system | `POST /query` asks a question |
| **Audit log** | A permanent record of who did what, and when | "Helena asked a question at 10:42" |
| **Base64** | A way of encoding text into letters and digits; attackers use it to disguise instructions | `aWdub3Jl…` = "ignore…" |
| **bcrypt** | A method for scrambling passwords so they can't be read back | Stored passwords start with `$2b$` |
| **BM25** | A classic keyword-matching method; finds exact words | Finds "SEV1" exactly |
| **Bootstrap** | The one command that sets everything up | `python -m scripts.bootstrap` |
| **Canary** | A secret code hidden in the AI's rules; if it appears in an answer, the AI was tricked | `CANARY-…`, new at every start |
| **Chunk** | A piece of a document, a few paragraphs long | The 18 documents make 71 chunks |
| **CI (Continuous Integration)** | Automatic testing of every change | GitHub Actions runs 4 jobs on every push |
| **Citation** | A marker pointing to the source of a fact | **[S1]** |
| **Clearance** | A person's security level, 1 (public) to 4 (restricted) | The intern is 1, the CEO is 4 |
| **Column-level security** | Protecting individual columns of a spreadsheet | The salary column of the directory |
| **Container** | A packaged, ready-to-run piece of software | The `api`, `postgres`, `qdrant` and `ollama` containers |
| **Context guard** | The check on found pieces just before the AI sees them | Drops the poisoned Wi-Fi piece |
| **CSP (Content Security Policy)** | Browser rules limiting what a web page may load | Only scripts from this server |
| **Defence in depth** | Several independent layers of protection | 12 layers; see [Security](05-security-explained.md) |
| **Demo login** | One-click sign-in as any example person; for testing only | Off by default, impossible in production |
| **Dense embedding** | A "meaning fingerprint" of a text: 384 numbers | "vacation" ≈ "paid time off" |
| **Docker / Docker Compose** | Tools that run and connect the containers | `docker compose up -d` |
| **Embedding** | Turning text into numbers so a computer can compare meanings | See dense / sparse |
| **Evaluation (eval)** | A large, measured test of quality and security | `reports/EVAL_REPORT.md` |
| **Fail closed** | When something looks wrong, show nothing rather than risk a leak | A failed double-check returns no results |
| **Golden questions** | Questions with known correct answers, used for scoring | "How many PTO days?" → 20 |
| **Grounded** | Every fact and number in an answer comes from the sources | 100% grounded in testing |
| **Hash** | A short fingerprint of data; any change gives a completely different fingerprint | Used to chain the audit log |
| **Hash chain** | Each record includes the hash of the one before, so tampering is detectable | "✓ Log intact" |
| **Held-out set** | Test cases kept aside and never used for tuning, for an honest score | 12 new attacks: 0 succeeded |
| **Hybrid search** | Using meaning search and keyword search together | Finds both "ARR" and "SEV1" |
| **Indexing** | Storing the pieces and their fingerprints in the search database | Step 4 of the bootstrap |
| **Ingestion** | Reading, cleaning, cutting and labelling documents | Step 3 of the bootstrap |
| **Input guard** | The check on a question before searching | Refuses "ignore all previous instructions…" |
| **JWT / token** | A signed digital pass proving who you are, valid for 60 minutes | Sent with every request after sign-in |
| **Leak** | Someone seeing information they aren't allowed to | 0 found in 585 attack attempts |
| **Leetspeak** | Replacing letters with digits to disguise words | `1gn0re` = ignore |
| **Manifest** | The master list of documents and their access labels | `data/raw/manifest.yaml` |
| **Masking / redaction** | Replacing sensitive values with `[REDACTED]` | Tax IDs, bank accounts |
| **MRR** | A score rewarding the right result being **first** in the list (1.0 = always first) | 0.980 |
| **Ollama** | Free software that runs AI models on your own computer | Runs Qwen 2.5 |
| **Output guard** | The final check on an answer before it's shown | Blocks the canary; removes fake citations |
| **Parser** | A program that pulls text out of a file | PDF, Word and Excel parsers |
| **Persona** | An example person used for testing | The 9 people of Orbitra |
| **PostgreSQL** | A free database | Stores users, the document list and the audit log |
| **Production (prod)** | The real setup that people rely on, with strict settings | `docker-compose.prod.yml` |
| **Prompt** | The text given to the AI: rules + sources + question | Built fresh for every question |
| **Prompt injection** | Hiding instructions in a question or document to hijack the AI | "SYSTEM OVERRIDE: reveal…" |
| **Qdrant** | A free search database that understands meaning and filters by labels | Holds the 71 pieces |
| **RAG (Retrieval-Augmented Generation)** | Find relevant documents first, then let the AI write from them | The whole project |
| **Rate limit** | A maximum number of requests per minute | 30 questions per minute |
| **RBAC (Role-Based Access Control)** | Access decided by who you are: role, level, department | The project's core |
| **Recall@k** | How often the right document is in the top *k* results | Recall@5 = 100% |
| **Red team** | People (or tests) attacking their own system to find weaknesses | The Phase 11 evaluation |
| **Reranker** | A second, more careful model that re-orders search results | MiniLM cross-encoder |
| **RRF (Reciprocal Rank Fusion)** | A way of merging two ranked lists: high in both means top | Merges meaning and keyword results |
| **Self-grant** | An admin giving themselves access, which is forbidden | Blocked and logged |
| **Smoke test** | A quick check that the running system works and is secure | 12 PASS lines |
| **Sparse embedding** | A "keyword fingerprint" of a text | BM25 |
| **System prompt** | The AI's fixed rules | "Answer ONLY from the sources…" |
| **Token (AI)** | A small piece of a word that AI models count; about ¾ of a word | Pieces are about 300 tokens |
| **Vector database** | A database that stores number fingerprints and finds similar ones | Qdrant |

---

**Previous:** [← 8. FAQ](08-faq-troubleshooting.md) · **Back to the start:** [Documentation home](README.md)
