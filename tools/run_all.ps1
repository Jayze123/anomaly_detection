$repoRoot = Split-Path -Parent $PSScriptRoot
$indexDir = Join-Path $repoRoot "anomaly_inspection"

if (Test-Path $indexDir) {
  Set-Location $indexDir
  python -m pip install -e .
  python -m app.main
} else {
  Set-Location $repoRoot
  python -m pip install -r requirements.txt
  python -m uvicorn src.api:app --reload
}
