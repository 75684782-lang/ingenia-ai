import { getJSON, postJSON, streamSSE } from "./api.js";
import {
  $,
  $$,
  toast,
  addUserMessage,
  createAssistantMessage,
  createToolCard,
  updateToolCard,
  addConfirmationActions,
  addStoredToolMessage,
  addSystemNote,
  clearChat,
  showWelcome,
  renderHistory,
  renderTools,
  renderOperations,
  updateStatus,
  formatTime,
} from "./ui.js";

const state = {
  sessionId: null,
  model: null,
  defaultModel: null,
  tools: [],
  streaming: false,
  controller: null,
  welcomeMessage: "",
  account: null,
  accountsEnabled: false,
  agentsEnabled: false,
  pairCountdown: null,
};

function sessionKey() {
  return state.account ? `ingenia.session.${state.account.id}` : "ingenia.session";
}

function setTitle(title) {
  $("#chat-title").textContent = title || "Nueva conversación";
}

function setSubtitle(text) {
  $("#chat-subtitle").textContent = text;
}

function updateButtons() {
  $("#send-btn").disabled = state.streaming;
  $("#stop-btn").disabled = !state.streaming;
  $("#prompt").disabled = state.streaming;
}

function hideWelcome() {
  const welcome = document.querySelector(".welcome");
  if (welcome) welcome.remove();
}

function newContext() {
  return { assistant: null, toolQueues: {} };
}

function ensureAssistant(ctx) {
  if (!ctx.assistant) ctx.assistant = createAssistantMessage();
  return ctx.assistant;
}

function queueToolCard(ctx, tool, args) {
  const card = createToolCard(tool, args);
  (ctx.toolQueues[tool] ||= []).push(card);
  return card;
}

function takeToolCard(ctx, tool) {
  const queue = ctx.toolQueues[tool];
  if (queue && queue.length) return queue.shift();
  return createToolCard(tool, null);
}

async function refreshTools() {
  try {
    const data = await getJSON("/api/tools");
    state.tools = data.tools || [];
    renderTools(state.tools);
  } catch (err) {
    toast(err.message, true);
  }
}

async function refreshHistory() {
  try {
    const data = await getJSON("/api/sessions");
    renderHistory(data.sessions || [], state.sessionId, loadSession);
  } catch (err) {
    console.error(err);
  }
}

async function refreshOperations() {
  try {
    const data = await getJSON("/api/operations?limit=20");
    renderOperations(data.operations || []);
  } catch (err) {
    console.error(err);
  }
}

async function refreshStatus() {
  try {
    const [ollama, civil] = await Promise.all([
      getJSON("/api/ollama/status"),
      getJSON("/api/civil3d/status"),
    ]);
    updateStatus({
      ollama,
      civil3d: civil,
      remote: Boolean(state.account),
    });
  } catch (err) {
    console.error(err);
  }
}

async function refreshAgents() {
  if (!state.agentsEnabled) return;
  const list = $("#agent-list");
  try {
    const data = await getJSON("/api/agents");
    list.replaceChildren();
    if (!data.agents.length) {
      const empty = document.createElement("p");
      empty.className = "empty-hint";
      empty.textContent = "Aún no hay PCs vinculadas.";
      list.appendChild(empty);
      return;
    }
    for (const agent of data.agents) {
      const row = document.createElement("div");
      row.className = "agent-item";
      const label = document.createElement("span");
      label.textContent = agent.name;
      const status = document.createElement("em");
      status.textContent = agent.online ? "conectada" : "desconectada";
      const revoke = document.createElement("button");
      revoke.className = "btn btn-ghost";
      revoke.type = "button";
      revoke.textContent = "Desvincular";
      revoke.addEventListener("click", async () => {
        if (!confirm(`¿Desvincular ${agent.name}?`)) return;
        try {
          await fetch(`/api/agents/${encodeURIComponent(agent.id)}`, {
            method: "DELETE",
            credentials: "same-origin",
          }).then(async (response) => {
            if (!response.ok) throw await parseResponseError(response);
          });
          await refreshAgents();
          await refreshStatus();
        } catch (err) {
          toast(err.message, true);
        }
      });
      row.append(label, status, revoke);
      list.appendChild(row);
    }
  } catch (err) {
    list.textContent = err.message;
  }
}

