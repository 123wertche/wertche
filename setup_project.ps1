param(
    [switch]$CheckOnly,
    [switch]$SkipDownload
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$VenvPython = Join-Path $Root '.venv\Scripts\python.exe'
$NodeDir = Join-Path $Root 'tools\node'
$NodeExe = Join-Path $NodeDir 'node.exe'
$NpmCmd = Join-Path $NodeDir 'npm.cmd'
$LarkDir = Join-Path $Root 'tools\lark'
$Requirements = Join-Path $Root 'requirements.txt'
$NodeArchive = Join-Path $Root 'tools\node-v24.17.0-win-x64.zip'
$NodeUrl = 'https://nodejs.org/dist/v24.17.0/node-v24.17.0-win-x64.zip'
$NodeHash = 'f2aa33b35b75aca5f3f7b85675a6f6423201053e9381911e64961f3bda2528ab'

function Invoke-Checked {
    param([string]$File, [string[]]$Arguments)
    & $File @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "command failed ($LASTEXITCODE): $File"
    }
}

function Test-BootstrapPython {
    param([string]$File, [string[]]$Arguments)
    try {
        & $File @Arguments '-c' 'import sys, venv; assert sys.version_info >= (3, 9)' *> $null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Find-BootstrapPython {
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($python -and (Test-BootstrapPython -File $python.Source -Arguments @())) { return @($python.Source) }
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher -and (Test-BootstrapPython -File $launcher.Source -Arguments @('-3'))) { return @($launcher.Source, '-3') }
    throw 'Python 3 is required to create the project-local .venv. Install Python, then rerun 初始化项目.cmd.'
}

if (-not (Test-Path -LiteralPath $VenvPython) -and -not $CheckOnly) {
    $bootstrap = @(Find-BootstrapPython)
    Invoke-Checked -File $bootstrap[0] -Arguments @($bootstrap[1..($bootstrap.Count - 1)] + @('-m', 'venv', (Join-Path $Root '.venv')))
}

if ((Test-Path -LiteralPath $VenvPython) -and -not $CheckOnly) {
    Invoke-Checked -File $VenvPython -Arguments @('-m', 'pip', 'install', '--disable-pip-version-check', '-r', $Requirements)
}

if (-not (Test-Path -LiteralPath $NodeExe) -and -not $CheckOnly) {
    if ($SkipDownload) { throw 'Project-local Node is missing. Rerun without -SkipDownload while online.' }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $NodeArchive) | Out-Null
    Invoke-WebRequest -Uri $NodeUrl -OutFile $NodeArchive -UseBasicParsing
    $actualHash = (Get-FileHash -LiteralPath $NodeArchive -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $NodeHash) { throw 'Downloaded Node archive failed SHA-256 verification.' }
    $temporary = Join-Path $Root ('tools\node-extract-' + [guid]::NewGuid().ToString('N'))
    Expand-Archive -LiteralPath $NodeArchive -DestinationPath $temporary -Force
    $expanded = Get-ChildItem -LiteralPath $temporary -Directory | Select-Object -First 1
    if ($null -eq $expanded -or -not (Test-Path -LiteralPath (Join-Path $expanded.FullName 'node.exe'))) { throw 'Node archive does not contain node.exe.' }
    New-Item -ItemType Directory -Force -Path $NodeDir | Out-Null
    Copy-Item -Path (Join-Path $expanded.FullName '*') -Destination $NodeDir -Recurse -Force
    Remove-Item -LiteralPath $temporary -Recurse -Force
    Remove-Item -LiteralPath $NodeArchive -Force
}

if ((Test-Path -LiteralPath $NpmCmd) -and -not $CheckOnly) {
    Invoke-Checked -File $NpmCmd -Arguments @('ci', '--prefix', $LarkDir, '--ignore-scripts')
}

if (Test-Path -LiteralPath $VenvPython) {
    & $VenvPython (Join-Path $Root 'preflight_douyin.py') '--json'
    exit $LASTEXITCODE
}

Write-Output '{"ok":false,"hint":"Project Python is missing. Run 初始化项目.cmd without -CheckOnly after installing Python 3."}'
exit 1
