# DonorBridge — Healthcare Resource Chatbot

A rule-based SQL chatbot for the **DonorBridge** healthcare resource
optimization system. The schema follows the DonorBridge ERD
([reference](https://github.com/shajiaalianwar55/DonorBridge)).
No LLM is used: input is matched to an intent via regex, each intent runs
a parameterized `SELECT` against a 3NF SQLite schema, and the result is
wrapped in a clean sentence. Every chat turn is logged into the
`CHAT_SESSION / CHAT_MESSAGE / INTENT_DETECTION / QUERY_EXECUTION_LOG`
tables that the ERD itself defines.

## Quick start

```bash
python -m venv venv
# Windows PowerShell
venv\Scripts\Activate.ps1
# macOS / Linux
# source venv/bin/activate

pip install -r requirements.txt
python init_db.py            # builds donorbridge.db from schema.sql
python api.py                # http://127.0.0.1:5000/
```

Then open <http://127.0.0.1:5000/> in your browser.

### Alternative UIs

```bash
# Terminal chat
python chatbot_backend.py

# Streamlit chat
streamlit run app.py
```

## Project layout

| File / folder         | Purpose                                                    |
|-----------------------|------------------------------------------------------------|
| `schema.sql`          | DonorBridge-ERD `CREATE TABLE` scripts + seed data         |
| `init_db.py`          | Builds `donorbridge.db` from `schema.sql`                  |
| `chatbot_backend.py`  | Intent classifier, SQL templates, formatter, chat logging  |
| `api.py`              | Flask REST API + serves the static frontend                |
| `static/`             | Modern HTML/CSS/JS chat UI                                 |
| `app.py`              | Streamlit chat UI (alternative)                            |
| `requirements.txt`    | Python dependencies                                        |

## Schema (matches the DonorBridge ERD)

Core entities

| Table             | Key columns                                                                                                                                       |
|-------------------|----------------------------------------------------------------------------------------------------------------------------------------------------|
| `HOSPITAL`        | `hospital_id`, `name`, `location`, `contact`                                                                                                       |
| `PATIENT`         | `patient_id`, `hospital_id`, `full_name`, `age`, `gender`, `blood_group`, `risk_score`, `created_at`                                              |
| `MEDICAL_RECORD`  | `record_id`, `patient_id`, `diagnosis`, `severity_level`, `stage`, `hemoglobin_level`                                                              |
| `DONOR`           | `donor_id`, `hospital_id`, `full_name`, `age`, `blood_group`, `donor_type`, `availability_status`, `eligibility_status`, `last_donation_date`     |
| `REQUEST`         | `request_id`, `patient_id`, `hospital_id`, `request_type`, `urgency_level`, `status`, `request_date`                                              |
| `BLOOD_REQUEST_DETAILS`  | `request_id (PK,FK)`, `blood_group_required`, `units_required`, `required_by`                                                              |
| `ORGAN_REQUEST_DETAILS`  | `request_id (PK,FK)`, `organ_type_required`, `max_wait_time_days`, `hla_notes`                                                             |
| `BLOOD_DONATION`  | `blood_donation_id`, `donor_id`, `donation_date`, `quantity_donated_ml`, `outcome`                                                                 |
| `BLOOD_UNIT`      | `blood_unit_id`, `blood_donation_id`, `blood_group`, `volume_ml`, `expiry_date`, `unit_status`                                                     |
| `BLOOD_INVENTORY` | `inventory_id`, `hospital_id`, `blood_group`, `available_units_summary`, `last_updated`                                                            |
| `ORGAN_OFFER`     | `organ_offer_id`, `donor_id`, `organ_type`, `availability_status`, `retrieval_date`, `medical_clearance`                                          |
| `MATCH_CANDIDATE` | `match_id`, `request_id`, `match_type`, `blood_unit_id (nullable)`, `organ_offer_id (nullable)`, `compatibility_score`, `priority_level`, `match_status` |
| `TRANSPLANT`      | `transplant_id`, `match_id`, `transplant_date`, `surgeon_name`, `outcome`                                                                          |

Chatbot subsystem (the chatbot writes to these)

| Table                  | Key columns                                                                            |
|------------------------|----------------------------------------------------------------------------------------|
| `CHAT_SESSION`         | `chat_session_id`, `hospital_id`, `user_role`, `started_at`                            |
| `CHAT_MESSAGE`         | `message_id`, `chat_session_id`, `sender_type`, `message_text`, `created_at`           |
| `INTENT_DETECTION`     | `intent_id`, `message_id`, `intent_code`, `confidence_score`, `detected_at`            |
| `SQL_TEMPLATE`         | `template_id`, `intent_code`, `sql_text`, `allowed_params`, `active_flag`              |
| `QUERY_EXECUTION_LOG`  | `execution_id`, `intent_id`, `template_id`, `param_json`, `execution_status`, `rows_returned`, `executed_at` |

## Intent map

| Keywords / question type                                        | Intent ID                 | SQL target                                              |
|-----------------------------------------------------------------|---------------------------|---------------------------------------------------------|
| `why`, `explain`, "why is hospital X at risk"                   | `EXPLAIN_ALERT`           | `BLOOD_INVENTORY` ⋈ `REQUEST` ⋈ `BLOOD_REQUEST_DETAILS` |
| `low`, `shortage`, `stock`, `inventory`, "how much blood"       | `CHECK_INVENTORY`         | `BLOOD_INVENTORY` (optionally by blood group)           |
| `priority`, `risk`, `surgery`, `urgent patients`                | `GET_HIGH_RISK_PATIENTS`  | `PATIENT` ⋈ `MEDICAL_RECORD` where `risk_score > 7`     |
| `transplant`, `waiting list`, `next kidney/liver/heart/lung`    | `GET_TRANSPLANT_PRIORITY` | `REQUEST` ⋈ `ORGAN_REQUEST_DETAILS` ⋈ `PATIENT`         |
| `donor`, `eligible`                                             | `GET_DONORS`              | `DONOR` where `Eligible` & `Available`                  |
| `pending`, `open requests`, `unfulfilled`, `requests`           | `GET_PENDING_REQUESTS`    | `REQUEST` where `status = 'Pending'`                    |
| `match`, `matching`, `candidates`, `compatibility`              | `GET_MATCH_CANDIDATES`    | `MATCH_CANDIDATE` ⋈ `REQUEST` ⋈ `PATIENT`               |
| `expiring`, `expiry`, `expired`, `near expiry`                  | `GET_EXPIRING_UNITS`      | `BLOOD_UNIT` ordered by `expiry_date`                   |
| `transplant history`, `past transplants`, `completed transplants`| `GET_TRANSPLANT_HISTORY` | `TRANSPLANT` ⋈ `MATCH_CANDIDATE` ⋈ `REQUEST` ⋈ `PATIENT`|

Unmatched input returns a fixed fallback sentence; empty result sets
return `"I could not find any relevant data for that request."`.

## "Intelligent" rules layered on top of SQL

| Rule                                              | Behavior                                                                |
|---------------------------------------------------|-------------------------------------------------------------------------|
| `available_units_summary < 5`                     | URGENT: stock critically low (per-blood-group)                          |
| `5 ≤ available_units_summary < 10`                | tagged `low` ("plan a shipment soon")                                   |
| `risk_score > 8`                                  | patient tagged `High Priority`                                          |
| `hemoglobin_level < 7`                            | tagged `Critical`                                                       |
| `7 ≤ hemoglobin_level ≤ 10`                       | tagged `Urgent`                                                         |
| `hemoglobin_level > 10`                           | tagged `Moderate`                                                       |
| Pending blood demand > inventory for that group   | hospital flagged AT RISK with the exact gap printed                     |

## Safety guarantees

- **No LLM** — regex keyword matching only.
- **SQL-injection safe** — every parameter is passed via `?` placeholders.
- **Bounded output** — every listing query uses `LIMIT 10`.
- **Hard-coded SELECTs only** — `_assert_select_only()` rejects anything else.
- **Audit trail** — every turn writes to `CHAT_MESSAGE`, `INTENT_DETECTION`
  and `QUERY_EXECUTION_LOG`; the chatbot only writes to those tables and
  to `CHAT_SESSION` (never to operational tables).

## REST API

| Endpoint                      | Method | Purpose                                       |
|-------------------------------|--------|-----------------------------------------------|
| `/api/health`                 | GET    | Simple health probe                           |
| `/api/hospitals`              | GET    | List hospitals for the dropdown               |
| `/api/intents`                | GET    | Suggested example questions                   |
| `/api/session`                | POST   | Create a new `CHAT_SESSION`                   |
| `/api/chat`                   | POST   | Send a message, get the bot reply             |
| `/api/history/<session_id>`   | GET    | Retrieve a session's full message history     |

`POST /api/chat` example:

```json
{
  "session_id": 1,
  "hospital_id": 1,
  "message": "Why is Hospital 1 at risk?"
}
```

Response:

```json
{
  "session_id": 1,
  "hospital_id": 1,
  "intent": "EXPLAIN_ALERT",
  "reply": "City General Hospital is at risk: pending blood requests exceed current inventory for O- (have 2, need 4)..."
}
```

## Adding a new intent (modularity)

1. Add a regex list to `INTENT_PATTERNS` under a new Intent ID.
2. Add the parameterized SQL (`SELECT`-only, `LIMIT 10`) to `INTENT_TO_SQL`.
3. Register a formatter in `FORMATTERS` that turns rows into a sentence.
4. (Optional) Add the SQL string to the `SQL_TEMPLATE` table so audit logs
   can reference it.

## Migration to a non-SQLite DBMS

`chatbot_backend.py` keeps the DB connection in two helpers:

- `_connect_readonly(db_path)` — for answering questions
- `_connect_readwrite(db_path)` — for chat-session logging

Replace these two functions with the appropriate driver
(`mysql.connector.connect(...)` / `psycopg2.connect(...)`), and switch
the `?` placeholders to `%s` (single find-and-replace inside
`INTENT_TO_SQL` and the chat-logging helpers).
