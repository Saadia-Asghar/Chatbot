"""Streamlit chat UI for the Healthcare Resource Optimization chatbot.

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
    _connect_readonly,
)


st.set_page_config(page_title="Healthcare Resource Chatbot", page_icon="🏥")


@st.cache_resource
def get_connection() -> sqlite3.Connection:
    if not os.path.exists(DB_PATH):
        st.error(
            f"Database file '{DB_PATH}' not found. Run `python init_db.py` first."
        )
        st.stop()
    return _connect_readonly(DB_PATH)


def get_hospitals(conn: sqlite3.Connection):
    cur = conn.cursor()
    cur.execute("SELECT HospitalID, Name FROM HospitalsTable ORDER BY HospitalID")
    return cur.fetchall()


st.title("🏥 Healthcare Resource Chatbot")
st.caption(
    "Rule-based SQL chatbot. Ask about blood inventory, high-risk patients, "
    "or transplant priority."
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

    st.markdown("**Try asking:**")
    st.markdown(
        "- What is the inventory for O- blood?\n"
        "- Is there any shortage or low stock?\n"
        "- Who are the high-risk patients with surgery scheduled?\n"
        "- Who should get the next kidney transplant?\n"
        "- Show me eligible donors.\n"
        "- Why is Hospital 1 at risk?"
    )

    if st.button("Clear chat"):
        st.session_state.messages = []
        st.rerun()

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

prompt = st.chat_input("Ask a question...")
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    reply = process_user_query(
        conn, prompt, hospital_id or DEFAULT_HOSPITAL_ID
    )
    st.session_state.messages.append({"role": "assistant", "content": reply})
    with st.chat_message("assistant"):
        st.markdown(reply)
