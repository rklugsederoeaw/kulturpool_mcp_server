# Kulturerbe MCP Server

Model Context Protocol (MCP) server for searching Austrian Cultural Heritage via the Kulturpool API.

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://python.org)
[![MCP](https://img.shields.io/badge/MCP-1.0+-green.svg)](https://modelcontextprotocol.io)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Overview

This MCP server provides secure, rate-limited access to Austria's cultural heritage through the [Kulturpool API](https://api.kulturpool.at). It implements a 6-tool progressive disclosure architecture designed for efficient context window usage and comprehensive cultural object discovery.

## Features

### 🔍 **6-Tool Progressive Disclosure Architecture**

1. **`kulturpool_explore`** - Initial exploration with facet analysis (< 2KB response)
2. **`kulturpool_search_filtered`** - Targeted search with comprehensive filters (≤ 20 results)
3. **`kulturpool_get_details`** - Find related objects using content-based search (≤ 3 IDs)
4. **`kulturpool_get_institutions`** - Complete institution directory with locations
5. **`kulturpool_get_institution_details`** - Detailed institution metadata
6. **`kulturpool_get_assets`** - Optimized image assets with transformations

### 🛡️ **Built-in Security**

- **Input Sanitization**: Protection against injection attacks
- **Rate Limiting**: 100 requests/hour per client
- **Response Limits**: < 10KB responses for context efficiency
- **Parameter Validation**: Comprehensive Pydantic-based validation
- **Safe URL Handling**: Restricted to Kulturpool API endpoints

### ⚡ **Performance Optimized**

- **Progressive Disclosure**: Start broad, then narrow down
- **Compressed Responses**: Essential metadata only
- **Facet-Based Navigation**: Smart filtering recommendations
- **Connection Pooling**: Efficient HTTP client with retry logic

## Installation

### Prerequisites

- Python 3.8 or higher
- pip package manager
- Git (for cloning the repository)

### Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/yourusername/kulturerbe_mcp.git
   cd kulturerbe_mcp
   ```

2. **Create and activate virtual environment:**

   **Windows:**
   ```cmd
   python -m venv .venv
   .venv\Scripts\activate
   ```

   **Linux/WSL/macOS:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Test the server:**

   **Windows:**
   ```cmd
   python server.py
   ```

   **Linux/WSL/macOS:**
   ```bash
   python3 server.py
   ```

### Claude Desktop Configuration

Add the server to your Claude Desktop MCP configuration file:

**Configuration file locations:**
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Linux:** `~/.config/Claude/claude_desktop_config.json`

#### Option 1: Windows with WSL (Recommended for this project)
```json
{
  "mcpServers": {
    "kulturerbe-mcp-server": {
      "command": "wsl",
      "args": ["-e", "/home/username/kulturerbe_mcp/run_server.sh"],
      "cwd": "\\\\wsl$\\Ubuntu\\home\\username\\kulturerbe_mcp",
      "env": {
        "VIRTUAL_ENV": "/home/username/kulturerbe_mcp/.venv",
        "PATH": "/home/username/kulturerbe_mcp/.venv/bin:$PATH"
      }
    }
  }
}
```

#### Option 2: Windows Native
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

#### Option 3: Linux/macOS
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

### Claude Code Configuration

For Claude Code in WSL/Linux environment:
```json
{
  "mcpServers": {
    "kulturerbe-mcp-server": {
      "command": "/home/username/kulturerbe_mcp/run_server.sh",
      "args": [],
      "cwd": "/home/username/kulturerbe_mcp",
      "env": {
        "VIRTUAL_ENV": "/home/username/kulturerbe_mcp/.venv",
        "PATH": "/home/username/kulturerbe_mcp/.venv/bin:$PATH"
      }
    }
  }
}
```

> **📝 Note:** Pre-configured options are available in `mcp_config.json` - copy the relevant section to your configuration file.

### Alternative: Launcher Scripts

**Windows:**
```cmd
run_server.bat
```

**Linux/WSL/macOS:**
```bash
chmod +x run_server.sh
./run_server.sh
```

## Usage Guide

### 1. Initial Exploration
Start with broad exploration to understand available data:

```python
# Get overview with facets
kulturpool_explore(query="Mozart")
```

**Returns:** Facet counts by institution, type, and time period with sample results.

### 2. Filtered Search
Use facets to narrow down results:

```python
# Targeted search with filters
kulturpool_search_filtered(
    query="Vienna",
    institutions=["Albertina", "Belvedere"],
    object_types=["IMAGE"],
    date_from=1800,
    date_to=1900,
    creators=["Klimt"],
    limit=15
)
```

**Advanced Filters:**
- **Date Range**: Interval overlap semantics (object's [dateMin,dateMax] overlaps [date_from,date_to])
- **Creators**: Partial matching with wildcards
- **Subjects**: Exact matching for topics
- **Media**: Filter by material/medium
- **Dublin Core Types**: Performance-limited object categorization

### 3. Related Object Discovery
Find related cultural objects using content-based search:

```python
# Find related objects
kulturpool_get_details(object_ids=["obj123", "obj456"])
```

### 4. Institution Management
Explore participating institutions:

```python
# Get institution directory
kulturpool_get_institutions(include_locations=True, language="de")

# Get detailed institution info
kulturpool_get_institution_details(institution_id=42, language="de")
```

### 5. Asset Optimization
Access optimized images with transformations:

```python
# Get optimized image assets
kulturpool_get_assets(
    asset_id="logo_123",
    width=400,
    height=300,
    format="webp",
    quality=85,
    fit="inside"
)
```

## Selection of supported institutions

Major Austrian cultural institutions participate in the Kulturpool network:

- **[Albertina](https://www.albertina.at/)** - Graphics and modern art
- **[Belvedere](https://www.belvedere.at/)** - Austrian art and baroque collections
- **[Österreichische Nationalbibliothek](https://www.onb.ac.at/)** - National library and archives
- **[Wiener Stadt- und Landesarchiv](https://www.wien.gv.at/kultur/archiv/)** - Vienna city archives
- **[MAK](https://www.mak.at/)** - Applied arts and contemporary art
- **[Weltmuseum Wien](https://www.weltmuseumwien.at/)** - Ethnographic collections
- **[Technisches Museum Wien](https://www.technischesmuseum.at/)** - Technology and industry
- **[Naturhistorisches Museum Wien](https://www.nhm-wien.ac.at/)** - Natural history

## Development

### Architecture

The server is built as a single-file implementation (`server.py`, ~1300 lines) with:

- **MCP Protocol**: Traditional stdio transport
- **Async/Await**: Full asynchronous operation
- **Pydantic Validation**: Type-safe parameter handling
- **Security Layer**: Input sanitization and rate limiting
- **Error Handling**: Comprehensive exception management

### Key Components

```
├── SecurityValidator     # Input sanitization and validation
├── RateLimiter          # Request rate limiting (100/hour)
├── KulturpoolClient     # HTTP client with retry logic
├── ResponseProcessor    # Data processing and facet analysis
└── Tool Handlers        # Six specialized tool implementations
```

## Configuration

### Environment Variables

No environment variables required - the server connects directly to the public Kulturpool API.

### Rate Limiting

- **Default**: 100 requests per hour per client
- **Configurable**: Modify `RateLimiter(max_requests=100, time_window=3600)`
- **Scope**: Global across all tool calls

### Response Limits

- **Explore**: < 2KB responses with facets
- **Search**: ≤ 20 results with full metadata
- **Details**: ≤ 3 object IDs per request
- **Overall**: < 10KB response size limit

## API Reference

### Data Sources

This server provides access to:

- **Base API**: `https://api.kulturpool.at/search/`
- **Institution API**: `https://api.kulturpool.at/institutions/`
- **Asset API**: `https://api.kulturpool.at/assets/`

### Object Types

- **IMAGE**: Photographs, paintings, drawings, graphics
- **TEXT**: Manuscripts, books, documents, letters
- **SOUND**: Audio recordings, music, oral history
- **VIDEO**: Film recordings, documentaries
- **3D**: Three-dimensional objects, sculptures

### Sort Options

- `titleSort:asc/desc` - Alphabetical by title
- `dataProvider:asc/desc` - By institution
- `dateMin:asc/desc` - By earliest date
- `dateMax:asc/desc` - By latest date

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Support

- **Issues**: [GitHub Issues](https://github.com/yourusername/kulturerbe_mcp/issues)
- **Discussions**: [GitHub Discussions](https://github.com/yourusername/kulturerbe_mcp/discussions)
- **API Documentation**: [Kulturpool API](https://api.kulturpool.at/docs)

## Development Credits

This MCP server was developed by **Robert Klugseder** (Austrian Academy of Sciences - Austrian Centre for Digital Humanities, [ÖAW-ACDH-CH](https://www.oeaw.ac.at/acdh/)) using **Vibe Coding** methodologies with assistance from **Claude Sonnet 4** via the **Claude Code CLI**.

## ⚠️ Beta Disclaimer

**This MCP server is a beta version and experimental software.**

- This software has undergone limited testing and should be considered experimental
- Use at your own risk in production environments
- The developers assume no liability for any damages, data loss, or other consequences arising from the use of this software
- No warranty is provided, either express or implied, regarding the functionality, reliability, or suitability of this software for any particular purpose

## Acknowledgments

- [Kulturpool](https://www.kulturpool.at/) - Austrian Cultural Heritage Platform
- [Model Context Protocol](https://modelcontextprotocol.io/) - Protocol specification
- [Anthropic](https://www.anthropic.com/) - Claude Desktop integration
- [Austrian Academy of Sciences](https://www.oeaw.ac.at/) - Research institution support
