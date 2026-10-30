# 8. FAQ and troubleshooting

---

## General questions

**Is this a real company's data?**
No. Orbitra Systems, its people, salaries and plans are all invented for testing. The
tax IDs even start with `FAKE-TX-`.

**Does it send my documents to ChatGPT or any outside company?**
No. The AI model runs on your own computer through Ollama. Nothing leaves the machine.

**Does it cost anything?**
No. Every part is free and open source. The only exceptions are optional: a domain name
if you want a public web address, and Docker Desktop's paid licence for large companies.
See [Deployment](DEPLOYMENT.md).

**Can I use my own documents?**
Yes. Sign in as an administrator and use **Admin → Upload** (PDF, Word or Excel, up to 10
MB), choosing who may read each document. See the [User guide](04-user-guide.md#upload-adding-a-new-document).

**Does it remember my previous questions?**
No. Each question is answered on its own, and the conversation is cleared when you reload
the page. That's deliberate: it keeps the system simpler and safer.

**Can it answer from the internet or general knowledge?**
No, only from the documents you're allowed to read. If the answer isn't there, it says
"couldn't find". That's what prevents made-up answers.

**Why "couldn't find" instead of "access denied"?**
"Access denied" would confirm that something secret exists. See
[The big picture](01-big-picture.md#couldnt-find-means-exactly-that-and-nothing-more).

**Can the administrator read everything?**
No. Admin rights mean **managing** documents, not reading them. The admin also can't give
themselves access, and sees `hidden` in the log for things they can't read.

**What if someone changes jobs?**
Update their account (`create_user` with the same ID, new clearance or departments). It
takes effect on their **next** question, even if they're signed in.

**How accurate is it?**
In testing: 95% of known questions answered correctly, 100% with the right source, and no
invented numbers. Always click **[S1]** to check important facts yourself.

---

## Troubleshooting

### "The page doesn't open" (http://localhost:8000/app/)

1. Is Docker Desktop open and showing **Engine running**? If not, open it and wait.
2. In PowerShell, inside the project folder:
   ```powershell
   docker compose ps
   ```
   The `api` line should say **healthy**. If it's missing or unhealthy:
   ```powershell
   docker compose up -d --wait
   ```
3. Still failing? Look at the error messages:
   ```powershell
   docker compose logs api --tail 50
   ```

### "The answer service is temporarily unavailable."

The AI model isn't running. Start it (GPU version shown; see [Installation step 7](03-installation.md#step-7-start-the-ai-model)):

```powershell
docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile llm up -d ollama
```

Check the model is downloaded (it should list `qwen2.5:7b` or `llama3.2:3b`):

```powershell
docker compose exec ollama ollama list
```

### Every question says "couldn't find", even easy ones

- **Documents not loaded?** Run the bootstrap again; it's safe to repeat:
  ```powershell
  docker compose exec api python -m scripts.bootstrap
  ```
- **Signed in as the right person?** The intern can only see 4 public documents. Try the
  CEO (Helena Voss).
- **Check with the smoke test:** `docker compose exec api python -m scripts.smoke_test`.
  If "CEO finds the salary" fails, the documents aren't indexed.

### "I can't help with that request" for a normal question

The question contained words that look like an attack, for example "ignore the rules
about…" or "pretend you are…". Rephrase it as a plain question.

### "Too many requests - please wait N seconds"

More than 30 questions in a minute. Wait the stated seconds.

### "Your session ended - please sign in again."

Sessions last 60 minutes. Sign in again.

### Sign-in fails with the right password

- Passwords are in `data\org\dev_credentials.yaml` (demo setup). Copy them exactly.
- After 10 attempts in a minute, sign-in is paused briefly. Wait a minute.
- The demo person buttons only appear if `DEMO_LOGIN=true` is in `.env`. After changing
  it, restart the API: `docker compose up -d --force-recreate api`.

### Answers are very slow

| Symptom | Cause | Fix |
|---|---|---|
| Only the first answer is slow (~30 s) | The AI model loads into memory | Normal |
| Every answer takes minutes | Running on the processor without a GPU | Use `llama3.2:3b`, or start Ollama with the GPU file |
| Slow after the computer was idle | The model was unloaded from memory | Normal; it reloads on the next question |

### Docker says "port is already allocated"

Another program uses port 8000, 5432, 6333 or 11434. Close it, or restart the computer.

### Admin: "administrators cannot grant themselves access"

Working as intended. Ask another administrator to make the change.

### Admin: the audit log shows "✗ Log altered at event #N"

Someone or something changed the audit records directly in the database. Treat it as a
security incident: don't modify anything, note the event number, and check who has
access to the server.

### Something else

1. Run the smoke test. It names the failing part.
2. Read `docker compose logs api --tail 100`. Look for lines with `ERROR`, `SECURITY` or
   `CRITICAL`.
3. Every response carries an `X-Request-ID`. The same ID appears in the logs and the audit
   log, which helps trace one specific request.

---

**Previous:** [← 7. How it was built](07-how-it-was-built.md) · **Next:** [9. Glossary →](09-glossary.md)
