param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
)

$ErrorActionPreference = 'Stop'
$javaHome = 'C:\Program Files\Java\jdk-25'
$javac = Join-Path $javaHome 'bin\javac.exe'
$sdk = Join-Path $ProjectRoot 'sdk\mycbr.jar'
$srcRoot = Join-Path $ProjectRoot 'java\src'
$binRoot = Join-Path $ProjectRoot 'java\bin'

if (-not (Test-Path $sdk)) {
    throw "Missing SDK jar: $sdk"
}
if (-not (Test-Path $javac)) {
    throw "Missing javac: $javac"
}

New-Item -ItemType Directory -Force -Path $binRoot | Out-Null
$sources = Get-ChildItem -Path $srcRoot -Recurse -Filter *.java | ForEach-Object { $_.FullName }
if (-not $sources) {
    throw "No Java sources found under $srcRoot"
}

& $javac -cp $sdk -d $binRoot $sources
Write-Host "Compiled Java service to $binRoot"
