"""DonorBridge — Rule-based SQL chatbot backend.

Schema follows the DonorBridge ERD (HOSPITAL, PATIENT, MEDICAL_RECORD,
DONOR, REQUEST [+ BLOOD_REQUEST_DETAILS / ORGAN_REQUEST_DETAILS],
BLOOD_DONATION, BLOOD_UNIT, BLOOD_INVENTORY, ORGAN_OFFER,
MATCH_CANDIDATE, TRANSPLANT, CHAT_SESSION, CHAT_MESSAGE,
INTENT_DETECTION, SQL_TEMPLATE, QUERY_EXECUTION_LOG).

Architecture
------------
    process_user_query(conn, text, hospital_id, session_id)
        -> detect_intent(text)             # regex keyword classifier
        -> INTENT_TO_SQL[intent]           # parameterized SELECT
        -> run_intent_query(...)
        -> format_response(intent, rows)
        OR
        -> explain_alert(conn, hospital_id)

Every turn writes to:
    CHAT_MESSAGE (User)  -> INTENT_DETECTION  -> QUERY_EXECUTION_LOG
    CHAT_MESSAGE (Bot)

Safety rules
------------
* No LLM. Regex keyword matching only.
* All `INTENT_TO_SQL` entries are hard-coded SELECT statements with `?`
  placeholders. `_assert_select_only()` is enforced at every execution.
* Output bounded with `LIMIT 10`.
* Unmatched input -> fixed fallback. Empty result set -> fixed "no data".
"""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple

DB_PATH = "donorbridge.db"
DEFAULT_HOSPITAL_ID = 1

URGENT_STOCK_THRESHOLD = 5
LOW_STOCK_THRESHOLD = 10

RISK_THRESHOLD = 7
HIGH_PRIORITY_RISK = 8
HB_CRITICAL = 7.0
HB_URGENT = 10.0

EXPIRY_SOON_DAYS = 14

FALLBACK_MESSAGE = (
    "I'm sorry, I can only answer questions about blood inventory, donors, "
    "donations, patients at risk, transplant priority, pending requests, "
    "match candidates, blood units expiring soon, transplant history, "
    "hospitals or the patient list. "
    "You can also ask 'Why is Hospital <id> at risk?'."
)
NO_DATA_MESSAGE = "I could not find any relevant data for that request."


# ==========================================================================
# Intent Classifier (keyword -> Intent ID)
# ==========================================================================

