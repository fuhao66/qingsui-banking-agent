[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path $PSScriptRoot -Parent
$apiRoot = Join-Path $repoRoot "services\api"
$webRoot = Join-Path $repoRoot "apps\web"
$dataRoot = Join-Path $repoRoot "data"
$toolsRoot = Join-Path $repoRoot "tools"
$runtimeFile = Join-Path $dataRoot "tunnel-processes.json"
$environmentFile = Join-Path $repoRoot ".env.tunnel"
$cloudflared = Join-Path $toolsRoot "cloudflared.exe"
$pythonExe = Join-Path $apiRoot ".venv\Scripts\python.exe"
$nextEntry = Join-Path $webRoot "node_modules\next\dist\bin\next"
$databaseFile = (Join-Path $dataRoot "banking-agent-public.db").Replace("\", "/")

function Test-PortListening([int]$Port) {
    foreach ($line in (& netstat.exe -ano -p tcp)) {
        if ($line -match "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+\d+\s*$") { return $true }
    }
    return $false
}

function New-RandomHex([int]$Bytes) {
    $buffer = New-Object byte[] $Bytes
    [Security.Cryptography.RandomNumberGenerator]::Fill($buffer)
    return [Convert]::ToHexString($buffer).ToLowerInvariant()
}

if (-not (Test-Path -LiteralPath $cloudflared)) { throw "缺少 tools/cloudflared.exe。" }
if (-not (Test-Path -LiteralPath $pythonExe)) { throw "后端虚拟环境不存在。" }
if (-not (Test-Path -LiteralPath $nextEntry)) { throw "前端依赖不存在。" }
if (Test-PortListening 3000 -or Test-PortListening 8000) {
    throw "端口 3000 或 8000 已占用，请先运行 scripts/stop-demo.ps1 或 scripts/stop-public-tunnel.ps1。"
}

New-Item -ItemType Directory -Path $dataRoot -Force | Out-Null
New-Item -ItemType Directory -Path $toolsRoot -Force | Out-Null

$nodeCommand = Get-Command node -ErrorAction SilentlyContinue
if ($nodeCommand) {
    $nodeExe = $nodeCommand.Source
} else {
    $nodeExe = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
    if (-not (Test-Path -LiteralPath $nodeExe)) { throw "未找到 Node.js。" }
}

if (-not (Test-Path -LiteralPath $environmentFile)) {
    $invite = "BANK-" + (New-RandomHex 4).ToUpperInvariant()
    $admin = New-RandomHex 32
    $hmac = New-RandomHex 32
    @(
        "PUBLIC_INVITE_CODE=$invite"
        "ADMIN_API_TOKEN=$admin"
        "SECURITY_HMAC_SECRET=$hmac"
        "EXPERIENCE_SESSION_HOURS=8"
        "EXPERIENCE_MAX_ACTIVE_SESSIONS=30"
        "EXPERIENCE_REQUESTS_PER_MINUTE=30"
    ) | Set-Content -LiteralPath $environmentFile -Encoding utf8
}

$publicValues = @{}
foreach ($line in Get-Content -LiteralPath $environmentFile) {
    if ($line -match "^([A-Z0-9_]+)=(.*)$") { $publicValues[$Matches[1]] = $Matches[2].Trim() }
}
foreach ($required in "PUBLIC_INVITE_CODE", "ADMIN_API_TOKEN", "SECURITY_HMAC_SECRET") {
    if ([string]::IsNullOrWhiteSpace([string]$publicValues[$required])) { throw "$required 未配置。" }
}

$rootEnvironment = Join-Path $repoRoot ".env"
if (Test-Path -LiteralPath $rootEnvironment) {
    foreach ($line in Get-Content -LiteralPath $rootEnvironment) {
        if ($line -match "^(AGENT_MODEL_PROVIDER|OPENAI_API_KEY|OPENAI_MODEL|DASHSCOPE_API_KEY|QWEN_BASE_URL|QWEN_MODEL)=(.*)$") {
            [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], "Process")
        }
    }
}
foreach ($entry in $publicValues.GetEnumerator()) {
    [Environment]::SetEnvironmentVariable([string]$entry.Key, [string]$entry.Value, "Process")
}
$env:APP_ENV = "production"
$env:PUBLIC_DEMO_MODE = "true"
$env:DATABASE_URL = "sqlite+aiosqlite:///$databaseFile"
$env:REDIS_URL = ""
$env:CORS_ORIGINS = "http://localhost:3000"
$env:NEXT_PUBLIC_REQUIRE_INVITE = "true"
$env:NEXT_PUBLIC_API_BASE_URL = ""
$env:INTERNAL_API_BASE_URL = "http://127.0.0.1:8000"

Push-Location $apiRoot
try {
    & $pythonExe -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw "数据库迁移失败。" }
    & $pythonExe -m app.db.seed
    if ($LASTEXITCODE -ne 0) { throw "演示数据初始化失败。" }
} finally { Pop-Location }

