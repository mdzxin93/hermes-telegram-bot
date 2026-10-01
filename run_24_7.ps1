# ==============================================================================
# Hermes Agent - 24/7 Global Supervisor (Cloudflare + Dashboard + Telegram)
# ==============================================================================
param(
    [switch]$NoDashboard,
    [switch]$NoCloudflare
)

$OutputEncoding = [System.Console]::OutputEncoding = [System.Console]::InputEncoding = [System.Text.Encoding]::UTF8
$repo = $PSScriptRoot

Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host "  Hermes Agent - 24/7 Global Runner (Cloudflare + Telegram)" -ForegroundColor Green
Write-Host "==================================================================" -ForegroundColor Cyan

# 1. Ensure logs directory exists
$logDir = Join-Path $repo "logs"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}
$telegramLog = Join-Path $logDir "telegram_hermes.log"
$cloudflareLog = Join-Path $logDir "cloudflare.log"
$dashboardLog = Join-Path $logDir "dashboard.log"

# 2. Check .env configuration
$envFile = Join-Path $repo ".env"
if (-not (Test-Path $envFile)) {
    Write-Host "[!] .env file not found at $envFile" -ForegroundColor Red
    Write-Host "Please copy .env.example to .env and configure your keys." -ForegroundColor Yellow
    exit 1
}

$envContent = Get-Content $envFile -Raw

# 3. Locate Python executable in Hermes runtime
$pyCandidates = @(
    (Get-ChildItem -Path "$env:LOCALAPPDATA\hermes\installs\*\environments\*\venv\Scripts\python.exe" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName -First 1),
    "$repo\.venv\Scripts\python.exe",
    "$repo\venv\Scripts\python.exe"
)
$pythonExe = $null
foreach ($cand in $pyCandidates) {
    if ($cand -and (Test-Path $cand)) {
        $pythonExe = $cand
        break
    }
}

if (-not $pythonExe) {
    Write-Host "[!] Could not find Hermes Python runtime. Running bootstrap setup..." -ForegroundColor Yellow
    & powershell.exe -ExecutionPolicy Bypass -File "$repo\setup-hermes.ps1" -RuntimeOnly
    $pythonExe = (Get-ChildItem -Path "$env:LOCALAPPDATA\hermes\installs\*\environments\*\venv\Scripts\python.exe" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName -First 1)
}

if (-not $pythonExe) {
    Write-Host "[X] Failed to locate Hermes Python runtime. Please run setup-hermes.ps1" -ForegroundColor Red
    exit 1
}

Write-Host "[+] Hermes Python runtime: $pythonExe" -ForegroundColor Green

# Array to keep track of child background processes for clean shutdown
$childProcesses = [System.Collections.Generic.List[System.Diagnostics.Process]]::new()

function Cleanup-Services {
    Write-Host "`nStopping background services..." -ForegroundColor Yellow
    foreach ($proc in $childProcesses) {
        if ($proc -and (-not $proc.HasExited)) {
            try {
                Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
            } catch {}
        }
    }
}

# 4. Start Hermes Web Dashboard (Local Port 9119)
if (-not $NoDashboard) {
    Write-Host "`n[*] Launching Hermes Web Dashboard on http://127.0.0.1:9119..." -ForegroundColor Cyan
    $webDistPath = Join-Path $repo "hermes_cli\web_dist"
    $env:HERMES_WEB_DIST = $webDistPath
    $dashPsi = New-Object System.Diagnostics.ProcessStartInfo
    $dashPsi.FileName = $pythonExe
    $dashPsi.Arguments = "hermes_cli/main.py dashboard --host 127.0.0.1 --port 9119 --no-open --skip-build"
    $dashPsi.WorkingDirectory = $repo
    $dashPsi.UseShellExecute = $false
    $dashPsi.RedirectStandardOutput = $true
    $dashPsi.RedirectStandardError = $true
    $dashPsi.EnvironmentVariables["HERMES_WEB_DIST"] = $webDistPath
    
    $dashProc = New-Object System.Diagnostics.Process
    $dashProc.StartInfo = $dashPsi
    [void]$dashProc.Start()
    $childProcesses.Add($dashProc)
    Write-Host "[+] Hermes Dashboard started (PID: $($dashProc.Id))" -ForegroundColor Green
}

