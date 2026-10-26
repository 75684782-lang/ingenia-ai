# Ingenia AI

Asistente web de ingeniería para **Autodesk Civil 3D**. El usuario trabaja desde la web,
mientras **Ollama**, el dibujo y el complemento de Civil 3D permanecen en su PC. Un conector
local mantiene una conexión cifrada saliente y solo retransmite los métodos autorizados.

> Estado honesto: la parte de IA/backend/frontend está implementada y probada. El
> complemento de Civil 3D está implementado pero **no ha sido compilado ni probado** en
> este equipo porque Civil 3D no está instalado. Sin una conexión real, las operaciones fallan
> explícitamente; nunca se simula un éxito.
>
> Render está configurado para cuentas, emparejamiento y SQLite en un disco persistente.
> El despliegue requiere sincronizar el Blueprint y aceptar el plan pagado con su disco.
> El complemento de Civil 3D todavía necesita compilarse y probarse en una PC con Civil 3D.
>
> En el modo web, los archivos DWG permanecen en el PC, pero los mensajes, el historial y
> los resultados de herramientas atraviesan y se guardan en el servidor. No introduzcas
> información sensible hasta definir y publicar la política de retención.

## Requisitos

- Windows 10/11 x64
- Python 3.12 (el lanzador `py -3.12` o `python`)
- [Ollama](https://ollama.com) instalado y en ejecución
- Un modelo local con soporte de herramientas (se recomienda `qwen2.5-coder:1.5b`)
- Civil 3D (solo para operaciones reales) y MSBuild/Visual Studio para compilar el plugin

Hardware de referencia detectado: AMD A9-9420, 7.5 GB RAM, GPU integrada. Usa modelos
pequeños; la inferencia es por CPU.

## Inicio rápido

```bat
scripts\check_environment.bat
scripts\start.bat
```

`start.bat` crea `backend\.venv`, instala dependencias, ofrece descargar el modelo
recomendado, arranca FastAPI en `http://127.0.0.1:8000`, abre el navegador y guarda el PID
para `stop.bat`.

Parar el backend:

```bat
scripts\stop.bat
```

Pruebas:

```bat
cd backend
.venv\Scripts\python -m pytest
```

## Estructura

```
backend/app/            FastAPI, Ollama, herramientas, conector, seguridad, SQLite
frontend/               UI oscura sin build (HTML/CSS/JS, módulos ES)
connectors/civil3d/     Complemento C# (multi-target net48 / net8.0-windows)
connectors/desktop/     Conector Python local para Ollama y Civil 3D
scripts/                start / stop / check_environment (.bat + .ps1)
docs/                   arquitectura, instalación, integración Civil 3D
```

## Herramientas

| Herramienta | Riesgo | Estado |
|---|---|---|
| `get_civil3d_status` | lectura | implementada |
| `get_active_drawing_info` | lectura | implementada |
| `list_drawing_objects` | lectura | implementada |
| `inspect_surface` | lectura | implementada |
| `list_alignments` | lectura | implementada |
| `create_surface` | escritura | implementada, requiere confirmación |
| `generate_contours` | escritura | implementada, requiere confirmación |
| `create_alignment_from_polyline` | escritura | implementada, requiere confirmación |
| `generate_profile` | escritura | implementada, requiere confirmación |
| `get_operation_status` | lectura | local (SQLite) |
| `calculate_volumes` | lectura | **experimental**, marcada como no verificada |

Las herramientas de escritura no se ejecutan sin una confirmación explícita del usuario.
El backend valida argumentos con esquemas Pydantic y rechaza cualquier herramienta que no
esté en el registro.

## Seguridad

- Servicio escuchando solo en `127.0.0.1`.
- Token local obligatorio (`INGENIA_AUTH_TOKEN`, cabecera `X-Ingenia-Token` o cookie).
- El plugin de Civil 3D escucha solo en loopback y exige `X-Ingenia-Token`.
- Sin ejecución de comandos de consola, SQL, PowerShell ni código generado por el modelo.
- Lista permitida de herramientas, validación de tipos, idempotencia, auditoría en SQLite.
- Confirmación de dos pasos para escrituras; el rechazo no modifica el dibujo.

## Modelo

Ollama expone los modelos instalados en el selector. Solo se habilitan como óptimos los que
declaran la capacidad `tools`. También puedes descargar cualquier modelo desde el panel
**Modelos** de la interfaz: se descarga con Ollama en tu equipo, nunca desde la web.

```bat
ollama pull qwen2.5-coder:1.5b
```

En 7.5 GB de RAM, un modelo de 7B es lento y puede agotar el tiempo de espera. El 1.5B es la
opción recomendada; el 7B sigue disponible si tu equipo lo soporta.

## Documentación

- [docs/installation.md](docs/installation.md)
- [docs/architecture.md](docs/architecture.md)
- [docs/civil3d-integration.md](docs/civil3d-integration.md)
- [docs/deployment.md](docs/deployment.md) — qué se puede alojar y qué no
- [connectors/desktop/README.md](connectors/desktop/README.md) — emparejar una PC a la web
- [connectors/civil3d/README.md](connectors/civil3d/README.md)
