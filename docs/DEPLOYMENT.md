# Deployment guide

Everything here is free: open-source software running on hardware you already have.
Anything that *could* cost money is marked **(cost)**.

## Contents

1. [Which setup do I need?](#1-which-setup-do-i-need)
2. [Dev stack with Docker](#2-dev-stack-with-docker)
3. [Production stack](#3-production-stack)
4. [User accounts in production](#4-user-accounts-in-production)
5. [Letting other people use it](#5-letting-other-people-use-it)
6. [Operations: updates, backups, monitoring](#6-operations-updates-backups-monitoring)
7. [Hardware](#7-hardware)
8. [Production checklist](#8-production-checklist)
9. [Known limitations](#9-known-limitations)

---

## 1. Which setup do I need?

| Setup | Databases | Login | Use it for |
|---|---|---|---|
| **Local dev** (`uvicorn --reload`) | SQLite + embedded Qdrant | demo personas | writing code |
| **Dev stack** (`docker-compose.yml`) | Postgres + Qdrant servers | demo personas, optional one-click demo login | demos, evals, trying it out |
| **Production stack** (`+ docker-compose.prod.yml`) | Postgres with a real password, Qdrant with an API key | real accounts only | anything other people rely on |

All three run the same code. Only the settings differ.

## 2. Dev stack with Docker

```powershell
docker compose up -d --build --wait                       # Postgres, Qdrant, API
docker compose --profile llm up -d ollama                 # local LLM (CPU)
#   with an NVIDIA GPU instead:
#   docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile llm up -d ollama
docker compose exec ollama ollama pull qwen2.5:7b         # once, ~4.7 GB (llama3.2:3b on CPU)
docker compose exec api python -m scripts.bootstrap       # users + ingest + index
docker compose exec api python -m scripts.smoke_test      # 12 checks, should all PASS
```

Open http://localhost:8000/app/. The persona passwords are in `data/org/dev_credentials.yaml`.

`--wait` returns once every service reports **healthy**. The API counts as healthy only when
`/health/ready` can reach both databases.

## 3. Production stack

### 3.1 Secrets

```powershell
Copy-Item .env.prod.example .env.prod      # git-ignored
python -c "import secrets; print(secrets.token_urlsafe(48))"   # run 3 times, one per secret
```

Fill in `POSTGRES_PASSWORD`, `QDRANT_API_KEY` and `JWT_SECRET_KEY` with **three different**
values. If any is missing, Compose stops with `set … in .env.prod`.

### 3.2 Start it

```powershell
$prod = "-f", "docker-compose.yml", "-f", "docker-compose.prod.yml", "--env-file", ".env.prod", "-p", "enterprise-rag-prod"
docker compose @prod up -d --build --wait
docker compose @prod exec api python -m scripts.bootstrap      # ingest + index (no demo users)
docker compose @prod exec api python -m scripts.smoke_test
```

On Linux or macOS, write the same flags out in full:
`docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.prod -p enterprise-rag-prod …`.

**Linux hosts only:** the API container runs as an unprivileged user (uid 1000). Let it write
the mounted data folders once with `sudo chown -R 1000 data/raw data/processed data/org`.
Docker Desktop on Windows and macOS doesn't need this.

### 3.3 What production changes

| | Dev stack | Production stack |
|---|---|---|
| `ENVIRONMENT` | dev | **prod**, forced in the compose file |
| JWT secret | from `.env` | required; the app refuses to start if it's weak or the placeholder |
| Demo login | optional | **off and forced off**; the app refuses to start if it's on |
| Demo personas | seeded | **refused** (`seed_users` won't run in prod) |
| Postgres | dev password | your password, in **separate volumes** (`-p enterprise-rag-prod`) |
| Qdrant | no auth | **API key on every request** (verified: no key → 401), telemetry off |
| Restarts | manual | `unless-stopped`: back after a crash or a reboot |
| Logs | unlimited | rotated, 3 × 10 MB per service |
| Ports | 127.0.0.1 only | 127.0.0.1 only |

Your dev `.env` isn't read in production (`env_file: !override`), so a leftover
`DEMO_LOGIN=true` there can't leak in.

The API talks to Qdrant over plain HTTP **inside Docker's private network**, so the client
prints "Api key is used with an insecure connection". Qdrant's port is published only on
127.0.0.1, so the key never crosses a real network. If you move Qdrant to another machine,
enable TLS on it first.

## 4. User accounts in production

Demo personas are blocked in prod, so add each real person:

```powershell
docker compose @prod exec api python -m scripts.create_user `
  --user-id u_jdoe --email jane.doe@example.com --name "Jane Doe" --title "Financial Analyst" `
  --role finance --clearance 3 --department finance
```

- The password is **generated and printed once**. Only its bcrypt hash is stored.
- Run the command again with the same `--user-id` to change clearance, departments or role,
  or to reset the password. The change applies on the user's **next request**, because every
  request reloads the user from the database (Phase 3).
- `--role admin` grants the admin screens, not extra reading rights.
- Repeat `--department` for people in several departments.

Documents and their access rules are managed by an admin in the web UI (**Admin →
Documents / Upload**) or through the `/admin` API.

## 5. Letting other people use it

By default every port listens on **127.0.0.1**, so nobody else can reach the system. Three
ways to change that, safest first:

| Option | Cost | Notes |
|---|---|---|
| **Tailscale** (private network between your devices) | free for personal use | Only people you invite can connect. No public exposure. Best for showing friends or reviewers. |
| **Cloudflare Tunnel** | free | A public HTTPS address without opening router ports. Pair it with Cloudflare Access (free tier) so only listed emails get in. |
| Your own domain + **Caddy** reverse proxy (automatic free HTTPS from Let's Encrypt) | **(cost)** a domain, about $10/year | Classic setup. Caddy listens on 443 and forwards to `127.0.0.1:8000`. |

Rules for any of these:
- **Use the production stack**, never the dev stack with demo login.
- Expose **only the API (port 8000)**. Never expose Postgres, Qdrant or Ollama.
- Behind a reverse proxy, every request appears to come from the proxy's IP, so the
  per-IP login rate limit would apply to everyone together. Start uvicorn with
  `--proxy-headers --forwarded-allow-ips=<proxy IP>` so the real client IP is used.
- Free cloud VMs exist (for example Oracle Cloud's "Always Free" tier) but need a payment
  card for sign-up **(cost risk)**. This project assumes your own computer.

## 6. Operations: updates, backups, monitoring

**Update:** `git pull`, then `docker compose @prod up -d --build --wait`, then run the
smoke test again. Re-running `bootstrap` is safe: unchanged documents are skipped.

**Back up** the things that can't be rebuilt:

```powershell
# users, document registry, audit log -> backup.dump (pg_dump's compressed format)
docker compose @prod exec -T postgres pg_dump -U rag -Fc -f /tmp/backup.dump enterprise_rag
docker compose @prod cp postgres:/tmp/backup.dump ./backup.dump
```

Also back up `data/raw/` (the documents and `manifest.yaml`). The Qdrant index **can** be
rebuilt from those with `scripts.bootstrap`, so backing it up is optional.

Restore:

```powershell
docker compose @prod cp ./backup.dump postgres:/tmp/backup.dump
docker compose @prod exec -T postgres pg_restore -U rag -d enterprise_rag --clean --if-exists /tmp/backup.dump
```

**Monitor:**
- `GET /health/ready` returns 503 when a database is down. The Docker healthcheck uses it.
- **Admin → Audit log** shows security counters (injections, failed logins, self-grants).
  **Verify chain** checks that the log hasn't been altered.
- `docker compose @prod logs -f api` shows `SECURITY` and `CRITICAL` lines, the ones that
  matter.

## 7. Hardware

| Part | Needs |
|---|---|
| API + embeddings + reranker | ~1.5 GB RAM, CPU only |
| Postgres + Qdrant (this corpus) | < 500 MB RAM |
| Ollama `qwen2.5:7b` | NVIDIA GPU with ~8 GB VRAM (answers in about 1–6 s) |
| Ollama `llama3.2:3b` | CPU-only alternative: slower and weaker with numbers |

`OLLAMA_KEEP_ALIVE` in `.env.prod` controls how long the model stays in GPU memory after a
question. Longer means no ~35 s cold start, but ~5.6 GB of GPU memory stays in use.

## 8. Production checklist

- [ ] `.env.prod` has three different random secrets and is **not** committed
- [ ] `docker compose @prod exec api python -m scripts.smoke_test` → ALL CHECKS PASSED
- [ ] No demo personas, and every real account created with `create_user`
- [ ] Only port 8000 is reachable from outside, through Tailscale, a tunnel or HTTPS
- [ ] A backup of the database and `data/raw/` exists, and you've tried restoring it once
- [ ] **Admin → Audit log → Verify chain** reports intact
- [ ] The CI badge is green for the commit you deployed

## 9. Known limitations

- **One API process.** Rate limits are kept in memory, so run a single uvicorn worker,
  which is the default. Several workers or servers would need a shared store such as Redis.
- **No database migrations.** Tables are created on startup. A schema change on a
  database with real data needs a migration tool (for example Alembic). `--reset` is
  dev-only.
- **Licence:** PyMuPDF is AGPL-3.0. If you offer this system **as a service to other
  people**, the AGPL requires making the complete source available to them. A public
  GitHub repository satisfies that.
