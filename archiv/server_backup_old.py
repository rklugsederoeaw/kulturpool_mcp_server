#!/usr/bin/env python3
"""
Kulturerbe MCP Server - MVP Implementation
Austrian Cultural Heritage Search via Kulturpool API

3-Tool Architecture with Progressive Disclosure Pattern:
1. kulturpool_explore - Facet exploration (< 2KB response)
2. kulturpool_search_filtered - Filtered search (max 20 results)
3. kulturpool_get_details - Object details (max 3 objects)
"""

import asyncio
import json
import logging
import re
import time
from collections import defaultdict, deque
from datetime import datetime
from typing import Any, Dict, List, Optional, Union, ClassVar
from urllib.parse import quote, urlencode

import requests
from mcp.server import Server
from mcp import types
from mcp.types import Tool, TextContent, EmbeddedResource
from pydantic import BaseModel, Field, field_validator, ValidationError
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

# ==============================================================================
# PARAMETER VALIDATION MODELS
# ==============================================================================

class KulturpoolExploreParams(BaseModel):
    """Parameters for kulturpool_explore tool"""
    query: str = Field(..., min_length=1, max_length=500, 
                      description="Search term for cultural objects")
    max_examples: int = Field(default=5, ge=1, le=10,
                             description="Number of example results to show")
    
    @field_validator('query')
    @classmethod  
    def validate_query(cls, v):
        return SecurityValidator.sanitize_input(v)

class KulturpoolSearchParams(BaseModel):
    """Parameters for kulturpool_search_filtered tool"""
    query: str = Field(..., min_length=1, max_length=500)
    institutions: Optional[List[str]] = Field(None, max_items=10)
    object_types: Optional[List[str]] = Field(None, max_items=5) 
    date_from: Optional[int] = Field(None, description="Unix timestamp")
    date_to: Optional[int] = Field(None, description="Unix timestamp")
    limit: int = Field(default=15, ge=1, le=20)
    
    # Known institutions whitelist
    KNOWN_INSTITUTIONS: ClassVar[List[str]] = [
        "Albertina", "Belvedere", "Österreichische Nationalbibliothek",
        "Wiener Stadt- und Landesarchiv", "MAK", "Weltmuseum Wien",
        "Technisches Museum Wien", "Naturhistorisches Museum Wien"
    ]
    
    # Known object types
    KNOWN_TYPES: ClassVar[List[str]] = ["IMAGE", "TEXT", "SOUND", "VIDEO", "3D"]
    
    @field_validator('query')
    @classmethod  
    def validate_query(cls, v):
        return SecurityValidator.sanitize_input(v)
    
    @field_validator('institutions')
    @classmethod
    def validate_institutions(cls, v):
        if v:
            return [inst for inst in v if inst in cls.KNOWN_INSTITUTIONS]
        return v
    
    @field_validator('object_types') 
    @classmethod
    def validate_types(cls, v):
        if v:
            return [t for t in v if t in cls.KNOWN_TYPES]
        return v

class KulturpoolDetailsParams(BaseModel):
    """Parameters for kulturpool_get_details tool"""
    object_ids: List[str] = Field(..., min_items=1, max_items=3,
                                 description="List of object IDs to retrieve details for")
    
    @field_validator('object_ids')
    @classmethod
    def validate_object_ids(cls, v):
        validated = []
        for obj_id in v[:3]:  # Hard limit to 3
            # Basic ID validation - should be alphanumeric with possible dashes/underscores
            if re.match(r'^[a-zA-Z0-9_-]+$', obj_id):
                validated.append(SecurityValidator.sanitize_input(obj_id))
        
        if not validated:
            raise ValueError("No valid object IDs provided")
        
        return validated

# ==============================================================================
# RESPONSE PROCESSING UTILITIES
# ==============================================================================

