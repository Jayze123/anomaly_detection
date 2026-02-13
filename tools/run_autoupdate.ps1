$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
python tools/auto_commit.py