INTENT_PATTERNS: Dict[str, List[str]] = {
    "EXPLAIN_ALERT": [
        r"\bwhy\b.*\b(risk|low|shortage|flagged|alert|short)\b",
        r"\bexplain\b.*\b(alert|risk|shortage)\b",
        r"\bwhy is hospital\b",
    ],
    "LIST_HOSPITALS": [
        r"\b(list|show|all|which)\b.*\bhospitals?\b",
        r"\bhospitals?\b\s*(list|available)?\s*$",
        r"\bhow many hospitals?\b",
    ],
    "GET_EXPIRING_UNITS": [
        r"\bexpir(ing|y|ed)\b",
        r"\bexpires?\b",
        r"\bnear expiry\b",
        r"\bshelf life\b",
    ],
    "GET_TRANSPLANT_HISTORY": [
        r"\btransplant\s+(history|records?|done|performed|log)\b",
        r"\bpast transplants?\b",
        r"\bcompleted transplants?\b",
        r"\btransplants? (so far|history)\b",
    ],
    "GET_TRANSPLANT_PRIORITY": [
        r"\btransplant\b",
        r"\borgan (request|waiting|list|priority|need)\b",
        r"\bwaiting list\b",
        r"\bnext (kidney|liver|heart|lung)\b",
    ],
    "GET_MATCH_CANDIDATES": [
        r"\bmatch(es|ing)?\b",
        r"\bcandidates?\b",
        r"\bcompatibility\b",
        r"\bcompatible (units?|donors?|matches?)\b",
    ],
    "GET_PENDING_REQUESTS": [
        r"\bpending\b",
        r"\bopen\s+requests?\b",
        r"\bunfulfilled\b",
        r"\brequests?\b",
        r"\bwhat'?s? (pending|open)\b",
    ],
    "GET_DONATIONS": [
        r"\bdonations?\b",
        r"\bblood donated\b",
        r"\bdonated\b",
        r"\bhow much blood was donated\b",
    ],
    "CHECK_INVENTORY": [
        r"\blow\b",
        r"\bshortage\b",
        r"\bstock\b",
        r"\binventory\b",
        r"\bhow much blood\b",
        r"\bblood\s+(units|supply|availability|available|left|remaining|group|type)\b",
        r"\bblood\s*group\b",
        r"\b(any|some|got|have)\b.*\bblood\b",
        r"\b(is|are)\s+(there|we|you)\b.*\bblood\b",
        r"\bdo\s+(you|we)\s+have\b.*\bblood\b",
        r"\bavailable\b.*\bblood\b",
        r"\bblood\b.*\bavailable\b",
        r"\bunits?\s+(of|for|left)\b",
        r"\b(remaining|left)\s+units?\b",
    ],
    "GET_HIGH_RISK_PATIENTS": [
        r"\bpriority\b",
        r"\brisk\b",
        r"\bsurgery\b",
        r"\bhigh[- ]risk\b",
        r"\burgent patients?\b",
        r"\bcritical patients?\b",
    ],
    "LIST_PATIENTS": [
        r"\b(list|show|all)\b.*\bpatients?\b",
        r"\bhow many patients?\b",
        r"\bpatients?\b\s*$",
    ],
    "GET_DONORS": [
        r"\bdonors?\b",
        r"\beligible\b",
        r"\bavailable donors?\b",
        r"\bwho can donate\b",
    ],
}


def detect_intent(user_input: str) -> Optional[str]:
    """Classify free-form input into one of the registered intent IDs."""
    text = user_input.lower().strip()
    for intent_id, patterns in INTENT_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text):
                return intent_id
    return None


BLOOD_TYPE_RE = re.compile(
    r"(?<![A-Za-z0-9])(AB[+-]|[OAB][+-])(?![A-Za-z0-9])", re.IGNORECASE
)
# Bareword blood family without sign: "O", "AB", "A blood", "B group".
# Requires the word "blood" or "group" or "type" nearby so we don't false-match
# every standalone "A" or "I" in the sentence.
BLOOD_FAMILY_RE = re.compile(
    r"(?<![A-Za-z0-9+\-])(AB|[OAB])(?![A-Za-z0-9+\-])\s*(?:blood|group|type)\b"
    r"|"
    r"\b(?:blood|group|type)\s+(AB|[OAB])(?![A-Za-z0-9+\-])",
    re.IGNORECASE,
)
HOSPITAL_ID_RE = re.compile(r"\bhospital(?:\s+id)?\s+(\d+)\b", re.IGNORECASE)


def extract_blood_type(user_input: str) -> Optional[str]:
    m = BLOOD_TYPE_RE.search(user_input)
    return m.group(1).upper() if m else None


def extract_blood_family(user_input: str) -> Optional[str]:
    """Return 'O', 'A', 'B', 'AB' if the user mentioned a bare blood family
    (e.g. 'O blood group', 'group A'). Returns None otherwise. Ignored if a
    full type with sign is already present.
    """
    if extract_blood_type(user_input):
        return None
    m = BLOOD_FAMILY_RE.search(user_input)
    if not m:
        return None
    family = (m.group(1) or m.group(2)).upper()
    return family


def extract_hospital_id(user_input: str) -> Optional[int]:
    m = HOSPITAL_ID_RE.search(user_input)
    return int(m.group(1)) if m else None


# ==========================================================================
# Query Generator (Intent -> SQL).
# These exactly mirror the rows seeded into the SQL_TEMPLATE table.
# ==========================================================================