# 5. Start Cloudflare Global Tunnel
if (-not $NoCloudflare) {
    $cfExe = Join-Path $repo "cloudflared.exe"
    if (-not (Test-Path $cfExe)) {
        Write-Host "Downloading cloudflared.exe..." -ForegroundColor Cyan
        Invoke-WebRequest -Uri "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" -OutFile $cfExe
    }

    $cfToken = $null
    if ($envContent -match "CLOUDFLARE_TUNNEL_TOKEN=([^\r\n#]+)") {
        $rawToken = $matches[1].Trim()
        if ($rawToken -and ($rawToken -ne "your_cloudflare_tunnel_token_here")) {
            $cfToken = $rawToken
        }
    }

    if ($cfToken) {
        Write-Host "`n[*] Starting Cloudflare Named Tunnel with token..." -ForegroundColor Cyan
        $cfArgs = "tunnel --no-autoupdate run --token $cfToken"
    } else {
        Write-Host "`n[*] Starting Cloudflare Global Quick Tunnel for http://127.0.0.1:9119..." -ForegroundColor Cyan
        $cfArgs = "tunnel --url http://127.0.0.1:9119 --http-host-header 127.0.0.1 --metrics 127.0.0.1:20241"
    }

    # Clear prior log
    "" | Out-File -FilePath $cloudflareLog -Encoding utf8

    $cfPsi = New-Object System.Diagnostics.ProcessStartInfo
    $cfPsi.FileName = $cfExe
    $cfPsi.Arguments = $cfArgs
    $cfPsi.WorkingDirectory = $repo
    $cfPsi.UseShellExecute = $false
    $cfPsi.RedirectStandardOutput = $true
    $cfPsi.RedirectStandardError = $true

    $cfProc = New-Object System.Diagnostics.Process
    $cfProc.StartInfo = $cfPsi
    
    $cfOutHandler = {
        if (-not [string]::IsNullOrEmpty($EventArgs.Data)) {
            $EventArgs.Data | Out-File -FilePath $using:cloudflareLog -Append -Encoding utf8
        }
    }
    Register-ObjectEvent -InputObject $cfProc -EventName OutputDataReceived -Action $cfOutHandler | Out-Null
    Register-ObjectEvent -InputObject $cfProc -EventName ErrorDataReceived -Action $cfOutHandler | Out-Null

    [void]$cfProc.Start()
    $cfProc.BeginOutputReadLine()
    $cfProc.BeginErrorReadLine()
    $childProcesses.Add($cfProc)

    # Wait briefly to extract the global Cloudflare URL
    if (-not $cfToken) {
        Write-Host "Resolving Cloudflare global Anycast URL..." -ForegroundColor DarkGray
        $globalUrl = $null
        for ($i = 0; $i -lt 15; $i++) {
            Start-Sleep -Seconds 1
            try {
                $qt = Invoke-RestMethod -Uri "http://127.0.0.1:20241/quicktunnel" -TimeoutSec 1 -ErrorAction SilentlyContinue
                if ($qt -and $qt.hostname) {
                    $globalUrl = "https://$($qt.hostname)"
                    break
                }
            } catch {}
            if (Test-Path $cloudflareLog) {
                $content = Get-Content $cloudflareLog -Raw -ErrorAction SilentlyContinue
                if ($content -match "https://[a-zA-Z0-9-]+\.trycloudflare\.com") {
                    $globalUrl = $matches[0]
                    break
                }
            }
        }
        if ($globalUrl) {
            Write-Host "`n==================================================================" -ForegroundColor Green
            Write-Host " HERMES IS NOW ACCESSIBLE GLOBALLY VIA CLOUDFLARE:" -ForegroundColor Green
            Write-Host " URL: $globalUrl" -ForegroundColor Cyan
            Write-Host "==================================================================" -ForegroundColor Green
        } else {
            Write-Host "Cloudflare tunnel is active. Check $cloudflareLog for connection logs." -ForegroundColor Yellow
        }
    } else {
        Write-Host "[+] Cloudflare Tunnel connected to your Zero Trust domain." -ForegroundColor Green
    }
}

# 6. Telegram Bot 24/7 Supervisor Watchdog Loop
Write-Host "`n[*] Starting Hermes Telegram Bot 24/7 Watchdog Supervisor for @Hsbzbz_bot..." -ForegroundColor Green
Write-Host "Press Ctrl+C to terminate all services.`n" -ForegroundColor DarkGray

try {
    $restartDelay = 5
    while ($true) {
        $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        Write-Host "[$timestamp] Starting Hermes Telegram Bot service..." -ForegroundColor Cyan
        "[$timestamp] === Hermes Telegram service started ===" | Out-File -FilePath $telegramLog -Append -Encoding utf8
        
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $pythonExe
        $psi.Arguments = "telegram_hermes.py"
        $psi.WorkingDirectory = $repo
        $psi.UseShellExecute = $false
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
        $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8

        $process = New-Object System.Diagnostics.Process
        $process.StartInfo = $psi

        $outHandler = {
            if (-not [string]::IsNullOrEmpty($EventArgs.Data)) {
                Write-Host $EventArgs.Data
                $EventArgs.Data | Out-File -FilePath $using:telegramLog -Append -Encoding utf8
            }
        }

        Register-ObjectEvent -InputObject $process -EventName OutputDataReceived -Action $outHandler | Out-Null
        Register-ObjectEvent -InputObject $process -EventName ErrorDataReceived -Action $outHandler | Out-Null

        try {
            [void]$process.Start()
            $process.BeginOutputReadLine()
            $process.BeginErrorReadLine()
            $process.WaitForExit()
            $exitCode = $process.ExitCode
        } catch {
            Write-Host "Error launching Telegram bot: $_" -ForegroundColor Red
            $exitCode = -1
        }

        $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        Write-Host "[$timestamp] Telegram Bot process exited with code $exitCode." -ForegroundColor Yellow
        "[$timestamp] Process exited with code $exitCode." | Out-File -FilePath $telegramLog -Append -Encoding utf8

        if ($exitCode -eq 0) {
            Write-Host "Process terminated cleanly. Exiting supervisor." -ForegroundColor Cyan
            break
        }

        Write-Host "Restarting Telegram Bot in 5 seconds..." -ForegroundColor Yellow
        Start-Sleep -Seconds 5
    }
} finally {
    Cleanup-Services
}
