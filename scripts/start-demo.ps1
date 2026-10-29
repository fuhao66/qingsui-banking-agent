[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path $PSScriptRoot -Parent
$apiRoot = Join-Path $repoRoot "services\api"
$webRoot = Join-Path $repoRoot "apps\web"
$runtimeRoot = Join-Path $repoRoot "data"
$runtimeFile = Join-Path $runtimeRoot "demo-processes.json"
$databaseFile = (Join-Path $runtimeRoot "banking-agent-demo.db").Replace("\", "/")
$pythonExe = Join-Path $apiRoot ".venv\Scripts\python.exe"
$nextEntry = Join-Path $webRoot "node_modules\next\dist\bin\next"

function Get-ListenerProcessId {
    param([Parameter(Mandatory)][int]$Port)

    foreach ($line in (& netstat.exe -ano -p tcp)) {
        if ($line -match "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+(\d+)\s*$") {
            return [int]$Matches[1]
        }
    }
    throw "无法确定端口 $Port 的监听进程。"
}

function Test-PortListening {
    param([Parameter(Mandatory)][int]$Port)

    foreach ($line in (& netstat.exe -ano -p tcp)) {
        if ($line -match "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+\d+\s*$") {
            return $true
        }
    }
    return $false
}

if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw "未找到后端虚拟环境。请先在 services/api 下创建 .venv 并安装依赖。"
}

if (-not (Test-Path -LiteralPath $nextEntry)) {
    throw "未找到前端依赖。请先在仓库根目录运行 pnpm install。"
}

$nodeCommand = Get-Command node -ErrorAction SilentlyContinue
if ($nodeCommand) {
    $nodeExe = $nodeCommand.Source
} else {
    $codexNode = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
    if (-not (Test-Path -LiteralPath $codexNode)) {
        throw "未找到 Node.js。请安装 Node.js 20+ 并加入 PATH。"
    }
    $nodeExe = $codexNode
}

foreach ($port in 3000, 8000) {
    if (Test-PortListening -Port $port) {
        throw "端口 $port 已被占用。请先运行 scripts/stop-demo.ps1，或关闭占用该端口的程序。"
    }
}

New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null

$oldDatabaseUrl = $env:DATABASE_URL
$oldCorsOrigins = $env:CORS_ORIGINS
$oldApiBase = $env:NEXT_PUBLIC_API_BASE_URL
$oldAgentProvider = $env:AGENT_MODEL_PROVIDER
$oldOpenAiKey = $env:OPENAI_API_KEY
$oldOpenAiModel = $env:OPENAI_MODEL
$oldDashScopeKey = $env:DASHSCOPE_API_KEY
$oldQwenBaseUrl = $env:QWEN_BASE_URL
$oldQwenModel = $env:QWEN_MODEL

try {
    $rootEnvironment = Join-Path $repoRoot ".env"
    if (Test-Path -LiteralPath $rootEnvironment) {
        foreach ($line in Get-Content -LiteralPath $rootEnvironment) {
            if ($line -match "^(AGENT_MODEL_PROVIDER|OPENAI_API_KEY|OPENAI_MODEL|DASHSCOPE_API_KEY|QWEN_BASE_URL|QWEN_MODEL)=(.*)$") {
                [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], "Process")
            }
        }
    }
    $env:DATABASE_URL = "sqlite+aiosqlite:///$databaseFile"
    $env:CORS_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"

    Push-Location $apiRoot
    try {
        & $pythonExe -m alembic upgrade head
        & $pythonExe -m app.db.seed
    } finally {
        Pop-Location
    }

    $apiStart = @{
        FilePath = $pythonExe
        ArgumentList = @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000")
        WorkingDirectory = $apiRoot
        WindowStyle = "Hidden"
        RedirectStandardOutput = (Join-Path $runtimeRoot "api.stdout.log")
        RedirectStandardError = (Join-Path $runtimeRoot "api.stderr.log")
        PassThru = $true
    }
    $apiProcess = Start-Process @apiStart

    $env:NEXT_PUBLIC_API_BASE_URL = "http://localhost:8000"
    $webStart = @{
        FilePath = $nodeExe
        ArgumentList = @($nextEntry, "dev", "-p", "3000")
        WorkingDirectory = $webRoot
        WindowStyle = "Hidden"
        RedirectStandardOutput = (Join-Path $runtimeRoot "web.stdout.log")
        RedirectStandardError = (Join-Path $runtimeRoot "web.stderr.log")
        PassThru = $true
    }
    $webProcess = Start-Process @webStart

    $deadline = (Get-Date).AddSeconds(25)
    do {
        Start-Sleep -Milliseconds 500
        try {
            $apiReady = (Invoke-WebRequest -UseBasicParsing "http://localhost:8000/health/live" -TimeoutSec 2).StatusCode -eq 200
        } catch {
            $apiReady = $false
        }
        try {
            $webReady = (Invoke-WebRequest -UseBasicParsing "http://localhost:3000" -TimeoutSec 2).StatusCode -eq 200
        } catch {
            $webReady = $false
        }
    } until (($apiReady -and $webReady) -or (Get-Date) -ge $deadline)

    if (-not ($apiReady -and $webReady)) {
        throw "演示服务未在 25 秒内就绪，请检查 data 目录下的日志。"
    }

    # Start-Process 返回的可能是启动器 PID；记录真正监听端口的服务进程，保证停止脚本可靠。
    $apiPid = Get-ListenerProcessId -Port 8000
    $webPid = Get-ListenerProcessId -Port 3000
    @{
        api_pid = $apiPid
        web_pid = $webPid
        api_launcher_pid = $apiProcess.Id
        web_launcher_pid = $webProcess.Id
        started_at = (Get-Date).ToString("o")
        web_url = "http://localhost:3000"
        api_url = "http://localhost:8000"
    } | ConvertTo-Json | Set-Content -LiteralPath $runtimeFile -Encoding utf8

    Write-Host "Banking Agent Demo 已启动" -ForegroundColor Green
    Write-Host "Web: http://localhost:3000"
    Write-Host "API: http://localhost:8000/docs"
} finally {
    $env:DATABASE_URL = $oldDatabaseUrl
    $env:CORS_ORIGINS = $oldCorsOrigins
    $env:NEXT_PUBLIC_API_BASE_URL = $oldApiBase
    $env:AGENT_MODEL_PROVIDER = $oldAgentProvider
    $env:OPENAI_API_KEY = $oldOpenAiKey
    $env:OPENAI_MODEL = $oldOpenAiModel
    $env:DASHSCOPE_API_KEY = $oldDashScopeKey
    $env:QWEN_BASE_URL = $oldQwenBaseUrl
    $env:QWEN_MODEL = $oldQwenModel
}
