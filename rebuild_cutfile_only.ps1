# TreeSitterCutFile.exe까지만 (core + language + cutfile) 재빌드
# - parse/collect/addon 단계는 전부 스킵

$ErrorActionPreference = "Stop"

$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$ALL = Join-Path $SCRIPT_DIR "rebuild_all.ps1"

if (!(Test-Path $ALL)) {
  throw "Missing rebuild_all.ps1: $ALL"
}

# [0]~[4]만 실행되도록 옵션으로 뒤 단계 차단
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $ALL -SkipParse -SkipCollect -SkipAddon
