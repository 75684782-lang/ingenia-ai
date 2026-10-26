$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot

function Write-Header($text) {
    Write-Host ""
    Write-Host "=== $text ===" -ForegroundColor Cyan
}

Write-Header "Sistema"
Write-Host ("Windows: " + (Get-CimInstance Win32_OperatingSystem).Caption)
Write-Host ("Arquitectura: " + $env:PROCESSOR_ARCHITECTURE)
$ram = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)
Write-Host ("RAM: {0} GB" -f $ram)

Write-Header "Python"
$pythonOk = $false
if (Get-Command py -ErrorAction SilentlyContinue) {
    $versions = & py -0p 2>$null
    Write-Host $versions
    $pythonOk = $true
} else {
    Write-Host "py (Python Launcher) no encontrado." -ForegroundColor Yellow
}
if (Get-Command python -ErrorAction SilentlyContinue) {
    Write-Host ("python: " + (& python --version 2>&1))
    $pythonOk = $true
} else {
    Write-Host "python no está en PATH." -ForegroundColor Yellow
}

Write-Header "Ollama"
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    Write-Host ((& ollama --version 2>&1) | Out-String)
    try {
        $tags = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 5
        if ($tags.models.Count -eq 0) {
            Write-Host "Ollama responde, pero no hay modelos descargados." -ForegroundColor Yellow
        } else {
            Write-Host "Modelos disponibles:"
            foreach ($model in $tags.models) {
                $tools = if ($model.capabilities -contains "tools") { "tools" } else { "-" }
                Write-Host ("  - {0} ({1}, {2})" -f $model.name, $model.details.parameter_size, $tools)
            }
        }
        if (-not ($tags.models.name -contains "qwen2.5-coder:1.5b")) {
            Write-Host "Sugerencia: ollama pull qwen2.5-coder:1.5b" -ForegroundColor Yellow
        }
    } catch {
        Write-Host "Ollama no responde en 127.0.0.1:11434. Inicia la aplicación Ollama." -ForegroundColor Yellow
    }
} else {
    Write-Host "Ollama no encontrado. Instala desde https://ollama.com" -ForegroundColor Yellow
}

Write-Header "Entorno virtual del backend"
$venv = Join-Path $root "backend\.venv\Scripts\python.exe"
if (Test-Path $venv) {
    Write-Host ("venv: " + $venv)
    Write-Host ((& $venv --version 2>&1))
} else {
    Write-Host "No existe backend\.venv. Ejecuta scripts\start.bat." -ForegroundColor Yellow
}

Write-Header "Autodesk Civil 3D"
$found = $false
foreach ($base in @("HKLM:\SOFTWARE\Autodesk\AutoCAD", "HKLM:\SOFTWARE\WOW6432Node\Autodesk\AutoCAD")) {
    if (Test-Path $base) {
        foreach ($key in Get-ChildItem $base -ErrorAction SilentlyContinue) {
            foreach ($product in Get-ChildItem $key.PSPath -ErrorAction SilentlyContinue) {
                $productName = (Get-ItemProperty $product.PSPath -ErrorAction SilentlyContinue).ProductName
                if ($productName) {
                    Write-Host ("  {0}\{1} -> {2}" -f $key.PSChildName, $product.PSChildName, $productName)
                    $found = $true
                }
            }
        }
    }
}
if (-not (Test-Path "C:\Program Files\Autodesk")) {
    Write-Host "No existe C:\Program Files\Autodesk." -ForegroundColor Yellow
}
$civilDll = Get-ChildItem "C:\Program Files\Autodesk" -Recurse -Filter "AeccDbMgd.dll" -ErrorAction SilentlyContinue -Depth 4 | Select-Object -First 1
if ($civilDll) {
    Write-Host ("AeccDbMgd.dll: " + $civilDll.FullName)
    $found = $true
} else {
    Write-Host "AeccDbMgd.dll no encontrado (Civil 3D no instalado o en otra ruta)." -ForegroundColor Yellow
}
if (-not $found) {
    Write-Host "El complemento C# no se podrá compilar ni probar en este equipo." -ForegroundColor Yellow
}

Write-Header ".NET / compilación"
$msbuild = "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\MSBuild\Current\Bin\MSBuild.exe"
if (Test-Path $msbuild) { Write-Host "MSBuild: $msbuild" } else { Write-Host "MSBuild de VS2022 BuildTools no encontrado." -ForegroundColor Yellow }
if (Get-Command dotnet -ErrorAction SilentlyContinue) {
    Write-Host ("dotnet: " + (& dotnet --version 2>&1))
} else {
    Write-Host "dotnet SDK no encontrado (necesario para Civil 3D 2025+ / .NET 8)." -ForegroundColor Yellow
}

Write-Header "Resumen"
Write-Host "Backend/frontend se pueden probar sin Civil 3D."
Write-Host "Las operaciones de Civil 3D devolverán mode=mock y NUNCA éxito simulado."
