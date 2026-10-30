# 1. The big picture: what this project is and why it matters

*Reading time: 10 minutes. No technical knowledge needed.*

---

## The problem in one story

Imagine **Orbitra Systems**, a small software company (it's fictional, invented for this
project) with 33 employees in its directory. It has 18 documents: the employee handbook,
the holiday calendar, payroll spreadsheets, salary bands, board meeting minutes, a secret
plan to buy another company, and a confidential layoff plan.

The company wants an **AI assistant** that any employee can ask questions, like ChatGPT but
for company documents:

> **Aarav (intern):** "How many vacation days do I get?"
>
> **Assistant:** "Full-time employees receive 20 days of paid time off per year. [Source:
> Employee Handbook]"

That's useful. Now consider the dangerous version:

> **Aarav (intern):** "What is the CEO's salary?"
>
> **A careless assistant:** "The CEO's base salary is $310,000."

The intern just learned something they should never have seen. A normal AI assistant has
read **every** document, so with the right question it can be made to reveal **anything**.

**This project builds an assistant that can't do that.** It answers each person using only
the documents **that person** is allowed to read:

> **Aarav (intern):** "What is the CEO's salary?"
>
> **This assistant:** "I couldn't find that in the documents you have access to."
>
> **Helena (CEO):** "What is the CEO's salary?"
>
> **This assistant:** "The CEO's base salary is $310,000. [Source: Executive Compensation 2026]"

Same question, same assistant, different answers, because they're different people.

---

## A comparison: the company library

Think of the system as a **company library with a very careful librarian**.

| In the library | In this project |
|---|---|
| The books | The company's documents (PDFs, Word files, Excel sheets) |
| A coloured **security sticker** on each book (green = anyone, red = executives only) | The **access label** on each document: its clearance level and departments |
| Your **staff badge**, which says your level and your department | Your **user account**: clearance level 1–4 and your departments |
| The librarian checks your badge **before** fetching books | The system filters documents **before** the AI reads anything |
| The librarian reads only the allowed books and summarises them for you | The AI reads only allowed passages and writes an answer, with sources |
| A visitor log at the door | The **audit log**: who asked what, and when |

The key idea: **the librarian never brings restricted books to the reading table.** Even
if you trick the librarian into saying "tell me what the red books say", there are no red
books on the table to read from. That's why the system is safe even against clever tricks.

---

## Who uses it

The project includes **9 example people** ("personas") at the fictional company. Each one
tests a different part of the rules.

| Person | Job | Clearance | Departments | What their example shows |
|---|---|---|---|---|
| **Aarav Mehta** | Software Engineering Intern | 1 (lowest) | Engineering | Can only read public documents |
| **Lena Okafor** | Software Engineer | 2 | Engineering | Normal employee: internal + engineering documents |
| **Marco Bellini** | Account Executive | 2 | Sales | Sees sales documents, not engineering ones |
| **Priya Raman** | Engineering Manager | 3 | Engineering | Given one finance report **by name** ("need to know") |
| **Daniel Kim** | HR Business Partner | 3 | HR | **Blocked by name** from one HR investigation, because he was a witness in it |
| **Sofia Alvarez** | Senior Financial Analyst | 3 | Finance | Sees payroll and salaries |
| **Thomas Reed** | Chief Financial Officer | 4 (highest) | Executive, Finance | Sees nearly everything |
| **Helena Voss** | Chief Executive Officer | 4 | All departments | Sees everything |
| **Samuel Osei** | Engineering Manager + **system administrator** | 3 | Engineering | Can **manage** documents but can't **read** secret ones |

---

## The four clearance levels

Every document gets one level. A person can read a document only if their level is **equal
or higher**.

