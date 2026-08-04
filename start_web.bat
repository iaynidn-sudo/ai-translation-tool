@echo off
chcp 65001 >nul
REM Start web UI, default port 5000, override with set PORT=8080
set PYTHON=%PYTHON%
if "%PYTHON%"=="" set PYTHON=python
%PYTHON% app.py --port %PORT%
