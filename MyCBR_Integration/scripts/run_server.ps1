param(
    [int]$Port = 8099,
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
)

$ErrorActionPreference = 'Stop'
$javaHome = 'C:\Program Files\Java\jdk-25'
$java = Join-Path $javaHome 'bin\java.exe'
$sdk = Join-Path $ProjectRoot 'sdk\mycbr.jar'
$binRoot = Join-Path $ProjectRoot 'java\bin'
$runtimeRoot = Join-Path $ProjectRoot 'runtime'

if (-not (Test-Path $java)) {
    throw "Missing java runtime: $java"
}
if (-not (Test-Path $sdk)) {
    throw "Missing SDK jar: $sdk"
}
if (-not (Test-Path $binRoot)) {
    throw "Compiled classes not found. Run build_server.ps1 first."
}

New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
& $java -cp "$binRoot;$sdk" mycbr.integration.MyCBRHttpServer $Port $runtimeRoot
