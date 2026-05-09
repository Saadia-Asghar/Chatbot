"""Flask REST API + static-file server for the DonorBridge chatbot.

Endpoints
---------
GET  /                  -> serves the SPA (static/index.html)
GET  /api/hospitals     -> list hospitals for the dropdown
POST /api/session       -> { hospital_id, user_role } -> { session_id }
POST /api/chat          -> { session_id, hospital_id, message } -> { reply, intent }
GET  /api/history/<sid> -> last messages of a chat session

Run with:
    pip install -r requirements.txt
    python init_db.py
    python api.py
Then open http://127.0.0.1:5000/
"""

from __future__ import annotations

import os
import sqlite3
from typing import Any, Dict

from flask import Flask, jsonify, request, send_from_directory

from chatbot_backend import (
    DB_PATH,
    DEFAULT_HOSPITAL_ID,
    detect_intent,
    process_user_query,
    start_chat_session,
    _connect_readwrite,
)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")


# --------------------------------------------------------------------------
# Per-request DB connection (sqlite3 connections are not thread-safe).
# --------------------------------------------------------------------------

def get_conn() -> sqlite3.Connection:
    if not os.path.exists(DB_PATH):
        raise RuntimeError(
            f"Database file '{DB_PATH}' not found. Run `python init_db.py` first."
        )
    return _connect_readwrite(DB_PATH)


def row_to_dict(cursor: sqlite3.Cursor, row) -> Dict[str, Any]:
    return {desc[0]: row[i] for i, desc in enumerate(cursor.description)}


# --------------------------------------------------------------------------
# Static frontend
# --------------------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


# --------------------------------------------------------------------------
# REST API
# --------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return jsonify({"status": "ok", "db": DB_PATH})


@app.get("/api/hospitals")
def list_hospitals():
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT hospital_id, name, location FROM HOSPITAL ORDER BY hospital_id"
        )
        return jsonify([row_to_dict(cur, r) for r in cur.fetchall()])
    finally:
        conn.close()


@app.post("/api/session")
def create_session():
    payload = request.get_json(silent=True) or {}
    hospital_id = int(payload.get("hospital_id", DEFAULT_HOSPITAL_ID))
    user_role = payload.get("user_role", "Doctor")

    if user_role not in {"Doctor", "Nurse", "Admin", "Coordinator"}:
        return jsonify({"error": "invalid user_role"}), 400

    conn = get_conn()
    try:
        sid = start_chat_session(conn, hospital_id, user_role)
        return jsonify({"session_id": sid, "hospital_id": hospital_id,
                        "user_role": user_role})
    finally:
        conn.close()


@app.post("/api/chat")
def chat():
    payload = request.get_json(silent=True) or {}
    message = (payload.get("message") or "").strip()
    if not message:
        return jsonify({"error": "message is required"}), 400

    hospital_id = int(payload.get("hospital_id", DEFAULT_HOSPITAL_ID))
    session_id = payload.get("session_id")

    conn = get_conn()
    try:
        if session_id is None:
            session_id = start_chat_session(conn, hospital_id, "Doctor")
        intent = detect_intent(message) or "FALLBACK"
        reply = process_user_query(conn, message, hospital_id, int(session_id))
        return jsonify({
            "session_id": int(session_id),
            "hospital_id": hospital_id,
            "intent": intent,
            "reply": reply,
        })
    finally:
        conn.close()


@app.get("/api/history/<int:session_id>")
def get_history(session_id: int):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT message_id, sender_type, message_text, created_at "
            "FROM CHAT_MESSAGE WHERE chat_session_id = ? "
            "ORDER BY message_id ASC",
            (session_id,),
        )
        return jsonify([row_to_dict(cur, r) for r in cur.fetchall()])
    finally:
        conn.close()


@app.get("/api/intents")
def list_intents():
    """Return the suggested example questions shown in the UI sidebar."""
    return jsonify([
        {"label": "Inventory of O- blood",     "text": "What is the inventory for O- blood?"},
        {"label": "Is there any O blood?",     "text": "Is there any O blood group available?"},
        {"label": "Any low stock?",            "text": "Is there any shortage or low stock?"},
        {"label": "High-risk patients",        "text": "Who are the high-risk patients?"},
        {"label": "List all patients",         "text": "List all patients."},
        {"label": "Next kidney transplant",    "text": "Who should get the next kidney transplant?"},
        {"label": "Eligible donors",           "text": "Show me the eligible donors."},
        {"label": "Recent donations",          "text": "Show me recent blood donations."},
        {"label": "Pending requests",          "text": "List the pending requests."},
        {"label": "Match candidates",          "text": "Show me the match candidates."},
        {"label": "Blood units expiring soon", "text": "Which blood units are expiring soon?"},
        {"label": "Transplant history",        "text": "Show me the transplant history."},
        {"label": "List hospitals",            "text": "List all hospitals."},
        {"label": "Why is Hospital 1 at risk?","text": "Why is Hospital 1 at risk?"},
    ])


if __name__ == "__main__":
    if not os.path.exists(DB_PATH):
        print(f"[!] {DB_PATH} not found. Run: python init_db.py")
    print("Starting DonorBridge chatbot on http://127.0.0.1:5000/")
    app.run(host="127.0.0.1", port=5000, debug=False)
