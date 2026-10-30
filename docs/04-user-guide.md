# 4. User guide

*For everyone who uses the assistant. Part 2 is for administrators.*

The assistant is a website called **Orbitra Assist**. Open it at
**http://localhost:8000/app/**. If it doesn't open, see the [Installation guide](03-installation.md).

---

# Part 1: for everyone

## Signing in

**Normal sign-in:** type your **Email** and password, then click **Sign in**.

**Demo sign-in** (only when the administrator turned on demo mode): under
**"Demo: sign in as…"** you'll see the 9 example people. Click one to become that person
instantly. This is for trying the system out; it never appears on a real company setup.

**Your session lasts 60 minutes.** After that you'll see *"Your session ended - please sign
in again."* That's a safety feature, not an error.

## The screen

```
┌────────────────────────────────────────────────────────────┐
│ Orbitra Assist  [Ask] [Admin*]   Aarav Mehta  [Sign out]   │ ← top bar
├────────────────────────────────────────────────────────────┤
│ Hi Aarav - what would you like to know?                    │
│ Suggestions: [How many days of PTO…] [What is the CEO's…]  │
│                                                            │
│ (your conversation appears here)                           │
│                                                            │
├────────────────────────────────────────────────────────────┤
│ [ Ask about company documents…                 ] [Ask]     │ ← question box
└────────────────────────────────────────────────────────────┘
  * the Admin tab appears only for administrators
```

- **Top bar:** your name and job, a **Sign out** button and, in demo mode, a **Switch demo
  user** list to change person.
- **Suggestions:** click one to ask it. They're good first examples.
- **Question box:** type and press **Enter** to send. **Shift+Enter** starts a new line.

## The three kinds of reply

### 1. An answer with sources ✅

> The CEO's base salary is $310,000 **[S1]**.
>
> **Sources (1)** ▸ S1 · Executive Compensation 2026 · page 1 · **Show source**

- **[S1]** is a citation. **Click it** and the matching source below lights up.
- **Show source** opens the exact passage the answer came from, so you can check it
  yourself.
- Every number in an answer comes from a source. The system was tested for made-up
  numbers and none were found.

### 2. "I couldn't find that in the documents you have access to." 🔍

This means **one of two things**, deliberately indistinguishable:
- the information isn't in any document, **or**
- it exists, but you aren't allowed to see it.

The assistant **never** says which. That's on purpose: saying "this is restricted" would
tell you a secret document exists.

**What to do:** try rephrasing (see the tips below). If you believe you **should** have
access, ask your administrator; it's a question about your clearance, not about the
assistant.

### 3. "I can't help with that request. Please ask a question about company documents." 🛑

The question looked like an attempt to trick the AI, for example *"ignore all previous
instructions…"*. The question is refused, and the attempt is recorded in the security log.
Rephrase it as a plain question.

## Tips for good questions

| Instead of… | Ask… | Why |
|---|---|---|
| "PTO?" | "How many days of PTO do full-time employees get per year?" | A full question finds better matches |
| "Tell me everything about payroll" | "What was the total gross payroll in Q3 2026?" | One specific fact per question works best |
| "What did they decide?" | "What did the board decide about Project Atlas?" | The assistant doesn't remember earlier questions; each one stands alone |
| "Is Lena paid well?" | "What is Lena Okafor's base salary?" | Ask for facts, not opinions |

**Exact codes and names work well**, for example "What is the first-response target for a
SEV1 incident?" The system searches both meaning **and** exact words.

## Try it: the same question as different people

In demo mode, use **Switch demo user** to see access control in action:

| Question | Ask as… | Expected reply |
|---|---|---|
| How many days of PTO do full-time employees get per year? | anyone | 20 days [S1] |
| What is the CEO's base salary? | Aarav (intern) | couldn't find |
| | Helena (CEO) | $310,000 [S1] |
| What is Lena Okafor's base salary? | Marco (sales) | couldn't find; salary column is HR/Finance only |
| | Sofia (finance) | $102,000 [S1] |
| Who is Lena Okafor's manager? | Marco (sales) | Priya Raman [S1]; the same spreadsheet, a public column |
| Which company is Project Atlas about acquiring? | Samuel (admin) | couldn't find; admin ≠ reader |
| | Helena (CEO) | Lumen Analytics [S1] |
| Which database stores telemetry rollups? | Lena (engineer) | TimescaleDB [S1], from the architecture document |
| | Thomas (CFO) | couldn't find; engineering-only document, even for the CFO |

## Good to know

- **Your conversation isn't saved.** Reloading the page or signing out clears it, and
  nothing is stored in your browser.
- **Answers aren't stored either.** The security log records **that** you asked and which
  documents were used, never the answer text.
- **There's a limit of 30 questions per minute.** Going over shows *"Too many requests -
  please wait N seconds."*
- **The first answer after the system starts can take about 30 seconds** while the AI loads.

---

# Part 2: for administrators

People with the **admin** role (in the examples, **Samuel Osei**) see an extra **Admin**
tab with three sections: **Documents**, **Upload** and **Audit log**.

