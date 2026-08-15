# Fix WorldView :8767 bind failure (WinError 10013)
# Root cause: netsh portproxy (0.0.0.0:8767 -> 127.0.0.1:8767, added 2026-08-07 for
# Boo's phone access) re-created its listener when iphlpsvc restarted 2026-08-14 13:10
# with the WorldView server dead. The portproxy listener now holds 8767 exclusively,
# so the server cannot bind (WSAEACCES on every address).
#
# Fix: delete portproxy -> start server (binds 127.0.0.1:8767) -> re-add portproxy
# (coexists with the specific bind, as it did on 2026-08-13) -> verify.
#
# MUST RUN AS ADMIN (UAC). Run from bash: powershell -File fix_worldview_port.ps1

$ErrorActionPreference = "Continue"

Write-Output "=== 1. Delete portproxy 8767 ==="
netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=8767
Start-Sleep -Seconds 2

Write-Output "=== 2. Start WorldView server (pythonw, windowless) ==="
$server = "C:\Users\bklyn\worldview\server.py"
$pythonw = "C:\Users\bklyn\AppData\Local\hermes\hermes-agent\venv\Scripts\pythonw.exe"
if (-not (Test-Path $server)) { Write-Output "ERROR: server.py missing"; exit 1 }
if (-not (Test-Path $pythonw)) { Write-Output "ERROR: pythonw missing"; exit 1 }
Start-Process -FilePath $pythonw -ArgumentList $server -WorkingDirectory "C:\Users\bklyn\worldview" -WindowStyle Hidden
Start-Sleep -Seconds 10

Write-Output "=== 3. Verify server on 127.0.0.1:8767 ==="
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:8767/api/health" -TimeoutSec 10 -UseBasicParsing
    Write-Output ("health: HTTP " + $r.StatusCode + " " + $r.Content.Substring(0, [Math]::Min(120, $r.Content.Length)))
} catch {
    Write-Output ("health FAIL: " + $_.Exception.Message)
}

Write-Output "=== 4. Re-add portproxy (phone access) ==="
netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=8767 connectaddress=127.0.0.1 connectport=8767
Start-Sleep -Seconds 2
netsh interface portproxy show all

Write-Output "=== 5. Final verification ==="
try {
    $r = Invoke-WebRequest -Uri "http://localhost:8767/api/health" -TimeoutSec 10 -UseBasicParsing
    Write-Output ("localhost health: HTTP " + $r.StatusCode)
} catch {
    Write-Output ("localhost health FAIL: " + $_.Exception.Message)
}
Get-NetTCPConnection -LocalPort 8767 -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Output ("listener: " + $_.LocalAddress + ":" + $_.LocalPort + " PID " + $_.OwningProcess)
}
Write-Output "=== DONE ==="
