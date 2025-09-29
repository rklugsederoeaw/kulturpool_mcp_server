#!/bin/bash
# Kulturerbe MCP Server Launcher
# Activates virtual environment and starts the server

# Set PATH to include common binary directories
export PATH="/usr/bin:/bin:/usr/local/bin:$PATH"

# Change to script directory using absolute dirname path
cd "$(/usr/bin/dirname "$0")"
source .venv/bin/activate
exec python3 server.py "$@"