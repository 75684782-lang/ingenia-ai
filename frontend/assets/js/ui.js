export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

let toastTimer = null;
export function toast(message, isError = false) {
  const box = $("#toast");
  if (!box) return;
  box.textContent = message;
  box.classList.toggle("error", isError);
  box.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => box.classList.remove("show"), 3800);
}

export function formatTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("es", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function clearChat() {
  const chat = $("#chat");
  chat.innerHTML = "";
}

export function showWelcome(message) {
  const chat = $("#chat");
  chat.innerHTML = "";
  const wrap = el("div", "welcome");
  wrap.innerHTML = `
    <div class="welcome-mark">IA</div>
    <h2>Asistente de ingeniería local</h2>
    <p>Consulto el dibujo abierto y ejecuto operaciones reales en Civil 3D. Todo el procesamiento de IA ocurre en tu equipo mediante Ollama.</p>
    <div class="suggestions">
      <button class="suggestion">Analiza el dibujo abierto y dime qué objetos contiene</button>
      <button class="suggestion">Enumera las superficies y sus datos</button>
      <button class="suggestion">Lista los alineamientos existentes</button>
      <button class="suggestion">Crea una superficie llamada Terreno Natural</button>
    </div>
    <p class="welcome-note"></p>`;
  wrap.querySelector(".welcome-note").textContent = message || "";
  chat.appendChild(wrap);
}

export function addUserMessage(text) {
  const chat = $("#chat");
  const msg = el("div", "msg user");
  msg.innerHTML = `
    <div class="msg-avatar">TÚ</div>
    <div class="msg-body">
      <div class="msg-role">Usuario</div>
      <div class="msg-text"></div>
    </div>`;
  msg.querySelector(".msg-text").textContent = text;
  chat.appendChild(msg);
  scrollChat();
  return msg;
}

export function createAssistantMessage() {
  const chat = $("#chat");
  const msg = el("div", "msg assistant");
  msg.innerHTML = `
    <div class="msg-avatar">IA</div>
    <div class="msg-body">
      <div class="msg-role">Ingenia AI</div>
      <div class="msg-text"><span class="thinking"><i></i><i></i><i></i></span></div>
    </div>`;
  chat.appendChild(msg);
  scrollChat();
  const textEl = msg.querySelector(".msg-text");
  let started = false;
  return {
    element: msg,
    append(text) {
      if (!started) {
        textEl.textContent = "";
        started = true;
      }
      textEl.textContent += text;
      scrollChat();
    },
    set(text) {
      started = true;
      textEl.textContent = text;
      scrollChat();
    },
    get text() {
      return textEl.textContent;
    },
    remove() {
      msg.remove();
    },
  };
}

export function createToolCard(tool, args) {
  const chat = $("#chat");
  const card = el("div", "tool-card");
  card.dataset.tool = tool;
  const head = el("div", "tool-head");
  head.appendChild(el("span", "tool-name", tool));
  const badge = el("span", "badge", "ejecutando");
  head.appendChild(badge);
  const meta = el("span", "tool-meta", "");
  head.appendChild(meta);
  card.appendChild(head);

  const detail = el("div", "tool-detail");
  card.appendChild(detail);
  if (args && Object.keys(args).length) {
    const pre = el("pre", "", JSON.stringify(args, null, 2));
    detail.appendChild(pre);
  }
  chat.appendChild(card);
  scrollChat();
  return { element: card, badge, meta, detail };
}

function summarize(result) {
  if (!result) return "";
  if (result.requires_confirmation) return result.message || "Pendiente de confirmación.";
  if (result.error) return result.error;
  if (result.message) return result.message;
  const inner = result.result;
  if (inner && inner.error) return inner.error;
  if (inner && inner.message) return inner.message;
  return "";
}

export function updateToolCard(card, result) {
  const status = result.status || (result.ok ? "completed" : "failed");
  const mode = result.mode || (result.result && result.result.mode) || "";
  card.badge.className = "badge";
  if (result.requires_confirmation || status === "pending_confirmation") {
    card.badge.classList.add("pending");
    card.badge.textContent = "confirmar";
    card.element.classList.add("pending");
  } else if (result.ok) {
    card.badge.classList.add("ok");
    card.badge.textContent = mode === "real" ? "real" : "ok";
    card.element.classList.add("ok");
  } else {
    card.badge.classList.add("bad");
    card.badge.textContent = mode === "mock" ? "simulado" : "error";
    card.element.classList.add("bad");
  }
  if (result.experimental) {
    const exp = el("span", "badge exp", "experimental");
    card.element.querySelector(".tool-head").appendChild(exp);
  }
  if (result.operation_id) {
    card.meta.textContent = `op ${result.operation_id.slice(0, 8)}`;
  }
  card.detail.innerHTML = "";
  const summary = summarize(result);
  if (summary) card.detail.appendChild(el("div", "", summary));

  const payload = result.result && typeof result.result === "object" ? result.result : result;
  if (payload && (payload.data || payload.operation || payload.errors)) {
    card.detail.appendChild(el("pre", "", JSON.stringify(payload.data ?? payload.operation ?? payload.errors, null, 2)));
  }
  scrollChat();
  return card;
}

export function addConfirmationActions(card, operationId, handlers) {
  const actions = el("div", "tool-actions");
  const approve = el("button", "btn btn-approve", "Confirmar y ejecutar");
  const reject = el("button", "btn btn-reject", "Cancelar");
  approve.addEventListener("click", () => handlers.onApprove(operationId, actions));
  reject.addEventListener("click", () => handlers.onReject(operationId, actions));
  actions.appendChild(approve);
  actions.appendChild(reject);
  card.element.appendChild(actions);
  scrollChat();
}

export function addStoredToolMessage(toolName, content) {
  const card = createToolCard(toolName, null);
  try {
    const parsed = JSON.parse(content);
    card.badge.className = "badge";
    card.badge.textContent = parsed.ok ? "ok" : parsed.status || "registrado";
    card.element.classList.add(parsed.ok ? "ok" : "bad");
    if (parsed.operation_id) card.meta.textContent = `op ${parsed.operation_id.slice(0, 8)}`;
    const summary = parsed.error || parsed.message || "";
    if (summary) card.detail.appendChild(document.createTextNode(summary));
  } catch {
    card.detail.textContent = content;
  }
  return card;
}

export function addSystemNote(text, isError = false) {
  const chat = $("#chat");
  const card = el("div", `tool-card ${isError ? "bad" : ""}`);
  const head = el("div", "tool-head");
  head.appendChild(el("span", "tool-name", isError ? "error" : "sistema"));
  head.appendChild(el("span", `badge ${isError ? "bad" : ""}`, isError ? "fallo" : "aviso"));
  card.appendChild(head);
  card.appendChild(el("div", "tool-detail", text));
  chat.appendChild(card);
  scrollChat();
  return card;
}

export function scrollChat() {
  const box = $("#chat-scroll");
  if (!box) return;
  requestAnimationFrame(() => {
    box.scrollTop = box.scrollHeight;
  });
}

export function renderHistory(sessions, activeId, onSelect) {
  const list = $("#history-list");
  list.innerHTML = "";
  if (!sessions.length) {
    list.appendChild(el("p", "empty-hint", "Aún no hay conversaciones."));
    return;
  }
  for (const session of sessions) {
    const item = el("button", "history-item");
    if (session.id === activeId) item.classList.add("active");
    item.appendChild(el("strong", "", session.title || "Conversación"));
    item.appendChild(el("small", "", formatTime(session.updated_at)));
    item.addEventListener("click", () => onSelect(session));
    list.appendChild(item);
  }
}

export function renderTools(tools) {
  const list = $("#tool-list");
  list.innerHTML = "";
  $("#tools-count").textContent = String(tools.length);
  for (const tool of tools) {
    const row = el("div", "tool-item");
    row.title = tool.description;
    row.appendChild(el("span", "t-name", tool.name));
    if (tool.experimental) row.appendChild(el("span", "badge exp", "exp"));
    const risk = el("span", `t-risk ${tool.risk}`, tool.risk === "write" ? "escritura" : "lectura");
    row.appendChild(risk);
    list.appendChild(row);
  }
}

export function renderOperations(operations) {
  const list = $("#op-list");
  list.innerHTML = "";
  if (!operations.length) {
    list.appendChild(el("p", "empty-hint", "Sin operaciones registradas."));
    return;
  }
  for (const op of operations) {
    const row = el("div", "op-item");
    row.appendChild(el("div", "op-tool", op.tool));
    const meta = el("div", "op-meta");
    meta.appendChild(el("b", op.status, op.status));
    meta.appendChild(el("span", "", formatTime(op.created_at)));
    row.appendChild(meta);
    row.title = op.error || op.id;
    list.appendChild(row);
  }
}

function setDot(selector, stateClass, labelEl, labelText) {
  const dot = $(selector);
  if (dot) {
    dot.classList.remove("ok", "bad", "warn");
    if (stateClass) dot.classList.add(stateClass);
  }
  if (labelEl && labelText !== undefined) labelEl.textContent = labelText;
}

export function updateStatus(payload) {
  const ollamaOk = Boolean(payload.ollama && payload.ollama.available);
  const civil = payload.civil3d || {};
  const civilConnected = Boolean(civil.connected) && civil.mode !== "mock";

  setDot("#dot-ollama", ollamaOk ? "ok" : "bad", $("#ollama-label"), ollamaOk ? "activo" : "sin conexión");
  setDot("#p-dot-ollama", ollamaOk ? "ok" : "bad");
  setDot("#dot-civil", civilConnected ? "ok" : civil.mode === "mock" ? "warn" : "bad", $("#civil-label"), civilConnected ? "conectado" : "no conectado");
  setDot("#p-dot-civil", civilConnected ? "ok" : civil.mode === "mock" ? "warn" : "bad");

  const pillOllama = $("#pill-ollama");
  pillOllama.className = `pill ${ollamaOk ? "ok" : "bad"}`;
  const pillCivil = $("#pill-civil");
  pillCivil.className = `pill ${civilConnected ? "ok" : "warn"}`;

  $("#p-ollama").textContent = ollamaOk ? "Disponible en 127.0.0.1:11434" : "No disponible";
  const civilText = civilConnected
    ? "Complemento conectado"
    : civil.mode === "mock"
      ? "Conector simulado · sin operaciones reales"
      : (civil.message || "Sin conexión");
  $("#p-civil").textContent = civilText;

  const drawing = civil.drawing || civil.active_drawing || null;
  const drawingName = typeof drawing === "string" ? drawing : drawing && (drawing.name || drawing.file);
  $("#p-drawing").textContent = drawingName || (civil.connected ? "Sin dibujo activo" : "—");
  $("#p-mode").textContent = civil.mode || "—";

  const note = $("#welcome-note");
  if (note) {
    note.textContent = ollamaOk
      ? civilConnected
        ? "Ollama y Civil 3D disponibles."
        : "Ollama disponible. Civil 3D no está conectado: las operaciones no se ejecutarán."
      : "Ollama no responde. Inicia el servicio local para conversar.";
  }
}

export { el };
