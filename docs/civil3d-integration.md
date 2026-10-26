# Integración con Civil 3D

> **Advertencia de verificación.** El complemento incluido se escribió contra las API
> públicas de AutoCAD/Civil 3D, pero **no fue compilado ni ejecutado** en el equipo de
> desarrollo porque Civil 3D no está instalado. No se declara "terminado" hasta completar el
> checklist de este documento en una máquina con Civil 3D.

## Versiones y framework

| Civil 3D | Runtime | Target | Ensamblados |
|---|---|---|---|
| 2023 / 2024 | .NET Framework 4.8 | `net48` | `AcMgd`, `AcDbMgd`, `AcCoreMgd` en la carpeta de AutoCAD; `AeccDbMgd` en `C3D\` |
| 2025 / 2026 | .NET 8 | `net8.0-windows` | mismos nombres, compilados para .NET 8 |

El proyecto usa multi-target `net48;net8.0-windows`. Ajusta la ruta y compila el target que
corresponda:

```bat
cd connectors\civil3d\source
"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\MSBuild\Current\Bin\MSBuild.exe" IngeniaBridge.csproj -p:Configuration=Release -p:Civil3DVersion=2024 -p:TargetFramework=net48
```

Para 2025+:

```bat
msbuild IngeniaBridge.csproj -p:Civil3DVersion=2025 -p:TargetFramework=net8.0-windows
```

Rutas por defecto:

- `C:\Program Files\Autodesk\AutoCAD 2024\AcMgd.dll`
- `C:\Program Files\Autodesk\AutoCAD 2024\C3D\AeccDbMgd.dll`

Si tu instalación difiere, pasa `-p:Civil3DInstallDir="D:\Autodesk\AutoCAD 2024"`.

## Configuración del token

Crea `ingenia.bridge.json` junto a `IngeniaBridge.dll`:

```json
{
  "host": "127.0.0.1",
  "port": 8756,
  "token": "EL-MISMO-TOKEN-QUE-CIVIL3D_TOKEN",
  "requestTimeoutSeconds": 60
}
```

También se admiten variables de entorno:

- `INGENIA_BRIDGE_HOST`
- `INGENIA_BRIDGE_PORT`
- `INGENIA_CIVIL3D_TOKEN`
- `INGENIA_BRIDGE_TIMEOUT`

Sin token, el puente **rechaza todas las solicitudes** con HTTP 401.

## Carga del complemento

Manual:

1. Abre Civil 3D.
2. `NETLOAD` y selecciona `IngeniaBridge.dll`.
3. Comprueba el estado con el comando `INGENIABRIDGE`.

Autoloader (recomendado para uso permanente):

```
%APPDATA%\Autodesk\ApplicationPlugins\IngeniaBridge.bundle\
  PackageContents.xml
  Contents\Windows\IngeniaBridge.dll
  Contents\Windows\ingenia.bridge.json
```

`PackageContents.xml` mínimo:

```xml
<?xml version="1.0" encoding="utf-8"?>
<ApplicationPackage SchemaVersion="1.0" AppVersion="1.0"
    Name="IngeniaBridge" Description="Puente local Ingenia AI">
  <Components>
    <RuntimeRequirements OS="Win64" Platform="AutoCAD*" SeriesMin="R24.0" />
    <ComponentEntry AppName="IngeniaBridge"
        ModuleName="./Contents/Windows/IngeniaBridge.dll"
        AppDescription="Puente local Ingenia AI" LoadOnAutoCADStartup="True" />
  </Components>
