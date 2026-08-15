# Kill the elevated WorldView server (PID 9196, started by fix script)
$log = 'C:\Users\bklyn\worldview\kill_log.txt'
"=== KILL $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" | Out-File -FilePath $log -Encoding utf8
Stop-Process -Id 9196 -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3
$p = Get-NetTCPConnection -LocalPort 8767 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess
"listeners after kill: $p" | Out-File -FilePath $log -Append -Encoding utf8
