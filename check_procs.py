"""Identify python processes holding worldview.db open (or orphans)."""
import subprocess, os

# Use PowerShell via a temp script file to avoid bash quoting issues
ps = r'''
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Select-Object ProcessId,WorkingSetSize,CommandLine | ConvertTo-Json
'''
with open(os.path.join(os.environ["TEMP"], "ps_procs.ps1"), "w") as f:
    f.write(ps)
out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                      os.path.join(os.environ["TEMP"], "ps_procs.ps1")],
                     capture_output=True, text=True, timeout=60).stdout
import json
try:
    procs = json.loads(out)
    if isinstance(procs, dict):
        procs = [procs]
    for p in procs:
        cmd = (p.get("CommandLine") or "")[:110]
        print(f"PID {p['ProcessId']:>6}  {p['WorkingSetSize']/1024/1024:6.0f}MB  {cmd}")
except Exception as e:
    print("parse fail:", e, out[:500])
