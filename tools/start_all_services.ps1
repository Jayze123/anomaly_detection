$repoRoot = Split-Path -Parent $PSScriptRoot
$nestedDir = Join-Path $repoRoot "anomaly_inspection"

# Prefer the directory that actually contains pyproject.toml.
if (Test-Path (Join-Path $repoRoot "pyproject.toml")) {
  $indexDir = $repoRoot
} elseif (Test-Path (Join-Path $nestedDir "pyproject.toml")) {
  $indexDir = $nestedDir
} else {
  $indexDir = $null
}

function Test-PortListening {
  param([int]$Port)
  $conn = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
  return $null -ne $conn
}

function Test-ProcessCommandContains {
  param([string]$Needle)
  $procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -and $_.CommandLine -like "*$Needle*"
  }
  return ($procs.Count -gt 0)
}

if ($indexDir) {
  Set-Location $indexDir

  if (Get-Command docker -ErrorAction SilentlyContinue) {
    docker compose up -d db
  }

  python -m pip install -e .

  if ((-not (Test-PortListening -Port 8080)) -and (-not (Test-ProcessCommandContains "python -m app.main"))) {
    Start-Process -FilePath powershell -ArgumentList @(
      "-NoProfile",
      "-ExecutionPolicy", "Bypass",
      "-Command", "cd `"$indexDir`"; python -m app.main"
    )
  }
} else {
  Set-Location $repoRoot
  python -m pip install -r requirements.txt

  if ((-not (Test-PortListening -Port 8000)) -and (-not (Test-ProcessCommandContains "python -m uvicorn src.api:app --reload"))) {
    Start-Process -FilePath powershell -ArgumentList @(
      "-NoProfile",
      "-ExecutionPolicy", "Bypass",
      "-Command", "cd `"$repoRoot`"; python -m uvicorn src.api:app --reload"
    )
  }
}

$autoUpdateCmd = "cd `"$repoRoot`"; python tools/auto_commit.py"
if (-not (Test-ProcessCommandContains "python tools/auto_commit.py")) {
  Start-Process -FilePath powershell -ArgumentList @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-Command", $autoUpdateCmd
  )
}

Write-Host "Services started."
Write-Host "App URL: http://127.0.0.1:8080 (or http://127.0.0.1:8000 fallback mode)"
