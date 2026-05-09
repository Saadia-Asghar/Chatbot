# DonorBridge Chatbot — Team Guide

A short guide for group members. Covers **what the bot can / cannot
answer**, **how it works**, and **how to clone and run it locally**.

Repo: <https://github.com/Saadia-Asghar/Chatbot>

---

## 1. Clone and run it locally (4 commands)

Requires **Python 3.9+** and **git**.

```bash
git clone https://github.com/Saadia-Asghar/Chatbot.git
cd Chatbot
pip install -r requirements.txt
python init_db.py        # builds donorbridge.db from schema.sql
python api.py            # starts http://127.0.0.1:5000/
```

Then open <http://127.0.0.1:5000/> in any browser. Pick a hospital from
the sidebar dropdown and click any **suggestion chip** to send a sample
question. Done.

### Two more ways to run it

| Command                       | UI                              |
|-------------------------------|---------------------------------|
| `python api.py`               | Web app (Flask + HTML/CSS/JS)   |
| `streamlit run app.py`        | Streamlit UI (alternative)      |
| `python chatbot_backend.py`   | Plain terminal chat             |

### One-shot smoke test (no UI)

```bash
python smoke_test.py
```

Runs **20 example questions** end-to-end and shows each reply, plus the
counts of rows written into the audit tables (`CHAT_MESSAGE`,
`INTENT_DETECTION`, `QUERY_EXECUTION_LOG`). Use this to convince
yourself the bot works before opening the browser.

### Optional — Windows PowerShell virtualenv

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
python init_db.py
python api.py
```

If port 5000 is busy, edit the last line of `api.py` (`port=5000`).

---

## 2. What the chatbot CAN answer (12 intents)

The bot is **rule-based** — it matches keywords in your sentence to one
of these 12 intents and runs a predefined `SELECT` against the
DonorBridge schema.

| #  | What you can ask                                                    | Sample reply                                                                |
|----|---------------------------------------------------------------------|------------------------------------------------------------------------------|
| 1  | Blood inventory by type — *"What is the inventory for O- blood?"*   | "Only 2 units of O- at City General Hospital. URGENT: Stock is critically low." |
| 2  | Blood inventory by family — *"Is there any O blood?"*               | Lists O+ and O- with critical/low/sufficient tags.                          |
| 3  | Whole-hospital stock — *"Any low stock?"*, *"Show inventory"*       | Lists every blood group at the hospital with tags.                          |
| 4  | High-risk patients — *"Who are the high-risk patients?"*            | Patients with `risk_score > 7`, tagged High Priority / Critical / Urgent.   |
| 5  | All patients — *"List all patients."*                               | Roster sorted by risk.                                                      |
| 6  | Transplant priority — *"Who should get the next kidney transplant?"*| Patients ordered by urgency + max wait, with the recommended next recipient.|
| 7  | Transplant history — *"Show me the transplant history."*            | Past transplants with surgeon and outcome.                                  |
| 8  | Match candidates — *"Show me the match candidates."*                | Proposed/accepted matches with compatibility score and priority.            |
| 9  | Pending requests — *"List the pending requests."*                   | Open requests sorted by urgency.                                            |
| 10 | Eligible donors — *"Show me the eligible donors."*                  | Donors that are both Eligible AND Available.                                |
| 11 | Recent donations — *"Show me recent blood donations."*              | Latest entries from BLOOD_DONATION.                                         |
| 12 | Blood units expiring soon — *"Which blood units are expiring soon?"*| Available units sorted by nearest expiry date.                              |
| ★  | Hospital risk explanation — *"Why is Hospital 1 at risk?"*          | Multi-step diagnostic comparing pending demand vs current inventory.        |
| ★  | List hospitals — *"List all hospitals."*                            | Hospital roster.                                                            |

### Tags the bot adds automatically

- **Inventory:** `< 5 units` → critical, `5–9` → low, `≥ 10` → sufficient
- **Risk score:** `> 8` → High Priority
- **Hemoglobin:** `< 7` → Critical, `7–10` → Urgent, `> 10` → Moderate

---

## 3. What the chatbot CANNOT answer / will NOT do

If your question doesn't match any of the 12 intents, you get this
fixed fallback (no hallucinated answer):

> I'm sorry, I can only answer questions about blood inventory, donors,
> donations, patients at risk, transplant priority, pending requests,
> match candidates, blood units expiring soon, transplant history,
> hospitals or the patient list. You can also ask
> 'Why is Hospital &lt;id&gt; at risk?'.

Concretely, the bot **will not**:

- Answer free-form medical questions ("What does anemia feel like?").
- Chit-chat ("Tell me a joke", "How are you?").
- Insert / update / delete data — only `SELECT` queries are allowed
  (every query is hard-coded; nothing the user types is interpolated
  into SQL).
- Run any LLM. There's no OpenAI/HuggingFace call anywhere; the
  classifier is regex on keywords.
- Cross hospitals in one answer (each query is scoped to the hospital
  selected in the sidebar). Use the dropdown to switch.
- Search the internet.
- Predict the future or do machine-learning forecasts (the "intelligent"
  tags are deterministic threshold rules, not ML).

---

## 4. How it works (one-page architecture)

```
   Browser (static/index.html + app.js)
            │  POST /api/chat  { hospital_id, session_id, message }
            ▼
   Flask  api.py
            │
            ▼
   chatbot_backend.process_user_query()
        ├─ detect_intent(text)              ← regex keyword match
        ├─ extract_blood_type / family / hospital_id
        ├─ INTENT_TO_SQL[intent]            ← parameterized SELECT
        ├─ run_intent_query()               ← cursor.execute(sql, params)
        └─ format_response(intent, rows)    ← rule-based sentence
                                              + critical/low/urgent tags
            │
            ▼
   SQLite (donorbridge.db)
        ├─ Operational tables (HOSPITAL, PATIENT, MEDICAL_RECORD,
        │   DONOR, REQUEST, BLOOD_REQUEST_DETAILS,
        │   ORGAN_REQUEST_DETAILS, BLOOD_DONATION, BLOOD_UNIT,
        │   BLOOD_INVENTORY, ORGAN_OFFER, MATCH_CANDIDATE, TRANSPLANT)
        │       — read-only for the bot
        └─ Chatbot subsystem  (CHAT_SESSION, CHAT_MESSAGE,
            INTENT_DETECTION, SQL_TEMPLATE, QUERY_EXECUTION_LOG)
                — bot writes one row per turn for full audit trail
