# 3. Installation guide (Windows, for beginners)

*Time needed: about 30–60 minutes, mostly waiting for downloads. No programming needed.*

Follow the steps **in order**. Each step says what to do, what you should see, and what to
do if it doesn't work. Text in grey boxes is something to **copy and paste**.

---

## Before you start: what you need

| Item | Minimum | Recommended |
|---|---|---|
| Computer | Windows 10 or 11 | Windows 11 |
| Memory (RAM) | 8 GB | 16 GB |
| Free disk space | 15 GB | 25 GB |
| Graphics card | not required | an **NVIDIA** card with 8 GB memory (answers in seconds, not minutes) |
| Internet | only for the first setup (about 6 GB of downloads) | |

**Not sure whether you have an NVIDIA card?** Press the Windows key, type `PowerShell`,
open it, paste the line below and press Enter:

```powershell
nvidia-smi
```

- A table with a card name (for example "GeForce RTX 5070") → ✅ you have one.
- "not recognized" → no NVIDIA card. That's fine: you'll use the smaller AI model in step 7.

---

## Step 1: install Docker Desktop

**What it is:** Docker runs ready-made "boxes" (containers) of software, so you don't have
to install a database, a search engine and an AI server one by one.

1. Go to **https://www.docker.com/products/docker-desktop/** and download Docker Desktop for
   Windows.
2. Run the installer and keep the default options.
3. **Restart your computer** if it asks.
4. Open **Docker Desktop** from the Start menu. Accept the agreement and skip the sign-in;
   you don't need an account.
5. Wait until the bottom-left corner says **"Engine running"** (green).

**Cost note:** Docker Desktop is free for personal use, education and small businesses.
Large companies (over 250 employees or $10M revenue) need a paid licence **(cost)**.

**Problem?** If Docker mentions **WSL** or **virtualization**, open PowerShell **as
Administrator** (right-click → "Run as administrator"), run `wsl --install`, restart, and
try again.

---

## Step 2: install Git

**What it is:** Git downloads the project and keeps it up to date.

1. Go to **https://git-scm.com/download/win** and download "Git for Windows".
2. Run the installer and keep **every default option**.

**No Git?** On the GitHub page, click **Code → Download ZIP**, unzip the folder, and skip
to Step 4.

---

## Step 3: download the project

1. Open **PowerShell** (Windows key → type `PowerShell` → Enter).
2. Go to your Documents folder and download the project:

```powershell
cd $HOME\Documents
```

```powershell
git clone https://github.com/Kartavya1905/enterprise-rag-rbac.git
```

**You should see:** `Cloning into 'enterprise-rag-rbac'...` and then `done`.

---

## Step 4: open the project folder

```powershell
cd $HOME\Documents\enterprise-rag-rbac
```

**Every command from now on is typed in this same window, inside this folder.** If you
close PowerShell, open it again and repeat this `cd` line first.

---

## Step 5: create your settings file

The project ships with an example settings file. Make your own copy:

```powershell
Copy-Item .env.example .env
```

**Optional but recommended for trying it out:** turn on one-click demo sign-in, so you
don't have to type passwords:

```powershell
notepad .env
```

In Notepad, find the line `DEMO_LOGIN=false`, change it to `DEMO_LOGIN=true`, save
(Ctrl+S) and close Notepad.

⚠️ Demo sign-in lets anyone using **this computer** sign in as anyone. It's fine on your
own PC, but never use it on a shared server. The production setup refuses to start with it.

**No NVIDIA card?** While Notepad is open, also change `LLM_MODEL=qwen2.5:7b` to
`LLM_MODEL=llama3.2:3b`.

---

## Step 6: start the system

```powershell
docker compose up -d --build --wait
```

**What happens:** Docker downloads and builds four pieces: the database (PostgreSQL), the
search engine (Qdrant), the assistant itself (API + website) and their connections. The
**first time takes 5–10 minutes.**

**You should see** at the end:

```
 ✔ Container enterprise-rag-rbac-postgres-1  Healthy
 ✔ Container enterprise-rag-rbac-qdrant-1    Healthy
 ✔ Container enterprise-rag-rbac-api-1       Healthy
```

"Healthy" means each piece started **and** passed its self-check.

---

## Step 7: start the AI model

**With an NVIDIA card:**

```powershell
docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile llm up -d ollama
```