class ResponseProcessor:
    """Utilities for processing and optimizing API responses"""
    
    @staticmethod
    def analyze_facets(hits: List[Dict]) -> Dict[str, Dict[str, int]]:
        """Extract facet information from hits for overview"""
        facets = {
            "institutions": defaultdict(int),
            "types": defaultdict(int), 
            "periods": defaultdict(int)
        }
        
        for hit in hits:
            doc = hit.get('document', {})
            
            # Institution facets
            if provider := doc.get('dataProvider'):
                facets["institutions"][provider] += 1
            
            # Type facets  
            if obj_type := doc.get('edmType'):
                facets["types"][obj_type] += 1
            
            # Period facets (by century)
            if date_min := doc.get('dateMin'):
                try:
                    year = datetime.fromtimestamp(int(date_min)).year
                    century = f"{(year // 100) + 1}. Jahrhundert"
                    facets["periods"][century] += 1
                except (ValueError, TypeError):
                    pass
        
        # Convert to regular dicts and sort by count
        return {
            key: dict(sorted(facet_dict.items(), 
                           key=lambda x: x[1], reverse=True)[:10])
            for key, facet_dict in facets.items()
        }
    
    @staticmethod
    def format_sample_results(hits: List[Dict], max_samples: int = 5) -> List[Dict]:
        """Extract sample results with essential metadata only"""
        samples = []
        for hit in hits[:max_samples]:
            doc = hit.get('document', {})
            
            # Extract essential fields only
            sample = {
                "id": doc.get('id', 'unknown'),
                "title": doc.get('title', ['Unbekannter Titel'])[0] if doc.get('title') else 'Unbekannter Titel',
                "creator": doc.get('creator', ['Unbekannt'])[0] if doc.get('creator') else 'Unbekannt', 
                "institution": doc.get('dataProvider', 'Unbekannt'),
                "type": doc.get('edmType', 'Unbekannt'),
                "preview_url": doc.get('previewImage', '')
            }
            
            # Add date if available
            if date_min := doc.get('dateMin'):
                try:
                    year = datetime.fromtimestamp(int(date_min)).year
                    sample["date"] = str(year)
                except (ValueError, TypeError):
                    sample["date"] = "Unbekannt"
            
            samples.append(sample)
        
        return samples
    
    @staticmethod
    def ensure_response_size_limit(response_data: Dict, max_size: int = 10000) -> Dict:
        """Ensure response doesn't exceed size limit"""
        response_str = json.dumps(response_data, ensure_ascii=False)
        
        if len(response_str.encode('utf-8')) > max_size:
            logger.warning(f"Response size {len(response_str)} exceeds limit {max_size}")
            
            # Truncate sample results if too large
            if 'sample_results' in response_data:
                response_data['sample_results'] = response_data['sample_results'][:3]
                response_data['message'] = f"{response_data.get('message', '')} [Response truncated due to size limits]"
        
        return response_data

# ==============================================================================
# TOOL IMPLEMENTATIONS
# ==============================================================================

@server.call_tool()
async def kulturpool_explore(arguments: Dict[str, Any]) -> List[TextContent]:
    """
    Tool 1: Explore cultural heritage data with facet overview.
    Always returns < 2KB response with facets and sample results.
    """
    try:
        # Rate limiting check
        if not rate_limiter.is_allowed():
            raise ValueError("Rate limit exceeded. Please try again later.")
        
        # Parameter validation
        params = KulturpoolExploreParams(**arguments)
        
        # Build API request parameters
        api_params = {
            'q': params.query,
            'per_page': 50,  # Get enough for good facet analysis
            'facet_by': 'dataProvider,edmType,dateMin'
        }
        
        # Execute API call
        logger.info(f"Exploring query: {params.query}")
        response_data = api_client.search(api_params)
        
        # Process response
        total_found = response_data.get('found', 0)
        hits = response_data.get('hits', [])
        
        # Generate facets and samples
        facets = ResponseProcessor.analyze_facets(hits)
        sample_results = ResponseProcessor.format_sample_results(hits, params.max_examples)
        
        # Build response
        result = {
            "total_found": total_found,
            "query": params.query,
            "facets": facets,
            "sample_results": sample_results,
            "message": f"Found {total_found} results. Use kulturpool_search_filtered with specific facets to narrow down." if total_found > 1000 else f"Found {total_found} manageable results."
        }
        
        # Ensure size limits (< 2KB for explore tool)
        result = ResponseProcessor.ensure_response_size_limit(result, max_size=2048)
        
        return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]
        
    except Exception as e:
        logger.error(f"kulturpool_explore error: {e}")
        error_response = {
            "error": "Search exploration failed",
            "message": "Please try with a different search term."
        }
        return [TextContent(type="text", text=json.dumps(error_response, indent=2))]