$apiProcess = Start-Process -FilePath $pythonExe -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000") -WorkingDirectory $apiRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $dataRoot "tunnel-api.stdout.log") -RedirectStandardError (Join-Path $dataRoot "tunnel-api.stderr.log") -PassThru
$webProcess = Start-Process -FilePath $nodeExe -ArgumentList @($nextEntry, "dev", "-p", "3000") -WorkingDirectory $webRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $dataRoot "tunnel-web.stdout.log") -RedirectStandardError (Join-Path $dataRoot "tunnel-web.stderr.log") -PassThru

$deadline = (Get-Date).AddSeconds(30)
while ((Get-Date) -lt $deadline -and (-not (Test-PortListening 3000) -or -not (Test-PortListening 8000))) { Start-Sleep -Milliseconds 500 }
if (-not (Test-PortListening 3000) -or -not (Test-PortListening 8000)) { throw "本地公网模式启动超时。" }

$tunnelOut = Join-Path $dataRoot "cloudflared.stdout.log"
$tunnelErr = Join-Path $dataRoot "cloudflared.stderr.log"
$tunnelProcess = Start-Process -FilePath $cloudflared -ArgumentList @("tunnel", "--url", "http://127.0.0.1:3000", "--no-autoupdate") -WorkingDirectory $repoRoot -WindowStyle Hidden -RedirectStandardOutput $tunnelOut -RedirectStandardError $tunnelErr -PassThru

$publicUrl = $null
$deadline = (Get-Date).AddSeconds(45)
while ((Get-Date) -lt $deadline -and -not $publicUrl) {
    Start-Sleep -Milliseconds 500
    $text = ((Get-Content -LiteralPath $tunnelOut -Raw -ErrorAction SilentlyContinue) + "`n" + (Get-Content -LiteralPath $tunnelErr -Raw -ErrorAction SilentlyContinue))
    if ($text -match "https://[a-z0-9-]+\.trycloudflare\.com") { $publicUrl = $Matches[0] }
    if ($tunnelProcess.HasExited) { throw "Cloudflare 隧道启动失败，请查看 data/cloudflared.stderr.log。" }
}
if (-not $publicUrl) { throw "未能在限定时间内取得公网地址。" }

# The quick-tunnel URL is only known after cloudflared starts. Restart the API once so
# signed IM confirmation links point to the current public PWA rather than localhost.
$env:PUBLIC_WEB_BASE_URL = $publicUrl
Stop-Process -Id $apiProcess.Id -Force
$apiProcess.WaitForExit()
$apiProcess = Start-Process -FilePath $pythonExe -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000") -WorkingDirectory $apiRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $dataRoot "tunnel-api.stdout.log") -RedirectStandardError (Join-Path $dataRoot "tunnel-api.stderr.log") -PassThru
$deadline = (Get-Date).AddSeconds(20)
while ((Get-Date) -lt $deadline -and -not (Test-PortListening 8000)) { Start-Sleep -Milliseconds 300 }
if (-not (Test-PortListening 8000)) { throw "API 使用公网安全链接配置重启失败。" }

@{ api = $apiProcess.Id; web = $webProcess.Id; tunnel = $tunnelProcess.Id; public_url = $publicUrl; started_at = (Get-Date).ToString("o") } | ConvertTo-Json | Set-Content -LiteralPath $runtimeFile -Encoding utf8
Write-Host "公网体验已启动" -ForegroundColor Green
Write-Host "地址：$publicUrl"
Write-Host ("邀请码：" + $publicValues["PUBLIC_INVITE_CODE"])
Write-Host "关闭命令：.\scripts\stop-public-tunnel.ps1"
