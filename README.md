# Healthcare Resource Optimization Chatbot

A rule-based SQL-interface chatbot for a DBMS course project. No LLM — input
is matched to an intent via regex, each intent runs a parameterized `SELECT`,
and the result is wrapped in a clean sentence. Includes an "Explain Why"
feature that justifies risk alerts with multi-step SQL.

## Design guarantees

- **No hallucinations** — unmatched input returns a fixed fallback; empty
  result sets return `"I don't know..."`.
- **Schema-aware** — only uses tables/columns defined in `schema.sql`.
- **Read-only** — the DB is opened with `mode=ro`; only predefined `SELECT`
  statements are executed.
- **SQL-injection safe** — every parameter is passed via `?` placeholders.
- **Bounded output** — every listing query uses `LIMIT 10`.
- **Modular** — add an intent in 3 steps (regex pattern, SQL in
  `INTENT_TO_SQL`, formatter in `FORMATTERS`).

## Project layout

| File                 | Purpose                                                  |
|----------------------|----------------------------------------------------------|
| `schema.sql`         | 3NF `CREATE TABLE` scripts + test data                   |
| `init_db.py`         | Builds `healthcare.db` from `schema.sql`                 |
| `chatbot_backend.py` | Intent classifier, query map, formatter, explain_alert   |
| `app.py`             | Streamlit chat UI                                        |
| `requirements.txt`   | Python dependencies                                      |

## Schema (3NF)

| Table             | Columns                                                                                 |
|-------------------|-----------------------------------------------------------------------------------------|
| `HospitalsTable`  | `HospitalID (PK)`, `Name`, `Location`, `AverageWeeklyUsage`                             |
| `InventoryTable`  | `InventoryID (PK)`, `HospitalID (FK)`, `BloodType`, `CurrentUnits`, `LastUpdated`       |
| `PatientsTable`   | `PatientID (PK)`, `HospitalID (FK)`, `Name`, `Condition`, `HemoglobinLevel`, `SurgeryScheduled`, `RiskScore` |
| `DonorsTable`     | `DonorID (PK)`, `Name`, `BloodType`, `EligibilityStatus`, `Location`                    |
| `OrganRequests`   | `RequestID (PK)`, `PatientID (FK)`, `OrganType`, `UrgencyScore`, `WaitTime`             |

## Intent map

| Keywords / question type                                   | Intent ID                 | SQL target                                                        |
|------------------------------------------------------------|---------------------------|-------------------------------------------------------------------|
| `why`, `explain`, "why is hospital X at risk"              | `EXPLAIN_ALERT`           | multi-step: `HospitalsTable` + `InventoryTable` (weeks of supply) |
| `low`, `shortage`, `stock`, `inventory`, "how much blood"  | `CHECK_INVENTORY`         | `InventoryTable` filtered by hospital (and optional blood type)   |
| `priority`, `risk`, `surgery`, `urgent patients`           | `GET_HIGH_RISK_PATIENTS`  | `PatientsTable` where `RiskScore > 7`                             |
| `transplant`, `waiting list`, `matching`, `next kidney`    | `GET_TRANSPLANT_PRIORITY` | `OrganRequests JOIN PatientsTable` by urgency + wait              |
| `donor`, `eligible`                                        | `GET_DONORS`              | `DonorsTable` where `EligibilityStatus = 'Eligible'`              |

Unmatched input returns:

> "I'm sorry, I can only provide information about blood inventory, patient
> risk, transplant priority, or donor eligibility. You can also ask
> 'Why is Hospital <id> at risk?'."

## Setup

```bash
python -m venv venv
# Windows PowerShell
venv\Scripts\Activate.ps1
# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
python init_db.py
```

## Run

Terminal chat:

```bash
python chatbot_backend.py
```

Browser chat UI:

```bash
streamlit run app.py
```

## "Intelligent" formatting rules

| Intent                   | Rule                                                                                                                                                |
|--------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------|
| `CHECK_INVENTORY`        | `units < 5` → append `URGENT: Stock is critically low.` `5 ≤ units < 10` → tagged `low` (plan a shipment). `units ≥ 10` → `sufficient`.             |
| `GET_HIGH_RISK_PATIENTS` | `RiskScore > 8` → tag `High Priority`. Hemoglobin triage: `< 7` → `Critical`; `7–10` → `Urgent`; `> 10` → `Moderate`. Both tags are shown together. |
| `EXPLAIN_ALERT` / Why    | `Hospital [Name] is at risk because current stock ([Stock]) is less than the average weekly usage ([Usage]).`                                       |
| Any intent, empty result | `I could not find any relevant data for that request.`                                                                                              |

## Test cases (seeded data)

1. **"What is the inventory for O- blood?"** (Hospital 1, 2 units)
   → `Only 2 units of O- at City General. URGENT: Stock is critically low. Please prioritize a new shipment.`
2. **"What is the inventory for O+ blood?"** (Hospital 1, 8 units)
   → `Inventory for O+ is running low (8 units at City General). Please plan a shipment soon.`
3. **"What is the inventory for B- blood?"** (Hospital 1, not stocked)
   → `I could not find any relevant data for that request.`
4. **"Who are the high-risk patients?"** (Hospital 2)
   → `Priya Nair [High Priority, Critical] - condition: Thalassemia, Hb 6.8 g/dL, risk 10/10, surgery scheduled.`
5. **"Who are the high-risk patients with surgery scheduled?"** (Hospital 1)
   → Asha Patel `[High Priority, Urgent]`, Meera Iyer `[High Priority, Urgent]`, Sanjay Gupta `[Urgent]` (risk 8 → not High Priority).
6. **"Who should get the next kidney transplant?"**
   → Meera Iyer (urgency 9, waiting 120 days) as top recipient.
7. **"Show me eligible donors."**
   → Ravi Menon (O-), Kiran Das (O+), Vikas Singh (B+).
8. **"Why is Hospital 1 at risk?"**
   → `Hospital City General is at risk because current stock (34 units) is less than the average weekly usage (40 units). That is approximately 0.85 weeks of supply. Critically low blood types: …`.
9. **"Why is Hospital 2 at risk?"**
   → `Hospital Green Valley Medical is within safe range: … about 2.20 weeks …`.
10. **"Tell me a joke."**
    → Fallback message.

## Coursework talking points

- **Decoupling** — the chatbot is decoupled from the database: intent
  classification (`INTENT_PATTERNS`) and SQL (`INTENT_TO_SQL`) are separate
  maps, so adding an intent never requires touching the router.
- **Rule-based prediction** — threshold-based SQL queries (`RiskScore > 7`,
  `CurrentUnits < 10`, `CurrentStock < AverageWeeklyUsage`) simulate
  predictive analytics without ML overhead while remaining auditable.
- **Safety** — every query is a hard-coded `SELECT` with `?` parameters; the
  SQLite connection is opened with `mode=ro`, so the chat interface cannot
  insert, update, or delete data even if a prompt tries to.

## Adding a new intent (modularity)

1. Add a regex list to `INTENT_PATTERNS` under a new Intent ID.
2. Add the SQL (parameterized, `SELECT`-only, `LIMIT 10`) to `INTENT_TO_SQL`.
3. Register a formatter in `FORMATTERS` that turns rows into a sentence.
4. If the intent needs extra params, add a branch in `run_intent_query`.