INTENT_TO_SQL: Dict[str, str] = {
    "CHECK_INVENTORY_ALL": """
        SELECT bi.blood_group, bi.available_units_summary, h.name
        FROM BLOOD_INVENTORY bi
        JOIN HOSPITAL h ON h.hospital_id = bi.hospital_id
        WHERE bi.hospital_id = ?
        ORDER BY bi.blood_group
        LIMIT 10
    """,
    "CHECK_INVENTORY_BY_TYPE": """
        SELECT bi.blood_group, bi.available_units_summary, h.name
        FROM BLOOD_INVENTORY bi
        JOIN HOSPITAL h ON h.hospital_id = bi.hospital_id
        WHERE bi.hospital_id = ? AND bi.blood_group = ?
        LIMIT 10
    """,
    "CHECK_INVENTORY_BY_FAMILY": """
        SELECT bi.blood_group, bi.available_units_summary, h.name
        FROM BLOOD_INVENTORY bi
        JOIN HOSPITAL h ON h.hospital_id = bi.hospital_id
        WHERE bi.hospital_id = ? AND bi.blood_group IN (?, ?)
        ORDER BY bi.blood_group
        LIMIT 10
    """,
    "LIST_HOSPITALS": """
        SELECT hospital_id, name, location, COALESCE(contact, '')
        FROM HOSPITAL
        ORDER BY hospital_id
        LIMIT 10
    """,
    "LIST_PATIENTS": """
        SELECT p.full_name, p.age, p.gender, p.blood_group, p.risk_score
        FROM PATIENT p
        WHERE p.hospital_id = ?
        ORDER BY p.risk_score DESC, p.full_name ASC
        LIMIT 10
    """,
    "GET_DONATIONS": """
        SELECT bd.blood_donation_id, d.full_name, d.blood_group,
               bd.donation_date, bd.quantity_donated_ml, bd.outcome
        FROM BLOOD_DONATION bd
        JOIN DONOR d ON d.donor_id = bd.donor_id
        WHERE d.hospital_id = ?
        ORDER BY date(bd.donation_date) DESC
        LIMIT 10
    """,
    "GET_HIGH_RISK_PATIENTS": """
        SELECT p.full_name, mr.diagnosis, mr.hemoglobin_level,
               p.risk_score, mr.severity_level
        FROM PATIENT p
        LEFT JOIN MEDICAL_RECORD mr ON mr.patient_id = p.patient_id
        WHERE p.hospital_id = ? AND p.risk_score > ?
        ORDER BY p.risk_score DESC
        LIMIT 10
    """,
    "GET_TRANSPLANT_PRIORITY": """
        SELECT p.full_name, ord.organ_type_required, r.urgency_level,
               ord.max_wait_time_days, r.status
        FROM REQUEST r
        JOIN ORGAN_REQUEST_DETAILS ord ON ord.request_id = r.request_id
        JOIN PATIENT p ON p.patient_id = r.patient_id
        WHERE r.hospital_id = ?
        ORDER BY r.urgency_level DESC, ord.max_wait_time_days ASC
        LIMIT 10
    """,
    "GET_DONORS": """
        SELECT full_name, blood_group, eligibility_status,
               availability_status, donor_type
        FROM DONOR
        WHERE hospital_id = ?
              AND eligibility_status = 'Eligible'
              AND availability_status = 'Available'
        ORDER BY blood_group
        LIMIT 10
    """,
    "GET_PENDING_REQUESTS": """
        SELECT r.request_id, r.request_type, p.full_name,
               r.urgency_level, r.status
        FROM REQUEST r
        JOIN PATIENT p ON p.patient_id = r.patient_id
        WHERE r.hospital_id = ? AND r.status = 'Pending'
        ORDER BY r.urgency_level DESC
        LIMIT 10
    """,
    "GET_EXPIRING_UNITS": """
        SELECT bu.blood_group, bu.volume_ml, bu.expiry_date, bu.unit_status
        FROM BLOOD_UNIT bu
        WHERE bu.unit_status = 'Available'
        ORDER BY date(bu.expiry_date) ASC
        LIMIT 10
    """,
    "GET_MATCH_CANDIDATES": """
        SELECT mc.match_id, mc.match_type, mc.compatibility_score,
               mc.priority_level, mc.match_status, p.full_name
        FROM MATCH_CANDIDATE mc
        JOIN REQUEST r ON r.request_id = mc.request_id
        JOIN PATIENT p ON p.patient_id = r.patient_id
        WHERE r.hospital_id = ?
        ORDER BY mc.compatibility_score DESC
        LIMIT 10
    """,
    "GET_TRANSPLANT_HISTORY": """
        SELECT t.transplant_id, t.transplant_date, t.surgeon_name, t.outcome,
               p.full_name, ord.organ_type_required
        FROM TRANSPLANT t
        JOIN MATCH_CANDIDATE mc ON mc.match_id = t.match_id
        JOIN REQUEST r ON r.request_id = mc.request_id
        JOIN PATIENT p ON p.patient_id = r.patient_id
        JOIN ORGAN_REQUEST_DETAILS ord ON ord.request_id = r.request_id
        WHERE r.hospital_id = ?
        ORDER BY date(t.transplant_date) DESC
        LIMIT 10
    """,
}

