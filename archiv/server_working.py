#!/usr/bin/env python3
"""
Kulturerbe MCP Server - Traditional MCP Implementation
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
# IMAGE URL HELPERS - USING OFFICIAL API FIELDS
# ==============================================================================

def _extract_image_urls(doc: Dict) -> Dict[str, str]:
    """Extract image URLs from official API fields with fallback logic"""
    preview_url = doc.get('previewImage', '')
    
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

class KulturpoolClient:
    """Secure HTTP client for Kulturpool API"""
    
    BASE_URL = "https://api.kulturpool.at/search/"
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
            
            # Special handling for filter_by and sort_by parameters that need unencoded characters
            special_params = {}
            if 'filter_by' in params:
                special_params['filter_by'] = params.pop('filter_by')
            if 'sort_by' in params:
                special_params['sort_by'] = params.pop('sort_by')
                
            if special_params:
                # Build URL manually with proper encoding for special parameters
                base_url = f"{self.BASE_URL}?{urlencode(params)}" if params else self.BASE_URL
                separator = "&" if "?" in base_url else "?"
                
                # Add special parameters while preserving :, =, & characters
                special_parts = []
                for key, value in special_params.items():
                    encoded_value = quote(value, safe='=:&')
                    special_parts.append(f"{key}={encoded_value}")
                
                full_url = f"{base_url}{separator}{'&'.join(special_parts)}"
                response = self.session.get(full_url, timeout=self.TIMEOUT)
            else:
                response = self.session.get(
                    self.BASE_URL,
                    params=params,
                    timeout=self.TIMEOUT
                )
            response.raise_for_status()
            return response.json()
            
        except requests.RequestException as e:
            raise ConnectionError(f"Kulturpool API request failed: {str(e)}")


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
            
            institutions = data.get("data", [])
            processed_institutions = []
            
            for inst in institutions:
                processed_inst = {
                    "id": inst.get("id"),
                    "name": inst.get("name"),
                    "web_collection_url": inst.get("web_collection_url"),
                    "website_url": inst.get("website_url")
                }
                
                if include_locations and inst.get("location"):
                    location = inst.get("location", {})
                    if location.get("coordinates"):
                        coords = location["coordinates"]
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
            return data.get("data", {})
        except requests.Timeout:
            raise ValueError("API request timed out")
        except requests.RequestException as e:
            raise ValueError(f"API request failed: {str(e)}")
    
    def get_asset(self, asset_id: str, width: Optional[int] = None, height: Optional[int] = None, format: str = "webp", quality: int = 85, fit: str = "inside") -> Dict[str, Any]:
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
            return {
                "asset_id": asset_id,
                "url": response.url,
                "content_type": response.headers.get("content-type", ""),
                "content_length": response.headers.get("content-length", ""),
                "transformations": params
            }
        except requests.Timeout:
            raise ValueError("API request timed out")
        except requests.RequestException as e:
            raise ValueError(f"API request failed: {str(e)}")

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
    sort_by: Optional[str] = Field(None)
    # NEW: Creator filter for Phase 1
    creators: Optional[List[str]] = Field(None, max_length=5)
    # NEW: Subject filter for Phase 2
    subjects: Optional[List[str]] = Field(None, max_length=10)
    # NEW: Media filter for Phase 3
    media: Optional[List[str]] = Field(None, max_length=5)
    # NEW: Dublin Core Type filter for Phase 4 - LIMITED due to performance
    dc_types: Optional[List[str]] = Field(None, max_length=3)
    
    # Known institutions whitelist
    KNOWN_INSTITUTIONS: ClassVar[List[str]] = [
        "Albertina", "Belvedere", "Österreichische Nationalbibliothek",
        "Wiener Stadt- und Landesarchiv", "MAK", "Weltmuseum Wien",
        "Technisches Museum Wien", "Naturhistorisches Museum Wien"
    ]
    
    # Known object types
    KNOWN_TYPES: ClassVar[List[str]] = ["IMAGE", "TEXT", "SOUND", "VIDEO", "3D"]
    
    # Known Dublin Core types (performance-limited list)
    KNOWN_DC_TYPES: ClassVar[List[str]] = [
        "Fotografie", "Gemälde", "Zeichnung", "Grafik", 
        "Druckwerk", "Karte", "Münze", "Medaille"
    ]
    
    # Known sort fields
    KNOWN_SORT_FIELDS: ClassVar[List[str]] = [
        "titleSort:asc", "titleSort:desc",
        "dataProvider:asc", "dataProvider:desc", 
        "dateMin:asc", "dateMin:desc",
        "dateMax:asc", "dateMax:desc"
    ]
    
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
    
    @field_validator('sort_by')
    @classmethod
    def validate_sort_by(cls, v):
        if v and v not in cls.KNOWN_SORT_FIELDS:
            raise ValueError(f"sort_by must be one of: {', '.join(cls.KNOWN_SORT_FIELDS)}")
        return v
    
    @field_validator('creators')
    @classmethod
    def validate_creators(cls, v):
        if v:
            # Sanitize each creator name
            sanitized = []
            for creator in v:
                sanitized_creator = SecurityValidator.sanitize_input(creator)
                if sanitized_creator:  # Only add non-empty creators
                    sanitized.append(sanitized_creator)
            return sanitized
        return v
    
    @field_validator('subjects')
    @classmethod
    def validate_subjects(cls, v):
        if v:
            # Sanitize each subject
            sanitized = []
            for subject in v:
                sanitized_subject = SecurityValidator.sanitize_input(subject)
                if sanitized_subject:  # Only add non-empty subjects
                    sanitized.append(sanitized_subject)
            return sanitized
        return v
    
    @field_validator('media')
    @classmethod
    def validate_media(cls, v):
        if v:
            # Sanitize each medium
            sanitized = []
            for medium in v:
                sanitized_medium = SecurityValidator.sanitize_input(medium)
                if sanitized_medium:  # Only add non-empty media
                    sanitized.append(sanitized_medium)
            return sanitized
        return v
    
    @field_validator('dc_types')
    @classmethod
    def validate_dc_types(cls, v):
        if v:
            # Performance-aware validation - limit to known types
            sanitized = []
            for dc_type in v:
                sanitized_type = SecurityValidator.sanitize_input(dc_type)
                if sanitized_type and sanitized_type in cls.KNOWN_DC_TYPES:
                    sanitized.append(sanitized_type)
            return sanitized
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
            }
            
            # Add image URLs using official API fields
            sample.update(_extract_image_urls(doc))
            
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
# TOOL HANDLERS
# ==============================================================================

@server.call_tool()
async def handle_call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle tool calls"""
    try:
        if name == "kulturpool_explore":
            return await kulturpool_explore_handler(arguments)
        elif name == "kulturpool_search_filtered":
            return await kulturpool_search_filtered_handler(arguments)
        elif name == "kulturpool_get_details":
            return await kulturpool_get_details_handler(arguments)
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]
    except Exception as e:
        error_response = {
            "error": f"Tool execution failed: {name}",
            "message": str(e)
        }
        return [TextContent(type="text", text=json.dumps(error_response, indent=2))]