async function createPairCode() {
  const button = $("#pair-btn");
  button.disabled = true;
  try {
    const data = await postJSON("/api/agents/pair-code", {});
    $("#pair-code").textContent = data.code;
    $("#pair-code-box").hidden = false;
    const expiry = Date.now() + data.expires_in * 1000;
    clearInterval(state.pairCountdown);
    const update = () => {
      const remaining = Math.max(0, Math.ceil((expiry - Date.now()) / 1000));
      $("#pair-expiry").textContent = remaining
        ? `Código válido durante ${Math.floor(remaining / 60)}:${String(remaining % 60).padStart(2, "0")}.`
        : "Código vencido. Genera uno nuevo.";
      if (!remaining) clearInterval(state.pairCountdown);
    };
    update();
    state.pairCountdown = setInterval(update, 1000);
    try {
      await navigator.clipboard?.writeText(data.code);
      toast("Código generado y copiado.");
    } catch {
      toast("Código generado. Cópialo para ingresarlo en el conector.");
    }
    await refreshAgents();
  } catch (err) {
    toast(err.message, true);
  } finally {
    button.disabled = false;
  }
}

async function parseResponseError(response) {
  let message = `${response.status} ${response.statusText}`;
  try {
    const body = await response.json();
    if (body.detail) message = body.detail;
  } catch {
    // Keep the HTTP status when the response has no JSON body.
  }
  return new Error(message);
}

async function loadModels() {
  const select = $("#model-select");
  try {
    const data = await getJSON("/api/ollama/models");
    const models = data.models || [];
    select.innerHTML = "";
    if (!models.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "Sin modelos instalados";
      select.appendChild(option);
      $("#model-hint").textContent =
        "No se detectaron modelos. Ejecuta: ollama pull qwen2.5-coder:1.5b";
      return;
    }
    for (const model of models) {
      const option = document.createElement("option");
      option.value = model.name;
      const traits = [];
      if (model.supports_tools) traits.push("tools");
      if (model.parameter_size) traits.push(model.parameter_size);
      option.textContent = traits.length ? `${model.name} · ${traits.join(" · ")}` : model.name;
      select.appendChild(option);
    }
    const remembered = localStorage.getItem("ingenia.model");
    const toolModels = models.filter((m) => m.supports_tools).map((m) => m.name);
    state.model =
      [remembered, state.defaultModel, ...toolModels, models[0].name].find(
        (name) => name && models.some((m) => m.name === name)
      ) || models[0].name;
    select.value = state.model;
    updateModelBadge();
    const supportsTools = models.some((m) => m.name === state.model && m.supports_tools);
    $("#model-hint").textContent = supportsTools
      ? "El modelo seleccionado admite llamadas a herramientas."
      : "Este modelo no declara soporte de herramientas; las operaciones de Civil 3D pueden no ser invocadas.";
  } catch (err) {
    select.innerHTML = '<option value="">Ollama no disponible</option>';
    $("#model-hint").textContent = err.message;
  }
}

function updateModelBadge() {
  $("#model-badge").textContent = `Modelo: ${state.model || "—"}`;
}

async function pullModel() {
  const input = $("#pull-model");
  const button = $("#pull-btn");
  const status = $("#pull-status");
  const fill = $("#pull-bar-fill");
  const name = input.value.trim();
  if (!name) {
    toast("Escribe el nombre del modelo, por ejemplo qwen2.5-coder:1.5b", true);
    return;
  }
  button.disabled = true;
  fill.style.width = "0%";
  status.textContent = `Iniciando descarga de ${name}…`;
  try {
    await streamSSE(
      "/api/ollama/pull",
      { model: name },
      (event) => {
        if (event.type === "progress") {
          const percent = event.percent;
          status.textContent =
            percent != null
              ? `${event.status || "descargando"} · ${percent}%`
              : event.status || "descargando…";
          if (percent != null) fill.style.width = `${Math.min(percent, 100)}%`;
        } else if (event.type === "done") {
          status.textContent = `Modelo listo: ${name}`;
          fill.style.width = "100%";
          toast(`Modelo descargado: ${name}`);
          loadModels();
        } else if (event.type === "error") {
          status.textContent = event.message;
          toast(event.message, true);
        }
      }
    );
  } catch (err) {
    status.textContent = err.message;
    toast(err.message, true);
  } finally {
    button.disabled = false;
  }
}

