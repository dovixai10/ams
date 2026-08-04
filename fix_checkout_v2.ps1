$content = Get-Content "c:\Users\ashwa\OneDrive\Desktop\ems-1\static\js\checkin-dashboard.js" -Raw
$content = $content -replace "                location.reload();", "                await this.loadUIState();`n                await this.loadDashboardData();"
$content | Set-Content "c:\Users\ashwa\OneDrive\Desktop\ems-1\static\js\checkin-dashboard.js" -NoNewline
Write-Host "Check-out handler fixed successfully!"
