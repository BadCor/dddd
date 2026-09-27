param(
    [switch]$Debug
)
$ErrorActionPreference = "Stop"

if ($env:OS -ne "Windows_NT") {
    throw "This build script must be run on Windows."
}

python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller is not installed. Run: python -m pip install -r requirements-build.txt"
}

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

Remove-Item -Recurse -Force -ErrorAction SilentlyContinue build, dist
New-Item -ItemType Directory -Force release | Out-Null
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue release\VoiceAssistant

if ($Debug) {
    $env:VOICE_ASSISTANT_DEBUG = "1"
} else {
    Remove-Item Env:VOICE_ASSISTANT_DEBUG -ErrorAction SilentlyContinue
}

python -m PyInstaller --clean --noconfirm voice_assistant.spec
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed."
}

New-Item -ItemType Directory -Force release\VoiceAssistant | Out-Null
Copy-Item dist\VoiceAssistant.exe release\VoiceAssistant\VoiceAssistant.exe
Copy-Item README.md release\VoiceAssistant\README.md

Write-Host "Build complete: release\VoiceAssistant\VoiceAssistant.exe"
