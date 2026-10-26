const jsonHeaders = { "Content-Type": "application/json" };

async function parseError(res) {
  let detail = `${res.status} ${res.statusText}`;
  try {
    const body = await res.json();
    if (body && body.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
  } catch {
    /* ignore */
  }
  return new Error(detail);
}

export async function getJSON(path) {
  const res = await fetch(path, { credentials: "same-origin" });
  if (!res.ok) throw await parseError(res);
  return res.json();
}

export async function postJSON(path, body) {
  const res = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers: jsonHeaders,
    body: JSON.stringify(body ?? {}),
  });
  if (!res.ok) throw await parseError(res);
  return res.json();
}

export async function streamSSE(path, body, onEvent, signal) {
  const res = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers: jsonHeaders,
    body: JSON.stringify(body ?? {}),
    signal,
  });
  if (!res.ok) throw await parseError(res);
  if (!res.body) throw new Error("El navegador no soporta streaming.");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let index;
    while ((index = buffer.indexOf("\n\n")) >= 0) {
      const raw = buffer.slice(0, index);
      buffer = buffer.slice(index + 2);
      for (const line of raw.split("\n")) {
        if (!line.startsWith("data:")) continue;
        const payload = line.slice(5).trim();
        if (!payload) continue;
        try {
          onEvent(JSON.parse(payload));
        } catch (err) {
          console.error("Evento SSE inválido", payload, err);
        }
      }
    }
  }
}
