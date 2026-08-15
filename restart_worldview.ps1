# One-shot: kill stale WorldView server -> delete portproxy -> start new server -> re-add portproxy -> verify
$log = 'C:\Users\bklyn\worldview\fix_log.txt'
"=== FULL RESTART $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" | Out-File -FilePath $log -Encoding utf8

# 1. Kill any python holding 8767 (stale server)
$listeners = Get-NetTCPConnection -LocalPort 8767 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess
foreach ($pid_ in $listeners) {
    $proc = Get-Process -Id $pid_ -ErrorAction SilentlyContinue
    if ($proc -and $proc.ProcessName -like 'python*') {
        Stop-Process -Id $pid_ -Force -ErrorAction SilentlyContinue
        "killed python $pid_" | Out-File -FilePath $log -Append -Encoding utf8
    }
}
Start-Sleep -Seconds 3

# 2. Delete portproxy (frees 0.0.0.0:8767 exclusive hold)
netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=8767
Start-Sleep -Seconds 2

# 3. Start server (pythonw, windowless)
$server = "C:\Users\bklyn\worldview\server.py"
$pythonw = "C:\Users\bklyn\AppData\Local\hermes\hermes-agent\venv\Scripts\pythonw.exe"
Start-Process -FilePath $pythonw -ArgumentList $server -WorkingDirectory "C:\Users\bklyn\worldview" -WindowStyle Hidden
Start-Sleep -Seconds 10

# 4. Verify
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:8767/api/health" -TimeoutSec 10 -UseBasicParsing
    "health: HTTP $($r.StatusCode)" | Out-File -FilePath $log -Append -Encoding utf8
} catch {
    "health FAIL: $($_.Exception.Message)" | Out-File -FilePath $log -Append -Encoding utf8
}

# 5. Re-add portproxy (phone access)
netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=8767 connectaddress=127.0.0.1 connectport=8767
Start-Sleep -Seconds 2

# 6. Final check
$p = Get-NetTCPConnection -LocalPort 8767 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess
"listeners: $p" | Out-File -FilePath $log -Append -Encoding utf8
"=== DONE ===" | Out-File -FilePath $log -Append -Encoding utf8
