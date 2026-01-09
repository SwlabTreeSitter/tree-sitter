param(
  [switch]$SkipParse,
  [switch]$SkipCollect,
  [switch]$SkipAddon
)

$ErrorActionPreference = "Stop"

# ===== 경로 =====
$ROOT = "C:\PL"
$TS   = Join-Path $ROOT "tree-sitter"
$LANG = Join-Path $ROOT "tree-sitter-smallbasic"
$EXT  = Join-Path $ROOT "moniExtension\Small-Basic-Extension"

$TS_EXE = Join-Path $TS "target\debug\tree-sitter.exe"

# VS 2022 vcvars64
$VS_VCVARS = "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"

function Assert-Path($p, $name) {
  if (!(Test-Path $p)) { throw "Missing ${name}: ${p}" }
}

Write-Host "=== [0] sanity checks ==="
Assert-Path $TS   "tree-sitter repo"
Assert-Path $LANG "tree-sitter-smallbasic repo"
Assert-Path $EXT  "Small-Basic-Extension"
Assert-Path (Join-Path $EXT "binding.gyp") "binding.gyp"
Assert-Path (Join-Path $EXT "native\src\addon.cc") "addon.cc"
Assert-Path $VS_VCVARS "vcvars64.bat"

Write-Host "=== [1] cargo build (tree-sitter core CLI) ==="
Push-Location $TS
cargo build
Pop-Location
Assert-Path $TS_EXE "tree-sitter.exe"

Write-Host "=== [2] generate/build (tree-sitter-smallbasic) ==="
Push-Location $LANG
& $TS_EXE generate --debug-build
& $TS_EXE build --debug
Pop-Location

if (-not $SkipParse) {
  Write-Host "=== [3] optional parse smoke test ==="
  $sample = Join-Path $LANG "examples\smallbasic\01_HelloWorld.sb"
  if (Test-Path $sample) {
    Push-Location $LANG
    & $TS_EXE parse --debug pretty $sample
    Pop-Location
  } else {
    Write-Host "   (skip) sample not found: $sample"
  }
}

Write-Host "=== [4] rebuild TreeSitterCutFile.exe (cl) ==="
# vcvars64.bat 로드 후 같은 cmd 세션에서 cl 실행
$clLine = 'cl TreeSitterCutFile.cpp lib/src/lib.c /MD /EHsc /std:c++17 /I./lib/include /I./lib/src /Fe:TreeSitterCutFile.exe'
$cmd = "`"$VS_VCVARS`" && cd /d `"$TS`" && del /q TreeSitterCutFile.exe 2>nul & $clLine"
cmd /c $cmd | Out-Host
Assert-Path (Join-Path $TS "TreeSitterCutFile.exe") "TreeSitterCutFile.exe"

if (-not $SkipCollect) {
  Write-Host "=== [5] run collection + per-file JSON ==="
  Push-Location $TS
  python .\batch_collect_win.py
  python .\per_file_json.py
  Pop-Location
} else {
  Write-Host "   (skip) collection/json"
}

if (-not $SkipAddon) {
  Write-Host "=== [6] rebuild VSCode addon (.node) ==="
  Push-Location $EXT

  # 의존성 설치 (이미 있으면 빠르게 끝남)
  if (Test-Path ".\package-lock.json") { npm ci } else { npm install }

  # binding.gyp가 루트에 있으니 "루트에서" rebuild가 정답
  # node-gyp가 로컬 의존성으로 잡혀있으니 npx 권장
  npx node-gyp rebuild

  Pop-Location

  # 산출물 확인(대부분 build\Release\sb_parser_addon.node)
  $nodeOut = Join-Path $EXT "build\Release\sb_parser_addon.node"
  if (Test-Path $nodeOut) {
    Write-Host "   addon built: $nodeOut"
  } else {
    Write-Host "   (warn) addon output not found at $nodeOut (check node-gyp output path)"
  }
} else {
  Write-Host "   (skip) addon rebuild"
}

Write-Host ""
Write-Host "✅ DONE: full rebuild pipeline completed."
