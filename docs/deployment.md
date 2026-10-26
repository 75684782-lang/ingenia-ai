# Despliegue y hosting

## Regla de oro

**La IA y el control de Civil 3D viven en el equipo del usuario; el hosting solo distribuye.**

Ingenia AI no incluye ni aloja ningún modelo. Cada usuario instala Ollama, descarga el modelo
que prefiera y lo usa desde la aplicación local. Publicar la app en un servidor no permite que
ese servidor use el Ollama ni el Civil 3D de otra persona.

## Por qué el backend no puede ir al hosting

| Recurso | Dónde vive | Un servidor remoto puede alcanzarlo |
| --- | --- | --- |
| Ollama (`127.0.0.1:11434`) | PC del usuario | No |
| Puente Civil 3D (`127.0.0.1:8756`) | PC del usuario, dentro de AutoCAD | No |
| Archivos `.dwg` y licencia Civil 3D | PC del usuario | No |

Además:

- El guard de seguridad solo acepta peticiones loopback; publicado dejaría de funcionar.
- Exponer el puente de Civil 3D a internet permitiría ejecutar comandos sobre dibujos ajenos.
  Está prohibido por diseño.
- Un Ollama en el servidor necesitaría CPU/GPU y RAM, y seguiría sin poder tocar Civil 3D.

## Arquitectura recomendada (web sin IA)

```
Usuario
  ├─ Navegador -> http://127.0.0.1:8000  (frontend + backend locales)
  ├─ Ollama local (modelos descargados por el usuario)
  └─ Civil 3D + plugin C# (127.0.0.1:8756)

Internet
  └─ Web de descarga/instrucciones (estática) + Releases con el instalador
```

1. La web publicada es una **landing de descarga** (HTML estático) con instrucciones.
2. El instalador se distribuye por GitHub Releases o un bucket (R2/S3).
3. Al abrir la app, corre en `http://127.0.0.1:8000`; el usuario elige o descarga modelos desde
   el panel **Modelos**.
4. El plugin de Civil 3D se instala con el bundle y se arranca dentro de AutoCAD.

Ventajas: sin coste de GPU, sin datos de dibujos en la nube, sin latencia de red y sin exponer
el puente.

## Dónde alojar cada pieza

| Pieza | Opción recomendada | Alternativas | Coste |
| --- | --- | --- | --- |
| Landing estática | Cloudflare Pages | Netlify, Vercel, GitHub Pages | Gratis |
| Instalador / releases | GitHub Releases | Cloudflare R2 + dominio, S3 | Gratis o centavos |
| Documentación | GitHub Pages o el mismo hosting estático | MkDocs en Cloudflare Pages | Gratis |
| Backend futuro con login | VPS (Hetzner, DigitalOcean) | Fly.io, Railway | 5–20 USD/mes |
| Ollama | **Siempre en el PC del usuario** | Servidor con GPU solo si se asume el coste | — |

No uses planes gratuitos tipo Render/Railway para Ollama: se duermen, tienen poca RAM y no
sirven para inferencia estable.

## Publicar la landing

1. Crea una carpeta `site/` con un `index.html` que explique requisitos (Windows, Civil 3D,
   Ollama) y enlace al instalador.
2. Súbela a Cloudflare Pages o Netlify (arrastrar y soltar o conectar el repositorio).
3. Publica el instalador en GitHub Releases y enlaza la última versión.
4. Añade HTTPS; nunca pidas credenciales en una página sin TLS.

## Empaquetar la app para usuarios

Opciones, de menor a mayor comodidad:

1. **ZIP + `scripts/start.bat`**: requiere Python 3.12 instalado. Es lo que existe hoy.
2. **PyInstaller**: genera un `.exe` del backend; el frontend y los assets se incluyen como
   datos. No requiere Python en el equipo destino.
3. **Inno Setup**: instalador con accesos directos, detección de Ollama y del bundle de Civil 3D.
   Recomendado para usuarios no técnicos.
4. **Autoinstalación del plugin**: copiar el `.bundle` a
   `%APPDATA%\Autodesk\ApplicationPlugins\` y avisar de reiniciar AutoCAD.

El plugin sigue compilándose aparte porque necesita los ensamblados de Autodesk; no lo incluyas
en el instalador si no está firmado o verificado.

## Demo gratuita en Render (para probar la interfaz)

El repositorio incluye `render.yaml` y `Dockerfile`. La demo sirve para validar UI, API, historial,
seguridad y mensajes de error; **no habrá modelos ni Civil 3D reales**.

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

### Probar con Ollama propio (opcional)

Si necesitas probar el chat desde la demo alojada, expón tu Ollama con un túnel (por ejemplo
Cloudflare Tunnel) y define `OLLAMA_URL` en el hosting. Ten en cuenta que estarás publicando tu
Ollama: protégelo, no lo dejes abierto y ciérralo al terminar. Para uso real, es mejor ejecutar
Ingenia AI en local.

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

## Alternativa híbrida (solo si más adelante hace falta)

Si en el futuro quieres una web central con cuentas y operar Civil 3D desde cualquier sitio:

- Backend alojado con autenticación real por usuario (no un token compartido).
- Un **agente local** en cada PC que abra una conexión saliente (WebSocket/TLS) hacia el
  hosting; el servidor nunca inicia conexiones al puente local.
- Cola de trabajos, auditoría por usuario y límites de uso.
- Aun así, Ollama puede quedarse en el equipo del usuario o en el servidor, pero no ambos sin
  definir el coste.

Esto **no está implementado** y es un cambio de arquitectura grande, no un despliegue.

## Lista de verificación antes de publicar

- [ ] La landing no incluye claves, tokens ni el `.env`.
- [ ] `backend/.env` y `backend/data/` están fuera del repositorio.
- [ ] El instalador se publica con hash SHA-256 y, si es posible, firma de código.
- [ ] Los puertos `8000`, `8756` y `11434` no se abren al exterior.
- [ ] El token local se genera por instalación (no reutilizar `ingenia-local-dev`).
- [ ] Se documenta que el modelo se descarga en el equipo del usuario.
