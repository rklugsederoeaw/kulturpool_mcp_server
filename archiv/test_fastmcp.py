#!/usr/bin/env python3
"""
Minimal FastMCP test server
"""

from mcp.server.fastmcp import FastMCP

# Create server
mcp = FastMCP("test-server")

@mcp.tool()
def test_tool(message: str) -> str:
    """Simple test tool"""
    return f"Hello, {message}!"

if __name__ == "__main__":
    print("Starting test FastMCP server...")
    mcp.run()