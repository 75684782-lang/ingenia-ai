$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$venv = Join-Path $backend ".venv"
$venvPython = Join-Path $venv "Scripts\python.exe"
$pidFile = Join-Path $backend ".ingenia.pid"
$logDir = Join-Path $backend "logs"

Write-Host "Ingenia AI - inicio" -ForegroundColor Cyan

# 1. Entorno virtual ---------------------------------------------------------
if (-not (Test-Path $venvPython)) {
    Write-Host "Creando entorno virtual con Python 3.12..."
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.12 -m venv $venv
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m venv $venv
    } else {
        Write-Host "No se encontró Python. Instala Python 3.12 x64." -ForegroundColor Red
        exit 1
    }
    if (-not (Test-Path $venvPython)) {
        Write-Host "No se pudo crear el entorno virtual." -ForegroundColor Red
        exit 1
    }
}

# 2. Dependencias ------------------------------------------------------------
Write-Host "Instalando/verificando dependencias..."
& $venvPython -m pip install --upgrade pip --quiet
& $venvPython -m pip install -r (Join-Path $backend "requirements.txt") --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Host "Falló la instalación de dependencias. Revisa la salida anterior." -ForegroundColor Red
    exit 1
}

# 3. Configuración -----------------------------------------------------------
$envFile = Join-Path $backend ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $backend ".env.example") $envFile
    Write-Host "Creado backend\.env a partir de .env.example. Revisa el token." -ForegroundColor Yellow
}

# 4. Ollama ------------------------------------------------------------------
try {
    $tags = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 3
    $modelNames = @($tags.models | ForEach-Object { $_.name })
    if (-not ($modelNames -contains "qwen2.5-coder:1.5b")) {
        Write-Host "No está descargado qwen2.5-coder:1.5b (recomendado para este equipo)." -ForegroundColor Yellow
        $answer = Read-Host "¿Descargarlo ahora (~1 GB)? [S/n]"
        if ($answer -ne "n" -and $answer -ne "N") {
            if (Get-Command ollama -ErrorAction SilentlyContinue) {
                & ollama pull qwen2.5-coder:1.5b
            } else {
                Write-Host "Ollama no está en PATH; descárgalo manualmente." -ForegroundColor Yellow
            }
        }
    }
} catch {
    Write-Host "Ollama no responde en 127.0.0.1:11434. La interfaz arrancará igualmente." -ForegroundColor Yellow
    Write-Host "Inicia Ollama y recarga la página." -ForegroundColor Yellow
}

# 5. ¿Ya está corriendo? -----------------------------------------------------
try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/health" -TimeoutSec 2
    if ($health.status -eq "ok") {
        Write-Host "El backend ya está en marcha en http://127.0.0.1:8000" -ForegroundColor Green
        Start-Process "http://127.0.0.1:8000"
        exit 0
    }
} catch {
    # no está corriendo
}

# 6. Arrancar backend --------------------------------------------------------
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stdout = Join-Path $logDir "server.out.log"
$stderr = Join-Path $logDir "server.err.log"

$process = Start-Process -FilePath $venvPython `
    -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000") `
    -WorkingDirectory $backend `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr `
    -PassThru -WindowStyle Hidden

$process.Id | Set-Content $pidFile
Write-Host ("Backend iniciado (PID {0}). Esperando respuesta..." -f $process.Id)

$ready = $false
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 750
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/health" -TimeoutSec 2
        if ($health.status -eq "ok") {
            $ready = $true
            break
        }
    } catch {
        # sigue arrancando
    }
    if ($process.HasExited) { break }
}

if (-not $ready) {
    Write-Host "El backend no respondió. Últimas líneas del log:" -ForegroundColor Red
    if (Test-Path $stderr) { Get-Content $stderr -Tail 30 }
    if (Test-Path $stdout) { Get-Content $stdout -Tail 30 }
    exit 1
}

Write-Host "Ingenia AI disponible en http://127.0.0.1:8000" -ForegroundColor Green
Start-Process "http://127.0.0.1:8000"