function handleEvent(event, ctx) {
  switch (event.type) {
    case "session": {
      if (event.session_id) {
        state.sessionId = event.session_id;
        localStorage.setItem("ingenia.session", state.sessionId);
      }
      break;
    }
    case "token": {
      ensureAssistant(ctx).append(event.text || "");
      break;
    }
    case "tool_start": {
      queueToolCard(ctx, event.tool, event.args);
      break;
    }
    case "tool_result": {
      const card = takeToolCard(ctx, event.tool);
      updateToolCard(card, event.result || {});
      if (event.result && event.result.requires_confirmation) {
        addConfirmationActions(card, event.result.operation_id, {
          onApprove: (opId, actions) => resolveOperation(opId, true, actions),
          onReject: (opId, actions) => resolveOperation(opId, false, actions),
        });
      }
      break;
    }
    case "confirmation_required": {
      toast("Operación pendiente de confirmación.");
      break;
    }
    case "assistant_message": {
      const text = (event.content || "").trim();
      if (text) {
        ensureAssistant(ctx).set(event.content);
        if (state.sessionId) {
          setTitle(text.split("\n")[0].slice(0, 80));
        }
      } else if (ctx.assistant && !ctx.assistant.text.trim()) {
        ctx.assistant.remove();
        ctx.assistant = null;
      }
      break;
    }
    case "error": {
      ensureAssistant(ctx).remove();
      ctx.assistant = null;
      addSystemNote(event.message || "Error desconocido.", true);
      break;
    }
    case "stopped": {
      addSystemNote(event.message || "Generación detenida.");
      break;
    }
    case "done": {
      break;
    }
    default:
      console.debug("Evento no manejado", event);
  }
}

async function runStream(path, body, ctx) {
  state.streaming = true;
  state.controller = new AbortController();
  updateButtons();
  try {
    await streamSSE(path, body, (event) => handleEvent(event, ctx), state.controller.signal);
  } catch (err) {
    if (err.name !== "AbortError") {
      addSystemNote(err.message, true);
      toast(err.message, true);
    }
  } finally {
    state.streaming = false;
    state.controller = null;
    updateButtons();
    refreshHistory();
    refreshOperations();
    refreshStatus();
  }
}

async function sendMessage(text) {
  if (state.streaming) return;
  const message = (text ?? $("#prompt").value).trim();
  if (!message) return;
  hideWelcome();
  addUserMessage(message);
  $("#prompt").value = "";
  autoSize();
  if (!state.sessionId) {
    setTitle(message.slice(0, 60));
    setSubtitle("Conversación local · Ollama");
  }
  const ctx = newContext();
  ctx.assistant = createAssistantMessage();
  await runStream(
    "/api/chat",
    { message, session_id: state.sessionId, model: state.model },
    ctx
  );
}

async function resolveOperation(operationId, approve, actionsEl) {
  if (actionsEl) {
    $$("button", actionsEl).forEach((button) => (button.disabled = true));
  }
  hideWelcome();
  const ctx = newContext();
  await runStream(
    "/api/chat/confirm",
    { operation_id: operationId, approve, model: state.model },
    ctx
  );
}

async function stopGeneration() {
  if (!state.streaming) return;
  try {
    if (state.sessionId) {
      await postJSON(`/api/chat/stop?session_id=${encodeURIComponent(state.sessionId)}`, {});
    }
  } catch (err) {
    console.error(err);
  }
  if (state.controller) state.controller.abort();
  toast("Generación detenida.");
}

async function newChat() {
  state.sessionId = null;
  localStorage.removeItem(sessionKey());
  clearChat();
  showWelcome(state.welcomeMessage);
  setTitle("Nueva conversación");
  setSubtitle("Conversa en español y opera Civil 3D mediante herramientas verificadas.");
  await refreshHistory();
}

async function loadSession(session) {
  try {
    const data = await getJSON(`/api/sessions/${encodeURIComponent(session.id)}/messages`);
    clearChat();
    state.sessionId = session.id;
    localStorage.setItem(sessionKey(), session.id);
    setTitle(session.title || "Conversación");
    setSubtitle(`Actualizada ${formatTime(session.updated_at)}`);
    for (const message of data.messages || []) {
      if (message.role === "user") addUserMessage(message.content);
      else if (message.role === "assistant") createAssistantMessage().set(message.content);
      else if (message.role === "tool" && message.tool_name)
        addStoredToolMessage(message.tool_name, message.content);
    }
    await refreshHistory();
  } catch (err) {
    toast(err.message, true);
  }
}

function autoSize() {
  const textarea = $("#prompt");
  textarea.style.height = "auto";
  textarea.style.height = `${Math.min(textarea.scrollHeight, 180)}px`;
}

