$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$pidFile = Join-Path $backend ".ingenia.pid"
$stopped = $false

Write-Host "Ingenia AI - detención" -ForegroundColor Cyan

if (Test-Path $pidFile) {
    $serverPid = (Get-Content $pidFile | Select-Object -First 1).Trim()
    if ($serverPid -match "^\d+$") {
        $process = Get-Process -Id ([int]$serverPid) -ErrorAction SilentlyContinue
        if ($process) {
            Write-Host ("Deteniendo backend (PID {0})..." -f $serverPid)
            Stop-Process -Id ([int]$serverPid) -Force
            $stopped = $true
        } else {
            Write-Host "El PID registrado ya no existe."
        }
    }
    Remove-Item $pidFile -ErrorAction SilentlyContinue
}

if (-not $stopped) {
    $connection = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($connection) {
        $candidate = Get-Process -Id $connection.OwningProcess -ErrorAction SilentlyContinue
        if ($candidate -and $candidate.Path -and $candidate.Path.StartsWith($backend, [System.StringComparison]::OrdinalIgnoreCase)) {
            Write-Host ("Deteniendo proceso del proyecto en el puerto 8000 (PID {0})..." -f $candidate.Id)
            Stop-Process -Id $candidate.Id -Force
            $stopped = $true
        } else {
            Write-Host "El puerto 8000 está ocupado por otro proceso; no se detuvo." -ForegroundColor Yellow
        }
    }
}

if ($stopped) {
    Write-Host "Backend detenido." -ForegroundColor Green
} else {
    Write-Host "No se encontró un backend de Ingenia AI en ejecución."
}

Write-Host "Nota: el plugin de Civil 3D se detiene con el comando INGENIABRIDGE_STOP o al cerrar Civil 3D."
