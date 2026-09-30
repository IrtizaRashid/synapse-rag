param(
  [string]$OutputDir = "backups"
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$output = Join-Path $root $OutputDir
New-Item -ItemType Directory -Force -Path $output | Out-Null

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$archive = Join-Path $output "rag-platform-local-$stamp.zip"
$temp = Join-Path $env:TEMP "rag-platform-backup-$stamp"

New-Item -ItemType Directory -Force -Path $temp | Out-Null

try {
  $data = Join-Path $root "data"
  if (Test-Path $data) {
    Copy-Item -LiteralPath $data -Destination (Join-Path $temp "data") -Recurse -Force
  }

  foreach ($name in @("README.md", "N8N.md", "PRODUCTION.md", "docker-compose.yml", "docker-compose.n8n.yml", "Caddyfile")) {
    $path = Join-Path $root $name
    if (Test-Path $path) {
      Copy-Item -LiteralPath $path -Destination (Join-Path $temp $name) -Force
    }
  }

  Compress-Archive -Path (Join-Path $temp "*") -DestinationPath $archive -Force
  Write-Output "Created backup: $archive"
  Write-Output "Note: .env and other secret files are intentionally excluded."
}
finally {
  if (Test-Path $temp) {
    Remove-Item -LiteralPath $temp -Recurse -Force
  }
}
