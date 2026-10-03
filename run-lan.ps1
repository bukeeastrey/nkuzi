# Starts Nkuzi so a friend on the same Wi-Fi or hotspot can use it from
# their own laptop or phone. Run it from the nkuzi folder:
#
#     .\run-lan.ps1
#
# The AI still runs on THIS laptop. The friend's device only shows the page
# and sends its microphone audio here.

$root = $PSScriptRoot
$port = 5174

# 1. The backend (only reachable from this laptop; visitors go through the page).
if (-not (Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue)) {
    Write-Host "Starting the backend in a new window..."
    Start-Process powershell -ArgumentList "-NoExit", "-File", "`"$root\backend\run.ps1`""
}

# 2. This laptop's addresses on the network (skipping "169.254.x.x", which means "no network").
$addresses = Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.IPAddress -ne "127.0.0.1" -and $_.IPAddress -notlike "169.254.*" -and $_.AddressState -eq "Preferred" } |
    Select-Object -ExpandProperty IPAddress

Write-Host ""
if (-not $addresses) {
    Write-Host "This laptop isn't on a network. Join the Wi-Fi or turn on your hotspot, then run this again." -ForegroundColor Yellow
    exit 1
}
Write-Host "Your friend opens one of these in Chrome or Edge (same Wi-Fi or hotspot):" -ForegroundColor Green
foreach ($address in $addresses) {
    Write-Host "    https://${address}:$port" -ForegroundColor Green
}
Write-Host ""
Write-Host "The first time, the browser warns that the connection isn't private."
Write-Host "That is expected (the certificate is made by this laptop): choose Advanced, then Proceed."
Write-Host "Then allow the microphone when asked."
Write-Host ""

# 3. Windows Firewall: is there a rule letting other devices reach this port?
$rule = Get-NetFirewallRule -DisplayName "Nkuzi LAN" -ErrorAction SilentlyContinue |
    Where-Object { $_.Enabled -eq "True" -and $_.Action -eq "Allow" }
# Windows treats each network as "Private" (home) or "Public" (cafe, many hotspots).
# Node.js is usually only allowed on Private ones.
$public = Get-NetConnectionProfile | Where-Object { $_.NetworkCategory -eq "Public" }
if (-not $rule) {
    if ($public) {
        Write-Host "This network ($($public.InterfaceAlias -join ', ')) is marked 'Public' in Windows, so the firewall will probably block your friend." -ForegroundColor Yellow
    } else {
        Write-Host "If Windows asks whether to allow Node.js on your networks, tick the boxes and allow it."
    }
    Write-Host "If your friend's device can't open the page, run this ONCE in PowerShell opened 'as administrator':"
    Write-Host "    New-NetFirewallRule -DisplayName 'Nkuzi LAN' -Direction Inbound -Protocol TCP -LocalPort $port -Action Allow" -ForegroundColor Yellow
    Write-Host ""
}

# 4. The page, served over HTTPS on the network (see frontend\vite.config.js).
$env:NKUZI_LAN = "1"
Set-Location "$root\frontend"
npm run dev
