from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import logging
import os
import random
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, WebSocketException

LOG = logging.getLogger("ingenia.connector")
OLLAMA_URL = "http://127.0.0.1:11434"
CIVIL3D_URL = "http://127.0.0.1:8756"
ALLOWED_TOOLS = {
    "get_civil3d_status",
    "get_active_drawing_info",
    "list_drawing_objects",
    "inspect_surface",
    "list_alignments",
    "create_surface",
    "generate_contours",
    "create_alignment_from_polyline",
    "generate_profile",
    "calculate_volumes",
}


class ConnectorError(RuntimeError):
    pass


def _config_path() -> Path:
    root = os.environ.get("LOCALAPPDATA")
    if root:
        return Path(root) / "IngeniaAI" / "connector.json"
    return Path.home() / ".ingenia-ai" / "connector.json"


def _load_config(path: Path) -> dict[str, Any]:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError) as exc:
        raise ConnectorError(f"No se pudo leer la configuración local: {exc}") from exc
    if not isinstance(config, dict):
        raise ConnectorError("La configuración local debe ser un objeto JSON.")
    return config


def _save_config(path: Path, config: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def _websocket_url(base_url: str) -> str:
    parsed = urlsplit(base_url.strip())
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ConnectorError("La URL no debe incluir credenciales, query ni fragmento.")
    host = (parsed.hostname or "").lower()
    local_hosts = {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme == "https":
        scheme = "wss"
    elif parsed.scheme == "http" and host in local_hosts:
        scheme = "ws"
    else:
        raise ConnectorError(
            "Usa una URL HTTPS para el servicio remoto; HTTP solo se permite en localhost."
        )
    return urlunsplit((scheme, parsed.netloc, "/ws/agent", "", ""))


async def _ollama_request(
    client: httpx.AsyncClient, method: str, params: dict[str, Any]
) -> Any:
    if method == "ollama.status":
        try:
            response = await client.get(f"{OLLAMA_URL}/api/tags", timeout=3)
            return {"available": response.is_success}
        except httpx.HTTPError:
            return {"available": False}
    if method == "ollama.models":
        response = await client.get(f"{OLLAMA_URL}/api/tags", timeout=15)
        response.raise_for_status()
        return response.json()
    raise ConnectorError("Método de Ollama no permitido.")


async def _civil3d_request(
    method: str, params: dict[str, Any], bridge_token: str
) -> Any:
    headers = {"X-Ingenia-Token": bridge_token} if bridge_token else {}
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(90, connect=3), follow_redirects=False
    ) as client:
        if method == "civil3d.status":
            response = await client.get(f"{CIVIL3D_URL}/status", headers=headers)
        elif method == "civil3d.call":
            tool = params.get("tool")
            if tool not in ALLOWED_TOOLS:
                raise ConnectorError("Herramienta de Civil 3D no permitida.")
            args = params.get("args")
            if not isinstance(args, dict):
                raise ConnectorError("Los argumentos de la herramienta no son válidos.")
            response = await client.post(
                f"{CIVIL3D_URL}/rpc",
                headers=headers,
                json={
                    "tool": tool,
                    "args": args,
                    "request_id": params.get("request_id"),
                },
            )
        else:
            raise ConnectorError("Método de Civil 3D no permitido.")
        response.raise_for_status()
        return response.json()


async def _dispatch(
    websocket,
    send_lock: asyncio.Lock,
    request: dict[str, Any],
    ollama: httpx.AsyncClient,
    bridge_token: str,
) -> None:
    request_id = request.get("id")
    method = request.get("method")
    params = request.get("params") or {}
    if not isinstance(request_id, str) or not isinstance(params, dict):
        raise ConnectorError("Solicitud remota mal formada.")

    async def send(payload: dict[str, Any]) -> None:
        async with send_lock:
            await websocket.send(json.dumps(payload, ensure_ascii=False))

    try:
        if method in {"ollama.chat", "ollama.pull"}:
            endpoint = "/api/chat" if method == "ollama.chat" else "/api/pull"
            payload = (
                {
                    "model": params.get("model"),
                    "messages": params.get("messages"),
                    "tools": params.get("tools"),
                    "stream": True,
                    "options": {"temperature": params.get("temperature", 0.2)},
                }
                if method == "ollama.chat"
                else {"model": params.get("model"), "stream": True}
            )
            async with ollama.stream(
                "POST", f"{OLLAMA_URL}{endpoint}", json=payload
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise ConnectorError("Ollama devolvió una respuesta inválida.") from exc
                    if chunk.get("error"):
                        raise ConnectorError(str(chunk["error"]))
                    await send({"type": "chunk", "id": request_id, "data": chunk})
            await send({"type": "end", "id": request_id})
            return
        if method in {"ollama.status", "ollama.models"}:
            result = await _ollama_request(ollama, method, params)
        elif method in {"civil3d.status", "civil3d.call"}:
            result = await _civil3d_request(method, params, bridge_token)
        else:
            raise ConnectorError("Método remoto no permitido.")
        await send({"type": "response", "id": request_id, "ok": True, "result": result})
    except (ConnectorError, httpx.HTTPError) as exc:
        await send(
            {"type": "response", "id": request_id, "ok": False, "error": str(exc)}
        )
    except ConnectionClosed:
        return


async def _ping(websocket, send_lock: asyncio.Lock) -> None:
    while True:
        await asyncio.sleep(20)
        async with send_lock:
            await websocket.send(json.dumps({"type": "ping"}))


async def _run_once(
    url: str,
    code: str | None,
    device_token: str | None,
    name: str,
    bridge_token: str,
    save_token,
) -> str:
    async with connect(
        url,
        ping_interval=20,
        ping_timeout=20,
        close_timeout=5,
        max_size=8 * 1024 * 1024,
    ) as websocket:
        if device_token:
            await websocket.send(
                json.dumps({"type": "authenticate", "token": device_token})
            )
        else:
            if not code:
                raise ConnectorError("Falta el código temporal para vincular esta PC.")
            await websocket.send(
                json.dumps({"type": "pair", "code": code, "name": name})
            )
        try:
            handshake = json.loads(await asyncio.wait_for(websocket.recv(), timeout=15))
        except (asyncio.TimeoutError, json.JSONDecodeError) as exc:
            raise ConnectorError("El servidor no completó el emparejamiento.") from exc
        except ConnectionClosed as exc:
            if exc.code == 1008 and device_token:
                raise ConnectorError(
                    "El servidor rechazó la credencial del conector. "
                    "Revócala en la web y vuelve a ejecutar con --reset."
                ) from exc
            raise
        if handshake.get("type") == "error":
            raise ConnectorError(handshake.get("error") or "No se pudo vincular la PC.")
        if device_token:
            if handshake.get("type") != "authenticated":
                raise ConnectorError("El servidor rechazó la credencial de este conector.")
        else:
            if handshake.get("type") != "paired" or not handshake.get("token"):
                raise ConnectorError("El servidor devolvió una respuesta de emparejamiento inválida.")
            device_token = handshake["token"]
            save_token(device_token)
            LOG.info("PC vinculada; credencial guardada en el perfil local de Windows.")

        LOG.info("Conector conectado. Mantén abierta esta ventana.")
        send_lock = asyncio.Lock()
        ping_task = asyncio.create_task(_ping(websocket, send_lock))
        tasks: set[asyncio.Task] = set()
        ollama = httpx.AsyncClient(
            timeout=httpx.Timeout(None, connect=5), follow_redirects=False
        )
        try:
            async for raw in websocket:
                try:
                    request = json.loads(raw)
                except json.JSONDecodeError:
                    LOG.warning("Se ignoró un mensaje inválido del servidor.")
                    continue
                if not isinstance(request, dict) or request.get("type") != "request":
                    continue
                task = asyncio.create_task(
                    _dispatch(
                        websocket, send_lock, request, ollama, bridge_token
                    )
                )
                tasks.add(task)
                task.add_done_callback(tasks.discard)
        finally:
            ping_task.cancel()
            for task in tasks:
                task.cancel()
            await asyncio.gather(ping_task, *tasks, return_exceptions=True)
            await ollama.aclose()
        return device_token


async def _run(args: argparse.Namespace) -> None:
    websocket_url = _websocket_url(args.url)
    config_path = _config_path()
    config = _load_config(config_path)
    if args.reset:
        config.pop("token", None)
    device_token = config.get("token")
    if device_token and not isinstance(device_token, str):
        raise ConnectorError("La credencial guardada no es válida.")
    if not device_token:
        code = getpass.getpass("Código temporal mostrado en la web: ").strip()
    else:
        code = None
    bridge_token = os.environ.get("INGENIA_CIVIL3D_TOKEN", "")

    def save_token(token: str) -> None:
        config["token"] = token
        config["server"] = args.url.rstrip("/")
        _save_config(config_path, config)

    delay = 1
    while True:
        try:
            if config.get("server") and config["server"] != args.url.rstrip("/"):
                raise ConnectorError(
                    "La credencial guardada pertenece a otro servidor. Usa --reset para volver a emparejar."
                )
            device_token = await _run_once(
                websocket_url,
                code,
                device_token,
                args.name,
                bridge_token,
                save_token,
            )
            code = None
            delay = 1
        except (WebSocketException, OSError, httpx.HTTPError) as exc:
            LOG.warning("Conexión interrumpida: %s", exc)
        except ConnectorError:
            raise
        LOG.info("Reintentando en %s segundos.", delay)
        await asyncio.sleep(delay + random.random())
        delay = min(delay * 2, 30)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Conector local de Ingenia AI para Ollama y Civil 3D."
    )
    parser.add_argument(
        "--url", required=True, help="URL HTTPS de la aplicación Ingenia AI."
    )
    parser.add_argument("--name", default=os.environ.get("COMPUTERNAME", "Mi PC"))
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Olvida la credencial guardada y solicita un nuevo código de emparejamiento.",
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    try:
        asyncio.run(_run(args))
    except (ConnectorError, KeyboardInterrupt) as exc:
        if isinstance(exc, KeyboardInterrupt):
            LOG.info("Conector detenido.")
            return
        LOG.error("%s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