keyword_to_sql_map = INTENT_TO_SQL  # spec-friendly alias


def _assert_select_only(query: str) -> None:
    if not query.lstrip().upper().startswith("SELECT"):
        raise ValueError("Only SELECT queries are allowed.")


def run_intent_query(
    conn: sqlite3.Connection,
    intent_id: str,
    hospital_id: int,
    user_input: str,
) -> Tuple[str, Sequence[Tuple[Any, ...]], Dict[str, Any]]:
    """Execute the predefined SQL for an intent.

    Returns (template_intent_code, rows, params_dict).
    `template_intent_code` is the actual SQL_TEMPLATE name we ran (which may
    be more specific than the user-facing intent, e.g. CHECK_INVENTORY_ALL
    vs. CHECK_INVENTORY_BY_TYPE) so we can attribute the execution log.
    """
    cursor = conn.cursor()

    if intent_id == "CHECK_INVENTORY":
        blood_type = extract_blood_type(user_input)
        if blood_type:
            sql = INTENT_TO_SQL["CHECK_INVENTORY_BY_TYPE"]
            _assert_select_only(sql)
            cursor.execute(sql, (hospital_id, blood_type))
            return "CHECK_INVENTORY_BY_TYPE", cursor.fetchall(), {
                "hospital_id": hospital_id, "blood_group": blood_type
            }
        family = extract_blood_family(user_input)
        if family:
            sql = INTENT_TO_SQL["CHECK_INVENTORY_BY_FAMILY"]
            _assert_select_only(sql)
            pos, neg = f"{family}+", f"{family}-"
            cursor.execute(sql, (hospital_id, pos, neg))
            return "CHECK_INVENTORY_BY_FAMILY", cursor.fetchall(), {
                "hospital_id": hospital_id, "blood_family": family,
                "groups": [pos, neg],
            }
        sql = INTENT_TO_SQL["CHECK_INVENTORY_ALL"]
        _assert_select_only(sql)
        cursor.execute(sql, (hospital_id,))
        return "CHECK_INVENTORY_ALL", cursor.fetchall(), {"hospital_id": hospital_id}

    if intent_id == "GET_HIGH_RISK_PATIENTS":
        sql = INTENT_TO_SQL["GET_HIGH_RISK_PATIENTS"]
        _assert_select_only(sql)
        cursor.execute(sql, (hospital_id, RISK_THRESHOLD))
        return intent_id, cursor.fetchall(), {
            "hospital_id": hospital_id, "risk_threshold": RISK_THRESHOLD
        }

    if intent_id in {
        "GET_TRANSPLANT_PRIORITY",
        "GET_DONORS",
        "GET_PENDING_REQUESTS",
        "GET_MATCH_CANDIDATES",
        "GET_TRANSPLANT_HISTORY",
        "LIST_PATIENTS",
        "GET_DONATIONS",
    }:
        sql = INTENT_TO_SQL[intent_id]
        _assert_select_only(sql)
        cursor.execute(sql, (hospital_id,))
        return intent_id, cursor.fetchall(), {"hospital_id": hospital_id}

    if intent_id == "GET_EXPIRING_UNITS":
        sql = INTENT_TO_SQL[intent_id]
        _assert_select_only(sql)
        cursor.execute(sql)
        return intent_id, cursor.fetchall(), {}

    if intent_id == "LIST_HOSPITALS":
        sql = INTENT_TO_SQL[intent_id]
        _assert_select_only(sql)
        cursor.execute(sql)
        return intent_id, cursor.fetchall(), {}

    raise ValueError(f"Unknown intent: {intent_id}")


