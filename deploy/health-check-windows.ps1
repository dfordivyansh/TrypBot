# TrypBot Windows Health Check Script
# Run this on Windows EC2 to verify application health

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "TrypBot Windows Health Check" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

$ProjectPath = "C:\Users\dford\Desktop\src"
$PythonExe = "$ProjectPath\.venv\Scripts\python.exe"

# Check 1: Redis
Write-Host "Check 1: Redis Status" -ForegroundColor Cyan
try {
    $RedisOutput = redis-cli ping 2>&1
    if ($RedisOutput -eq "PONG") {
        Write-Host "✓ Redis is responding" -ForegroundColor Green
    } else {
        Write-Host "✗ Redis not responding: $RedisOutput" -ForegroundColor Red
    }
} catch {
    Write-Host "✗ Redis CLI not found or not running" -ForegroundColor Red
}
Write-Host ""

# Check 2: Python Application
Write-Host "Check 2: Python Application" -ForegroundColor Cyan
$DaphneProcesses = Get-Process daphne -ErrorAction SilentlyContinue
if ($DaphneProcesses) {
    Write-Host "✓ Daphne is running ($($DaphneProcesses.Count) process(es))" -ForegroundColor Green
    $DaphneProcesses | ForEach-Object {
        Write-Host "  PID: $($_.Id), CPU: $($_.CPU)%, Memory: $([math]::Round($_.WorkingSet / 1MB, 2)) MB" -ForegroundColor White
    }
} else {
    Write-Host "✗ Daphne is not running" -ForegroundColor Red
}
Write-Host ""

# Check 3: HTTP Response
Write-Host "Check 3: HTTP Response" -ForegroundColor Cyan
try {
    $Response = Invoke-WebRequest -Uri "http://127.0.0.1:8000/" -TimeoutSec 10
    Write-Host "✓ Application is responding (HTTP $($Response.StatusCode))" -ForegroundColor Green
} catch {
    Write-Host "✗ Application not responding: $($_.Exception.Message)" -ForegroundColor Red
}
Write-Host ""

# Check 4: Database
Write-Host "Check 4: Database Connection" -ForegroundColor Cyan
Set-Location $ProjectPath
try {
    $CheckOutput = & $PythonExe manage.py check --deploy 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ Database connection and migrations are valid" -ForegroundColor Green
    } else {
        Write-Host "✗ Database check failed:" -ForegroundColor Red
        Write-Host $CheckOutput -ForegroundColor Red
    }
} catch {
    Write-Host "✗ Database check error: $($_.Exception.Message)" -ForegroundColor Red
}
Write-Host ""

# Check 5: Memory Usage
Write-Host "Check 5: Memory Usage" -ForegroundColor Cyan
$TotalMemory = (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB
$FreeMemory = (Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1GB
$UsedMemory = $TotalMemory - $FreeMemory
$MemoryPercent = [math]::Round(($UsedMemory / $TotalMemory) * 100, 2)

Write-Host "Total Memory: $([math]::Round($TotalMemory, 2)) GB" -ForegroundColor White
Write-Host "Used Memory: $([math]::Round($UsedMemory, 2)) GB ($MemoryPercent%)" -ForegroundColor White
Write-Host "Free Memory: $([math]::Round($FreeMemory, 2)) GB" -ForegroundColor White

if ($MemoryPercent -gt 80) {
    Write-Host "⚠ High memory usage detected!" -ForegroundColor Yellow
} else {
    Write-Host "✓ Memory usage is acceptable" -ForegroundColor Green
}
Write-Host ""

# Check 6: Disk Usage
Write-Host "Check 6: Disk Usage" -ForegroundColor Cyan
$CDrive = Get-PSDrive C
$DiskPercent = [math]::Round(($CDrive.Used / $CDrive.Free) * 100, 2)

Write-Host "Used: $([math]::Round($CDrive.Used / 1GB, 2)) GB" -ForegroundColor White
Write-Host "Free: $([math]::Round($CDrive.Free / 1GB, 2)) GB" -ForegroundColor White

if ($DiskPercent -gt 80) {
    Write-Host "⚠ High disk usage detected!" -ForegroundColor Yellow
} else {
    Write-Host "✓ Disk usage is acceptable" -ForegroundColor Green
}
Write-Host ""

# Check 7: Recent Errors (if logs exist)
Write-Host "Check 7: Recent Errors" -ForegroundColor Cyan
$LogPath = "$ProjectPath\logs"
if (Test-Path $LogPath) {
    $RecentErrors = Get-ChildItem $LogPath -Filter "*.log" | Get-Content | Select-String -Pattern "error|Error|ERROR" | Select-Object -Last 5
    if ($RecentErrors) {
        Write-Host "⚠ Found recent errors:" -ForegroundColor Yellow
        $RecentErrors | ForEach-Object { Write-Host "  $_" -ForegroundColor Yellow }
    } else {
        Write-Host "✓ No recent errors found" -ForegroundColor Green
    }
} else {
    Write-Host "⚠ No log directory found at $LogPath" -ForegroundColor Yellow
}
Write-Host ""

# Summary
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Health Check Summary" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "To monitor live processes:" -ForegroundColor White
Write-Host "  Get-Process daphne | Format-Table Id, CPU, WorkingSet" -ForegroundColor White
Write-Host ""
Write-Host "To monitor memory:" -ForegroundColor White
Write-Host "  Get-Process | Sort-Object WorkingSet -Descending | Select-Object -First 10" -ForegroundColor White
Write-Host ""
Write-Host "To check Redis:" -ForegroundColor White
Write-Host "  redis-cli info memory" -ForegroundColor White
Write-Host ""
