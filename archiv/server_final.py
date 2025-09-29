#!/usr/bin/env python3
"""
Kulturerbe MCP Server v2.2 - Institution Management Tools Added
Austrian Cultural Heritage Search via Kulturpool API

6-Tool Architecture with Progressive Disclosure Pattern:
1. kulturpool_explore - Facet exploration (< 2KB response)
2. kulturpool_search_filtered - Filtered search (max 20 results)  
3. kulturpool_get_details - Object details (max 3 objects)
4. kulturpool_get_institutions - List all institutions
5. kulturpool_get_institution_details - Detailed institution info
6. kulturpool_get_assets - Optimized image transformations
"""

import json
import time
from collections import defaultdict, deque
from datetime import datetime
from urllib.parse import quote, urlencode
from typing import Any, Dict, List, Optional, ClassVar

import requests
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
from pydantic import BaseModel, Field, field_validator, ValidationError
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Create MCP server
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
                raise ValueError(f"Potentially dangerous pattern detected: {pattern}")
        
        # Limit length
        return value[:500]

class RateLimiter:
    """Simple rate limiter with sliding window"""
    
    def __init__(self, max_requests: int = 100, window_hours: int = 1):
        self.max_requests = max_requests
        self.window_seconds = window_hours * 3600
        self.requests = deque()
    
    def is_allowed(self) -> bool:
        """Check if request is allowed under rate limit"""
        now = time.time()
        
        # Remove old requests outside window
        while self.requests and self.requests[0] < now - self.window_seconds:
            self.requests.popleft()
        
        # Check if under limit
        if len(self.requests) < self.max_requests:
            self.requests.append(now)
            return True
        
        return False

# Global rate limiter - 100 requests per hour
rate_limiter = RateLimiter(max_requests=100, window_hours=1)

# ==============================================================================
# RESPONSE PROCESSING UTILITIES
# ==============================================================================

