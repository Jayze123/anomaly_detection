$repoRoot = Split-Path -Parent $PSScriptRoot
$indexDir = Join-Path $repoRoot "anomaly_inspection"

function Test-PortListening {
  param([int]$Port)
  $conn = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
  return $null -ne $conn
}

if (Test-Path $indexDir) {
  Set-Location $indexDir

  if (Get-Command docker -ErrorAction SilentlyContinue) {
    docker compose up -d db
  }

  python -m pip install -e .

  if (-not (Test-PortListening -Port 8080)) {
    Start-Process -FilePath powershell -ArgumentList @(
      "-NoProfile",
      "-ExecutionPolicy", "Bypass",
      "-Command", "cd `"$indexDir`"; python -m app.main"
    )
  }
} else {
  Set-Location $repoRoot
  python -m pip install -r requirements.txt

  if (-not (Test-PortListening -Port 8000)) {
    Start-Process -FilePath powershell -ArgumentList @(
      "-NoProfile",
      "-ExecutionPolicy", "Bypass",
      "-Command", "cd `"$repoRoot`"; python -m uvicorn src.api:app --reload"
    )
  }
}

$autoUpdateCmd = "cd `"$repoRoot`"; python tools/auto_commit.py"
Start-Process -FilePath powershell -ArgumentList @(
  "-NoProfile",
  "-ExecutionPolicy", "Bypass",
  "-Command", $autoUpdateCmd
)

Write-Host "Services started."
Write-Host "App URL: http://127.0.0.1:8080 (or http://127.0.0.1:8000 fallback mode)"