async def kulturpool_explore_handler(arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle kulturpool_explore tool calls"""
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
    
    return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

async def kulturpool_search_filtered_handler(arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle kulturpool_search_filtered tool calls"""
    # Rate limiting check
    if not rate_limiter.is_allowed():
        raise ValueError("Rate limit exceeded. Please try again later.")
    
    # Parameter validation
    params = KulturpoolSearchParams(**arguments)
    
    # Build API filters - correct Kulturpool API syntax
    filters = []
    
    # Institution filters - multiple institutions as separate filters
    if params.institutions:
        for institution in params.institutions:
            filters.append(f"dataProvider:={institution}")
    
    # Object type filters - multiple types as separate filters  
    if params.object_types:
        for obj_type in params.object_types:
            filters.append(f"edmType:={obj_type}")
    
    # Date range filters
    if params.date_from:
        filters.append(f"dateMin:>={params.date_from}")
    if params.date_to:
        filters.append(f"dateMax:<={params.date_to}")
    
    # NEW: Creator filters - wildcard search for partial matching
    if params.creators:
        for creator in params.creators:
            filters.append(f"creator:*{creator}*")
    
    # NEW: Subject filters - exact matching for topics/themes
    if params.subjects:
        for subject in params.subjects:
            filters.append(f"subject:={subject}")
    
    # NEW: Media filters - exact matching for material/technique
    if params.media:
        for medium in params.media:
            filters.append(f"medium:={medium}")
    
    # NEW: Dublin Core Type filters - PERFORMANCE WARNING: can generate large result sets
    if params.dc_types:
        for dc_type in params.dc_types:
            filters.append(f"dcType:={dc_type}")
    
    # Build API parameters
    api_params = {
        'q': params.query,
        'per_page': params.limit
    }
    
    if filters:
        api_params['filter_by'] = ' && '.join(filters)
    
    if params.sort_by:
        api_params['sort_by'] = params.sort_by
    
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
            "detail_url": doc.get('isShownAt')
        }
        
        # Add image URLs using official API fields
        result_obj.update(_extract_image_urls(doc))
        
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
            "date_to": params.date_to,
            "creators": params.creators,
            "subjects": params.subjects,
            "media": params.media,
            "dc_types": params.dc_types
        },
        "results": results,
        "message": f"Results contain detailed metadata. Note: kulturpool_get_details has API limitations - use these search results directly." if results else "No results found. Try different filters."
    }
    
    return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