class ResponseProcessor:
    """Utilities for processing and formatting API responses"""
    
    @staticmethod
    def analyze_facets(hits: List[Dict]) -> Dict[str, Dict]:
        """Extract and count facets from search results"""
        facets = {
            "institutions": defaultdict(int),
            "types": defaultdict(int),
            "dates": defaultdict(int),
            "creators": defaultdict(int),
            "subjects": defaultdict(int),
            "media": defaultdict(int)
        }
        
        for hit in hits:
            doc = hit.get('document', {})
            
            # Institution facets
            provider = doc.get('dataProvider', '')
            if provider:
                facets["institutions"][provider] += 1
            
            # Type facets
            edm_type = doc.get('edmType', '')
            if edm_type:
                facets["types"][edm_type] += 1
            
            # Date facets (decades)
            date_min = doc.get('dateMin')
            if date_min:
                try:
                    decade = (int(date_min) // 10) * 10
                    facets["dates"][f"{decade}s"] += 1
                except (ValueError, TypeError):
                    pass
            
            # Creator facets
            creator = doc.get('creator', '')
            if creator:
                facets["creators"][creator] += 1
            
            # Subject facets
            subjects = doc.get('subject', [])
            if isinstance(subjects, list):
                for subject in subjects:
                    facets["subjects"][subject] += 1
            elif subjects:
                facets["subjects"][subjects] += 1
            
            # Media facets
            medium = doc.get('medium', '')
            if medium:
                facets["media"][medium] += 1
        
        # Convert to sorted lists (top 10 each)
        result = {}
        for facet_type, counts in facets.items():
            result[facet_type] = dict(sorted(counts.items(), 
                                           key=lambda x: x[1], 
                                           reverse=True)[:10])
        
        return result
    
    @staticmethod
    def format_sample_results(hits: List[Dict], max_results: int) -> List[Dict]:
        """Format sample results for exploration"""
        samples = []
        for hit in hits[:max_results]:
            doc = hit.get('document', {})
            
            # Get image information
            images = ResponseProcessor.extract_image_urls(doc)
            
            sample = {
                "id": doc.get('id', ''),
                "title": doc.get('title', 'Untitled'),
                "creator": doc.get('creator', 'Unknown'),
                "institution": doc.get('dataProvider', ''),
                "type": doc.get('edmType', ''),
                "date": doc.get('dateMin', ''),
                "preview_url": images["preview_url"]
            }
            samples.append(sample)
        
        return samples
    
    @staticmethod
    def extract_image_urls(doc: Dict) -> Dict[str, str]:
        """Extract and construct image URLs from document"""
        # Get base preview URL
        preview_url = doc.get('preview', '')
        
        # Try official API fields first
        large_image = doc.get('isShownBy', '')
        medium_image = doc.get('object', '')
        
        # Fallback to URL manipulation if API fields are empty
        if not large_image and preview_url:
            if "_medium.webp" in preview_url:
                large_image = preview_url.replace("_medium.webp", "_large.webp")
            elif ".webp" in preview_url and "_medium" not in preview_url:
                large_image = preview_url.replace(".webp", "_large.webp")
            else:
                large_image = preview_url  # Use preview as fallback
        
        if not medium_image and preview_url:
            if "_small.webp" in preview_url:
                medium_image = preview_url.replace("_small.webp", "_medium.webp")
            else:
                medium_image = preview_url  # Use preview as fallback
        
        return {
            "preview_url": preview_url,
            "large_image": large_image,
            "medium_image": medium_image,
            "iiif_manifest": doc.get('iiifManifest', '')
        }

# ==============================================================================
# KULTURPOOL API CLIENT
# ==============================================================================

class KulturpoolAPIClient:
    """HTTP client for Kulturpool API with retry logic and timeout handling"""
    
    def __init__(self):
        self.base_url = "https://api.kulturpool.at"
        self.session = requests.Session()
        
        # Configure retry strategy
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
        # Set headers
        self.session.headers.update({
            'User-Agent': 'Kulturerbe-MCP-Server/2.2 (Austrian Cultural Heritage Search)',
            'Accept': 'application/json',
            'Accept-Encoding': 'gzip, deflate'
        })
    
    def search(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute search request"""
        url = f"{self.base_url}/search"
        
        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.Timeout:
            raise ValueError("API request timed out")
        except requests.RequestException as e:
            raise ValueError(f"API request failed: {str(e)}")
    
    def get_institutions(self, include_locations: bool = True, language: str = "de") -> Dict[str, Any]:
        """Get list of all institutions"""
        url = f"{self.base_url}/institutions/"
        params = {}
        
        if language in ["de", "en"]:
            params["language"] = language
        
        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            # Process institutions to manage response size
            institutions = data.get('data', [])
            processed_institutions = []
            
            for inst in institutions:
                processed_inst = {
                    "id": inst.get('id'),
                    "name": inst.get('name'),
                    "web_collection_url": inst.get('web_collection_url'),
                    "website_url": inst.get('website_url')
                }
                
                # Include location if requested and available
                if include_locations and inst.get('location'):
                    location = inst.get('location', {})
                    if location.get('coordinates'):
                        coords = location['coordinates']
                        if coords and len(coords) > 0 and len(coords[0]) >= 2:
                            processed_inst["location"] = {
                                "lat": coords[0][1],
                                "lng": coords[0][0]
                            }
                
                processed_institutions.append(processed_inst)
            
            return {
                "institutions": processed_institutions,
                "total_count": len(processed_institutions)
            }
            
        except requests.Timeout:
            raise ValueError("API request timed out")
        except requests.RequestException as e:
            raise ValueError(f"API request failed: {str(e)}")
    
    def get_institution_details(self, institution_id: int, language: str = "de") -> Dict[str, Any]:
        """Get detailed information about a specific institution"""
        url = f"{self.base_url}/institutions/{institution_id}"
        params = {}
        
        if language in ["de", "en"]:
            params["language"] = language
        
        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            # Return the institution data
            return data.get('data', {})
            
        except requests.Timeout:
            raise ValueError("API request timed out")
        except requests.RequestException as e:
            raise ValueError(f"API request failed: {str(e)}")
    
    def get_asset(self, asset_id: str, width: Optional[int] = None, 
                 height: Optional[int] = None, format: str = "webp",
                 quality: int = 85, fit: str = "inside") -> Dict[str, Any]:
        """Get optimized asset with transformations"""
        url = f"{self.base_url}/assets/{asset_id}"
        params = {}
        
        if width:
            params["width"] = width
        if height:
            params["height"] = height
        if format in ["webp", "jpeg", "png"]:
            params["format"] = format
        if 1 <= quality <= 100:
            params["quality"] = quality
        if fit in ["inside", "outside", "cover", "fill"]:
            params["fit"] = fit
        
        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            # Return metadata about the transformed asset
            return {
                "asset_id": asset_id,
                "url": response.url,
                "content_type": response.headers.get('content-type', ''),
                "content_length": response.headers.get('content-length', ''),
                "transformations": params
            }
            
        except requests.Timeout:
            raise ValueError("API request timed out")
        except requests.RequestException as e:
            raise ValueError(f"API request failed: {str(e)}")

# Global API client
api_client = KulturpoolAPIClient()

# ==============================================================================
# PARAMETER VALIDATION MODELS
# ==============================================================================
    response = {
        "search_ids": params.object_ids,
        "related_objects": related_objects[:20]
    }
    
    return [TextContent(type="text", text=json.dumps(response, indent=2, ensure_ascii=False))]

# NEW Phase 5: Institution Management Handlers

async def kulturpool_get_institutions_handler(arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle kulturpool_get_institutions tool calls"""
    if not rate_limiter.is_allowed():
        raise ValueError("Rate limit exceeded. Please try again later.")
    
    params = InstitutionsListParams(**arguments)
    
    try:
        response_data = api_client.get_institutions(
            include_locations=params.include_locations,
            language=params.language
        )
        
        response_data["request_params"] = {
            "include_locations": params.include_locations,
            "language": params.language
        }
        response_data["response_info"] = {
            "timestamp": datetime.now().isoformat(),
            "data_source": "Kulturpool API",
            "note": "Use kulturpool_get_institution_details for complete information about specific institutions"
        }
        
        return [TextContent(type="text", text=json.dumps(response_data, indent=2, ensure_ascii=False))]
        
    except Exception as e:
        raise ValueError(f"Failed to retrieve institutions: {str(e)}")

async def kulturpool_get_institution_details_handler(arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle kulturpool_get_institution_details tool calls"""
    if not rate_limiter.is_allowed():
        raise ValueError("Rate limit exceeded. Please try again later.")
    
    params = InstitutionDetailsParams(**arguments)
    
    try:
        institution_data = api_client.get_institution_details(
            institution_id=params.institution_id,
            language=params.language
        )
        
        processed_data = {
            "institution_id": params.institution_id,
            "basic_info": {
                "name": institution_data.get('name', ''),
                "web_collection_url": institution_data.get('web_collection_url', ''),
                "website_url": institution_data.get('website_url', '')
            },
            "location": None,
            "images": {
                "favicon": institution_data.get('favicon', {}),
                "hero_image": institution_data.get('hero_image', {})
            },
            "metadata": {
                "intermediate_provider": institution_data.get('intermediate_provider'),
                "language": params.language,
                "timestamp": datetime.now().isoformat()
            }
        }
        
        # Process location data if available
        location = institution_data.get('location', {})
        if location and location.get('coordinates'):
            coords = location['coordinates']
            if coords and len(coords) > 0 and len(coords[0]) >= 2:
                processed_data["location"] = {
                    "type": location.get('type', 'MultiPoint'),
                    "coordinates": {
                        "longitude": coords[0][0],
                        "latitude": coords[0][1]
                    }
                }
        
        processed_data["note"] = "For image assets, use kulturpool_get_assets with asset IDs from favicon or hero_image"
        
        return [TextContent(type="text", text=json.dumps(processed_data, indent=2, ensure_ascii=False))]
        
    except Exception as e:
        raise ValueError(f"Failed to retrieve institution details for ID {params.institution_id}: {str(e)}")

async def kulturpool_get_assets_handler(arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle kulturpool_get_assets tool calls"""
    if not rate_limiter.is_allowed():
        raise ValueError("Rate limit exceeded. Please try again later.")
    
    params = AssetParams(**arguments)
    
    try:
        asset_data = api_client.get_asset(
            asset_id=params.asset_id,
            width=params.width,
            height=params.height,
            format=params.format,
            quality=params.quality,
            fit=params.fit
        )
        
        asset_data["usage_info"] = {
            "original_asset_id": params.asset_id,
            "transformation_applied": bool(params.width or params.height),
            "timestamp": datetime.now().isoformat(),
            "note": "This URL provides optimized image with specified transformations"
        }
        
        return [TextContent(type="text", text=json.dumps(asset_data, indent=2, ensure_ascii=False))]
        
    except Exception as e:
        raise ValueError(f"Failed to retrieve asset {params.asset_id}: {str(e)}")

# ==============================================================================
# TOOL REGISTRATION
# ==============================================================================

@server.list_tools()
async def list_tools() -> List[Tool]:
    """List available tools"""
    return [
        Tool(
            name="kulturpool_explore",
            description="Explore Austrian cultural heritage with facet overview. Always returns < 2KB response with facets and sample results.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query for cultural objects",
                        "minLength": 1,
                        "maxLength": 500
                    },
                    "max_examples": {
                        "type": "integer",
                        "description": "Maximum number of sample results to return",
                        "minimum": 1,
                        "maximum": 10,
                        "default": 5
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="kulturpool_search_filtered",
            description="Filtered search with specific facets. Returns max 20 results with detailed metadata.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query",
                        "minLength": 1,
                        "maxLength": 500
                    },
                    "institutions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter by institutions",
                        "maxItems": 10
                    },
                    "object_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter by object types (IMAGE, TEXT, SOUND, VIDEO, 3D)",
                        "maxItems": 5
                    },
                    "date_from": {
                        "type": "integer",
                        "description": "Filter by start date (Unix timestamp)"
                    },
                    "date_to": {
                        "type": "integer",
                        "description": "Filter by end date (Unix timestamp)"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results to return",
                        "minimum": 1,
                        "maximum": 20,
                        "default": 15
                    },
                    "sort_by": {
                        "type": "string",
                        "description": "Sort results by field (titleSort:asc, titleSort:desc, dataProvider:asc, dataProvider:desc, dateMin:asc, dateMin:desc, dateMax:asc, dateMax:desc)",
                        "enum": ["titleSort:asc", "titleSort:desc", "dataProvider:asc", "dataProvider:desc", "dateMin:asc", "dateMin:desc", "dateMax:asc", "dateMax:desc"]
                    },
                    "creators": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter by creators/artists (supports partial matching)",
                        "maxItems": 5
                    },
                    "subjects": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter by subjects/topics (exact matching)",
                        "maxItems": 10
                    },
                    "media": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter by medium/material (e.g., 'Handschrift', 'Glasdia', 'Fotografie')",
                        "maxItems": 5
                    },
                    "dc_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter by Dublin Core types (e.g., 'Fotografie', 'Gemälde'). WARNING: Can generate large result sets",
                        "maxItems": 3
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="kulturpool_get_details",
            description="Find related cultural objects using object IDs as search terms. Uses content-based search to discover similar objects, related works, or objects from same collections. Does NOT retrieve additional metadata (use kulturpool_search_filtered results directly for complete object details).",
            inputSchema={
                "type": "object",
                "properties": {
                    "object_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Object IDs to use as search terms for finding related cultural objects and collections",
                        "minItems": 1,
                        "maxItems": 3
                    }
                },
                "required": ["object_ids"]
            }
        ),
        Tool(
            name="kulturpool_get_institutions",
            description="Get comprehensive list of all participating cultural institutions in the Kulturpool network. Returns institution names, IDs, websites, and optional geographical coordinates.",
            inputSchema={
                "type": "object",
                "properties": {
                    "include_locations": {
                        "type": "boolean",
                        "description": "Include geographical coordinates for institutions",
                        "default": True
                    },
                    "language": {
                        "type": "string",
                        "description": "Response language (de for German, en for English)",
                        "enum": ["de", "en"],
                        "default": "de"
                    }
                }
            }
        ),
        Tool(
            name="kulturpool_get_institution_details",
            description="Get detailed information about a specific cultural institution, including location data, images, and multilingual content. Use institution IDs from kulturpool_get_institutions.",
            inputSchema={
                "type": "object",
                "properties": {
                    "institution_id": {
                        "type": "integer",
                        "description": "Institution ID (get from kulturpool_get_institutions)",
                        "minimum": 1
                    },
                    "language": {
                        "type": "string",
                        "description": "Response language (de for German, en for English)",
                        "enum": ["de", "en"],
                        "default": "de"
                    }
                },
                "required": ["institution_id"]
            }
        ),
        Tool(
            name="kulturpool_get_assets",
            description="Get optimized image assets with dynamic transformations. Supports resizing, format conversion, and quality adjustment for institution logos, hero images, and other visual assets.",
            inputSchema={
                "type": "object",
                "properties": {
                    "asset_id": {
                        "type": "string",
                        "description": "Asset ID (get from institution details, favicon, hero_image fields)"
                    },
                    "width": {
                        "type": "integer",
                        "description": "Target width in pixels (1-4000)",
                        "minimum": 1,
                        "maximum": 4000
                    },
                    "height": {
                        "type": "integer",
                        "description": "Target height in pixels (1-4000)",
                        "minimum": 1,
                        "maximum": 4000
                    },
                    "format": {
                        "type": "string",
                        "description": "Output image format",
                        "enum": ["webp", "jpeg", "png"],
                        "default": "webp"
                    },
                    "quality": {
                        "type": "integer",
                        "description": "Image quality percentage (1-100)",
                        "minimum": 1,
                        "maximum": 100,
                        "default": 85
                    },
                    "fit": {
                        "type": "string",
                        "description": "Resize behavior: inside (maintain aspect ratio within bounds), outside (fill bounds, may crop), cover (fill exactly), fill (stretch to fit)",
                        "enum": ["inside", "outside", "cover", "fill"],
                        "default": "inside"
                    }
                },
                "required": ["asset_id"]
            }
        )
    ]

# ==============================================================================
# MAIN SERVER ENTRY POINT
# ==============================================================================

async def main():
    """Run the MCP server"""
    import sys
    import asyncio
    from mcp.server.models import InitializationOptions
    from mcp.server.lowlevel.server import NotificationOptions
    from mcp.types import ServerCapabilities
    
    print("Starting Kulturerbe MCP Server v2.2...", file=sys.stderr)
    print("6-Tool Progressive Disclosure Architecture:", file=sys.stderr)
    print("1. kulturpool_explore - Facet overview (< 2KB)", file=sys.stderr)
    print("2. kulturpool_search_filtered - Filtered results (≤ 20)", file=sys.stderr)
    print("3. kulturpool_get_details - Related objects (≤ 3 objects)", file=sys.stderr)
    print("4. kulturpool_get_institutions - Institution list", file=sys.stderr)
    print("5. kulturpool_get_institution_details - Institution details", file=sys.stderr)
    print("6. kulturpool_get_assets - Optimized image assets", file=sys.stderr)
    print("Rate limit: 100 requests/hour per client", file=sys.stderr)
    
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="kulturerbe-mcp-server",
                server_version="2.2.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
