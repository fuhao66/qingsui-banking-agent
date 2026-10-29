[CmdletBinding()]
param(
    [switch]$ValidateOnly
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path $PSScriptRoot -Parent
$environmentFile = Join-Path $repoRoot ".env.public"
$composeFile = Join-Path $repoRoot "docker-compose.public.yml"

if (-not (Test-Path -LiteralPath $environmentFile)) {
    throw "缺少 .env.public。请复制 .env.public.example 并填写域名和密钥。"
}

$required = @(
    "PUBLIC_DOMAIN",
    "POSTGRES_PASSWORD",
    "PUBLIC_INVITE_CODE",
    "ADMIN_API_TOKEN",
    "SECURITY_HMAC_SECRET",
    "DASHSCOPE_API_KEY"
)
$values = @{}
foreach ($line in Get-Content -LiteralPath $environmentFile) {
    if ($line -match "^([A-Z0-9_]+)=(.*)$") {
        $values[$Matches[1]] = $Matches[2].Trim()
    }
}
foreach ($name in $required) {
    $value = [string]$values[$name]
    if ([string]::IsNullOrWhiteSpace($value) -or $value -match "replace-with|example\.com") {
        throw "$name 尚未配置为真实值。"
    }
}
foreach ($name in "POSTGRES_PASSWORD", "PUBLIC_INVITE_CODE", "ADMIN_API_TOKEN", "SECURITY_HMAC_SECRET") {
    if ([string]$values[$name].Length -lt 16) {
        throw "$name 至少需要 16 个字符。"
    }
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "未找到 Docker。请先安装 Docker Engine 与 Compose 插件。"
}

Push-Location $repoRoot
try {
    & docker compose --env-file $environmentFile -f $composeFile config --quiet
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose 配置校验失败。"
    }
    Write-Host "公网部署配置校验通过，未输出任何密钥。" -ForegroundColor Green
    if (-not $ValidateOnly) {
        & docker compose --env-file $environmentFile -f $composeFile up -d --build
        if ($LASTEXITCODE -ne 0) {
            throw "公网服务启动失败。"
        }
        Write-Host ("部署已启动：https://" + $values["PUBLIC_DOMAIN"]) -ForegroundColor Green
    }
} finally {
    Pop-Location
}
