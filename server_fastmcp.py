#!/usr/bin/env python3
"""
Kulturerbe MCP Server - FastMCP Implementation
Austrian Cultural Heritage Search via Kulturpool API

3-Tool Architecture with Progressive Disclosure Pattern:
1. kulturpool_explore - Facet exploration (< 2KB response)
2. kulturpool_search_filtered - Filtered search (max 20 results)
3. kulturpool_get_details - Object details (max 3 objects)
"""

import json
import time
from collections import defaultdict, deque
from datetime import datetime
from typing import Any, Dict, List, Optional, ClassVar
from urllib.parse import quote, urlencode

import requests
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field, field_validator, ValidationError
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Create FastMCP server
mcp = FastMCP("kulturerbe-mcp-server")

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
            raise ConnectionError(f"Kulturpool API request failed: {str(e)}")

# Global API client
api_client = KulturpoolClient()

# ==============================================================================
# PARAMETER VALIDATION MODELS
# ==============================================================================

class KulturpoolExploreParams(BaseModel):
    """Parameters for kulturpool_explore tool"""
    query: str = Field(..., min_length=1, max_length=500)
    max_examples: int = Field(default=5, ge=1, le=10)
    
    @field_validator('query')
    @classmethod  
    def validate_query(cls, v):
        return SecurityValidator.sanitize_input(v)

class KulturpoolSearchParams(BaseModel):
    """Parameters for kulturpool_search_filtered tool"""
    query: str = Field(..., min_length=1, max_length=500)
    institutions: Optional[List[str]] = Field(None, max_length=10)
    object_types: Optional[List[str]] = Field(None, max_length=5) 
    date_from: Optional[int] = Field(None)
    date_to: Optional[int] = Field(None)
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
    object_ids: List[str] = Field(..., min_length=1, max_length=3)
    
    @field_validator('object_ids')
    @classmethod
    def validate_object_ids(cls, v):
        import re
        validated = []
        for obj_id in v[:3]:  # Hard limit to 3
            # Basic ID validation
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

# ==============================================================================
# TOOL IMPLEMENTATIONS
# ==============================================================================

@mcp.tool()
def kulturpool_explore(query: str, max_examples: int = 5) -> str:
    """
    Explore Austrian cultural heritage with facet overview.
    Always returns < 2KB response with facets and sample results.
    """
    try:
        # Rate limiting check
        if not rate_limiter.is_allowed():
            raise ValueError("Rate limit exceeded. Please try again later.")
        
        # Parameter validation
        params = KulturpoolExploreParams(query=query, max_examples=max_examples)
        
        # Build API request parameters
        api_params = {
            'q': params.query,
            'per_page': 50,  # Get enough for good facet analysis
            'facet_by': 'dataProvider,edmType,dateMin'
        }
        
        # Execute API call
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
        
        return json.dumps(result, indent=2, ensure_ascii=False)
        
    except Exception as e:
        error_response = {
            "error": "Search exploration failed",
            "message": "Please try with a different search term."
        }
        return json.dumps(error_response, indent=2)

@mcp.tool()
def kulturpool_search_filtered(
    query: str, 
    institutions: Optional[List[str]] = None,
    object_types: Optional[List[str]] = None,
    date_from: Optional[int] = None,
    date_to: Optional[int] = None,
    limit: int = 15
) -> str:
    """
    Filtered search with specific facets.
    Returns max 20 results with detailed metadata.
    """
    try:
        # Rate limiting check
        if not rate_limiter.is_allowed():
            raise ValueError("Rate limit exceeded. Please try again later.")
        
        # Parameter validation
        params = KulturpoolSearchParams(
            query=query,
            institutions=institutions,
            object_types=object_types,
            date_from=date_from,
            date_to=date_to,
            limit=limit
        )
        
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
            'sort_by': '_score:desc'
        }
        
        if filters:
            api_params['filter_by'] = ' && '.join(filters)
        
        # Execute API call
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
                "subjects": doc.get('subject', [])[:5],
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
        
        return json.dumps(result, indent=2, ensure_ascii=False)
        
    except Exception as e:
        error_response = {
            "error": "Filtered search failed", 
            "message": "Please check your filters and try again."
        }
        return json.dumps(error_response, indent=2)

@mcp.tool()
def kulturpool_get_details(object_ids: List[str]) -> str:
    """
    Get detailed metadata for specific objects.
    Returns complete information for max 3 objects.
    """
    try:
        # Rate limiting check
        if not rate_limiter.is_allowed():
            raise ValueError("Rate limit exceeded. Please try again later.")
        
        # Parameter validation
        params = KulturpoolDetailsParams(object_ids=object_ids)
        
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
                        "relation": doc.get('relation', [])[:5]
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
        
        return json.dumps(result, indent=2, ensure_ascii=False)
        
    except Exception as e:
        error_response = {
            "error": "Detail retrieval failed",
            "message": "Please check the object IDs and try again."
        }
        return json.dumps(error_response, indent=2)

# ==============================================================================
# MAIN SERVER ENTRY POINT
# ==============================================================================

if __name__ == "__main__":
    print("Starting Kulturerbe MCP Server...")
    print("3-Tool Progressive Disclosure Architecture:")
    print("1. kulturpool_explore - Facet overview (< 2KB)")
    print("2. kulturpool_search_filtered - Filtered results (≤ 20)")
    print("3. kulturpool_get_details - Complete metadata (≤ 3 objects)")
    print("Rate limit: 100 requests/hour per client")
    
    mcp.run()