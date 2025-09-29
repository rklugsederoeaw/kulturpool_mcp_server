@echo off
REM Kulturerbe MCP Server Launcher for Windows
REM Activates virtual environment and starts the server

REM Change to script directory
cd /d "%~dp0"

REM Activate virtual environment
call .venv\Scripts\activate.bat

REM Start the server with all passed arguments
python server.py %*