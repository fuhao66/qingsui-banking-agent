[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path $PSScriptRoot -Parent
$environmentFile = Join-Path $repoRoot ".env.public"
if (-not (Test-Path -LiteralPath $environmentFile)) {
    throw "缺少 .env.public。"
}
$values = @{}
foreach ($line in Get-Content -LiteralPath $environmentFile) {
    if ($line -match "^([A-Z0-9_]+)=(.*)$") {
        $values[$Matches[1]] = $Matches[2].Trim()
    }
}
$headers = @{ "X-Admin-Token" = $values["ADMIN_API_TOKEN"] }
Invoke-RestMethod -Uri ("https://" + $values["PUBLIC_DOMAIN"] + "/api/v1/admin/experience-stats") -Headers $headers
