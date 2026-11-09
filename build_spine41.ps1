$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$vs = "C:\Program Files\Microsoft Visual Studio\18\Community"
Import-Module "$vs\Common7\Tools\Microsoft.VisualStudio.DevShell.dll"
Enter-VsDevShell -VsInstallPath $vs -SkipAutomaticLocation -DevCmdArguments "-arch=x64 -no_logo" | Out-Null
$src = Join-Path $root "native\spine-runtimes-4.1\spine-c\spine-c"
$incs = Join-Path $src "include"
$obj = Join-Path $root "native\obj41"
New-Item -ItemType Directory -Force -Path $obj | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $root "native\out") | Out-Null
$srcs = @(Get-ChildItem (Join-Path $src "src\spine\*.c") | ForEach-Object { $_.FullName }) + (Join-Path $root "native\build\spine_stub.c") + (Join-Path $root "native\build\spine_renpy.c")
$out = Join-Path $root "native\out\spine4.1.dll"
& cl /nologo /O2 /LD /D_CRT_SECURE_NO_WARNINGS /FI (Join-Path $root "native\build\export_config.h") /D "SPINE_RENPY_VER=41" /I $incs /Fo"$obj\\" @srcs /link /OUT:$out
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Output "built $out"
