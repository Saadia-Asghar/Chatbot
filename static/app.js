/* DonorBridge chatbot frontend */
(() => {
  const API = {
    hospitals: "/api/hospitals",
    session:   "/api/session",
    chat:      "/api/chat",
    intents:   "/api/intents",
    health:    "/api/health",
  };

  const el = {
    hospitalSelect: document.getElementById("hospital-select"),
    roleSelect:     document.getElementById("role-select"),
    newSessionBtn:  document.getElementById("new-session-btn"),
    sessionMeta:    document.getElementById("session-meta"),
    suggestions:    document.getElementById("suggestions"),
    messages:       document.getElementById("messages"),
    emptyState:     document.getElementById("empty-state"),
    composer:       document.getElementById("composer"),
    composerInput:  document.getElementById("composer-input"),
    sendBtn:        document.getElementById("send-btn"),
    statusPill:     document.getElementById("status-pill"),
  };

  const state = {
    hospitalId: null,
    role: "Doctor",
    sessionId: null,
    busy: false,
  };

  // ---------------- networking ----------------
  async function jsonFetch(url, options = {}) {
    const res = await fetch(url, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    if (!res.ok) {
      const err = await res.text().catch(() => res.statusText);
      throw new Error(`${res.status} ${err}`);
    }
    return res.json();
  }

  // ---------------- bootstrap ----------------
  async function bootstrap() {
    try {
      await jsonFetch(API.health);
      setStatus("online", "Online");
    } catch {
      setStatus("offline", "API offline");
    }

    try {
      const [hospitals, intents] = await Promise.all([
        jsonFetch(API.hospitals),
        jsonFetch(API.intents),
      ]);
      populateHospitals(hospitals);
      populateSuggestions(intents);
      await ensureSession();
    } catch (e) {
      console.error(e);
      setStatus("offline", "Failed to load");
    }
  }

  function setStatus(cls, text) {
    el.statusPill.classList.remove("online", "offline");
    if (cls) el.statusPill.classList.add(cls);
    el.statusPill.textContent = text;
  }

  function populateHospitals(rows) {
    el.hospitalSelect.innerHTML = "";
    rows.forEach((h) => {
      const opt = document.createElement("option");
      opt.value = h.hospital_id;
      opt.textContent = `${h.name} — ${h.location}`;
      el.hospitalSelect.appendChild(opt);
    });
    if (rows.length > 0) state.hospitalId = Number(rows[0].hospital_id);
  }

  function populateSuggestions(items) {
    el.suggestions.innerHTML = "";
    items.forEach((s) => {
      const li = document.createElement("li");
      const btn = document.createElement("button");
      btn.className = "suggestion-btn";
      btn.textContent = s.label;
      btn.title = s.text;
      btn.addEventListener("click", () => {
        el.composerInput.value = s.text;
        el.composerInput.focus();
      });
      li.appendChild(btn);
      el.suggestions.appendChild(li);
    });
  }

  async function ensureSession() {
    const data = await jsonFetch(API.session, {
      method: "POST",
      body: JSON.stringify({
        hospital_id: state.hospitalId,
        user_role: state.role,
      }),
    });
    state.sessionId = data.session_id;
    el.sessionMeta.textContent =
      `Session #${data.session_id} · ${data.user_role} · Hospital ${data.hospital_id}`;
  }

  // ---------------- rendering ----------------
  function hideEmptyState() {
    if (el.emptyState && el.emptyState.parentElement === el.messages) {
      el.messages.removeChild(el.emptyState);
    }
  }

  function escapeHtml(text) {
    return text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function appendBubble({ sender, text, intent }) {
    hideEmptyState();
    const row = document.createElement("div");
    row.className = `bubble-row ${sender}`;

    const avatar = document.createElement("div");
    avatar.className = `avatar ${sender}`;
    avatar.textContent = sender === "user" ? "You" : "DB";

    const bubble = document.createElement("div");
    bubble.className = `bubble ${sender}`;

    const intentTag = (sender === "bot" && intent && intent !== "FALLBACK")
      ? `<span class="intent-tag">${escapeHtml(intent)}</span>` : "";

    const time = new Date().toLocaleTimeString([], {
      hour: "2-digit", minute: "2-digit",
    });

    bubble.innerHTML =
      `${intentTag}${escapeHtml(text)}<span class="meta">${time}</span>`;

    row.appendChild(avatar);
    row.appendChild(bubble);
    el.messages.appendChild(row);
    el.messages.scrollTop = el.messages.scrollHeight;
    return bubble;
  }

  function appendTyping() {
    hideEmptyState();
    const row = document.createElement("div");
    row.className = "bubble-row bot";
    row.dataset.typing = "1";

    const avatar = document.createElement("div");
    avatar.className = "avatar bot";
    avatar.textContent = "DB";

    const bubble = document.createElement("div");
    bubble.className = "bubble bot";
    bubble.innerHTML = `<span class="typing"><span></span><span></span><span></span></span>`;

    row.appendChild(avatar);
    row.appendChild(bubble);
    el.messages.appendChild(row);
    el.messages.scrollTop = el.messages.scrollHeight;
    return row;
  }

  function clearMessages() {
    el.messages.innerHTML = "";
    el.messages.appendChild(el.emptyState);
  }

  // ---------------- events ----------------
  el.composer.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const text = el.composerInput.value.trim();
    if (!text || state.busy) return;

    state.busy = true;
    el.sendBtn.disabled = true;
    appendBubble({ sender: "user", text });
    el.composerInput.value = "";

    const typingRow = appendTyping();

    try {
      const data = await jsonFetch(API.chat, {
        method: "POST",
        body: JSON.stringify({
          hospital_id: state.hospitalId,
          session_id: state.sessionId,
          message: text,
        }),
      });
      typingRow.remove();
      appendBubble({ sender: "bot", text: data.reply, intent: data.intent });
    } catch (e) {
      typingRow.remove();
      appendBubble({
        sender: "bot",
        text: "Sorry, the server returned an error. Please try again.",
      });
      console.error(e);
    } finally {
      state.busy = false;
      el.sendBtn.disabled = false;
      el.composerInput.focus();
    }
  });

  el.hospitalSelect.addEventListener("change", async (ev) => {
    state.hospitalId = Number(ev.target.value);
    clearMessages();
    await ensureSession();
  });

  el.roleSelect.addEventListener("change", async (ev) => {
    state.role = ev.target.value;
    clearMessages();
    await ensureSession();
  });

  el.newSessionBtn.addEventListener("click", async () => {
    clearMessages();
    await ensureSession();
  });

  bootstrap();
})();
