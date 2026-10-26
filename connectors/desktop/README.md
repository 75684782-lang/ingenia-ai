# Conector local de Ingenia AI

El conector permite usar desde la web la instalación local de Ollama y el complemento
IngeniaBridge de Civil 3D. Mantiene una conexión saliente `wss://` hacia Ingenia AI; no abre
puertos en el PC ni publica Ollama, Civil 3D o los dibujos en Internet.

## Requisitos

- Windows 10/11 y Python 3.12.
- Ollama instalado, iniciado y con un modelo descargado.
- Civil 3D con IngeniaBridge iniciado para ejecutar operaciones sobre dibujos.
- Cuenta habilitada en el servidor Ingenia AI y el código temporal mostrado en **Mi PC**.

## Primer inicio

Desde la carpeta del proyecto:

```powershell
py -3.12 -m pip install -r connectors\desktop\requirements.txt
py -3.12 connectors\desktop\agent.py --url https://ingenia-ai.onrender.com
```

Escribe el código temporal que aparece en la web. El conector guardará la credencial del
dispositivo en `%LOCALAPPDATA%\IngeniaAI\connector.json` y se reconectará automáticamente.
Mantén abierta la ventana del conector mientras trabajas. Para detenerlo, pulsa `Ctrl+C`.

## Civil 3D

Configura el mismo token en `ingenia.bridge.json` junto a `IngeniaBridge.dll` y en la variable
de entorno `INGENIA_CIVIL3D_TOKEN` del usuario que ejecuta el conector. El complemento debe
estar cargado en Civil 3D y escuchar en `127.0.0.1:8756`.

Ollama se consulta únicamente en `127.0.0.1:11434`. La lista de métodos del conector está
limitada a Ollama y a las herramientas registradas para Civil 3D; no acepta comandos, rutas
de archivos ni código arbitrario enviados por la web.

## Seguridad y desvinculación

- Usa siempre HTTPS en el servidor remoto. El cliente rechaza HTTP para hosts remotos.
- La credencial del conector se entrega una sola vez al emparejar y se almacena en el perfil
  local de Windows. Protege el acceso a tu cuenta de Windows.
- Puedes revocar el dispositivo desde la web. Para volver a emparejarlo, elimina el conector
  desde **Mi PC** y ejecuta el comando con `--reset`.
- No compartas el código temporal ni la credencial local. No expongas los puertos `8756` ni
  `11434`.

## Estado de despliegue

Las funciones de cuentas y conectores requieren `INGENIA_ACCOUNTS=true` y
`INGENIA_USE_AGENTS=true` en el servidor, además de una base de datos persistente. La demo
Render actual almacena SQLite en `/tmp` y no activa cuentas; no la uses aún para vincular
dispositivos hasta configurar almacenamiento persistente.
