$ErrorActionPreference = 'Stop'
& py -3 (Join-Path $PSScriptRoot 'install.py') @args
exit $LASTEXITCODE
