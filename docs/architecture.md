# Arquitectura

```
┌──────────────────────────┐
│ Navegador (frontend)     │
│ HTML/CSS/JS, SSE, WS     │
└─────────────┬────────────┘
              │ http://127.0.0.1:8000 (token local)
┌─────────────▼──────────────────────────────────────────────┐
│ Backend FastAPI                                            │
│  ├─ ChatService: bucle de tool-calling, confirmaciones      │
│  ├─ OllamaClient: /api/tags, /api/chat (stream, tools)      │
│  ├─ ToolRegistry: 11 herramientas + esquemas Pydantic       │
│  ├─ ToolExecutor: validación, riesgo, idempotencia, auditoría│
│  ├─ OperationStore: SQLite (sesiones, mensajes, operaciones)│
│  └─ Civil3DClient: HTTP local con token                     │
└─────────────┬──────────────────────────────────────────────┘
              │ http://127.0.0.1:8756 (token compartido)
┌─────────────▼──────────────────────────────────────────────┐
│ Plugin C# en Civil 3D                                       │
│  ├─ HttpBridge: servidor TCP/HTTP mínimo, solo loopback     │
│  ├─ MainThreadDispatcher: cola + Application.Idle          │
│  └─ ToolHandlers: API oficial de AutoCAD/Civil 3D          │
│      (LockDocument + Transaction, commit/abort)             │
└────────────────────────────────────────────────────────────┘
```

## Flujo de una orden

1. El frontend envía `POST /api/chat` y lee eventos SSE.
2. `ChatService` construye el contexto (historial + prompt de sistema) y llama a Ollama
   con el esquema de herramientas.
3. Ollama puede responder texto o solicitar una herramienta.
4. `ToolExecutor` valida los argumentos con Pydantic y consulta el nivel de riesgo.
5. Si la herramienta es de escritura y no hay confirmación, se registra una operación
   `pending_confirmation` y se devuelve `confirmation_required`. **No se toca el dibujo.**
6. El usuario confirma (`POST /api/chat/confirm`). El ejecutor incrementa el estado a
   `running` y llama al conector.
7. `Civil3DClient` envía `POST /rpc` al puente, que encola el trabajo en el hilo principal
   de AutoCAD, dentro de un bloqueo de documento y una transacción.
8. El resultado real (`ok`, `mode`, `data` o `error`) se devuelve al backend, se guarda y se
   entrega al modelo para que redacte la respuesta.
9. El modelo nunca recibe datos inventados: si `ok=false` o `mode=mock`, la instrucción de
   sistema le obliga a decir que la operación no se ejecutó.

## Riesgo y confirmación

- `read`: se ejecuta sin confirmación (consultas).
- `write`: crea una operación pendiente; el usuario debe aprobar.
- `experimental`: se marca en la UI y en el resultado; no se declara verificada.
- Toda operación queda registrada con identificador único, argumentos, estado y resultado.

## Idempotencia

La clave se calcula con `sha256(session_id + tool + args)` o la proporciona el cliente. Una
operación ya completada con la misma clave devuelve el mismo resultado sin volver a llamar
al plugin. Las confirmaciones repetidas sobre una operación ya resuelta devuelven su estado,
no la reejecutan.

## Persistencia

SQLite (`backend/data/ingenia.db`):

- `sessions`: conversaciones.
- `messages`: historial visible (usuario, asistente, trazas de herramientas).
- `operations`: auditoría, estado, idempotencia y contexto pendiente para confirmaciones.

## Seguridad

- Bind exclusivo a `127.0.0.1` en backend y plugin.
- Token compartido backend ↔ plugin; el plugin rechaza todo si no hay token configurado.
- Guard de red: solo hosts loopback y token válido.
- Rate limit en memoria.
- No se ejecuta código generado por el modelo; solo herramientas registradas.
- El plugin nunca abre puertos fuera de loopback.

## Fallback simulado

Si el plugin no responde y `CIVIL3D_FALLBACK_TO_MOCK=true`, `Civil3DClient` delega en
`MockConnector`, que devuelve siempre `ok=false`, `mode="mock"` y un mensaje explícito. Esto
permite probar la UI sin Civil 3D sin riesgo de confundir simulación con operación real.

## Extensibilidad

El registro de herramientas y el conector están desacoplados. Para soportar otro programa de
ingeniería se implementa un conector que exponga el mismo contrato (`status`, `call`) y se
registran nuevas herramientas en `backend/app/tools/definitions.py` y `registry.py`.