# ==========================================================================
# Result Formatter (rows -> natural-language sentence)
# ==========================================================================


def _stock_tag(units: int) -> str:
    if units < URGENT_STOCK_THRESHOLD:
        return "critical"
    if units < LOW_STOCK_THRESHOLD:
        return "low"
    return "sufficient"


def _format_check_inventory(rows: Sequence[Tuple[Any, ...]]) -> str:
    hospital_name = rows[0][2]
    urgent = [(bt, u) for bt, u, _ in rows if u < URGENT_STOCK_THRESHOLD]

    if len(rows) == 1:
        bt, units, _ = rows[0]
        if units < URGENT_STOCK_THRESHOLD:
            return (
                f"Only {units} units of {bt} at {hospital_name}. "
                f"URGENT: Stock is critically low. Please prioritize a new shipment."
            )
        if units < LOW_STOCK_THRESHOLD:
            return (
                f"Inventory for {bt} is running low "
                f"({units} units at {hospital_name}). Please plan a shipment soon."
            )
        return f"Inventory for {bt} is sufficient ({units} units at {hospital_name})."

    parts = [f"{u} units of {bt} ({_stock_tag(u)})" for bt, u, _ in rows]
    sentence = f"Inventory at {hospital_name}: " + ", ".join(parts) + "."
    if urgent:
        urgent_types = ", ".join(bt for bt, _ in urgent)
        sentence += (
            f" URGENT: Stock is critically low for {urgent_types}. "
            f"Please prioritize a new shipment."
        )
    return sentence


def _categorize_hemoglobin(hb: Optional[float]) -> str:
    if hb is None:
        return "Unknown"
    if hb < HB_CRITICAL:
        return "Critical"
    if hb <= HB_URGENT:
        return "Urgent"
    return "Moderate"


def _format_high_risk_patients(rows: Sequence[Tuple[Any, ...]]) -> str:
    parts = []
    for name, diagnosis, hb, score, severity in rows:
        tags = []
        if score > HIGH_PRIORITY_RISK:
            tags.append("High Priority")
        tags.append(_categorize_hemoglobin(hb))
        if severity:
            tags.append(severity)
        tag_str = ", ".join(tags)
        hb_str = f"Hb {hb} g/dL" if hb is not None else "Hb unknown"
        diag = diagnosis or "no diagnosis on file"
        parts.append(
            f"{name} [{tag_str}] - {diag}, {hb_str}, risk {score}/10"
        )
    return (
        "Based on our data, the following patients are at high risk: "
        + "; ".join(parts) + "."
    )


def _format_transplant_priority(rows: Sequence[Tuple[Any, ...]]) -> str:
    parts = [
        f"{name} needs a {organ} (urgency {urgency}/10, max wait "
        f"{wait:g} days, status {status})"
        for name, organ, urgency, wait, status in rows
    ]
    top_name = rows[0][0]
    return (
        f"Transplant priority order: {'; '.join(parts)}. "
        f"Recommended next recipient: {top_name}."
    )


def _format_donors(rows: Sequence[Tuple[Any, ...]]) -> str:
    parts = [
        f"{name} ({bt}, {donor_type}, {avail.lower()})"
        for name, bt, _elig, avail, donor_type in rows
    ]
    return "Eligible & available donors: " + "; ".join(parts) + "."


