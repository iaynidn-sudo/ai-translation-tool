@echo off
chcp 65001 >nul
REM Start MCP server over stdio for MCP clients like workbuddy
set PYTHON=%PYTHON%
if "%PYTHON%"=="" set PYTHON=python
%PYTHON% mcp_server.py
