# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Model Context Protocol (MCP) server that provides Austrian Cultural Heritage search functionality via the Kulturpool API. The server implements a 6-tool progressive disclosure architecture with built-in security features.

## Development Commands

### Running the Server

**Windows:**
```cmd
# Direct execution (requires .venv to be activated)
python server.py

# Using the launcher script (handles venv activation)
run_server.bat
```

**Linux/WSL/macOS:**
```bash
# Direct execution (requires .venv to be activated)
python3 server.py

# Using the launcher script (handles venv activation)
./run_server.sh
```

### Dependencies
```bash
# Install dependencies (all platforms)
pip install -r requirements.txt
```

### Virtual Environment

**Windows:**
```cmd
# Create venv
python -m venv .venv

# Activate
.venv\Scripts\activate

# Deactivate
deactivate
```

**Linux/WSL/macOS:**
```bash
# Create venv
python3 -m venv .venv

# Activate
source .venv/bin/activate

# Deactivate
deactivate
```

### Testing
Test files are located in the `archiv/` directory:
- `test_server.py` - Main server tests
- `test_server_simple.py` - Simple functionality tests
- `test_fastmcp.py` - FastMCP implementation tests
- `test_server_venv.py` - Virtual environment tests

## Architecture

### Core Components

**Main Server (`server.py`)**
- Single-file MCP server implementation (~1400 lines)
- Uses traditional MCP server pattern with stdio transport
- Implements 6 progressive disclosure tools for cultural heritage search

**Tool Architecture**
1. `kulturpool_explore` - Initial facet exploration (< 2KB responses)
2. `kulturpool_search_filtered` - Targeted filtered search (≤ 20 results)
3. `kulturpool_get_details` - Object details retrieval (≤ 3 objects)
4. `kulturpool_get_institutions` - Institution listings with locations
5. `kulturpool_get_institution_details` - Detailed institution information
6. `kulturpool_get_assets` - Optimized image asset access

### Security Features

**Input Validation (`SecurityValidator` class)**
- Sanitizes dangerous characters and patterns
- Protects against prompt injection attacks
- Enforces input length limits (500 chars max)

**Rate Limiting (`RateLimiter` class)**
- 100 requests per hour limit
- Single-client simplified implementation
- Uses deque for efficient request tracking

**Response Controls**
- Response size limits (< 10KB)
- Progressive disclosure pattern to manage context windows
- Compressed JSON responses

### API Integration

**Kulturpool API**
- Base URL: `https://api.kulturpool.at/search`
- Handles Austrian cultural heritage data
- Supports major institutions: Albertina, Belvedere, ÖNB, etc.
- Response format: JSON with standardized object structure

**HTTP Client Configuration**
- Retry strategy with exponential backoff
- Connection pooling and timeout handling
- Request session management

## Configuration

### MCP Client Configuration

**Windows:**
```json
{
  "mcpServers": {
    "kulturerbe-mcp-server": {
      "command": "python",
      "args": ["C:\\path\\to\\kulturerbe_mcp\\server.py"],
      "cwd": "C:\\path\\to\\kulturerbe_mcp",
      "env": {}
    }
  }
}
```

**Linux/WSL/macOS:**
```json
{
  "mcpServers": {
    "kulturerbe-mcp-server": {
      "command": "python3",
      "args": ["/path/to/kulturerbe_mcp/server.py"],
      "cwd": "/path/to/kulturerbe_mcp",
      "env": {}
    }
  }
}
```

### Claude Code Permissions
Configured in `.claude/settings.local.json` with permissions for:
- MCP tool execution
- Git operations
- WebFetch for kulturpool.at domain
- Zen tools for debugging and chat

## Development Notes

### Development Environment
This project was developed in **WSL Ubuntu** and is designed to work cross-platform:
- **Primary**: WSL Ubuntu (Linux environment in Windows)
- **Secondary**: Native Windows, macOS, Linux
- **Python**: Version 3.8+ required on all platforms

### Code Structure
- Single-file server implementation for simplicity
- Heavy use of Pydantic for request/response validation
- Async/await pattern throughout
- Comprehensive error handling and logging
- Platform-agnostic Python code (no OS-specific dependencies)

### Platform Considerations
- **Paths**: Unix-style in WSL/Linux (`/path/to/file`), Windows-style in native Windows (`C:\path\to\file`)
- **Python Command**: `python3` in Linux/macOS, `python` in Windows
- **Virtual Environment**: Different activation scripts per platform
- **Scripts**: `.sh` for Unix-like systems, `.bat` for Windows

### Backup Versions
The `archiv/` directory contains numerous backup versions of the server:
- `server_working.py` - Known working version
- `server_final.py` - Final implementation
- Various incremental backups and test versions

### Memory Integration
Project includes integration with Claude memory systems for storing and retrieving cultural heritage search context.