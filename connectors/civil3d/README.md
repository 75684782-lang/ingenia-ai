# IngeniaBridge (complemento Civil 3D)

Complemento .NET que expone un puente HTTP local para que Ingenia AI ejecute operaciones
dentro de Civil 3D.

## Compilar

Requisitos: Civil 3D instalado y MSBuild (VS 2022 Build Tools o superior).

```bat
"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\MSBuild\Current\Bin\MSBuild.exe" IngeniaBridge.csproj -p:Configuration=Release -p:Civil3DVersion=2024 -p:TargetFramework=net48
```

Para Civil 3D 2025/2026 usa `-p:Civil3DVersion=2025 -p:TargetFramework=net8.0-windows` y
ten instalado el SDK de .NET 8.

## Configurar

Copia `ingenia.bridge.json` junto al DLL (mismo token que `CIVIL3D_TOKEN` en `backend\.env`).
Sin token el puente rechaza todo.

## Cargar

`NETLOAD` → `IngeniaBridge.dll` → comando `INGENIABRIDGE`.

## Estado

El código está completo pero **no verificado** contra una instalación real de Civil 3D.
Consulta `docs/civil3d-integration.md` para el checklist y las APIs que requieren
verificación por versión.
