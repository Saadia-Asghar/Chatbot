"""Rule-based SQL chatbot backend for the Healthcare Resource Optimization System.

Architecture (deliberately modular for adding new intents later):

    process_user_query(conn, text, hospital_id)          <-- public router
        -> detect_intent(text)                           Phase 2: classifier
        -> INTENT_TO_SQL[intent]                         Phase 2: query map
        -> run_intent_query(...)                         parameterized exec
        -> format_response(intent, rows)                 natural language out
        OR
        -> explain_alert(conn, hospital_id)              Phase 3: "Explain Why"

Safety rules:
    * No LLM / NLP. Regex keyword matching only.
    * Read-only: only the predefined SELECT statements in INTENT_TO_SQL and
      EXPLAIN_QUERIES run, and the SQLite connection is opened as mode=ro.
    * SQL-injection safe: every parameter is passed via ? placeholders.
    * Hallucination-proof: unmatched input -> fixed fallback.
    * Output bounded: LIMIT 10 on every listing query.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple

DB_PATH = "healthcare.db"
DEFAULT_HOSPITAL_ID = 1

# Inventory thresholds (rule-based "prediction").
URGENT_STOCK_THRESHOLD = 5         # units < 5  -> "URGENT: Stock is critically low."
LOW_STOCK_THRESHOLD = 10           # units < 10 -> flagged as "low" (plan a shipment)

# Patient thresholds.
RISK_THRESHOLD = 7                 # RiskScore > 7 -> returned as high-risk
HIGH_PRIORITY_RISK = 8             # RiskScore > 8 -> tagged "High Priority"
HB_CRITICAL = 7.0                  # hemoglobin triage thresholds
HB_URGENT = 10.0

FALLBACK_MESSAGE = (
    "I'm sorry, I can only provide information about blood inventory, "
    "patient risk, transplant priority, or donor eligibility. "
    "You can also ask 'Why is Hospital <id> at risk?'."
)
NO_DATA_MESSAGE = "I could not find any relevant data for that request."


# ==========================================================================
# Phase 2 - Intent Classifier (keywords -> Intent ID)
# ==========================================================================

# Order matters: earlier entries win. "Why" questions must be checked before
# generic stock/risk keywords so they route to the Explain Alert handler.
INTENT_PATTERNS: Dict[str, List[str]] = {
    "EXPLAIN_ALERT": [
        r"\bwhy\b.*\b(risk|low|shortage|flagged|alert)\b",
        r"\bexplain\b.*\b(alert|risk|shortage)\b",
        r"\bwhy is hospital\b",
    ],
    "CHECK_INVENTORY": [
        r"\blow\b",
        r"\bshortage\b",
        r"\bstock\b",
        r"\binventory\b",
        r"\bhow much blood\b",
        r"\bblood (units|supply|availability)\b",
    ],
    "GET_HIGH_RISK_PATIENTS": [
        r"\bpriority\b",
        r"\brisk\b",
        r"\bsurgery\b",
        r"\bhigh[- ]risk\b",
        r"\burgent patients?\b",
        r"\bcritical patients?\b",
    ],
    "GET_TRANSPLANT_PRIORITY": [
        r"\btransplant\b",
        r"\borgan (request|waiting|list|priority)\b",
        r"\bwaiting list\b",
        r"\bmatching\b",
        r"\bnext (kidney|liver|heart|lung)\b",
    ],
    "GET_DONORS": [
        r"\bdonors?\b",
        r"\beligible\b",
    ],
}


def detect_intent(user_input: str) -> Optional[str]:
    """Classify free-form input into one of the registered Intent IDs."""
    text = user_input.lower().strip()
    for intent_id, patterns in INTENT_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text):
                return intent_id
    return None


# Extract a specific blood type (e.g. O-, AB+) mentioned in the question.
BLOOD_TYPE_RE = re.compile(
    r"(?<![A-Za-z0-9])(AB[+-]|[OAB][+-])(?![A-Za-z0-9])", re.IGNORECASE
)

# Extract "hospital 2" or "hospital id 2" from a question.
HOSPITAL_ID_RE = re.compile(r"\bhospital(?:\s+id)?\s+(\d+)\b", re.IGNORECASE)


def extract_blood_type(user_input: str) -> Optional[str]:
    match = BLOOD_TYPE_RE.search(user_input)
    return match.group(1).upper() if match else None


def extract_hospital_id(user_input: str) -> Optional[int]:
    match = HOSPITAL_ID_RE.search(user_input)
    return int(match.group(1)) if match else None


# ==========================================================================
# Phase 2 - Query Generator (Intent -> SQL)
# ==========================================================================

# This mapping is what the project spec calls the "keyword_to_sql_map":
# a single source of truth linking an Intent ID to its parameterized SQL.
INTENT_TO_SQL: Dict[str, str] = {
    "CHECK_INVENTORY_ALL": """
        SELECT i.BloodType, i.CurrentUnits, h.Name
        FROM InventoryTable i
        JOIN HospitalsTable h ON h.HospitalID = i.HospitalID
        WHERE i.HospitalID = ?
        ORDER BY i.BloodType
        LIMIT 10
    """,
    "CHECK_INVENTORY_BY_TYPE": """
        SELECT i.BloodType, i.CurrentUnits, h.Name
        FROM InventoryTable i
        JOIN HospitalsTable h ON h.HospitalID = i.HospitalID
        WHERE i.HospitalID = ? AND i.BloodType = ?
        LIMIT 10
    """,
    "GET_HIGH_RISK_PATIENTS": """
        SELECT Name, Condition, HemoglobinLevel, RiskScore, SurgeryScheduled
        FROM PatientsTable
        WHERE HospitalID = ? AND RiskScore > ?
        ORDER BY RiskScore DESC, SurgeryScheduled DESC
        LIMIT 10
    """,
    "GET_TRANSPLANT_PRIORITY": """
        SELECT p.Name, o.OrganType, o.UrgencyScore, o.WaitTime
        FROM OrganRequests o
        JOIN PatientsTable p ON p.PatientID = o.PatientID
        WHERE p.HospitalID = ?
        ORDER BY o.UrgencyScore DESC, o.WaitTime DESC
        LIMIT 10
    """,
    "GET_DONORS": """
        SELECT Name, BloodType, EligibilityStatus, Location
        FROM DonorsTable
        WHERE EligibilityStatus = 'Eligible'
        ORDER BY BloodType
        LIMIT 10
    """,
}

# Alias using the exact name the project spec asks for.
keyword_to_sql_map = INTENT_TO_SQL


def _assert_select_only(query: str) -> None:
    if not query.lstrip().upper().startswith("SELECT"):
        raise ValueError("Only SELECT queries are allowed.")


def run_intent_query(
    conn: sqlite3.Connection,
    intent_id: str,
    hospital_id: int,
    user_input: str,
) -> Sequence[Tuple[Any, ...]]:
    """Execute the predefined SQL for an intent, always parameterized."""
    cursor = conn.cursor()

    if intent_id == "CHECK_INVENTORY":
        blood_type = extract_blood_type(user_input)
        if blood_type:
            sql = INTENT_TO_SQL["CHECK_INVENTORY_BY_TYPE"]
            _assert_select_only(sql)
            cursor.execute(sql, (hospital_id, blood_type))
        else:
            sql = INTENT_TO_SQL["CHECK_INVENTORY_ALL"]
            _assert_select_only(sql)
            cursor.execute(sql, (hospital_id,))
        return cursor.fetchall()

    if intent_id == "GET_HIGH_RISK_PATIENTS":
        sql = INTENT_TO_SQL["GET_HIGH_RISK_PATIENTS"]
        _assert_select_only(sql)
        cursor.execute(sql, (hospital_id, RISK_THRESHOLD))
        return cursor.fetchall()

    if intent_id == "GET_TRANSPLANT_PRIORITY":
        sql = INTENT_TO_SQL["GET_TRANSPLANT_PRIORITY"]
        _assert_select_only(sql)
        cursor.execute(sql, (hospital_id,))
        return cursor.fetchall()

    if intent_id == "GET_DONORS":
        sql = INTENT_TO_SQL["GET_DONORS"]
        _assert_select_only(sql)
        cursor.execute(sql)
        return cursor.fetchall()

    raise ValueError(f"Unknown intent: {intent_id}")


# ==========================================================================
# Phase 2 - Result Formatter (rows -> natural language)
# ==========================================================================


def _stock_tag(units: int) -> str:
    """Rule-based tag for a single inventory row."""
    if units < URGENT_STOCK_THRESHOLD:
        return "critical"
    if units < LOW_STOCK_THRESHOLD:
        return "low"
    return "sufficient"


def _format_check_inventory(rows: Sequence[Tuple[Any, ...]]) -> str:
    """Rows are (BloodType, CurrentUnits, HospitalName)."""
    hospital_name = rows[0][2]
    urgent = [
        (bt, units) for bt, units, _ in rows if units < URGENT_STOCK_THRESHOLD
    ]

    if len(rows) == 1:
        blood_type, units, _ = rows[0]
        if units < URGENT_STOCK_THRESHOLD:
            return (
                f"Only {units} units of {blood_type} at {hospital_name}. "
                f"URGENT: Stock is critically low. Please prioritize a new shipment."
            )
        if units < LOW_STOCK_THRESHOLD:
            return (
                f"Inventory for {blood_type} is running low "
                f"({units} units at {hospital_name}). Please plan a shipment soon."
            )
        return (
            f"Inventory for {blood_type} is sufficient "
            f"({units} units at {hospital_name})."
        )

    parts = [
        f"{units} units of {bt} ({_stock_tag(units)})" for bt, units, _ in rows
    ]
    sentence = f"Inventory at {hospital_name}: " + ", ".join(parts) + "."
    if urgent:
        urgent_types = ", ".join(bt for bt, _ in urgent)
        sentence += (
            f" URGENT: Stock is critically low for {urgent_types}. "
            f"Please prioritize a new shipment."
        )
    return sentence


def _categorize_hemoglobin(hb: float) -> str:
    """Map a hemoglobin level to a triage tag."""
    if hb < HB_CRITICAL:
        return "Critical"
    if hb <= HB_URGENT:
        return "Urgent"
    return "Moderate"


def _format_high_risk_patients(rows: Sequence[Tuple[Any, ...]]) -> str:
    """Rows are (Name, Condition, HemoglobinLevel, RiskScore, SurgeryScheduled)."""
    parts = []
    for name, condition, hb, score, surgery in rows:
        tags = []
        if score > HIGH_PRIORITY_RISK:
            tags.append("High Priority")
        tags.append(_categorize_hemoglobin(hb))
        tag_str = ", ".join(tags)
        surg = ", surgery scheduled" if surgery else ""
        parts.append(
            f"{name} [{tag_str}] - condition: {condition}, Hb {hb} g/dL, "
            f"risk {score}/10{surg}"
        )
    return (
        "Based on our data, the following patients are at high risk: "
        + "; ".join(parts)
        + "."
    )


def _format_transplant_priority(rows: Sequence[Tuple[Any, ...]]) -> str:
    parts = [
        f"{name} needs a {organ} (urgency {urgency}/10, waiting {wait} days)"
        for name, organ, urgency, wait in rows
    ]
    top_name = rows[0][0]
    return (
        f"Transplant priority order: {'; '.join(parts)}. "
        f"Recommended next recipient: {top_name}."
    )


def _format_donors(rows: Sequence[Tuple[Any, ...]]) -> str:
    parts = [f"{name} ({bt}, {location})" for name, bt, _status, location in rows]
    return "Eligible donors: " + "; ".join(parts) + "."


FORMATTERS = {
    "CHECK_INVENTORY": _format_check_inventory,
    "GET_HIGH_RISK_PATIENTS": _format_high_risk_patients,
    "GET_TRANSPLANT_PRIORITY": _format_transplant_priority,
    "GET_DONORS": _format_donors,
}


def format_response(intent_id: str, rows: Sequence[Tuple[Any, ...]]) -> str:
    """Generic formatter dispatch; returns NO_DATA_MESSAGE on empty results."""
    if not rows:
        return NO_DATA_MESSAGE
    formatter = FORMATTERS.get(intent_id)
    if formatter is None:
        return NO_DATA_MESSAGE
    return formatter(rows)


# ==========================================================================
# Phase 3 - "Explain Why" (multi-step diagnostic)
# ==========================================================================

EXPLAIN_QUERIES: Dict[str, str] = {
    "HOSPITAL_USAGE": """
        SELECT Name, AverageWeeklyUsage
        FROM HospitalsTable
        WHERE HospitalID = ?
    """,
    "TOTAL_STOCK": """
        SELECT COALESCE(SUM(CurrentUnits), 0)
        FROM InventoryTable
        WHERE HospitalID = ?
    """,
    "STOCK_BY_TYPE": """
        SELECT BloodType, CurrentUnits
        FROM InventoryTable
        WHERE HospitalID = ?
        ORDER BY CurrentUnits ASC
        LIMIT 10
    """,
}


def explain_alert(conn: sqlite3.Connection, hospital_id: int) -> str:
    """Justify why a hospital is flagged as 'high risk'.

    Multi-step: fetches AverageWeeklyUsage, current total stock, and the
    lowest-stock blood types, then computes weeks-of-supply.
    """
    cursor = conn.cursor()

    cursor.execute(EXPLAIN_QUERIES["HOSPITAL_USAGE"], (hospital_id,))
    row = cursor.fetchone()
    if row is None:
        return f"I don't know. No hospital found with ID {hospital_id}."
    hospital_name, avg_weekly_usage = row

    cursor.execute(EXPLAIN_QUERIES["TOTAL_STOCK"], (hospital_id,))
    (total_stock,) = cursor.fetchone()

    cursor.execute(EXPLAIN_QUERIES["STOCK_BY_TYPE"], (hospital_id,))
    stock_rows = cursor.fetchall()

    if avg_weekly_usage <= 0:
        return (
            f"{hospital_name} has no recorded weekly usage, so no risk "
            f"calculation is possible."
        )

    weeks_of_stock = total_stock / avg_weekly_usage
    critical_items = [
        f"{bt} ({units} units)" for bt, units in stock_rows
        if units < LOW_STOCK_THRESHOLD
    ]

    if total_stock < avg_weekly_usage:
        explanation = (
            f"Hospital {hospital_name} is at risk because current stock "
            f"({total_stock} units) is less than the average weekly usage "
            f"({avg_weekly_usage:g} units)."
            f" That is approximately {weeks_of_stock:.2f} weeks of supply."
        )
    else:
        explanation = (
            f"Hospital {hospital_name} is within safe range: current stock "
            f"({total_stock} units) covers about {weeks_of_stock:.2f} weeks "
            f"at the average weekly usage of {avg_weekly_usage:g} units."
        )

    if critical_items:
        explanation += (
            f" Critically low blood types: {', '.join(critical_items)}."
        )
    return explanation


# ==========================================================================
# Public API - the router used by the CLI and the Streamlit UI
# ==========================================================================


def process_user_query(
    conn: sqlite3.Connection,
    input_string: str,
    hospital_id: int = DEFAULT_HOSPITAL_ID,
) -> str:
    """End-to-end: route a user string to the right intent and return text."""
    if not input_string or not input_string.strip():
        return FALLBACK_MESSAGE

    intent_id = detect_intent(input_string)
    if intent_id is None:
        return FALLBACK_MESSAGE

    try:
        if intent_id == "EXPLAIN_ALERT":
            target_hospital = extract_hospital_id(input_string) or hospital_id
            return explain_alert(conn, target_hospital)

        rows = run_intent_query(conn, intent_id, hospital_id, input_string)
        return format_response(intent_id, rows)
    except sqlite3.Error as e:
        return f"Database error: {e}"


# Backwards-compatible alias used by earlier tests / UI code.
def handle_user_query(
    conn: sqlite3.Connection,
    user_input: str,
    hospital_id: int = DEFAULT_HOSPITAL_ID,
) -> str:
    return process_user_query(conn, user_input, hospital_id)


def _connect_readonly(db_path: str) -> sqlite3.Connection:
    """Open SQLite in read-only mode so the chat interface cannot mutate data."""
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def main() -> None:
    conn = _connect_readonly(DB_PATH)
    try:
        print("Healthcare chatbot ready. Type 'exit' to quit.")
        while True:
            try:
                user_input = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not user_input:
                continue
            if user_input.lower() in {"exit", "quit"}:
                break
            print("Bot:", process_user_query(conn, user_input))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
