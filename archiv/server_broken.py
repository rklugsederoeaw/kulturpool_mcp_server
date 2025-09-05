#!/usr/bin/env python3
"""
Kulturerbe MCP Server - MVP Implementation with Virtual Environment Support
Austrian Cultural Heritage Search via Kulturpool API

3-Tool Architecture with Progressive Disclosure Pattern:
1. kulturpool_explore - Facet exploration (< 2KB response)
2. kulturpool_search_filtered - Filtered search (max 20 results)
3. kulturpool_get_details - Object details (max 3 objects)

Virtual Environment Setup:
- Uses .venv in project root
- All dependencies isolated
- MCP config points to .venv/Scripts/python.exe
"""

import asyncio
import json
import logging
import re
import sys
import os
import time
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, ClassVar
from urllib.parse import quote, urlencode

# Virtual Environment Check
def check_virtual_env():
    """Verify we're running in the correct virtual environment"""
    venv_path = Path(__file__).parent.parent / ".venv"
    current_executable = Path(sys.executable)
    
    if venv_path.exists():
        expected_python = venv_path / "Scripts" / "python.exe"
        try:
            if current_executable.samefile(expected_python):
                print(f"✓ Running in virtual environment: {venv_path}")
            else:
                print(f"⚠ Not running in expected venv! Current: {current_executable}, Expected: {expected_python}")
        except:
            print(f"ℹ Virtual environment check inconclusive")
    else:
        print("ℹ No .venv directory found - running in system Python")

# Check environment before imports
check_virtual_env()

import requests
from mcp.server import Server
from mcp.types import Tool, TextContent, EmbeddedResource
from pydantic import BaseModel, Field, validator
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize MCP Server
server = Server("kulturerbe-mcp-server")

# ==============================================================================
# SECURITY & RATE LIMITING CLASSES
# ==============================================================================

class SecurityValidator:
    """Input validation and sanitization against prompt injection"""
    
    DANGEROUS_CHARS = ['<', '>', '"', "'", '&', ';', '|', '`', '$']
    DANGEROUS_PATTERNS = ['javascript:', 'data:', 'vbscript:', 'file:', 
                         'ignore previous instructions', 'system prompt', 
                         'assistant:', 'human:', '```', 'eval(', 'exec(',
                         'import os', 'subprocess', '/etc/passwd', '../']
    
    @staticmethod
    def sanitize_input(value: str) -> str:
        """Sanitize input string from dangerous characters and patterns"""
        if not isinstance(value, str):
            raise ValueError("Input must be string")
        
        # Remove dangerous characters
        for char in SecurityValidator.DANGEROUS_CHARS:
            value = value.replace(char, '')
        
        # Check for dangerous patterns
        value_lower = value.lower()
        for pattern in SecurityValidator.DANGEROUS_PATTERNS:
            if pattern in value_lower:
                raise ValueError(f"Security violation: dangerous pattern detected")
        
        # Length limits
        if len(value) > 500:
            raise ValueError("Input too long (max 500 characters)")
        
        return value.strip()

class RateLimiter:
    """Rate limiting: 100 requests per hour per client"""
    
    def __init__(self, max_requests: int = 100, time_window: int = 3600):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = defaultdict(deque)
    
    def is_allowed(self, client_id: str = "default") -> bool:
        """Check if request is allowed for client"""
        now = time.time()
        client_requests = self.requests[client_id]
        
        # Remove old requests outside time window
        while client_requests and client_requests[0] < now - self.time_window:
            client_requests.popleft()
        
        # Check limit
        if len(client_requests) >= self.max_requests:
            return False
        
        # Add current request
        client_requests.append(now)
        return True

# Global rate limiter instance
rate_limiter = RateLimiter()

# ==============================================================================
# KULTURPOOL API CLIENT  
# ==============================================================================

class KulturpoolClient:
    """Secure HTTP client for Kulturpool API"""
    
    BASE_URL = "https://api.kulturpool.at/search"
    TIMEOUT = 10
    
    def __init__(self):
        self.session = requests.Session()
        
        # Configure retry strategy
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.headers.update({
            'User-Agent': 'Kulturerbe-MCP-Server/1.0'
        })
    
    def search(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute search with security validation"""
        try:
            # Validate URL
            if not self.BASE_URL.startswith("https://api.kulturpool.at"):
                raise ValueError("Only Kulturpool API allowed")
            
            response = self.session.get(
                self.BASE_URL,
                params=params,
                timeout=self.TIMEOUT
            )
            response.raise_for_status()
            return response.json()
            
        except requests.RequestException as e:
            logger.error(f"API request failed: {e}")
            raise ConnectionError(f"Kulturpool API request failed: {str(e)}")

# Global API client
api_client = KulturpoolClient()
                        "date_end": doc.get('dateMax'),
                        "format": doc.get('format', []),
                        "identifier": doc.get('identifier', []),
                        "relation": doc.get('relation', [])[:5]
                    }
                }
                
                for date_field in ['date_created', 'date_end']:
                    if detailed_obj["metadata"][date_field]:
                        try:
                            timestamp = int(detailed_obj["metadata"][date_field])
                            detailed_obj["metadata"][date_field] = {
                                "timestamp": timestamp,
                                "formatted": datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d"),
                                "year": datetime.fromtimestamp(timestamp).year
                            }
                        except (ValueError, TypeError):
                            pass
                
                detailed_objects.append(detailed_obj)
                
            except Exception as obj_error:
                logger.error(f"Error fetching object {obj_id}: {obj_error}")
                detailed_objects.append({
                    "id": obj_id,
                    "error": f"Failed to fetch object details: {str(obj_error)}"
                })
        
        result = {
            "requested_objects": len(params.object_ids),
            "successful_retrievals": len([obj for obj in detailed_objects if "error" not in obj]),
            "objects": detailed_objects
        }
        
        result = ResponseProcessor.ensure_response_size_limit(result)
        
        return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]
        
    except Exception as e:
        logger.error(f"kulturpool_get_details error: {e}")
        error_response = {
            "error": "Detail retrieval failed",
            "message": "Please check the object IDs and try again."
        }
        return [TextContent(type="text", text=json.dumps(error_response, indent=2))]

@server.list_tools()
async def list_tools() -> List[Tool]:
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
