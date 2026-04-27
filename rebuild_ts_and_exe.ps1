# ============================================================
# rebuild_ts_and_exe.ps1
# rebuild_ts_and_exe.sh 의 Windows 포트.
# tree-sitter Rust 라이브러리(cargo) + TreeSitterCutFile.exe (cl) 를 빌드한다.
# ============================================================

#Requires -Version 5.0
$ErrorActionPreference = "Stop"

# 스크립트 위치 기준 절대경로 자동 계산 (parent/tree-sitter 구조 가정)
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root      = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$TsDir     = Join-Path $Root "tree-sitter"
$ExeName   = "TreeSitterCutFile.exe"

Write-Host "=== [1] Cargo Build (Tree-sitter lib) ==="
Set-Location $TsDir
cargo build
if ($LASTEXITCODE -ne 0) { throw "cargo build failed" }

Write-Host ""
Write-Host "=== [2] Rebuild TreeSitterCutFile (cl) ==="
Get-ChildItem -Path $TsDir -Filter "*.obj" -File -ErrorAction SilentlyContinue | Remove-Item -Force
if (Test-Path $ExeName) { Remove-Item $ExeName -Force }

Write-Host " -> Compiling and linking with cl..."
# cl 은 `vcvarsall.bat x64` (또는 Developer PowerShell for VS) 환경에서 실행되어야 한다.
& cl TreeSitterCutFile.cpp lib/src/lib.c `
     /MD /EHsc /std:c++17 `
     /I./lib/include /I./lib/src `
     "/Fe:$ExeName"
if ($LASTEXITCODE -ne 0) { throw "cl build failed (Developer PowerShell 환경에서 실행했는지 확인하세요)" }

if (-not (Test-Path $ExeName)) {
    Write-Host " -> Build failed"
    exit 1
}

Write-Host " -> Build success: $ExeName"
Write-Host ""
Write-Host "DONE."