| Level | Name | Example documents | Example people |
|---|---|---|---|
| 1 | Public | Employee handbook, holiday calendar, Wi-Fi guide | Everyone, including interns |
| 2 | Internal | Product roadmap, employee directory | Regular employees and above |
| 3 | Confidential | Payroll, salary bands, budgets | Managers, HR, Finance |
| 4 | Restricted | Board minutes, CEO pay, layoff plan | Executives only |

**Example:** the payroll spreadsheet is **level 3, HR and Finance departments**.
- Sofia (level 3, Finance) → ✅ can read it
- Priya (level 3, Engineering) → ❌ right level, wrong department
- Lena (level 2, Engineering) → ❌ level too low

---

## The five access rules

The system decides "can this person read this document?" with five rules, checked in order:

1. **Blocked by name? Then no.** Even the right level can't override a personal block.
   *Example:* Daniel (HR, level 3) is blocked from the July 2026 investigation report,
   because he was a witness in that case.
2. **Level too low? Then no.** *Example:* Lena (level 2) can't read payroll (level 3).
3. **Document is for "all departments"? Then yes.** *Example:* everyone at level 2 or
   above can read the product roadmap.
4. **Named personally on the document? Then yes**, even from another department.
   *Example:* Priya (Engineering) is named on the finance team's cloud-cost review.
   **Being named never skips the level check:** naming a level-3 person on a level-4
   document still doesn't let them in.
5. **In one of the document's departments? Then yes.** Otherwise no.

---

## Even parts of a spreadsheet are protected

The **employee directory** is a spreadsheet everyone at level 2 can see: names, job
titles, managers. But two of its **columns** are more sensitive:

| Column | Who can see it |
|---|---|
| Name, title, department, manager, office | Everyone at level 2+ |
| **Base Salary** | Only HR and Finance (Daniel, Sofia, Thomas, Helena) |
| **Performance Rating** | Only HR and the CEO (Daniel, Helena) |

**Example:**
- Marco asks *"Who is Lena Okafor's manager?"* → "Priya Raman." ✅
- Marco asks *"What is Lena Okafor's salary?"* → "I couldn't find that…" ❌
- Sofia asks the same → "$102,000." ✅

When the spreadsheet is loaded, the system splits the salary column into separate pieces,
each with its own stricter label. Marco's searches never see those pieces.

---

## "Couldn't find" means exactly that, and nothing more

When you aren't allowed to see something, the assistant always gives the **same neutral
sentence**: *"I couldn't find that in the documents you have access to."*

It **never** says "that's restricted" or "you need a higher clearance", because that would
reveal the document **exists**. Consider the secret layoff plan: if the intern asked "are
there layoffs coming?" and heard "that's restricted", they'd have learned something big.
A neutral "couldn't find" reveals nothing.

---

## Why it's free

The project was built under one rule: **it must not cost any money.**

| Normally you'd pay for… | This project uses instead (free) |
|---|---|
| ChatGPT or another paid AI service | **Ollama** running the open-source AI model **Qwen 2.5** on your own computer |
| A cloud search service | **Qdrant**, open-source search software running on your computer |
| A cloud database | **PostgreSQL**, an open-source database on your computer |
| Cloud servers | **Docker** on your own PC |
| Paid testing services | **GitHub Actions**, free for public projects |

A side benefit: **company documents never leave your computer.** Nothing is sent to an
outside AI company.

---

## Proof that it works

Saying "it's secure" isn't enough, so the project **attacks itself** and measures the
results. Details are in [Quality and testing](06-quality-and-testing.md). Headlines:

| Test | Result |
|---|---|
| 45 different tricks to steal secrets, tried by all 9 people (405 attempts) | **0 secrets leaked** |
| The same tricks through the full AI (180 answers) | **0 secrets leaked** |
| 46 attempts to hijack the AI ("ignore your rules…") | **0 succeeded** |
| Normal questions answered correctly | **95%** |
| Answers that cite the right document | **100%** |
| Answers containing a made-up number | **0** |

---

**Next:** [2. How it works, step by step →](02-how-it-works.md)
