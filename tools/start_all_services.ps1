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
  foreach ($procId in $pids) {
    $p = Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue
    if ($p) {
      $owners += "$($p.Name) (PID $procId)"
    } else {
      $owners += "PID $procId"
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

function Get-FreePort {
  param([int[]]$Candidates)
  foreach ($p in $Candidates) {
    if (-not (Test-PortListening -Port $p)) {
      return $p
    }
  }
  return $null
}

if ($indexDir) {
  Set-Location $indexDir

  if (Get-Command docker -ErrorAction SilentlyContinue) {
    docker compose up -d db
  }

  python -m pip install -e .

  if (-not (Test-ProcessCommandContains "python -m app.main")) {
    $targetPort = 8080
    $owners8080 = Get-PortOwners -Port 8080
    if ($owners8080.Count -gt 0) {
      $free = Get-FreePort -Candidates @(8081, 8082, 8083)
      if ($free -ne $null) {
        $targetPort = $free
      } else {
        Write-Host "Warning: no free app port found in 8080-8083."
      }
    }
    Start-Process -FilePath powershell -ArgumentList @(
      "-NoProfile",
      "-ExecutionPolicy", "Bypass",
      "-Command", "cd `"$indexDir`"; `$env:APP_PORT=`"$targetPort`"; python -m app.main"
    )
    Start-Sleep -Seconds 2
    if (-not (Test-ProcessCommandContains "python -m app.main")) {
      $owners = Get-PortOwners -Port $targetPort
      if ($owners.Count -gt 0) {
        Write-Host "Warning: app service did not start. Port $targetPort is in use by: $($owners -join ', ')"
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
Write-Host "App URL: check 8080 first, then 8081-8083 fallback (or 8000 in legacy fallback mode)"
