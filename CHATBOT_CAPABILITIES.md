# DonorBridge Chatbot — What It Can Answer

A quick reference for the team. The chatbot answers natural-language
questions in **12 intent categories**. It always picks one hospital
context (selected from the sidebar dropdown), runs a hard-coded
parameterized `SELECT` against the DonorBridge schema, and replies in
plain English.

> If the question doesn't match any intent, the bot returns a fixed
> "I'm sorry, I can only answer …" message — never a hallucinated answer.

---

## 1. Blood inventory questions

What it covers: current units of each blood group at a hospital.

Examples that work:

- "What is the inventory for O- blood?"
- "Is there O blood group?" *(asks about both O+ and O-)*
- "Do you have any AB blood?"
- "Any A blood available?"
- "How much B+ blood do we have?"
- "Show me the inventory."
- "Is there any low stock or shortage?"
- "Blood units left?"
- "Are there any units of A- remaining?"

Sample reply

> Inventory at City General Hospital: 5 units of A+ (low),
> 4 units of A- (critical), 6 units of AB+ (low), 9 units of B+ (low),
> 8 units of O+ (low), 2 units of O- (critical).
> URGENT: Stock is critically low for A-, O-.
> Please prioritize a new shipment.

Tags applied automatically:
- `< 5 units` → **critical** (URGENT shipment)
- `5 – 9 units` → **low** (plan a shipment)
- `≥ 10 units` → **sufficient**

---

## 2. "Why is Hospital X at risk?" (Explain Alert)

A multi-step diagnostic. Joins `BLOOD_INVENTORY` with pending
`BLOOD_REQUEST_DETAILS` and shows where demand exceeds supply.

Examples:

- "Why is Hospital 1 at risk?"
- "Why is Hospital 2 flagged?"
- "Explain the alert."
- "Why low stock?"

Sample reply

> City General Hospital is at risk: pending blood requests exceed
> current inventory for O- (have 2, need 4). Critically low blood
> groups: O- (2 units), A- (4 units), A+ (5 units), AB+ (6 units),
> O+ (8 units), B+ (9 units).

---

## 3. High-risk patients

Lists patients with `risk_score > 7`, joined with their medical record
(diagnosis, hemoglobin, severity).

Examples:

- "Who are the high-risk patients?"
- "Show me critical patients."
- "Patients with surgery scheduled?"
- "Who needs urgent care?"
- "High-risk priority patients?"

Tags applied:
- `risk_score > 8` → **High Priority**
- Hemoglobin: `< 7` → **Critical**, `7 – 10` → **Urgent**, `> 10` → **Moderate**

---

## 4. List all patients

Plain listing, ordered by risk score.

Examples:

- "List all patients."
- "Show patients."
- "How many patients?"

---

## 5. Transplant priority (next recipient)

Joins `REQUEST` ⋈ `ORGAN_REQUEST_DETAILS` ⋈ `PATIENT`.

Examples:

- "Who should get the next kidney transplant?"
- "Show me the organ waiting list."
- "Transplant priority?"
- "Who is next on the liver list?"
- "Organ waiting list?"

---

## 6. Transplant history

Past / completed transplants from the `TRANSPLANT` table.

Examples:

- "Show me the transplant history."
- "Past transplants?"
- "Completed transplants log."

---

## 7. Match candidates

Reads `MATCH_CANDIDATE` (proposed/accepted matches between requests and
either blood units or organ offers).

Examples:

- "Show me the match candidates."
- "Any matches?"
- "Compatibility scores?"
- "Compatible donors?"

---

## 8. Pending requests

Open requests (`status = 'Pending'`) at the hospital.

Examples:

- "List the pending requests."
- "What's pending?"
- "Show open requests."
- "Unfulfilled requests?"

---

## 9. Eligible donors

Donors who are `eligibility_status = 'Eligible'` AND `availability_status = 'Available'`.

Examples:

- "Show me the eligible donors."
- "Who can donate blood?"
- "Available donors?"
- "List donors."

---

## 10. Recent blood donations

Reads `BLOOD_DONATION` joined with `DONOR`, latest first.

Examples:

- "Show me recent blood donations."
- "How much blood was donated?"
- "Recent donations?"

---

## 11. Blood units expiring soon

Lists `BLOOD_UNIT` rows where `unit_status = 'Available'`, ordered by
nearest `expiry_date`.

Examples:

- "Which blood units are expiring soon?"
- "Near expiry stock?"
- "Expired units?"
- "Shelf life of blood units?"

---

## 12. List hospitals

Examples:

- "List all hospitals."
- "Show hospitals."
- "How many hospitals?"

---

## What the bot will NOT answer

Anything outside the 12 intents above. The bot returns a fixed fallback:

> I'm sorry, I can only answer questions about blood inventory, donors,
> donations, patients at risk, transplant priority, pending requests,
> match candidates, blood units expiring soon, transplant history,
> hospitals or the patient list. You can also ask
> 'Why is Hospital &lt;id&gt; at risk?'.

It also will not:
- Insert / update / delete data (only `SELECT` queries are allowed).
- Run free-form SQL the user types.
- Use any LLM — all classification is regex on keywords.
- Answer questions outside the DonorBridge schema (no general medical
  advice, no internet search, no chit-chat).

---

## How to demo to the team

1. `python init_db.py` — builds `donorbridge.db` from `schema.sql`.
2. `python api.py` — starts the Flask web app at <http://127.0.0.1:5000/>.
3. Pick a hospital on the left, click any **suggestion chip** in the
   sidebar to send a sample question.
4. Open `donorbridge.db` in DB Browser to show that
   `CHAT_SESSION`, `CHAT_MESSAGE`, `INTENT_DETECTION` and
   `QUERY_EXECUTION_LOG` are populated for every turn — that's the
   audit trail the ERD prescribes.

Suggested demo script:

| Step | Question                              | Shows                              |
|------|---------------------------------------|------------------------------------|
| 1    | "List all hospitals."                 | LIST_HOSPITALS                     |
| 2    | "Show patients."                      | LIST_PATIENTS                      |
| 3    | "Who are the high-risk patients?"     | GET_HIGH_RISK_PATIENTS + tagging   |
| 4    | "Is there O blood group?"             | CHECK_INVENTORY by family          |
| 5    | "Show me the eligible donors."        | GET_DONORS                         |
| 6    | "Show me recent blood donations."     | GET_DONATIONS                      |
| 7    | "List the pending requests."          | GET_PENDING_REQUESTS               |
| 8    | "Show me the match candidates."       | GET_MATCH_CANDIDATES               |
| 9    | "Who should get the next kidney transplant?" | GET_TRANSPLANT_PRIORITY     |
| 10   | "Which blood units are expiring soon?"| GET_EXPIRING_UNITS                 |
| 11   | "Show me the transplant history."     | GET_TRANSPLANT_HISTORY             |
| 12   | "Why is Hospital 1 at risk?"          | EXPLAIN_ALERT (multi-step)         |
| 13   | "Tell me a joke."                     | Fallback (proves no hallucination) |
