        except Exception as e:
            logger.error(f"kulturpool_get_details error: {e}")
            error_response = {
                "error": "Detail retrieval failed",
                "message": "Please check the object IDs and try again."
            }
            return [TextContent(type="text", text=json.dumps(error_response, indent=2))]

# ==============================================================================
# SERVER SETUP AND TOOL REGISTRATION
# ==============================================================================

@server.list_tools()
async def list_tools() -> List[Tool]:
    """Register available tools with minimal descriptions to save context"""
    return [
        Tool(
            name="kulturpool_explore",
            description="Explore Austrian cultural heritage with facet overview. Returns total count, facets, and sample results.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search term for cultural objects"
                    },
                    "max_examples": {
                        "type": "integer", 
                        "default": 5,
                        "minimum": 1,
                        "maximum": 10,
                        "description": "Number of example results"
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="kulturpool_search_filtered", 
            description="Filtered search with specific facets. Returns max 20 detailed results.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search term"
                    },
                    "institutions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter by institutions"
                    },
                    "object_types": {
                        "type": "array", 
                        "items": {"type": "string", "enum": ["IMAGE", "TEXT", "SOUND", "VIDEO", "3D"]},
                        "description": "Filter by object types"
                    },
                    "date_from": {
                        "type": "integer",
                        "description": "Start date (Unix timestamp)"
                    },
                    "date_to": {
                        "type": "integer", 
                        "description": "End date (Unix timestamp)"
                    },
                    "limit": {
                        "type": "integer",
                        "default": 15,
                        "minimum": 1,
                        "maximum": 20,
                        "description": "Number of results to return"
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="kulturpool_get_details",
            description="Get complete metadata for specific objects (max 3).",
            inputSchema={
                "type": "object", 
                "properties": {
                    "object_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": 3,
                        "description": "List of object IDs to retrieve"
                    }
                },
                "required": ["object_ids"]
            }
        )
    ]

# ==============================================================================
# MAIN SERVER ENTRY POINT
# ==============================================================================

def main():
    """Start the MCP server"""
    import mcp
    
    logger.info("Starting Kulturerbe MCP Server...")
    logger.info("Virtual Environment Configuration:")
    logger.info(f"  Python executable: {sys.executable}")
    logger.info(f"  Virtual env: {os.environ.get('VIRTUAL_ENV', 'Not set')}")
    logger.info("3-Tool Progressive Disclosure Architecture:")
    logger.info("1. kulturpool_explore - Facet overview (< 2KB)")
    logger.info("2. kulturpool_search_filtered - Filtered results (≤ 20)")
    logger.info("3. kulturpool_get_details - Complete metadata (≤ 3 objects)")
    logger.info("Rate limit: 100 requests/hour per client")
    
    # Run the server
    mcp.run_server(server)

if __name__ == "__main__":
    main()