> **Important:** admin rights let you **manage** documents, not **read** them. Samuel's
> questions still only see what clearance 3 + Engineering allows. And you **can't give
> yourself access** to anything.

## Documents: who can read what

A table of every document:

| Column | Meaning |
|---|---|
| Document | Title and its ID (for example `payroll-2026-q3`) |
| Clearance | 1 Public · 2 Internal · 3 Confidential · 4 Restricted |
| Departments | Which departments may read it (`all` = every department) |
| Allowed | People named individually (they skip the department check, **not** the clearance check) |
| Denied | People blocked individually (this beats everything else) |
| Chunks | How many searchable pieces the document became |

### Changing who can read a document

1. Click **Edit access** on the document's row.
2. Change any of:
   - **Clearance**: 1 to 4.
   - **Departments**: tick one or more.
   - **Allowed users**: user IDs separated by commas, for example `u_eng_manager`.
   - **Denied users**: user IDs separated by commas.
3. Click **Save**. You'll see *"Access updated for …"*.

**The change applies to search immediately**, within seconds.

**Examples:**

| Goal | What to set |
|---|---|
| Make the Wi-Fi guide internal-only | Clearance **2** |
| Let Priya (Engineering) read the cloud-cost review | Allowed users: **u_eng_manager** |
| Keep Daniel out of an investigation he's part of | Denied users: **u_hr_partner** |
| Share budgets with HR as well | Departments: tick **hr** in addition |

**What gets refused, and why:**

| You try… | Result |
|---|---|
| Adding **yourself** to a document you can't read | ❌ *"administrators cannot grant themselves access"* (logged as a security event) |
| Saving with no department ticked | ❌ every document needs at least one department |

⚠️ **Check user IDs carefully.** The system doesn't check that an ID in *Allowed users* or
*Denied users* belongs to a real person, so a typo (`u_hr_partnr`) is saved silently and
blocks nobody. After saving, compare the **Allowed** and **Denied** columns with what you
meant. Also note that ticking **all** already means every department, so adding other
departments alongside it changes nothing.

### Removing a document

Click **Remove** and confirm. The document disappears from search immediately. **The
original file is kept** on disk, so you can add it back later.

## Upload: adding a new document

1. **File**: a PDF, Word (.docx) or Excel (.xlsx) file, up to **10 MB**.
2. **Document id**: a short name using lowercase letters, numbers and dashes, for example
   `hr-relocation-policy`.
3. **Title**: what people will see, for example "HR Relocation Policy 2027".
4. **Clearance** and **Departments**: who may read it.
5. Click **Upload**. You'll see *"Uploaded HR Relocation Policy 2027 (4 chunks)"*.

It's searchable **right away**, by the people you allowed. To name individual people
(allowed or denied), upload first, then use **Edit access**.

**Safety checks on every upload:**
- The file must really **be** what its name says: a `.pdf` that's actually something else
  is rejected.
- Hidden text inside it is removed (see [How it works](02-how-it-works.md)).
- If the file can't be read, nothing is added; everything is undone.

## Audit log: the security dashboard

### Top: the last 24 hours

| Card | What it counts | When to worry |
|---|---|---|
| Questions | Questions asked | — |
| **Injections refused** | Questions that tried to trick the AI | A sudden jump: someone is probing |
| **Failed logins** | Wrong passwords | Many for one account: password guessing |
| **Self-grants blocked** | Admins trying to give themselves access | Any at all: talk to that admin |
| **Rate limited** | People who sent too many requests | A script may be scraping |
| Answer time p95 (ms) | 95% of answers were faster than this | Rising: the AI computer is overloaded |

Cards that should be zero turn **red** when they aren't.

### The tamper check

Next to the title you'll see **"✓ Log intact - N events verified"**, checked every time the
page opens.

**How it works, simply:** every log entry contains a fingerprint of the entry before it,
like links in a chain. If anyone edits or deletes an old entry, even directly in the
database, the chain breaks, and the badge turns red: **"✗ Log altered at event #N"**,
naming the exact spot.

### Recent events

The last 50 events: time, type (query, search, login, admin, audit_view), outcome, user,
question and documents. Use the **event type** list to filter, and **Refresh** to update.

**You'll see `hidden` in some rows. That's intentional.** If a question touched documents
**you** aren't allowed to read, the question and document names are hidden from you.
**Example:** when Helena asks about the CEO's salary, Samuel sees her event as **hidden**.
Otherwise an admin could learn secrets just by reading other people's questions.

Viewing the audit log is itself logged (`audit_view`): the people who watch others are
also recorded.

## Adding real people (production)

On a real company setup, demo people are switched off and every person is added with one
command (run by whoever manages the server):

```powershell
docker compose exec api python -m scripts.create_user --user-id u_jdoe --email jane.doe@example.com --name "Jane Doe" --title "Financial Analyst" --role finance --clearance 3 --department finance
```

It prints a random password **once**; give it to the person privately. Running it again
for the same `--user-id` updates their clearance or departments (effective on their next
question) and gives them a new password. Details: [Deployment guide](DEPLOYMENT.md#4-user-accounts-in-production).

---

**Previous:** [← 3. Installation](03-installation.md) · **Next:** [5. Security explained →](05-security-explained.md)