def _format_pending_requests(rows: Sequence[Tuple[Any, ...]]) -> str:
    parts = [
        f"#{rid} {rtype} for {name} (urgency {urg}/10, {status})"
        for rid, rtype, name, urg, status in rows
    ]
    return "Pending requests: " + "; ".join(parts) + "."


def _format_expiring_units(rows: Sequence[Tuple[Any, ...]]) -> str:
    parts = [
        f"{bt} ({vol} ml, expires {exp})"
        for bt, vol, exp, _status in rows
    ]
    return "Available blood units sorted by expiry: " + "; ".join(parts) + "."


def _format_match_candidates(rows: Sequence[Tuple[Any, ...]]) -> str:
    parts = [
        f"#{mid} {mtype} match for {name}, score {score:.2f}, "
        f"priority {priority}, status {status}"
        for mid, mtype, score, priority, status, name in rows
    ]
    return "Match candidates: " + "; ".join(parts) + "."


def _format_transplant_history(rows: Sequence[Tuple[Any, ...]]) -> str:
    parts = [
        f"#{tid} on {tdate}: {organ} for {name} by {surgeon} ({outcome})"
        for tid, tdate, surgeon, outcome, name, organ in rows
    ]
    return "Transplant history: " + "; ".join(parts) + "."


def _format_list_hospitals(rows: Sequence[Tuple[Any, ...]]) -> str:
    parts = [f"#{hid} {name} ({loc})" for hid, name, loc, _contact in rows]
    return "Registered hospitals: " + "; ".join(parts) + "."


def _format_list_patients(rows: Sequence[Tuple[Any, ...]]) -> str:
    parts = [
        f"{name} ({age} {gender}, {bg}, risk {score}/10)"
        for name, age, gender, bg, score in rows
    ]
    return "Patients at this hospital: " + "; ".join(parts) + "."


def _format_donations(rows: Sequence[Tuple[Any, ...]]) -> str:
    parts = [
        f"#{did} {name} ({bg}) donated {qty} ml on {ddate} - {outcome}"
        for did, name, bg, ddate, qty, outcome in rows
    ]
    return "Recent blood donations: " + "; ".join(parts) + "."


FORMATTERS = {
    "CHECK_INVENTORY": _format_check_inventory,
    "GET_HIGH_RISK_PATIENTS": _format_high_risk_patients,
    "GET_TRANSPLANT_PRIORITY": _format_transplant_priority,
    "GET_DONORS": _format_donors,
    "GET_PENDING_REQUESTS": _format_pending_requests,
    "GET_EXPIRING_UNITS": _format_expiring_units,
    "GET_MATCH_CANDIDATES": _format_match_candidates,
    "GET_TRANSPLANT_HISTORY": _format_transplant_history,
    "LIST_HOSPITALS": _format_list_hospitals,
    "LIST_PATIENTS": _format_list_patients,
    "GET_DONATIONS": _format_donations,
}


def format_response(intent_id: str, rows: Sequence[Tuple[Any, ...]]) -> str:
    if not rows:
        return NO_DATA_MESSAGE
    formatter = FORMATTERS.get(intent_id)
    if formatter is None:
        return NO_DATA_MESSAGE
    return formatter(rows)


# ==========================================================================
# "Explain Why" — multi-step diagnostic
# Computes risk = hospital has pending blood requests for groups whose
# inventory cannot cover them, OR any blood group below LOW_STOCK_THRESHOLD.
# ==========================================================================

EXPLAIN_QUERIES: Dict[str, str] = {
    "HOSPITAL": "SELECT name FROM HOSPITAL WHERE hospital_id = ?",
    "INVENTORY": """
        SELECT blood_group, available_units_summary
        FROM BLOOD_INVENTORY
        WHERE hospital_id = ?
        ORDER BY available_units_summary ASC
    """,
    "PENDING_DEMAND": """
        SELECT brd.blood_group_required, COALESCE(SUM(brd.units_required), 0)
        FROM REQUEST r
        JOIN BLOOD_REQUEST_DETAILS brd ON brd.request_id = r.request_id
        WHERE r.hospital_id = ? AND r.status = 'Pending'
        GROUP BY brd.blood_group_required
    """,
}


