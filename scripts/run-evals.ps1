[CmdletBinding()]
param(
    [ValidateSet("deterministic", "qwen", "openai", "auto")]
    [string]$Provider = "deterministic",
    [ValidateRange(0, 1000)]
    [int]$Limit = 0
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path $PSScriptRoot -Parent
$apiRoot = Join-Path $repoRoot "services\api"
$pythonExe = Join-Path $apiRoot ".venv\Scripts\python.exe"
$caseFile = Join-Path $apiRoot "evals\cases.json"
$reportFile = Join-Path $repoRoot "data\eval-report-$Provider.json"
$environmentNames = @(
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "DASHSCOPE_API_KEY",
    "QWEN_BASE_URL",
    "QWEN_MODEL"
)
$previousValues = @{}

if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw "未找到后端虚拟环境：$pythonExe"
}

try {
    foreach ($name in $environmentNames) {
        $previousValues[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
    }
    $rootEnvironment = Join-Path $repoRoot ".env"
    if (Test-Path -LiteralPath $rootEnvironment) {
        foreach ($line in Get-Content -LiteralPath $rootEnvironment) {
            if ($line -match "^(OPENAI_API_KEY|OPENAI_MODEL|DASHSCOPE_API_KEY|QWEN_BASE_URL|QWEN_MODEL)=(.*)$") {
                [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], "Process")
            }
        }
    }

    $arguments = @(
        "-m", "app.evals.runner",
        "--provider", $Provider,
        "--cases", $caseFile,
        "--output", $reportFile
    )
    if ($Limit -gt 0) {
        $arguments += @("--limit", $Limit)
    }

    Push-Location $apiRoot
    try {
        & $pythonExe @arguments
        if ($LASTEXITCODE -ne 0) {
            throw "评测运行失败，退出码：$LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }
}
finally {
    foreach ($name in $environmentNames) {
        [Environment]::SetEnvironmentVariable($name, $previousValues[$name], "Process")
    }
}
