# Kulturerbe MCP Server

Austrian Cultural Heritage Search Server for Model Context Protocol (MCP).

## Features

- **3-Tool Progressive Disclosure Architecture**
  
  - `kulturpool_explore` - Initial exploration with facets (< 2KB response)
  - `kulturpool_search_filtered` - Targeted search with filters (≤ 20 results)
  - `kulturpool_get_details` - Complete metadata for specific objects (≤ 3 objects)

- **Built-in Security**
  
  - Input sanitization and validation
  - Prompt injection protection  
  - Rate limiting (100 requests/hour)
  - Response size limits (< 10KB)

- **Optimized for Context Windows**
  
  - Progressive disclosure pattern
  - Compressed responses
  - Facet-based navigation

## Installation

1. Install dependencies:
   
   ```bash
   pip install -r requirements.txt
   ```

2. Test the server:
   
   ```bash
   python server.py
   ```

3. Configure Claude Desktop:
   Add to your Claude Desktop MCP configuration:
   
   ```json
   {
   "mcpServers": {
    "kulturerbe-mcp-server": {
      "command": "python",
      "args": ["C:\\claude_local\\kulturerbe_mcp\\kulturerbe_mcp_server\\server.py"],
      "cwd": "C:\\claude_local\\kulturerbe_mcp\\kulturerbe_mcp_server",
      "env": {}
    }
   }
   }
   ```

## Usage Examples

### 1. Initial Exploration

```
Use kulturpool_explore with query "Mozart" to get an overview
```

### 2. Filtered Search

```
Use kulturpool_search_filtered with:
- query: "Wien"
- institutions: ["Albertina"]
- object_types: ["IMAGE"] 
- limit: 10
```

### 3. Detailed Information

```
Use kulturpool_get_details with object_ids: ["obj123", "obj456"]
```

## Supported Institutions

- Albertina
- Belvedere  
- Österreichische Nationalbibliothek
- Wiener Stadt- und Landesarchiv
- MAK
- Weltmuseum Wien
- Technisches Museum Wien
- Naturhistorisches Museum Wien

## API Information

This server connects to the Austrian Kulturpool API (https://api.kulturpool.at/search), providing access to cultural heritage data from major Austrian institutions.
