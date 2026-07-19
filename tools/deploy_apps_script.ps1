[CmdletBinding()]
param(
  [string]$ScriptId,
  [string]$DeploymentId,
  [switch]$Login
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$bindingPath = Join-Path $repoRoot '.apps-script-deployment.json'
$claspPath = Join-Path $repoRoot '.clasp.json'

function Write-Utf8File([string]$Path, [string]$Content) {
  $encoding = New-Object System.Text.UTF8Encoding($false)
  [System.IO.File]::WriteAllText($Path, $Content + [Environment]::NewLine, $encoding)
}

if (Test-Path $bindingPath) {
  $binding = Get-Content -Raw -Encoding UTF8 $bindingPath | ConvertFrom-Json
  if (-not $ScriptId) { $ScriptId = [string]$binding.scriptId }
  if (-not $DeploymentId) { $DeploymentId = [string]$binding.deploymentId }
}

if (-not $ScriptId -or $ScriptId -notmatch '^[A-Za-z0-9_-]{20,}$') {
  throw 'A valid Apps Script Script ID is required. Find it in Apps Script > Project Settings > Script ID.'
}
if (-not $DeploymentId -or $DeploymentId -notmatch '^[A-Za-z0-9_-]{5,}$') {
  throw 'A valid web-app Deployment ID is required. Find it in Apps Script > Deploy > Manage deployments.'
}

$bindingJson = @{ scriptId = $ScriptId; deploymentId = $DeploymentId } | ConvertTo-Json
$claspJson = @{ scriptId = $ScriptId; rootDir = '.' } | ConvertTo-Json
Write-Utf8File $bindingPath $bindingJson
Write-Utf8File $claspPath $claspJson

Push-Location $repoRoot
try {
  if ($Login) {
    & npx --yes @google/clasp@latest login
    if ($LASTEXITCODE -ne 0) { throw 'Google authorization for clasp failed.' }
  }

  & npx --yes @google/clasp@latest push --force
  if ($LASTEXITCODE -ne 0) { throw 'Apps Script source push failed.' }

  $release = 'HVHN Apps Script ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
  & npx --yes @google/clasp@latest deploy --deploymentId $DeploymentId --description $release
  if ($LASTEXITCODE -ne 0) { throw 'Web-app deployment update failed.' }

  Write-Host 'Apps Script source and web-app deployment were updated together.'
} finally {
  Pop-Location
}
