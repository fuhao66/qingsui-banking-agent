[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path $PSScriptRoot -Parent
$apiRoot = Join-Path $repoRoot "services\api"
$dataRoot = Join-Path $repoRoot "data"
$runtimeFile = Join-Path $dataRoot "tunnel-processes.json"
$environmentFile = Join-Path $repoRoot ".env.tunnel"
$pythonExe = Join-Path $apiRoot ".venv\Scripts\python.exe"
$databaseFile = (Join-Path $dataRoot "banking-agent-public.db").Replace("\", "/")

if (-not (Test-Path -LiteralPath $runtimeFile)) { throw "公网隧道尚未运行。" }
$runtime = Get-Content -LiteralPath $runtimeFile -Raw | ConvertFrom-Json

foreach ($file in @((Join-Path $repoRoot ".env"), $environmentFile)) {
    if (Test-Path -LiteralPath $file) {
        foreach ($line in Get-Content -LiteralPath $file) {
            if ($line -match "^([A-Z0-9_]+)=(.*)$") {
                [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2].Trim(), "Process")
            }
        }
    }
}
$env:APP_ENV = "production"
$env:PUBLIC_DEMO_MODE = "true"
$env:DATABASE_URL = "sqlite+aiosqlite:///$databaseFile"
$env:REDIS_URL = ""
$env:CORS_ORIGINS = "http://localhost:3000"
$env:PUBLIC_WEB_BASE_URL = [string]$runtime.public_url

$oldProcess = Get-Process -Id ([int]$runtime.api) -ErrorAction SilentlyContinue
if ($oldProcess) {
    Stop-Process -Id $oldProcess.Id -Force
    $oldProcess.WaitForExit()
}
Start-Sleep -Milliseconds 500

$apiProcess = Start-Process -FilePath $pythonExe -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000") -WorkingDirectory $apiRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $dataRoot "tunnel-api.stdout.log") -RedirectStandardError (Join-Path $dataRoot "tunnel-api.stderr.log") -PassThru
$deadline = (Get-Date).AddSeconds(20)
$ready = $false
while ((Get-Date) -lt $deadline) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8000/health/live" -TimeoutSec 2
        if ($response.StatusCode -eq 200) { $ready = $true; break }
    } catch { Start-Sleep -Milliseconds 300 }
}
if (-not $ready) { throw "API 重启后未通过就绪检查。" }

$runtime.api = $apiProcess.Id
$runtime | ConvertTo-Json | Set-Content -LiteralPath $runtimeFile -Encoding utf8
Write-Host "API 已重新加载，公网地址保持不变：$($runtime.public_url)" -ForegroundColor Green
