# Script to install dlib on Windows
# This script provides multiple options for installing dlib

Write-Host "Installing dlib for Python 3.10 on Windows..." -ForegroundColor Green
Write-Host ""

# Check if Visual Studio Build Tools are installed
$vsPath = Get-ChildItem "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools" -ErrorAction SilentlyContinue
if (-not $vsPath) {
    Write-Host "Visual Studio Build Tools not found. Installing..." -ForegroundColor Yellow
    Write-Host "This will download and install Visual Studio Build Tools (large download ~3GB)" -ForegroundColor Yellow
    Write-Host ""
    
    # Try to install using winget
    $wingetCheck = Get-Command winget -ErrorAction SilentlyContinue
    if ($wingetCheck) {
        Write-Host "Installing Visual Studio Build Tools using winget..." -ForegroundColor Cyan
        winget install Microsoft.VisualStudio.2022.BuildTools --silent --accept-package-agreements --accept-source-agreements --override "--wait --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
        
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Visual Studio Build Tools installed successfully!" -ForegroundColor Green
        } else {
            Write-Host "Installation may have failed. Please install manually from:" -ForegroundColor Red
            Write-Host "https://visualstudio.microsoft.com/visual-cpp-build-tools/" -ForegroundColor Cyan
            Write-Host ""
            Write-Host "Make sure to select 'Desktop development with C++' workload" -ForegroundColor Yellow
            exit 1
        }
    } else {
        Write-Host "winget not available. Please install Visual Studio Build Tools manually:" -ForegroundColor Red
        Write-Host "1. Download from: https://visualstudio.microsoft.com/visual-cpp-build-tools/" -ForegroundColor Cyan
        Write-Host "2. Run the installer" -ForegroundColor Cyan
        Write-Host "3. Select 'Desktop development with C++' workload" -ForegroundColor Cyan
        Write-Host "4. Install and restart your terminal" -ForegroundColor Cyan
        exit 1
    }
} else {
    Write-Host "Visual Studio Build Tools found!" -ForegroundColor Green
}

Write-Host ""
Write-Host "Installing dlib..." -ForegroundColor Cyan

# Activate virtual environment and install dlib
& .venv\Scripts\python.exe -m pip install dlib==20.0.0

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "dlib installed successfully!" -ForegroundColor Green
    Write-Host "Now installing face-recognition..." -ForegroundColor Cyan
    & .venv\Scripts\python.exe -m pip install face-recognition==1.3.0
    if ($LASTEXITCODE -eq 0) {
        Write-Host ""
        Write-Host "All packages installed successfully!" -ForegroundColor Green
    }
} else {
    Write-Host ""
    Write-Host "dlib installation failed. Please try:" -ForegroundColor Red
    Write-Host "1. Make sure Visual Studio Build Tools are installed" -ForegroundColor Yellow
    Write-Host "2. Restart your terminal/PowerShell" -ForegroundColor Yellow
    Write-Host "3. Run: .venv\Scripts\activate" -ForegroundColor Yellow
    Write-Host "4. Run: pip install dlib" -ForegroundColor Yellow
}

