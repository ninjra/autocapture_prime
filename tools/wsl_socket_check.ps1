param(
    [string]$WslExe = "C:\Windows\System32\wsl.exe"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

& $WslExe --% -e bash -lc "python3 -c \"import socket; s=socket.socket(); s.bind(('127.0.0.1',0)); s.close(); print('bind_ok')\""