function connectStatusSocket() {
  try {
    const protocol = location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${protocol}://${location.host}/ws/status`);
    socket.addEventListener("message", (event) => {
      try {
        updateStatus({
          ...JSON.parse(event.data),
          remote: Boolean(state.account),
        });
      } catch (err) {
        console.error(err);
      }
    });
    socket.addEventListener("close", () => setTimeout(connectStatusSocket, 8000));
  } catch (err) {
    console.error(err);
  }
}

function bindEvents() {
  $("#send-btn").addEventListener("click", () => sendMessage());
  $("#stop-btn").addEventListener("click", stopGeneration);
  $("#new-chat").addEventListener("click", newChat);
  $("#refresh-history").addEventListener("click", refreshHistory);
  $("#refresh-ops").addEventListener("click", refreshOperations);
  $("#pull-btn").addEventListener("click", pullModel);
  $("#pair-btn").addEventListener("click", createPairCode);
  $("#pull-model").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      pullModel();
    }
  });
  $("#model-select").addEventListener("change", (event) => {
    state.model = event.target.value;
    localStorage.setItem("ingenia.model", state.model);
    updateModelBadge();
  });

  const textarea = $("#prompt");
  textarea.addEventListener("input", autoSize);
  textarea.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendMessage();
    }
  });

  document.addEventListener("click", (event) => {
    const suggestion = event.target.closest(".suggestion");
    if (suggestion) {
      sendMessage(suggestion.textContent);
    }
  });

  $("#toggle-sidebar").addEventListener("click", () => {
    document.querySelector(".app-shell").classList.toggle("sidebar-open");
  });
  $("#toggle-panel").addEventListener("click", () => {
    document.querySelector(".app-shell").classList.toggle("panel-open");
  });

  $$(".nav-item").forEach((item) => {
    item.addEventListener("click", () => {
      const target = item.dataset.focus;
      if (!target) return;
      const shells = document.querySelector(".app-shell");
      shells.classList.add("panel-open");
      const card = document.querySelector(`#card-${target}`);
      if (card) card.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });
}

function setAuthMode(mode) {
  const register = mode === "register";
  $("#auth-name-field").hidden = !register;
  $("#auth-name").required = register;
  $("#auth-password").autocomplete = register ? "new-password" : "current-password";
  $("#auth-submit").textContent = register ? "Crear cuenta" : "Iniciar sesión";
  $("#auth-login-tab").classList.toggle("btn-ghost", register);
  $("#auth-register-tab").classList.toggle("btn-ghost", !register);
  $("#auth-login-tab").setAttribute("aria-selected", String(!register));
  $("#auth-register-tab").setAttribute("aria-selected", String(register));
  $("#auth-error").textContent = "";
  $("#auth-form").dataset.mode = mode;
}

function bindAuthEvents() {
  setAuthMode("login");
  $("#auth-login-tab").addEventListener("click", () => setAuthMode("login"));
  $("#auth-register-tab").addEventListener("click", () => setAuthMode("register"));
  $("#auth-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const mode = event.currentTarget.dataset.mode || "login";
    const submit = $("#auth-submit");
    submit.disabled = true;
    $("#auth-error").textContent = "";
    const payload = {
      email: $("#auth-email").value.trim(),
      password: $("#auth-password").value,
    };
    if (mode === "register") payload.name = $("#auth-name").value.trim();
    try {
      await postJSON(`/api/auth/${mode}`, payload);
      location.reload();
    } catch (err) {
      $("#auth-error").textContent = err.message;
    } finally {
      submit.disabled = false;
    }
  });
  $("#logout-btn").addEventListener("click", async () => {
    try {
      await postJSON("/api/auth/logout", {});
      location.reload();
    } catch (err) {
      toast(err.message, true);
    }
  });
}

async function prepareAccount() {
  bindAuthEvents();
  const mode = await getJSON("/api/auth/mode");
  state.accountsEnabled = Boolean(mode.accounts);
  if (!state.accountsEnabled) return true;
  if (!mode.user) {
    $("#app-shell").hidden = true;
    $("#auth-screen").hidden = false;
    return false;
  }
  state.account = mode.user;
  $("#account-controls").hidden = false;
  $("#account-name").textContent = mode.user.name || mode.user.email;
  return true;
}

const GUIDE_SEEN_KEY = "ingenia.guide.seen.v1";
const GUIDE_SESSION_KEY = "ingenia.guide.session.v1";

function isLocalApp() {
  return ["localhost", "127.0.0.1", "::1", "[::1]"].includes(location.hostname);
}

function openGuide() {
  const modal = $("#guide-modal");
  if (!modal) return;
  modal.hidden = false;
  document.body.classList.add("modal-open");
  $("#guide-close").focus();
}