def explain_alert(conn: sqlite3.Connection, hospital_id: int) -> Tuple[str, Dict[str, Any]]:
    cur = conn.cursor()

    cur.execute(EXPLAIN_QUERIES["HOSPITAL"], (hospital_id,))
    row = cur.fetchone()
    if row is None:
        return f"I don't know. No hospital found with ID {hospital_id}.", {
            "hospital_id": hospital_id
        }
    (hospital_name,) = row

    cur.execute(EXPLAIN_QUERIES["INVENTORY"], (hospital_id,))
    inventory = cur.fetchall()

    cur.execute(EXPLAIN_QUERIES["PENDING_DEMAND"], (hospital_id,))
    demand = {bg: units for bg, units in cur.fetchall()}

    inv_map = {bg: u for bg, u in inventory}
    shortfalls = []
    for bg, needed in demand.items():
        have = inv_map.get(bg, 0)
        if have < needed:
            shortfalls.append((bg, have, needed))

    critical_items = [
        f"{bg} ({u} units)" for bg, u in inventory if u < LOW_STOCK_THRESHOLD
    ]

    if shortfalls:
        gaps = ", ".join(
            f"{bg} (have {have}, need {need})"
            for bg, have, need in shortfalls
        )
        explanation = (
            f"{hospital_name} is at risk: pending blood requests exceed "
            f"current inventory for {gaps}."
        )
    elif critical_items:
        explanation = (
            f"{hospital_name} has low blood-bank stock for some groups, "
            f"even though pending demand is currently covered."
        )
    else:
        explanation = (
            f"{hospital_name} is within safe range: current inventory covers "
            f"all pending blood requests and no group is below the low-stock "
            f"threshold ({LOW_STOCK_THRESHOLD} units)."
        )

    if critical_items:
        explanation += f" Critically low blood groups: {', '.join(critical_items)}."

    payload = {
        "hospital_id": hospital_id,
        "hospital_name": hospital_name,
        "shortfalls": shortfalls,
        "critical_items": critical_items,
    }
    return explanation, payload


# ==========================================================================
# Chat-session logging (CHAT_SESSION / CHAT_MESSAGE / INTENT_DETECTION /
# QUERY_EXECUTION_LOG). These are WRITE operations, so they require a
# read/write connection — see _connect_readwrite() below.
# ==========================================================================


def start_chat_session(
    conn: sqlite3.Connection,
    hospital_id: int,
    user_role: str = "Doctor",
) -> int:
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO CHAT_SESSION (hospital_id, user_role) VALUES (?, ?)",
        (hospital_id, user_role),
    )
    conn.commit()
    return cur.lastrowid


def _log_message(
    conn: sqlite3.Connection,
    session_id: int,
    sender_type: str,
    text: str,
) -> int:
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO CHAT_MESSAGE (chat_session_id, sender_type, message_text) "
        "VALUES (?, ?, ?)",
        (session_id, sender_type, text),
    )
    conn.commit()
    return cur.lastrowid


def _log_intent(
    conn: sqlite3.Connection,
    message_id: int,
    intent_code: str,
    confidence: float = 1.0,
) -> int:
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO INTENT_DETECTION (message_id, intent_code, confidence_score) "
        "VALUES (?, ?, ?)",
        (message_id, intent_code, confidence),
    )
    conn.commit()
    return cur.lastrowid


def _template_id_for(conn: sqlite3.Connection, intent_code: str) -> Optional[int]:
    cur = conn.cursor()
    cur.execute(
        "SELECT template_id FROM SQL_TEMPLATE "
        "WHERE intent_code = ? AND active_flag = 1 "
        "ORDER BY template_id DESC LIMIT 1",
        (intent_code,),
    )
    row = cur.fetchone()
    return row[0] if row else None


