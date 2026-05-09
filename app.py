"""Streamlit chat UI for the DonorBridge chatbot (secondary frontend).

Run with:
    streamlit run app.py
"""

from __future__ import annotations

import os
import sqlite3

import streamlit as st

from chatbot_backend import (
    DB_PATH,
    DEFAULT_HOSPITAL_ID,
    process_user_query,
    start_chat_session,
    _connect_readwrite,
)


st.set_page_config(page_title="DonorBridge Chatbot", page_icon="🩸")


@st.cache_resource
def get_connection() -> sqlite3.Connection:
    if not os.path.exists(DB_PATH):
        st.error(
            f"Database file '{DB_PATH}' not found. Run `python init_db.py` first."
        )
        st.stop()
    return _connect_readwrite(DB_PATH)


def get_hospitals(conn: sqlite3.Connection):
    cur = conn.cursor()
    cur.execute("SELECT hospital_id, name FROM HOSPITAL ORDER BY hospital_id")
    return cur.fetchall()


st.title("🩸 DonorBridge Chatbot")
st.caption(
    "Rule-based SQL chatbot. Ask about blood inventory, donors, "
    "high-risk patients, requests, matches, or transplant priority."
)

conn = get_connection()

with st.sidebar:
    st.header("Settings")
    hospitals = get_hospitals(conn)
    hospital_id = st.selectbox(
        "Hospital",
        options=[h[0] for h in hospitals],
        format_func=lambda hid: next(name for i, name in hospitals if i == hid),
        index=0 if hospitals else None,
    )
    user_role = st.selectbox(
        "Role", ["Doctor", "Nurse", "Coordinator", "Admin"], index=0
    )

    st.markdown("**Try asking:**")
    st.markdown(
        "- What is the inventory for O- blood?\n"
        "- Is there any shortage or low stock?\n"
        "- Who are the high-risk patients?\n"
        "- Who should get the next kidney transplant?\n"
        "- Show me eligible donors.\n"
        "- List the pending requests.\n"
        "- Show me the match candidates.\n"
        "- Which blood units are expiring soon?\n"
        "- Show me the transplant history.\n"
        "- Why is Hospital 1 at risk?"
    )

    if st.button("New chat session"):
        st.session_state.pop("messages", None)
        st.session_state.pop("session_id", None)
        st.rerun()

if "session_id" not in st.session_state:
    st.session_state.session_id = start_chat_session(
        conn, hospital_id or DEFAULT_HOSPITAL_ID, user_role
    )

if "messages" not in st.session_state:
    st.session_state.messages = []

st.caption(f"Session #{st.session_state.session_id} · {user_role}")

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

prompt = st.chat_input("Ask a question…")
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    reply = process_user_query(
        conn,
        prompt,
        hospital_id or DEFAULT_HOSPITAL_ID,
        st.session_state.session_id,
    )
    st.session_state.messages.append({"role": "assistant", "content": reply})
    with st.chat_message("assistant"):
        st.markdown(reply)
