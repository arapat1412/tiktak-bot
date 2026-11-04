param([switch]$Desktop, [switch]$Test)
Set-Location $PSScriptRoot
$env:PATH = "C:\Bot\tools\platform-tools;" + $env:PATH
$env:ADBUTILS_ADB_PATH = 'C:\Bot\tools\platform-tools\adb.exe'
$env:TAKTIK_DB_PATH = Join-Path $PSScriptRoot 'data\taktik-data.db'
New-Item -ItemType Directory -Force (Join-Path $PSScriptRoot 'data\tmp') | Out-Null
$env:TEMP = Join-Path $PSScriptRoot 'data\tmp'
$env:TMP = $env:TEMP
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if ($Test) { & $python -m pytest @args }
elseif ($Desktop) { & $python -m customer_desktop @args }
else { & $python -m taktik @args }
exit $LASTEXITCODE

