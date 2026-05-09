"""End-to-end smoke test for the DonorBridge chatbot.

Runs one example for every intent and prints the bot reply.
Verifies that chat-session logging is also working.
"""

from __future__ import annotations

from chatbot_backend import (
    DB_PATH,
    process_user_query,
    start_chat_session,
    _connect_readwrite,
)

CASES = [
    ("CHECK_INVENTORY (specific)",  1, "What is the inventory for O- blood?"),
    ("CHECK_INVENTORY (family O)",  1, "Is there O blood group?"),
    ("CHECK_INVENTORY (family AB)", 1, "Do you have any AB blood?"),
    ("CHECK_INVENTORY (informal)",  1, "any A blood available?"),
    ("CHECK_INVENTORY (all)",       1, "Is there any low stock?"),
    ("CHECK_INVENTORY (missing)",   1, "What is the inventory for B- blood?"),
    ("GET_HIGH_RISK_PATIENTS",      1, "Who are the high-risk patients?"),
    ("LIST_PATIENTS",               1, "List all patients."),
    ("GET_TRANSPLANT_PRIORITY",     1, "Who should get the next kidney transplant?"),
    ("GET_DONORS",                  1, "Show me the eligible donors."),
    ("GET_DONORS (who can donate)", 1, "Who can donate blood?"),
    ("GET_DONATIONS",               1, "Show me recent blood donations."),
    ("GET_PENDING_REQUESTS",        1, "List the pending requests."),
    ("GET_MATCH_CANDIDATES",        1, "Show me the match candidates."),
    ("GET_EXPIRING_UNITS",          1, "Which blood units are expiring soon?"),
    ("GET_TRANSPLANT_HISTORY",      1, "Show me the transplant history."),
    ("LIST_HOSPITALS",              1, "List all hospitals."),
    ("EXPLAIN_ALERT (at risk)",     1, "Why is Hospital 1 at risk?"),
    ("EXPLAIN_ALERT (safe)",        2, "Why is Hospital 2 at risk?"),
    ("FALLBACK",                    1, "Tell me a joke."),
]


def main() -> None:
    conn = _connect_readwrite(DB_PATH)
    try:
        sid = start_chat_session(conn, hospital_id=1, user_role="Doctor")
        print(f"[session #{sid}]\n")
        for label, hospital, q in CASES:
            print(f"--- {label} (hospital={hospital}) ---")
            print(f"You : {q}")
            print(f"Bot : {process_user_query(conn, q, hospital, sid)}\n")

        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM CHAT_MESSAGE WHERE chat_session_id = ?",
            (sid,),
        )
        (n_msgs,) = cur.fetchone()
        cur.execute(
            "SELECT COUNT(*) FROM INTENT_DETECTION id "
            "JOIN CHAT_MESSAGE m ON m.message_id = id.message_id "
            "WHERE m.chat_session_id = ?",
            (sid,),
        )
        (n_intents,) = cur.fetchone()
        cur.execute(
            "SELECT COUNT(*) FROM QUERY_EXECUTION_LOG q "
            "JOIN INTENT_DETECTION id ON id.intent_id = q.intent_id "
            "JOIN CHAT_MESSAGE m ON m.message_id = id.message_id "
            "WHERE m.chat_session_id = ?",
            (sid,),
        )
        (n_exec,) = cur.fetchone()
        print(
            f"[audit] CHAT_MESSAGE rows={n_msgs}, "
            f"INTENT_DETECTION rows={n_intents}, "
            f"QUERY_EXECUTION_LOG rows={n_exec}"
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