</ApplicationPackage>
```

Ajusta `SeriesMin` a tu versión (R24.0 para 2024, R25.0 para 2025).

## Comandos

| Comando | Acción |
|---|---|
| `INGENIABRIDGE` | Muestra estado y configuración |
| `INGENIABRIDGE_START` | Inicia el puente |
| `INGENIABRIDGE_STOP` | Detiene el puente |

## Protocolo

- `GET /status` → `{ connected, mode: "real", data: { drawing, units, versions } }`
- `POST /rpc` con `{ "tool": "...", "args": {...}, "request_id": "..." }`

Cabecera obligatoria: `X-Ingenia-Token`.

Respuesta:

```json
{ "ok": true, "mode": "real", "tool": "create_surface", "request_id": "...", "data": {...} }
```

En error: `ok=false`, `error` descriptivo. El backend convierte cualquier `ok=false` en un
fallo visible y el modelo no puede afirmar que la operación se realizó.

## Ejecución en el hilo correcto

El puente encola cada solicitud y la ejecuta en `Application.Idle`, con
`Document.LockDocument()` y una `Transaction`. Si el handler devuelve `ok=false`, la
transacción se revierte. Los objetos de Civil 3D nunca se tocan desde el hilo HTTP.

## Herramientas implementadas

| Herramienta | API utilizada | Riesgo de verificación |
|---|---|---|
| `get_civil3d_status` / `get_active_drawing_info` | `Document`, `Database.Insunits`, versión de ensamblado | bajo |
| `list_drawing_objects` | `CivilDocument.GetSurfaceIds/GetAlignmentIds`, ModelSpace | bajo |
| `inspect_surface` | `Surface` (`ElevationMin`, `Area2D`, etc.) | bajo |
| `list_alignments` | `Alignment`, `GetProfileIds` | bajo |
| `create_surface` | `TinSurface.Create`, `Styles.SurfaceStyles` | bajo |
| `generate_contours` | reflexión sobre `SurfaceStyle` (`GetContourStylePlan/Model`, `MajorInterval`) | **alto** |
| `create_alignment_from_polyline` | reflexión sobre `Alignment.CreateFromPolyline` | **alto** |
| `generate_profile` | `Profile.CreateFromSurface` | medio |
| `calculate_volumes` | reflexión `TinVolumeSurface.Create` + `GetVolumeProperties` | **alto** |

Las rutas marcadas como altas usan reflexión **a propósito**: si la firma no existe en la
versión instalada, la herramienta devuelve un error explícito y revierte la transacción.
Nunca se simula éxito. Sustituye la reflexión por la API documentada de tu versión una vez
verificada.

## Checklist de verificación real

1. Compilar el target correcto sin errores (adjuntar log).
2. `NETLOAD` y confirmar el mensaje del comando `INGENIABRIDGE`.
3. `GET /status` desde PowerShell:
   ```powershell
   Invoke-RestMethod http://127.0.0.1:8756/status -Headers @{ "X-Ingenia-Token" = "TOKEN" }
   ```
4. En Ingenia AI, pedir "analiza el dibujo abierto".
5. `create_surface` con un nombre nuevo → confirmar → verificar en el árbol de Civil 3D y
   con `get_operation_status`.
6. `generate_contours` → comprobar visualmente los intervalos.
7. `create_alignment_from_polyline` con un handle real (`list_drawing_objects`).
8. `generate_profile` → comprobar que aparece el perfil.
9. `calculate_volumes` → contrastar con la medición manual de Civil 3D.
10. Probar con el plugin detenido: la UI debe mostrar `mode=mock` y `ok=false`, sin cambios
    en el dibujo.
11. Probar token incorrecto: HTTP 401 y ningún cambio.
12. Probar cierre de Civil 3D durante una operación: error claro, sin éxito falso.

## Limitaciones conocidas

- No hay validación de que el estilo de superficie exista antes de crear la superficie
  (se comprueba en el handler; si no existe, la transacción se revierte).
- `generate_contours` modifica el estilo compartido de la superficie.
- Los volúmenes se calculan con una superficie de volumen temporal que se elimina al final.
- El plugin no implementa cancelación cooperativa de operaciones largas.
- No se ha probado en ninguna versión real de Civil 3D todavía.
