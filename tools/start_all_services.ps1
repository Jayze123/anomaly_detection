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

function Get-PortOwners {
  param([int]$Port)
  $conns = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
  if (-not $conns) { return @() }
  $pids = $conns | Select-Object -ExpandProperty OwningProcess -Unique
  $owners = @()
  foreach ($pid in $pids) {
    $p = Get-CimInstance Win32_Process -Filter "ProcessId=$pid" -ErrorAction SilentlyContinue
    if ($p) {
      $owners += "$($p.Name) (PID $pid)"
    } else {
      $owners += "PID $pid"
    }
  }
  return $owners
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

  if (-not (Test-ProcessCommandContains "python -m app.main")) {
    Start-Process -FilePath powershell -ArgumentList @(
      "-NoProfile",
      "-ExecutionPolicy", "Bypass",
      "-Command", "cd `"$indexDir`"; python -m app.main"
    )
    Start-Sleep -Seconds 2
    if (-not (Test-ProcessCommandContains "python -m app.main")) {
      $owners = Get-PortOwners -Port 8080
      if ($owners.Count -gt 0) {
        Write-Host "Warning: app service did not start. Port 8080 is in use by: $($owners -join ', ')"
      } else {
        Write-Host "Warning: app service did not start. Check startup logs in the new PowerShell window."
      }
    }
  }
} else {
  Set-Location $repoRoot
  python -m pip install -r requirements.txt

  if (-not (Test-ProcessCommandContains "python -m uvicorn src.api:app --reload")) {
    Start-Process -FilePath powershell -ArgumentList @(
      "-NoProfile",
      "-ExecutionPolicy", "Bypass",
      "-Command", "cd `"$repoRoot`"; python -m uvicorn src.api:app --reload"
    )
    Start-Sleep -Seconds 2
    if (-not (Test-ProcessCommandContains "python -m uvicorn src.api:app --reload")) {
      $owners = Get-PortOwners -Port 8000
      if ($owners.Count -gt 0) {
        Write-Host "Warning: fallback service did not start. Port 8000 is in use by: $($owners -join ', ')"
      } else {
        Write-Host "Warning: fallback service did not start. Check startup logs in the new PowerShell window."
      }
    }
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