```

### Three clean layers in `chatbot_backend.py`

1. **Intent classification** — `INTENT_PATTERNS` dict of regex lists.
2. **Query map** — `INTENT_TO_SQL` dict of parameterized SELECTs (these
   are also seeded into the `SQL_TEMPLATE` table so audit logs reference
   them).
3. **Formatter** — `FORMATTERS` dict mapping intent → function that
   turns rows into a sentence and applies the tag rules.

Adding a new intent is exactly 3 dict entries — no router changes
needed.

### Safety guarantees baked in

- **No SQL injection** — every parameter goes through `?` placeholders.
- **`SELECT` only** — `_assert_select_only()` aborts anything else.
- **Bounded output** — every listing query has `LIMIT 10`.
- **No hallucinations** — unmatched input → fixed fallback string;
  empty result set → fixed "no data" string.
- **Audit trail** — every turn writes one row each into `CHAT_MESSAGE`
  (×2: User + Bot), `INTENT_DETECTION`, and `QUERY_EXECUTION_LOG`.

---

## 5. Where things live in the repo

| Path                       | Purpose                                              |
|----------------------------|------------------------------------------------------|
| `schema.sql`               | DonorBridge ERD CREATE TABLE + seed data             |
| `init_db.py`               | Builds `donorbridge.db` from `schema.sql`            |
| `chatbot_backend.py`       | Intent classifier, SQL templates, formatter, logging |
| `api.py`                   | Flask REST API + serves the static frontend          |
| `static/index.html`        | Web UI markup                                        |
| `static/styles.css`        | Web UI styling (dark theme)                          |
| `static/app.js`            | Web UI behavior + fetch() calls                      |
| `app.py`                   | Streamlit UI (alternative)                           |
| `smoke_test.py`            | End-to-end test — runs 20 example questions          |
| `requirements.txt`         | Python deps (`flask`, `streamlit`)                   |
| `README.md`                | Project documentation (technical)                    |
| `CHATBOT_CAPABILITIES.md`  | Long-form list of every example question that works  |
| `TEAM_GUIDE.md`            | This file — quick guide for group members            |

---

## 6. Demo script (5 minutes for a presentation)

After running `python api.py`, walk through these in the browser:

1. *"List all hospitals."* — proves the bot is talking to the DB.
2. *"Show patients."* — `LIST_PATIENTS`.
3. *"Who are the high-risk patients?"* — shows the auto-tagging.
4. *"Is there O blood group?"* — bareword family lookup (fuzzy).
5. *"Show me the eligible donors."* — donor table + business rule.
6. *"Show me recent blood donations."* — donation history.
7. *"List the pending requests."* — open requests at this hospital.
8. *"Show me the match candidates."* — match table.
9. *"Who should get the next kidney transplant?"* — multi-table join.
10. *"Which blood units are expiring soon?"* — temporal query.
11. *"Show me the transplant history."* — completed transplants.
12. *"Why is Hospital 1 at risk?"* — multi-step "explain" diagnostic.
13. *"Tell me a joke."* — proves the bot will not hallucinate.

Then optionally open `donorbridge.db` in **DB Browser for SQLite** and
show that `CHAT_MESSAGE`, `INTENT_DETECTION`, and `QUERY_EXECUTION_LOG`
have new rows for every question you just asked — that's the audit
trail the ERD requires.

---

## 7. Common issues

| Symptom                                              | Fix                                                    |
|------------------------------------------------------|--------------------------------------------------------|
| `Database file 'donorbridge.db' not found`           | Run `python init_db.py` first.                         |
| `ModuleNotFoundError: No module named 'flask'`       | Run `pip install -r requirements.txt`.                 |
| Port 5000 already in use                             | Edit the last line of `api.py` (change `port=5000`).   |
| Browser shows "API offline"                          | Make sure `python api.py` is still running.            |
| Bot returns the fallback for every question          | Re-run `python init_db.py` — the seed data is missing. |
| Got an old / wrong reply after editing `schema.sql`  | Re-run `python init_db.py` to rebuild the DB.          |
