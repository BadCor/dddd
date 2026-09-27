param(
    [string]$Exe = ".\release\VoiceAssistant\VoiceAssistant.exe"
)
$ErrorActionPreference = "Stop"
if (-not (Test-Path $Exe)) { throw "Executable not found: $Exe" }

$p = Start-Process -FilePath (Resolve-Path $Exe) -PassThru
Start-Sleep -Seconds 5
if ($p.HasExited) {
    throw "VoiceAssistant.exe exited during startup with code $($p.ExitCode)."
}
$p.CloseMainWindow() | Out-Null
if (-not $p.WaitForExit(5000)) {
    Stop-Process -Id $p.Id -Force
    throw "Executable did not close within the smoke-test timeout."
}
Write-Host "Packaged startup/clean-close smoke test passed."