async def kulturpool_get_details_handler(arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle kulturpool_get_details tool calls - find related objects using IDs as search terms"""
    # Rate limiting check
    if not rate_limiter.is_allowed():
        raise ValueError("Rate limit exceeded. Please try again later.")
    
    # Parameter validation
    params = KulturpoolDetailsParams(**arguments)
    
    related_searches = []
    
    # Use each object ID as search term to find related objects
    for obj_id in params.object_ids:
        try:
            # Search using the ID as a search term to find related content
            api_params = {
                'q': obj_id,
                'per_page': 5,  # Find up to 5 related objects per ID
                'sort_by': '_score:desc'  # Most relevant first
            }
            
            response_data = api_client.search(api_params)
            hits = response_data.get('hits', [])
            total_found = response_data.get('found', 0)
            
            related_objects = []
            for hit in hits:
                doc = hit.get('document', {})
                related_obj = {
                    "id": doc.get('id'),
                    "title": doc.get('title', [''])[0] if doc.get('title') else '',
                    "creator": doc.get('creator', []),
                    "institution": doc.get('dataProvider'),
                    "type": doc.get('edmType'),
                    "preview_url": doc.get('previewImage'),
                    "detail_url": doc.get('isShownAt'),
                    "relevance_note": f"Found by searching for '{obj_id}'"
                }
                
                # Add date if available
                if date_min := doc.get('dateMin'):
                    try:
                        related_obj["date"] = datetime.fromtimestamp(int(date_min)).year
                    except (ValueError, TypeError):
                        pass
                
                related_objects.append(related_obj)
            
            related_searches.append({
                "search_term": obj_id,
                "total_found": total_found,
                "returned": len(related_objects),
                "related_objects": related_objects,
                "note": f"Objects found by using '{obj_id}' as search term"
            })
            
        except Exception as search_error:
            related_searches.append({
                "search_term": obj_id,
                "error": f"Search failed: {str(search_error)}",
                "related_objects": []
            })
    
    # Build final response
    result = {
        "search_strategy": "Using object IDs as search terms to find related cultural objects",
        "searches_performed": len(params.object_ids),
        "results": related_searches,
        "note": "This tool finds related objects by content-based search, not direct ID lookup"
    }
    
    return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]
    """Handle kulturpool_get_details tool calls"""
    # Rate limiting check
    if not rate_limiter.is_allowed():
        raise ValueError("Rate limit exceeded. Please try again later.")
    
    # Parameter validation
    params = KulturpoolDetailsParams(**arguments)
    
    detailed_objects = []
    
    # Fetch details for each object ID
    for obj_id in params.object_ids:
        try:
            # Search for specific object by ID using multiple strategies
            # Strategy 1: Search in identifier and related fields
            api_params = {
                'q': obj_id,
                'query_by': 'identifier,title,alternative',
                'per_page': 1
            }
            
            response_data = api_client.search(api_params)
            hits = response_data.get('hits', [])
            
            # Strategy 2: If no results, try broader search across all fields
            if not hits:
                api_params = {
                    'q': obj_id,
                    'per_page': 1
                }
                response_data = api_client.search(api_params)
                hits = response_data.get('hits', [])
            
            # Strategy 3: If still no results, try exact ID match in title field
            if not hits:
                api_params = {
                    'q': f'"{obj_id}"',  # Exact match with quotes
                    'query_by': 'identifier,title,alternative',
                    'per_page': 1
                }
                response_data = api_client.search(api_params)
                hits = response_data.get('hits', [])
            
            # Strategy 3: If still no results, try exact ID match in title field
            if not hits:
                api_params = {
                    'q': f'"{obj_id}"',  # Exact match with quotes
                    'query_by': 'identifier,title,alternative',
                    'per_page': 1
                }
                response_data = api_client.search(api_params)
                hits = response_data.get('hits', [])
            
            if not hits:
                detailed_objects.append({
                    "id": obj_id,
                    "error": "Direct ID lookup not supported by Kulturpool API",
                    "explanation": "This API only supports content-based search, not direct ID access",
                    "suggestion": "Use kulturpool_search_filtered with specific search terms to find objects. The search results already contain detailed metadata.",
                    "workflow": "1. Use kulturpool_explore to find topics → 2. Use kulturpool_search_filtered with specific filters → 3. Results contain all available details"
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
            
            # Add image URLs using official API fields
            detailed_obj.update(_extract_image_urls(doc))
            
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
                "error": "API access error",
                "message": "Unable to access Kulturpool API for this request",
                "technical_details": str(obj_error),
                "suggestion": "This API requires content-based search. Use kulturpool_search_filtered instead."
            })
    
    # Build final response
    result = {
        "requested_objects": len(params.object_ids),
        "successful_retrievals": len([obj for obj in detailed_objects if "error" not in obj]),
        "objects": detailed_objects
    }
    
    return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

# ==============================================================================
# TOOL DEFINITIONS
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
            description="Filtered search with specific facets. Returns max 20 results with complete metadata. Supports creators, subjects, media, and Dublin Core type filters.",
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
                        "description": "Filter by institutions (e.g., 'Albertina', 'Belvedere', 'Österreichische Nationalbibliothek')",
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
                        "description": "Filter by creators/artists (supports partial matching, e.g., 'Mozart', 'Dürer')",
                        "maxItems": 5
                    },
                    "subjects": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter by subjects/topics (exact matching, e.g., 'Portrait', 'Historische Person')",
                        "maxItems": 10
                    },
                    "media": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter by medium/material (exact matching, e.g., 'Handschrift', 'Glasdia', 'Fotografie')",
                        "maxItems": 5
                    },
                    "dc_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter by Dublin Core types (e.g., 'Fotografie', 'Gemälde'). WARNING: Can generate large result sets. Use with other filters.",
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
    
    print("Starting Kulturerbe MCP Server...", file=sys.stderr)
    print("3-Tool Progressive Disclosure Architecture:", file=sys.stderr)
    print("1. kulturpool_explore - Facet overview (< 2KB)", file=sys.stderr)
    print("2. kulturpool_search_filtered - Filtered results (≤ 20)", file=sys.stderr)
    print("3. kulturpool_get_details - Complete metadata (≤ 3 objects)", file=sys.stderr)
    print("Rate limit: 100 requests/hour per client", file=sys.stderr)
    
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="kulturerbe-mcp-server",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())