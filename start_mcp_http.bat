@echo off
chcp 65001 >nul
REM Start MCP server over HTTP, default 127.0.0.1:8000, override with set MCP_HOST=127.0.0.1:9000
set PYTHON=%PYTHON%
if "%PYTHON%"=="" set PYTHON=python
if "%MCP_HOST%"=="" set MCP_HOST=127.0.0.1:8000
%PYTHON% mcp_server.py --http %MCP_HOST%
