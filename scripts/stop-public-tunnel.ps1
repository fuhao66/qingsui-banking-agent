[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path $PSScriptRoot -Parent
$runtimeFile = Join-Path $repoRoot "data\tunnel-processes.json"
if (-not (Test-Path -LiteralPath $runtimeFile)) {
    Write-Host "未发现正在运行的公网隧道。"
    exit 0
}
$runtime = Get-Content -LiteralPath $runtimeFile -Raw | ConvertFrom-Json
foreach ($processId in @($runtime.tunnel, $runtime.web, $runtime.api)) {
    if ($processId) {
        $process = Get-Process -Id ([int]$processId) -ErrorAction SilentlyContinue
        if ($process) { Stop-Process -Id $process.Id -Force }
    }
}
Remove-Item -LiteralPath $runtimeFile -Force
Write-Host "公网体验隧道已停止。数据库仍保留在 data 目录。"
