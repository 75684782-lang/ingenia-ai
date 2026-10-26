# Arquitectura

```
Navegador
   │ HTTPS + cookie de sesión por usuario
   ▼
FastAPI en Render ───── SQLite persistente (cuentas, sesiones, auditoría)
   ▲                         │
   │ WSS saliente            │ órdenes solo para el usuario autenticado
   │ autenticado             ▼
Conector local en Windows ─ Ollama (127.0.0.1:11434)
   │                       Civil 3D Bridge (127.0.0.1:8756)
   └──────────────────────► Plugin C# cargado en Civil 3D
                             Application.Idle + LockDocument + Transaction
```

En modo local, el navegador sigue conectándose directamente al backend local y este usa
`OllamaClient` y `Civil3DClient`. En modo web, `RemoteOllamaClient` y
`AgentCivil3DConnector` envían solicitudes por la conexión WebSocket del conector emparejado.

## Flujo de una orden

1. El navegador envía `POST /api/chat` con su cookie de sesión y lee eventos SSE.
2. El backend determina el usuario y construye el contexto de su propia sesión.
3. `RemoteOllamaClient` retransmite la solicitud al conector asociado a ese usuario; el
   conector consulta Ollama en loopback y devuelve los fragmentos de respuesta.
4. Ollama puede responder texto o solicitar una herramienta.
5. `ToolExecutor` valida los argumentos con Pydantic y consulta el nivel de riesgo.
6. Si la herramienta es de escritura y no hay confirmación, se registra una operación
   `pending_confirmation` y se devuelve `confirmation_required`. **No se toca el dibujo.**
7. El usuario confirma (`POST /api/chat/confirm`). El ejecutor incrementa el estado a
   `running` y llama al conector.
8. El conector local llama al puente en loopback. Este encola el trabajo en el hilo principal
   de AutoCAD, dentro de un bloqueo de documento y una transacción.
9. El resultado real (`ok`, `mode`, `data` o `error`) vuelve por WSS, se guarda y se entrega
   al modelo para que redacte la respuesta.
10. El modelo nunca recibe datos inventados: si `ok=false` o `mode=mock`, la instrucción de
   sistema le obliga a decir que la operación no se ejecutó.

## Riesgo y confirmación

- `read`: se ejecuta sin confirmación (consultas).
- `write`: crea una operación pendiente; el usuario debe aprobar.
- `experimental`: se marca en la UI y en el resultado; no se declara verificada.
- Toda operación queda registrada con identificador único, argumentos, estado y resultado.

## Idempotencia

La clave se calcula incluyendo usuario, sesión, herramienta y argumentos; las claves
proporcionadas por el cliente también se aíslan por usuario. Una operación ya completada con
la misma clave devuelve el mismo resultado sin volver a llamar al plugin. Las confirmaciones
repetidas sobre una operación ya resuelta devuelven su estado, no la reejecutan.

## Persistencia

SQLite (`backend/data/ingenia.db`):

- `users`, `auth_sessions`, `agents`, `pair_codes`: cuentas, sesiones, dispositivos y códigos
  de un solo uso.
- `sessions`: conversaciones.
- `messages`: historial visible (usuario, asistente, trazas de herramientas). En el modo web,
  los prompts y resultados pasan por el servidor y quedan almacenados en esta base.
- `operations`: auditoría, estado, idempotencia y contexto pendiente para confirmaciones.

## Seguridad

- El plugin y Ollama solo escuchan en loopback; nunca se publican sus puertos.
- El conector inicia WSS; Render no inicia conexiones al PC.
- El emparejamiento usa un código temporal de un solo uso y credenciales del conector guardadas
  como hashes en el servidor.
- Las API, sesiones, operaciones y confirmaciones se restringen al usuario autenticado.
- Los métodos del agente se limitan a Ollama y a las herramientas registradas; no ejecuta
  comandos ni código arbitrario.
- Hay límites de frecuencia en memoria; en despliegues multiinstancia deben compartirse.
- No se ejecuta código generado por el modelo; solo herramientas registradas.
- El plugin nunca abre puertos fuera de loopback.

## Fallback simulado

En modo local, si el plugin no responde y `CIVIL3D_FALLBACK_TO_MOCK=true`, `Civil3DClient`
delega en `MockConnector`, que devuelve siempre `ok=false`, `mode="mock"` y un mensaje
explícito. En modo web, si no hay conector emparejado, la operación devuelve fallo y no se
invoca ningún recurso local.

## Extensibilidad

El registro de herramientas y el conector están desacoplados. Para soportar otro programa de
ingeniería se implementa un conector que exponga el mismo contrato (`status`, `call`) y se
registran nuevas herramientas en `backend/app/tools/definitions.py` y `registry.py`.
