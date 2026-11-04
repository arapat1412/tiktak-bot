param([string]$Python = '', [switch]$SkipEngine)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
Set-Location -LiteralPath $repo
if (-not $Python) { $Python = Join-Path $repo '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $Python)) { throw 'Install requirements-desktop.txt and requirements-build.txt in .venv first.' }

function Invoke-DesktopFreeze([string[]]$BuildArgs) {
    # Host tools can put incompatible ICU/UCRT DLLs on PATH. Resolve dependencies
    # only from the selected Python/packages and Windows, never unrelated apps.
    $savedBuildPath = $env:PATH
    try {
        $env:PATH = "$(Split-Path -Parent $Python);$env:SystemRoot\System32;$env:SystemRoot"
        & $Python -m PyInstaller @BuildArgs
        if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
    } finally { $env:PATH = $savedBuildPath }
}

if (-not $SkipEngine) {
    # Derive the customer wrapper build from the upstream spec so manifest/data
    # collection has one source of truth. Never edit the upstream build definition.
    $source = Get-Content -LiteralPath (Join-Path $repo 'taktik_launcher.spec') -Raw
    $source = $source.Replace('[str(BRIDGES_DIR / "launcher.py")]', '[str(BOT_DIR / "customer_desktop" / "engine_worker.py")]')
    $source = $source.Replace('name="taktik_launcher"', 'name="customer_engine"')
    if (-not $source.Contains('customer_desktop" / "engine_worker.py')) { throw 'Upstream spec format changed; inspect build definition.' }
    $spec = Join-Path $repo 'customer_engine.generated.spec'
    try {
        [System.IO.File]::WriteAllText($spec, $source, [System.Text.UTF8Encoding]::new($false))
        Invoke-DesktopFreeze -BuildArgs @('--noconfirm','--clean','--distpath','dist\customer-engine','--workpath','build\customer-engine',$spec)
    } finally {
        if (Test-Path -LiteralPath $spec) { Remove-Item -LiteralPath $spec }
    }
}
Invoke-DesktopFreeze -BuildArgs @('--noconfirm','--clean','--distpath','dist\customer-desktop','--workpath','build\customer-desktop','customer_desktop\packaging\desktop.spec')
$destination = Join-Path $repo 'dist\customer-desktop\TikTokKorean'
$engineSource = Join-Path $repo 'dist\customer-engine\customer_engine'
if (-not (Test-Path -LiteralPath (Join-Path $engineSource 'customer_engine.exe'))) { throw 'Build the engine first.' }
New-Item -ItemType Directory -Path (Join-Path $destination 'engine') -Force | Out-Null
Copy-Item -Path (Join-Path $engineSource '*') -Destination (Join-Path $destination 'engine') -Recurse -Force
& $Python customer_desktop\packaging\verify_build.py $destination
if ($LASTEXITCODE -ne 0) { throw 'Portable build smoke test failed.' }
foreach ($name in @('LICENSE','NOTICE')) { Copy-Item -LiteralPath (Join-Path $repo $name) -Destination $destination -Force }
Copy-Item -LiteralPath (Join-Path $PSScriptRoot '..\README.vi.md') -Destination (Join-Path $destination 'HUONG-DAN.md') -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot '..\resources') -Destination $destination -Recurse -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'THIRD-PARTY.md') -Destination $destination -Force
& $Python customer_desktop\packaging\collect_licenses.py $destination
if ($LASTEXITCODE -ne 0) { throw 'License inventory failed.' }
& $Python customer_desktop\packaging\package_source.py $destination
if ($LASTEXITCODE -ne 0) { throw 'Corresponding source archive failed.' }
Write-Output "Built: $destination\TikTokKorean.exe"
