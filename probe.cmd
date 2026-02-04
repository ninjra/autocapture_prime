@echo off
set "AUTOCAPTURE_ROOT=%~dp0"
powershell -nop -c "$env:AUTOCAPTURE_ROOT='%AUTOCAPTURE_ROOT%'; iex (gc -raw '%~dp0probe.ps1')" %*
exit /b %errorlevel%
