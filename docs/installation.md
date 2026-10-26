# Instalación

## 1. Requisitos

- Windows 10/11 x64.
- Python 3.12 (recomendado). Verifica con `python --version` o `py -3.12 --version`.
- Ollama instalado y ejecutándose.
- Navegador moderno (Chrome/Edge/Firefox).
- Opcional para operaciones reales: Civil 3D + Visual Studio/MBuild.

## 2. Configurar Ollama

```bat
ollama --version
ollama list
ollama pull qwen2.5-coder:1.5b
```

El backend detecta automáticamente los modelos y marca los que soportan `tools`. No se
descargan modelos grandes de forma automática. Si `ollama list` falla, abre la aplicación
de Ollama y espera a que aparezca en la bandeja del sistema.

También puedes descargar cualquier modelo desde el panel **Modelos** de la interfaz: escribe
el tag (por ejemplo `llama3.2:3b` o `qwen2.5-coder:1.5b`) y pulsa **Descargar**. La descarga
la hace Ollama en tu equipo y muestra el progreso; la web no incluye ninguna IA.

## 3. Arrancar Ingenia AI

```bat
scripts\check_environment.bat
scripts\start.bat
```

`start.ps1`:

1. Crea `backend\.venv` con Python 3.12 si no existe.
2. Instala `backend\requirements.txt`.
3. Copia `backend\.env.example` a `backend\.env` si falta.
4. Comprueba Ollama y ofrece descargar `qwen2.5-coder:1.5b`.
5. Lanza uvicorn en `127.0.0.1:8000` (logs en `backend\logs`).
6. Abre `http://127.0.0.1:8000`.

Para detener el backend:

```bat
scripts\stop.bat
```

## 4. Variables de entorno

Edita `backend\.env`:

| Variable | Descripción |
|---|---|
| `INGENIA_HOST` / `INGENIA_PORT` | Bind local (por defecto 127.0.0.1:8000) |
| `INGENIA_AUTH_TOKEN` | Token exigido por la API local; cámbialo |
| `OLLAMA_URL` | URL de Ollama (por defecto `http://127.0.0.1:11434`) |
| `OLLAMA_MODEL` | Modelo por defecto |
| `OLLAMA_TIMEOUT` | Segundos de espera por respuesta |
| `CIVIL3D_BRIDGE_URL` | URL del plugin (`http://127.0.0.1:8756`) |
| `CIVIL3D_TOKEN` | Token compartido con el plugin; **debe coincidir** |
| `CIVIL3D_FALLBACK_TO_MOCK` | `true` para seguir funcionando sin Civil 3D (sin éxito simulado) |
| `CIVIL3D_TIMEOUT` | Segundos de espera del plugin |
| `DATABASE_PATH` | Ruta opcional de SQLite |
| `RATE_LIMIT_PER_MINUTE` | Límite de solicitudes por minuto |
| `MAX_TOOL_STEPS` | Máximo de iteraciones de herramientas por turno |

El token del frontend se entrega como cookie HttpOnly al cargar `/`, de modo que el
JavaScript no necesita conocerlo ni exponerlo.

## 5. Ejecutar pruebas

```bat
cd backend
.venv\Scripts\python -m pytest
```

Las pruebas no requieren Ollama ni Civil 3D: usan dobles de prueba en memoria. Las pruebas
con `MockConnector` verifican explícitamente que **nunca** se devuelve `ok=true` en modo
simulado.

## 6. Solución de problemas

**Ollama no responde**
- Inicia la aplicación Ollama.
- Verifica `Invoke-RestMethod http://127.0.0.1:11434/api/tags`.
- Si tu firewall bloquea loopback, permite la aplicación local.

**El backend no arranca**
- Revisa `backend\logs\server.err.log`.
- Comprueba que el puerto 8000 esté libre: `Get-NetTCPConnection -LocalPort 8000`.
- Borra `backend\.venv` y vuelve a ejecutar `start.bat` si el entorno quedó corrupto.

**El modelo no llama herramientas**
- Usa un modelo con capacidad `tools` (el selector los lista).
- Baja la temperatura o usa `qwen2.5-coder:1.5b`.
- Revisa el tiempo de espera: modelos grandes en CPU pueden superar `OLLAMA_TIMEOUT`.

**401 en la interfaz**
- Recarga `http://127.0.0.1:8000/` para renovar la cookie.
- Si cambiaste `INGENIA_AUTH_TOKEN`, reinicia el backend y recarga.

**Civil 3D aparece como "no conectado"**
- Es lo esperado si el plugin no está compilado/cargado.
- Consulta `docs/civil3d-integration.md`.

## 7. Desinstalación

- `scripts\stop.bat`
- Elimina `backend\.venv`, `backend\.env`, `backend\data` y `backend\logs` si quieres limpiar
  datos locales.
- En Civil 3D, descarga el plugin y elimina la carpeta de Autoloader.
