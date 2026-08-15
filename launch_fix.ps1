# Launcher: runs fix_worldview_port.ps1 elevated and logs all output
$log = 'C:\Users\bklyn\worldview\fix_log.txt'
"=== LAUNCHED $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" | Out-File -FilePath $log -Encoding utf8
& 'C:\Users\bklyn\worldview\fix_worldview_port.ps1' *>> $log
"=== EXIT CODE: $LASTEXITCODE ===" | Out-File -FilePath $log -Append -Encoding utf8
