[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path $PSScriptRoot -Parent
$runtimeFile = Join-Path $repoRoot "data\demo-processes.json"

if (-not (Test-Path -LiteralPath $runtimeFile)) {
    Write-Host "没有找到本项目的运行记录，演示服务可能尚未启动。"
    exit 0
}

$runtime = Get-Content -Raw -LiteralPath $runtimeFile | ConvertFrom-Json

foreach ($processId in @($runtime.web_pid, $runtime.api_pid)) {
    if (-not $processId) { continue }
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($process -and $process.ProcessName -in @("node", "python", "python3")) {
        Stop-Process -Id $processId -Force
    }
}

Remove-Item -LiteralPath $runtimeFile -Force
Write-Host "Banking Agent Demo 已停止。数据库保留在 data 目录，便于继续演示。" -ForegroundColor Green
