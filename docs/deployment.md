# Despliegue y hosting

## Regla de oro

**La web coordina; la IA y Civil 3D permanecen en el equipo de cada usuario.**

El usuario abre la web, inicia sesión y empareja un conector local. Este inicia una conexión
saliente cifrada a la web y retransmite únicamente métodos permitidos a Ollama y al puente de
Civil 3D en `127.0.0.1`. El backend no se conecta directamente al PC ni recibe archivos DWG.
Los prompts, el historial y los metadatos/resultados de herramientas sí pasan por el backend y
se almacenan en su base de datos; informa esta política y define su retención antes de aceptar
datos sensibles.

El backend ya contiene el flujo de cuentas, emparejamiento y enrutamiento del agente. La
instancia desplegada en Render **continúa en modo demo** hasta activar las cuentas y configurar
almacenamiento persistente; su SQLite actual está en `/tmp`.

## Límites de red y datos

| Recurso | Dónde vive | Un servidor remoto puede alcanzarlo |
| --- | --- | --- |
| Ollama (`127.0.0.1:11434`) | PC del usuario | Solo a través del conector autenticado |
| Puente Civil 3D (`127.0.0.1:8756`) | PC del usuario, dentro de AutoCAD | Solo a través del conector autenticado |
| Archivos `.dwg` y licencia Civil 3D | PC del usuario | No |

## Arquitectura web con conector local

```
Usuario
  ├─ Navegador -> https://ingenia-ai.onrender.com (web y API)
  ├─ Conector local -> WSS saliente autenticado y emparejado por cuenta
  ├─ Ollama local (modelos descargados por el usuario)
  └─ Civil 3D + plugin C# (127.0.0.1:8756)

Render
  ├─ API, cuentas, sesiones y coordinación
  └─ Sin conexiones entrantes al PC ni acceso directo a sus programas
```

El emparejamiento usa un código temporal de un solo uso. El servidor almacena el hash de la
credencial permanente del conector; el conector guarda la credencial en el perfil local de
Windows. Cada cuenta solo puede enviar órdenes al dispositivo que esa misma cuenta emparejó.
Los métodos se limitan a las operaciones listadas por el backend y el conector; no se permiten
comandos ni código arbitrario.

## Dónde alojar cada pieza

| Pieza | Opción recomendada | Alternativas | Coste |
| --- | --- | --- | --- |
| Landing estática | Cloudflare Pages | Netlify, Vercel, GitHub Pages | Gratis |
| Instalador / releases | GitHub Releases | Cloudflare R2 + dominio, S3 | Gratis o centavos |
| Documentación | GitHub Pages o el mismo hosting estático | MkDocs en Cloudflare Pages | Gratis |
| Backend y WebSocket | Render con almacenamiento persistente | VPS, Fly.io, Railway | Según proveedor |
| Base de datos de cuentas y dispositivos | PostgreSQL gestionado o almacenamiento persistente | SQLite en disco persistente para una sola instancia | Según proveedor |
| Ollama | **Siempre en el PC del usuario** | Servidor con GPU solo si se asume el coste | — |

No uses planes gratuitos tipo Render/Railway para Ollama: se duermen, tienen poca RAM y no
sirven para inferencia estable.

## Preparar la instancia web para cuentas

No habilites cuentas en Render mientras `DATABASE_PATH` apunte a `/tmp`: ese directorio es
efímero y perder una sesión o una credencial de dispositivo dejaría al usuario sin acceso. El
servicio también debe mantener una instancia única o usar infraestructura compartida para
WebSockets y límites de solicitudes.

Cuando el almacenamiento persistente esté listo, configura:

```text
INGENIA_ALLOW_REMOTE=true
INGENIA_COOKIE_SECURE=true
INGENIA_ACCOUNTS=true
INGENIA_USE_AGENTS=true
DATABASE_PATH=<ruta persistente>
```

El backend actual soporta SQLite; una base externa como PostgreSQL requiere adaptar la capa de
persistencia antes de usarla. Usa HTTPS, conserva secretos fuera del repositorio y configura
un respaldo de la base de datos.

## Demo actual en Render

El repositorio incluye `render.yaml` y `Dockerfile`. La demo sirve para validar UI, API, historial,
seguridad y mensajes de error. Las cuentas y el emparejamiento no están activados en esta
instancia; **no conectes dispositivos ni uses dibujos reales**.

1. Sube el proyecto a GitHub.
2. En Render: **New → Blueprint** → elige el repositorio. Detecta `render.yaml`.
3. Espera el despliegue y abre la URL `https://<servicio>.onrender.com`.
4. La cookie de acceso se instala al abrir `/`. Comparte la URL solo con quienes vayan a probar.
5. Revisa los logs del servicio si algo falla.

Comportamiento esperado en la demo:

- El panel **Modelos** mostrará que Ollama no está disponible y no listará modelos.
- El chat responderá con un error claro de conexión con Ollama; no inventará respuestas.
- `Civil 3D` aparecerá como `connected=false` y `mode=mock`; las operaciones nunca fingirán éxito.
- La base SQLite vive en `/tmp` y se pierde al reiniciar el servicio (plan gratuito).

Para probar el chat web con Ollama local, habilita el modo de cuentas solo después de configurar
persistencia y ejecuta el [conector local](../connectors/desktop/README.md). No uses túneles
para publicar Ollama o Civil 3D.

### Docker en cualquier proveedor

```bat
docker build -t ingenia-ai .
docker run -p 8000:8000 ^
  -e INGENIA_ALLOW_REMOTE=true ^
  -e INGENIA_AUTH_TOKEN=un-token-largo ^
  -e INGENIA_COOKIE_SECURE=false ^
  ingenia-ai
```

Con HTTPS cambia `INGENIA_COOKIE_SECURE=true`. No publiques los puertos `8756` ni `11434`.

### Qué reportar tras probar la demo

- Pantalla o endpoint donde falla y hora aproximada.
- Texto exacto del error y navegador usado.
- Si el problema es visual, captura; si es de API, la respuesta de `/api/health` y `/api/ollama/status`.

## Lista de verificación antes de publicar

- [ ] La landing no incluye claves, tokens ni el `.env`.
- [ ] `backend/.env` y la base de datos persistente están fuera del repositorio.
- [ ] El instalador se publica con hash SHA-256 y, si es posible, firma de código.
- [ ] Los puertos `8000`, `8756` y `11434` no se abren al exterior.
- [ ] El token local se genera por instalación (no reutilizar `ingenia-local-dev`).
- [ ] Cuentas y dispositivos usan almacenamiento persistente y sesiones por usuario.
- [ ] Se documenta que el modelo se descarga y ejecuta en el equipo del usuario.