```powershell
docker compose exec ollama ollama pull qwen2.5:7b
```

**Without an NVIDIA card:**

```powershell
docker compose --profile llm up -d ollama
```

```powershell
docker compose exec ollama ollama pull llama3.2:3b
```

**What happens:** the AI model is downloaded once: about **4.7 GB** for qwen2.5:7b, or
**2 GB** for llama3.2:3b. You'll see a progress bar, then `success`.

**Which model?**

| | qwen2.5:7b | llama3.2:3b |
|---|---|---|
| Needs | NVIDIA card, 8 GB | any computer |
| Answer time | about 1–6 seconds | 10–60 seconds on a processor |
| Quality | reads tables and numbers reliably (95% correct in our tests) | weaker with numbers |

---

## Step 8: load the documents and create the users

One command does everything:

```powershell
docker compose exec api python -m scripts.bootstrap
```

**What happens, in 5 stages:**

```
=== 1/5 Documents       → checks the 18 company documents are there
=== 2/5 Login accounts  → creates the 9 example people
=== 3/5 Ingest          → reads, cleans and cuts the documents into 71 pieces
=== 4/5 Index           → fingerprints the pieces (first time: downloads ~150 MB)
=== 5/5 Local LLM       → checks the AI model is ready
Ready. Open http://localhost:8000/app/
```

In stage 3 you'll see `office-wifi-guide: removed 1 hidden item(s)`. **That's expected**:
it's the hidden trap in the Wi-Fi guide being removed (see
[How it works, step 3](02-how-it-works.md#step-3-removing-hidden-text-a-hidden-attack-example)).

**The passwords** for the 9 people are saved in `data\org\dev_credentials.yaml`. Open it
with `notepad data\org\dev_credentials.yaml`.

---

## Step 9: check that everything works

```powershell
docker compose exec api python -m scripts.smoke_test
```

**You should see 12 lines saying `PASS`**, ending with **`ALL CHECKS PASSED`**. They check,
for example, that the intern **can't** find the CEO's salary and the CEO **can**.

---

## Step 10: open the assistant 🎉

Open your web browser and go to: **http://localhost:8000/app/**

- With demo sign-in on: click any person, for example **Aarav Mehta**.
- Otherwise: type the email and password from `dev_credentials.yaml`.

Continue with the [User guide](04-user-guide.md).

**Not working?** Run the smoke test from Step 9 again: a failing line tells you which part
to look at.

---

## Everyday use

| I want to… | Command (inside the project folder) |
|---|---|
| Stop everything (frees memory) | `docker compose --profile llm stop` |
| Start again later (GPU) | `docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile llm up -d --wait` |
| Start again later (no GPU) | `docker compose --profile llm up -d --wait` |
| Get the latest version | `git pull`, then `docker compose up -d --build --wait` |
| See what's running | `docker compose ps` |
| See error messages | `docker compose logs api --tail 50` |

Your users, documents and settings are **kept** when you stop and start. You don't need
to repeat Steps 7–8 after a restart.

## Removing everything

```powershell
docker compose --profile llm down -v
```

This deletes the containers **and their stored data** (database, search index, downloaded
AI model). Your project folder stays; delete it like any normal folder.

---

## Common problems

| What you see | What it means | Fix |
|---|---|---|
| `docker: command not found` / `not recognized` | Docker isn't installed or not started | Do Step 1; open Docker Desktop and wait for "Engine running" |
| `error during connect` / `cannot find the file specified … dockerDesktopLinuxEngine` | Docker Desktop is closed | Open Docker Desktop, wait for the green status, try again |
| `port is already allocated` (8000, 5432 or 6333) | Another program uses that port | Close the other program, or restart your computer |
| The chat shows *"The answer service is temporarily unavailable."* | The AI model isn't running or isn't downloaded | Repeat Step 7 |
| The first answer takes 30+ seconds | The AI model is loading into memory | Normal once after each start; later answers are fast |
| Answers are very slow (minutes) | No GPU in use | Use llama3.2:3b (Steps 5 and 7), or check you used the GPU command |
| `Bootstrap stopped: … failed` | One stage failed | Read the lines just above it; run `docker compose logs api --tail 50` |

More answers: [FAQ and troubleshooting](08-faq-troubleshooting.md).

---

**Previous:** [← 2. How it works](02-how-it-works.md) · **Next:** [4. User guide →](04-user-guide.md)
