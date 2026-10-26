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
instancia de Render usa cuentas, conectores locales y SQLite en un disco persistente. El servicio
está configurado para una sola instancia porque el disco no se comparte entre instancias.

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

## Producción en Render

`render.yaml` configura el servicio con plan Starter, un disco persistente de 1 GB en `/var/data`
y estas opciones:

```text
INGENIA_ALLOW_REMOTE=true
INGENIA_COOKIE_SECURE=true
INGENIA_ACCOUNTS=true
INGENIA_USE_AGENTS=true
DATABASE_PATH=/var/data/ingenia.db
CIVIL3D_FALLBACK_TO_MOCK=false
```

El servicio de pago y el disco pueden generar cargos mensuales; confirma el precio vigente en
Render. El disco no permite escalar a varias instancias y desactiva los despliegues sin
interrupción. Render crea snapshots diarios del disco y conserva los disponibles durante siete
días; no sustituyen una política propia de respaldos. La base se crea vacía en `/var/data`; no se
migran sesiones temporales que hubiera en `/tmp`.

El registro público está abierto. Cada usuario crea su cuenta, vincula su propio conector y puede
revocarlo desde la web. No se suben dibujos DWG, pero prompts, historial y resultados de
herramientas se guardan en la SQLite persistente. No uses datos sensibles hasta definir y publicar
una política de privacidad y retención apropiada.

### Preparar una PC de usuario

1. Abre la URL de Render y crea una cuenta.
2. Sigue la guía de [instalación y conexión del conector local](../connectors/desktop/README.md).
3. Instala Ollama y descarga el modelo indicado. El modelo corre en la PC, no en Render.
4. Para operar Civil 3D, compila e instala el complemento siguiendo la
   [guía de integración](./civil3d-integration.md); usa un dibujo de prueba y verifica el token.
5. Abre **Mi PC**, genera un código temporal e ingrésalo en el conector.
6. Comprueba que el estado del conector y Ollama aparece conectado antes de enviar una orden.

Si el proyecto ya está enlazado a Render como Blueprint, sincroniza el Blueprint después de
publicar cambios en `render.yaml` y acepta el cambio al plan pagado y la creación del disco. Antes
de probar, confirma en el Dashboard que el disco está montado y que `DATABASE_PATH` apunta a
`/var/data/ingenia.db`. Si no hay almacenamiento persistente, no habilites cuentas.

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

### Qué reportar si falla la conexión

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
- [ ] Antes de usar datos reales, publicar política de privacidad, retención y eliminación de cuentas.
