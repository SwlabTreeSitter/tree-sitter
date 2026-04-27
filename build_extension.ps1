# ============================================================
# build_extension.ps1
# run_pipeline_all.sh --build-only 의 Windows 포트.
# code-completion-extension 사용에 필요한 빌드를 한 번에 수행한다.
#
# 단계:
#   [1] tree-sitter Rust lib (cargo) + TreeSitterCutFile.exe (cl)
#   [2] code-completion-extension/ 의 npm 의존성 설치
#   [3] generate_build_config.py (binding.gyp 자동 생성)
#   [4] node-gyp rebuild (네이티브 addon 빌드)
#
# 평가 파이프라인은 실행하지 않는다 (run_pipeline_all.sh의 --build-only 와 동일).
# ============================================================

#Requires -Version 5.0
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root      = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$TsDir     = Join-Path $Root "tree-sitter"
$ExtDir    = Join-Path $Root "code-completion-extension"

Write-Host "  [ALL] Building TreeSitterCutFile.exe + VSCode addon..."

# [1] tree-sitter + TreeSitterCutFile.exe
& (Join-Path $TsDir "rebuild_ts_and_exe.ps1")
if ($LASTEXITCODE -ne 0) { throw "rebuild_ts_and_exe.ps1 failed" }

# [2~4] VSCode addon
if (-not (Test-Path $ExtDir)) {
    Write-Host "  [ALL] code-completion-extension not found at $ExtDir (skip addon build)"
    exit 0
}

Set-Location $ExtDir

if (Test-Path "package-lock.json") {
    npm ci --silent
} else {
    npm install --silent
}
if ($LASTEXITCODE -ne 0) { throw "npm install/ci failed" }

python generate_build_config.py
if ($LASTEXITCODE -ne 0) { throw "generate_build_config.py failed" }

npx node-gyp rebuild
if ($LASTEXITCODE -ne 0) { throw "node-gyp rebuild failed" }

Write-Host "  [ALL] VSCode addon rebuild done."
Set-Location $TsDir

Write-Host ""
Write-Host "  [ALL] --build-only: build finished, skipping evaluation."