function closeGuide() {
  const modal = $("#guide-modal");
  if (!modal) return;
  modal.hidden = true;
  document.body.classList.remove("modal-open");
  sessionStorage.setItem(GUIDE_SESSION_KEY, "1");
  if ($("#guide-hide").checked) localStorage.setItem(GUIDE_SEEN_KEY, "1");
}

function initGuide() {
  const demo = !isLocalApp();
  if (demo) {
    const note = $("#guide-demo-note");
    note.hidden = false;
    const pill = $("#demo-pill");
    if (pill) {
      pill.hidden = false;
      if (state.accountsEnabled) pill.textContent = "Conectar PC";
    }
    if (state.accountsEnabled) {
      note.textContent =
        "La web está alojada; tu Ollama y Civil 3D permanecen en tu PC. Vincula el conector desde el panel Mi PC.";
      $("#guide-title").textContent = "Conecta tu PC con Ingenia AI";
      setSubtitle("Conecta tu PC para usar Ollama y Civil 3D desde esta web.");
      const localInstall = document.querySelector(".guide-steps li:nth-child(3)");
      localInstall.querySelector("strong").textContent = "Vincula tu PC con la web";
      localInstall.querySelector("p").textContent =
        "Inicia sesión, abre Mi PC en el panel derecho, genera un código y ejecútalo en el conector local. El conector mantiene una conexión cifrada saliente.";
    } else {
      setSubtitle("Demo alojada · Conecta el conector local desde Mi PC para trabajar con tus programas.");
    }
  }
  $("#guide-hide").checked = Boolean(localStorage.getItem(GUIDE_SEEN_KEY));

  $("#open-guide").addEventListener("click", openGuide);
  $("#open-guide-nav").addEventListener("click", openGuide);
  const demoPill = $("#demo-pill");
  if (demoPill) demoPill.addEventListener("click", openGuide);
  $("#guide-close").addEventListener("click", closeGuide);
  $("#guide-skip").addEventListener("click", closeGuide);
  $("#guide-start").addEventListener("click", closeGuide);
  $("#guide-modal").addEventListener("click", (event) => {
    if (event.target.id === "guide-modal") closeGuide();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !$("#guide-modal").hidden) closeGuide();
  });
  $("#guide-hide").addEventListener("change", (event) => {
    if (event.target.checked) localStorage.setItem(GUIDE_SEEN_KEY, "1");
    else localStorage.removeItem(GUIDE_SEEN_KEY);
  });

  const seen = localStorage.getItem(GUIDE_SEEN_KEY);
  const seenThisSession = sessionStorage.getItem(GUIDE_SESSION_KEY);
  if (!seen && !seenThisSession) {
    setTimeout(openGuide, 350);
  }
}

async function init() {
  try {
    if (!(await prepareAccount())) return;
  } catch (err) {
    $("#app-shell").hidden = true;
    $("#auth-screen").hidden = false;
    $("#auth-error").textContent = err.message;
    return;
  }
  bindEvents();
  initGuide();
  updateButtons();
  autoSize();

  try {
    const config = await getJSON("/api/config");
    state.defaultModel = config.default_model;
    state.agentsEnabled = Boolean(config.agents_enabled && state.account);
    $("#card-connect").hidden = !state.agentsEnabled;
    $("#cfg-api").textContent = location.origin;
    $("#cfg-location").textContent = state.account ? "web" : "local";
    $("#cfg-model").textContent = config.default_model || "—";
    $("#cfg-fallback").textContent = config.civil3d_fallback_to_mock ? "activado" : "desactivado";
  } catch (err) {
    console.error(err);
  }

  await Promise.all([
    loadModels(),
    refreshTools(),
    refreshStatus(),
    refreshHistory(),
    refreshOperations(),
    refreshAgents(),
  ]);
  connectStatusSocket();
  if (state.agentsEnabled) setInterval(refreshAgents, 10000);

  if (!isLocalApp() && !state.accountsEnabled) {
    const note = $("#welcome-note");
    if (note) {
      note.textContent = "Demo alojada: descarga e instala la app para conectar tu Ollama y Civil 3D.";
    }
  }

  const saved = localStorage.getItem(sessionKey());
  if (saved) {
    try {
      const data = await getJSON(`/api/sessions/${encodeURIComponent(saved)}/messages`);
      if (data.session) await loadSession(data.session);
    } catch {
      localStorage.removeItem(sessionKey());
    }
  }
}

init();
