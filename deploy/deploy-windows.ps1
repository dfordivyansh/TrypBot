# TrypBot Windows Deployment Script
# Run this on Windows EC2 t3.micro
# Usage: Right-click -> Run with PowerShell

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "TrypBot Windows Deployment Script" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# Check if running as Administrator
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "ERROR: This script must be run as Administrator" -ForegroundColor Red
    Write-Host "Right-click the script and select 'Run as Administrator'" -ForegroundColor Yellow
    exit 1
}

# Set paths
$ProjectPath = "C:\Users\dford\Desktop\src"
$VenvPath = "$ProjectPath\.venv"
$PythonExe = "$VenvPath\Scripts\python.exe"
$PipExe = "$VenvPath\Scripts\pip.exe"
$BackupPath = "C:\Users\dford\Desktop\backups\$(Get-Date -Format 'yyyyMMdd_HHmmss')"

Write-Host "Project Path: $ProjectPath" -ForegroundColor Green
Write-Host "Virtual Environment: $VenvPath" -ForegroundColor Green
Write-Host ""

# Create backup directory
Write-Host "Step 1: Creating backup..." -ForegroundColor Yellow
New-Item -ItemType Directory -Force -Path $BackupPath | Out-Null
if (Test-Path "$ProjectPath\convoapi\settings.py") {
    Copy-Item "$ProjectPath\convoapi\settings.py" "$BackupPath\"
    Write-Host "✓ Backed up settings.py" -ForegroundColor Green
}
if (Test-Path "$ProjectPath\convoapi\asgi.py") {
    Copy-Item "$ProjectPath\convoapi\asgi.py" "$BackupPath\"
    Write-Host "✓ Backed up asgi.py" -ForegroundColor Green
}
Write-Host "Backups saved to: $BackupPath" -ForegroundColor Green
Write-Host ""

# Install Redis (if not installed)
Write-Host "Step 2: Checking Redis..." -ForegroundColor Yellow
$RedisInstalled = Get-Service redis-server -ErrorAction SilentlyContinue
if (-not $RedisInstalled) {
    Write-Host "Redis not found. Installing Redis for Windows..." -ForegroundColor Yellow
    # Download Redis for Windows
    $RedisUrl = "https://github.com/microsoftarchive/redis/releases/download/win-3.2.100/Redis-x64-3.2.100.zip"
    $RedisZip = "$env:TEMP\redis.zip"
    $RedisPath = "C:\Redis"
    
    Write-Host "Downloading Redis..." -ForegroundColor Yellow
    Invoke-WebRequest -Uri $RedisUrl -OutFile $RedisZip
    
    Write-Host "Extracting Redis..." -ForegroundColor Yellow
    Expand-Archive -Path $RedisZip -DestinationPath $RedisPath -Force
    
    Write-Host "Installing Redis as service..." -ForegroundColor Yellow
    & "$RedisPath\redis-server.exe" --service-install
    Start-Service redis-server
    Set-Service redis-server -StartupType Automatic
    
    Write-Host "✓ Redis installed and started" -ForegroundColor Green
    Remove-Item $RedisZip -Force
} else {
    Write-Host "✓ Redis already installed" -ForegroundColor Green
    $RedisStatus = Get-Service redis-server
    if ($RedisStatus.Status -ne "Running") {
        Write-Host "Starting Redis..." -ForegroundColor Yellow
        Start-Service redis-server
        Write-Host "✓ Redis started" -ForegroundColor Green
    }
}
Write-Host ""

# Activate virtual environment and install dependencies
Write-Host "Step 3: Installing Python dependencies..." -ForegroundColor Yellow
if (Test-Path $VenvPath) {
    & $PipExe install --upgrade pip
    & $PipExe install -r "$ProjectPath\requirements.txt"
    Write-Host "✓ Dependencies installed" -ForegroundColor Green
} else {
    Write-Host "ERROR: Virtual environment not found at $VenvPath" -ForegroundColor Red
    exit 1
}
Write-Host ""

# Run database migrations
Write-Host "Step 4: Running database migrations..." -ForegroundColor Yellow
Set-Location $ProjectPath
& $PythonExe manage.py migrate
Write-Host "✓ Migrations completed" -ForegroundColor Green
Write-Host ""

# Collect static files
Write-Host "Step 5: Collecting static files..." -ForegroundColor Yellow
& $PythonExe manage.py collectstatic --noinput
Write-Host "✓ Static files collected" -ForegroundColor Green
Write-Host ""

# Windows Service Configuration
Write-Host "Step 6: Configuring Windows Service..." -ForegroundColor Yellow
# For Windows, we typically use NSSM (Non-Sucking Service Manager)
# This is a placeholder - actual Windows service setup depends on your configuration
Write-Host "NOTE: Windows service configuration requires NSSM or manual setup" -ForegroundColor Yellow
Write-Host "For now, we'll use the existing process manager" -ForegroundColor Yellow
Write-Host ""

# Health check
Write-Host "Step 7: Running health check..." -ForegroundColor Yellow
try {
    $Response = Invoke-WebRequest -Uri "http://127.0.0.1:8000/" -TimeoutSec 10
    if ($Response.StatusCode -eq 200) {
        Write-Host "✓ Application is responding" -ForegroundColor Green
    } else {
        Write-Host "⚠ Application returned HTTP $($Response.StatusCode)" -ForegroundColor Yellow
    }
} catch {
    Write-Host "⚠ Application health check failed. May still be starting up..." -ForegroundColor Yellow
}
Write-Host ""

# Summary
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Deployment Summary" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "✓ Backup location: $BackupPath" -ForegroundColor Green
Write-Host "✓ Redis status:" -ForegroundColor Green
Get-Service redis-server | Select-Object Name, Status
Write-Host ""
Write-Host "⚠ IMPORTANT NOTES FOR WINDOWS EC2 t3.micro:" -ForegroundColor Yellow
Write-Host "  - Instance has only 1GB RAM (limited for production)" -ForegroundColor Yellow
Write-Host "  - Daphne configured for 1 worker only (memory constraints)" -ForegroundColor Yellow
Write-Host "  - Windows service setup requires NSSM (not automated)" -ForegroundColor Yellow
Write-Host "  - Strongly recommend upgrading to t3.large (2 vCPU, 8GB RAM)" -ForegroundColor Yellow
Write-Host ""
Write-Host "To monitor:" -ForegroundColor Cyan
Write-Host "  - Check Redis: redis-cli ping" -ForegroundColor White
Write-Host "  - Check logs: Check your process manager logs" -ForegroundColor White
Write-Host "  - Monitor memory: Task Manager or Get-Process" -ForegroundColor White
Write-Host ""
Write-Host "Deployment completed!" -ForegroundColor Green
