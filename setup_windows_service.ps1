# ==============================================================================
# Hermes Agent - Windows 24/7 Background Task Setup
# ==============================================================================
# This script registers a Windows Scheduled Task named "HermesTelegramBot247"
# that starts automatically when you log into Windows, running in the background.

$taskName = "HermesTelegramBot247"
$repo = $PSScriptRoot
$vbsRunner = Join-Path $repo "run_hidden.vbs"
$batRunner = Join-Path $repo "start_bot.bat"

Write-Host "Setting up 24/7 background autostart for Hermes Telegram Bot..." -ForegroundColor Cyan

# Create hidden VBS launcher so no console window is displayed
$vbsContent = @"
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "powershell.exe -ExecutionPolicy Bypass -WindowStyle Hidden -File ""$repo\run_24_7.ps1""", 0, False
"@
[System.IO.File]::WriteAllText($vbsRunner, $vbsContent, [System.Text.Encoding]::ASCII)
Write-Host "✓ Created hidden runner: $vbsRunner" -ForegroundColor Green

# Register Scheduled Task using schtasks
$action = "wscript.exe `"$vbsRunner`""
$cmd = "schtasks /Create /TN `"$taskName`" /TR `"$action`" /SC ONLOGON /RL HIGHEST /F"

Write-Host "Registering Windows task: $taskName" -ForegroundColor Cyan
Invoke-Expression $cmd

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "✅ Hermes Telegram Bot 24/7 service successfully registered!" -ForegroundColor Green
    Write-Host "• It will now start automatically whenever your computer starts / logs in."
    Write-Host "• To start it immediately in the background, run: schtasks /Run /TN `"$taskName`""
    Write-Host "• To stop it: schtasks /End /TN `"$taskName`""
    Write-Host "• To remove it: schtasks /Delete /TN `"$taskName`" /F"
} else {
    Write-Host "⚠️ Could not register task automatically (may require Administrator permissions)." -ForegroundColor Yellow
    Write-Host "You can always run it directly via start_bot.bat" -ForegroundColor Cyan
}