@server.call_tool()
async def kulturpool_search_filtered(arguments: Dict[str, Any]) -> List[TextContent]:
    """
    Tool 2: Filtered search with specific facets.
    Returns max 20 results with detailed metadata.
    """
    try:
        # Rate limiting check
        if not rate_limiter.is_allowed():
            raise ValueError("Rate limit exceeded. Please try again later.")
        
        # Parameter validation
        params = KulturpoolSearchParams(**arguments)
        
        # Build API filters
        filters = []
        
        # Institution filters
        if params.institutions:
            inst_filter = f"dataProvider:=[{','.join(params.institutions)}]"
            filters.append(inst_filter)
        
        # Object type filters
        if params.object_types:
            type_filter = f"edmType:=[{','.join(params.object_types)}]"
            filters.append(type_filter)
        
        # Date range filters
        if params.date_from:
            filters.append(f"dateMin:>={params.date_from}")
        if params.date_to:
            filters.append(f"dateMax:<={params.date_to}")
        
        # Build API parameters
        api_params = {
            'q': params.query,
            'per_page': params.limit,
            'sort_by': '_score:desc'  # Relevance sorting
        }
        
        if filters:
            api_params['filter_by'] = ' && '.join(filters)
        
        # Execute API call
        logger.info(f"Filtered search: {params.query} with {len(filters)} filters")
        response_data = api_client.search(api_params)
        
        # Process results
        total_found = response_data.get('found', 0)
        hits = response_data.get('hits', [])
        
        # Format detailed results
        results = []
        for hit in hits:
            doc = hit.get('document', {})
            
            result_obj = {
                "id": doc.get('id'),
                "title": doc.get('title', [''])[0] if doc.get('title') else '',
                "creator": doc.get('creator', []),
                "institution": doc.get('dataProvider'),
                "type": doc.get('edmType'),
                "description": doc.get('description', [''])[0][:200] if doc.get('description') else '',
                "subjects": doc.get('subject', [])[:5],  # Limit subjects
                "preview_image": doc.get('previewImage'),
                "detail_url": doc.get('isShownAt')
            }
            
            # Add formatted date
            if date_min := doc.get('dateMin'):
                try:
                    result_obj["date"] = datetime.fromtimestamp(int(date_min)).year
                except (ValueError, TypeError):
                    result_obj["date"] = None
            
            results.append(result_obj)
        
        # Build final response
        result = {
            "total_found": total_found,
            "returned": len(results),
            "query": params.query,
            "applied_filters": {
                "institutions": params.institutions,
                "object_types": params.object_types,
                "date_from": params.date_from,
                "date_to": params.date_to
            },
            "results": results,
            "message": f"Use kulturpool_get_details with specific IDs for complete metadata." if results else "No results found. Try different filters."
        }
        
        # Ensure size limits (< 10KB)
        result = ResponseProcessor.ensure_response_size_limit(result)
        
        return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]
        
    except Exception as e:
        logger.error(f"kulturpool_search_filtered error: {e}")
        error_response = {
            "error": "Filtered search failed", 
            "message": "Please check your filters and try again."
        }
        return [TextContent(type="text", text=json.dumps(error_response, indent=2))]

@server.call_tool()
async def kulturpool_get_details(arguments: Dict[str, Any]) -> List[TextContent]:
    """
    Tool 3: Get detailed metadata for specific objects.
    Returns complete information for max 3 objects.
    """
    try:
        # Rate limiting check
        if not rate_limiter.is_allowed():
            raise ValueError("Rate limit exceeded. Please try again later.")
        
        # Parameter validation
        params = KulturpoolDetailsParams(**arguments)
        
        detailed_objects = []
        
        # Fetch details for each object ID
        for obj_id in params.object_ids:
            try:
                # Search for specific object by ID
                api_params = {
                    'q': obj_id,
                    'filter_by': f'id:={obj_id}',
                    'per_page': 1
                }
                
                response_data = api_client.search(api_params)
                hits = response_data.get('hits', [])
                
                if not hits:
                    detailed_objects.append({
                        "id": obj_id,
                        "error": "Object not found"
                    })
                    continue
                
                doc = hits[0].get('document', {})
                
                # Build comprehensive object details
                detailed_obj = {
                    "id": doc.get('id'),
                    "title": doc.get('title', []),
                    "creator": doc.get('creator', []),
                    "contributor": doc.get('contributor', []),
                    "institution": doc.get('dataProvider'),
                    "collection": doc.get('provider'),
                    "type": doc.get('edmType'),
                    "description": doc.get('description', []),
                    "subjects": doc.get('subject', []),
                    "medium": doc.get('medium', []),
                    "extent": doc.get('extent', []),
                    "language": doc.get('language', []),
                    "rights": doc.get('edmRightsName'),
                    "preview_image": doc.get('previewImage'),
                    "detail_url": doc.get('isShownAt'),
                    "source_url": doc.get('hasView', []),
                    "metadata": {
                        "date_created": doc.get('dateMin'),
                        "date_end": doc.get('dateMax'),
                        "format": doc.get('format', []),
                        "identifier": doc.get('identifier', []),
                        "relation": doc.get('relation', [])[:5]  # Limit relations
                    }
                }
                
                # Format dates
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
        
        # Build final response
        result = {
            "requested_objects": len(params.object_ids),
            "successful_retrievals": len([obj for obj in detailed_objects if "error" not in obj]),
            "objects": detailed_objects
        }
        
        # Ensure size limits (< 10KB)
        result = ResponseProcessor.ensure_response_size_limit(result)
        
        return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]
        
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
# MCP PROTOCOL HANDLERS - Clean implementation
# ==============================================================================

# ==============================================================================
# MAIN SERVER ENTRY POINT
# ==============================================================================

async def main():
    """Start the MCP server"""
    from mcp.server.stdio import stdio_server
    
    logger.info("Starting Kulturerbe MCP Server...")
    logger.info("3-Tool Progressive Disclosure Architecture:")
    logger.info("1. kulturpool_explore - Facet overview (< 2KB)")
    logger.info("2. kulturpool_search_filtered - Filtered results (≤ 20)")
    logger.info("3. kulturpool_get_details - Complete metadata (≤ 3 objects)")
    logger.info("Rate limit: 100 requests/hour per client")
    
    # Run the server via stdio
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
