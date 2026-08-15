# stopgap_8768.py — TEMPORARY stopgap launcher (created by cron 2026-08-14).
# Serves WorldView on 127.0.0.1:8768 while :8767 is blocked by the portproxy
# exclusive hold (svchost/iphlpsvc owns 0.0.0.0:8767; deleting it needs admin).
# Runs the REAL server.py code unchanged, only the bind port differs.
# KILL THIS FILE's process once 8767 is restored (fix_worldview_port.ps1 as admin).
import pathlib

_src = pathlib.Path(__file__).resolve().parent.joinpath("server.py").read_text(encoding="utf-8")
_src = _src.replace("port=8767", "port=8768")
exec(compile(_src, "server.py", "exec"))
