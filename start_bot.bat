@echo off
title Hermes Agent 24/7 Global Runner (Cloudflare + Telegram)
cd /d "%~dp0"
powershell.exe -ExecutionPolicy Bypass -NoExit -File "%~dp0run_24_7.ps1"
pause
