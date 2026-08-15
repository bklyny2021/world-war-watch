# Restart WorldView server with current code (elevated helper)
# Kills any process running worldview\server.py (master + workers), then runs
# the proven fix script (delete portproxy -> start server -> re-add portproxy).
$log = 'C:\Users\bklyn\worldview\restart_log.txt'
"=== RESTART $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" | Out-File -FilePath $log -Encoding utf8
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'worldview[\\/]server\.py' } | ForEach-Object {
    "killing $($_.ProcessId) $($_.Name)" | Out-File -FilePath $log -Append -Encoding utf8
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 3
& 'C:\Users\bklyn\worldview\fix_worldview_port.ps1' *>> $log
"=== DONE exit $LASTEXITCODE ===" | Out-File -FilePath $log -Append -Encoding utf8