def _log_execution(
    conn: sqlite3.Connection,
    intent_id_pk: int,
    template_id: int,
    params: Dict[str, Any],
    status: str,
    rows_returned: int,
) -> None:
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO QUERY_EXECUTION_LOG "
        "(intent_id, template_id, param_json, execution_status, rows_returned) "
        "VALUES (?, ?, ?, ?, ?)",
        (intent_id_pk, template_id, json.dumps(params), status, rows_returned),
    )
    conn.commit()


# ==========================================================================
# Public router
# ==========================================================================


def process_user_query(
    conn: sqlite3.Connection,
    input_string: str,
    hospital_id: int = DEFAULT_HOSPITAL_ID,
    session_id: Optional[int] = None,
) -> str:
    """Route a user string -> reply. If `session_id` is provided, every step
    is logged to CHAT_MESSAGE / INTENT_DETECTION / QUERY_EXECUTION_LOG.
    """
    if not input_string or not input_string.strip():
        return FALLBACK_MESSAGE

    user_msg_id = (
        _log_message(conn, session_id, "User", input_string)
        if session_id is not None else None
    )

    intent_id = detect_intent(input_string)

    if intent_id is None:
        if session_id is not None and user_msg_id is not None:
            _log_intent(conn, user_msg_id, "FALLBACK", confidence=0.0)
            _log_message(conn, session_id, "Bot", FALLBACK_MESSAGE)
        return FALLBACK_MESSAGE

    intent_pk = (
        _log_intent(conn, user_msg_id, intent_id)
        if session_id is not None and user_msg_id is not None else None
    )

    try:
        if intent_id == "EXPLAIN_ALERT":
            target_hospital = extract_hospital_id(input_string) or hospital_id
            reply, payload = explain_alert(conn, target_hospital)
            if intent_pk is not None:
                tid = _template_id_for(conn, "EXPLAIN_ALERT_INVENTORY")
                if tid is not None:
                    _log_execution(conn, intent_pk, tid, payload, "OK", 1)
                _log_message(conn, session_id, "Bot", reply)
            return reply

        template_code, rows, params = run_intent_query(
            conn, intent_id, hospital_id, input_string
        )
        reply = format_response(intent_id, rows)

        if intent_pk is not None:
            tid = _template_id_for(conn, template_code)
            status = "OK" if rows else "Empty"
            if tid is not None:
                _log_execution(conn, intent_pk, tid, params, status, len(rows))
            _log_message(conn, session_id, "Bot", reply)
        return reply

    except sqlite3.Error as e:
        err = f"Database error: {e}"
        if intent_pk is not None:
            tid = _template_id_for(conn, intent_id) or 0
            if tid:
                _log_execution(conn, intent_pk, tid, {"error": str(e)}, "Error", 0)
            _log_message(conn, session_id, "Bot", err)
        return err


def handle_user_query(
    conn: sqlite3.Connection,
    user_input: str,
    hospital_id: int = DEFAULT_HOSPITAL_ID,
    session_id: Optional[int] = None,
) -> str:
    return process_user_query(conn, user_input, hospital_id, session_id)


# ==========================================================================
# Connection helpers
# ==========================================================================


def _connect_readonly(db_path: str = DB_PATH) -> sqlite3.Connection:
    """Read-only connection — used by formatters / answering questions."""
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def _connect_readwrite(db_path: str = DB_PATH) -> sqlite3.Connection:
    """Read-write connection — used by the chat-session logging.
    The chatbot only ever INSERTs into the CHAT_* / INTENT_DETECTION /
    QUERY_EXECUTION_LOG tables; never into the operational tables.
    """
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def main() -> None:
    conn = _connect_readwrite(DB_PATH)
    try:
        session_id = start_chat_session(conn, DEFAULT_HOSPITAL_ID, "Doctor")
        print(f"DonorBridge chatbot ready (session #{session_id}). "
              f"Type 'exit' to quit.")
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
            print("Bot:", process_user_query(
                conn, user_input, DEFAULT_HOSPITAL_ID, session_id
            ))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
