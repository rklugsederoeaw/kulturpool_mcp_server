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
import asyncio
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
        self.base_url = "https://api.kulturpool.at"  # Add base_url attribute
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
                    # Encode filter_by preserving only essential separators
                    # Encode parentheses and pipes to avoid proxy parsing issues
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
            
            institutions = data.get('data', [])
            processed_institutions = []
            
            for inst in institutions:
                processed_inst = {
                    "id": inst.get('id'),
                    "name": inst.get('name'),
                    "web_collection_url": inst.get('web_collection_url'),
                    "website_url": inst.get('website_url')
                }
                
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
            return data.get('data', {})
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
                "content_type": response.headers.get('content-type', ''),
                "content_length": response.headers.get('content-length', ''),
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
    def _to_year(value) -> Optional[int]:
        """Convert mixed date values (year or epoch s/ms) to a year.
        Returns None if not convertible or implausible.
        """
        try:
            n = int(value)
        except (ValueError, TypeError):
            return None
        # Treat small integers as years
        if n <= 3000:
            return n if 1000 <= n <= 2100 else None
        # Heuristic: ms -> s
        if n > 10_000_000_000:
            n //= 1000
        try:
            return datetime.utcfromtimestamp(n).year
        except Exception:
            return None
    
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
            
            # Period facets (by century) using dateMin, fallback to dateMax
            date_value = doc.get('dateMin') if doc.get('dateMin') is not None else doc.get('dateMax')
            if date_value is not None:
                year = ResponseProcessor._to_year(date_value)
                if year:
                    century = f"{((year - 1)//100) + 1}. Jahrhundert"
                    facets["periods"][century] += 1
        
        # Convert to regular dicts and sort by count
        return {
            key: dict(sorted(facet_dict.items(), 
                           key=lambda x: x[1], reverse=True)[:10])
            for key, facet_dict in facets.items()
        }

    @staticmethod
    def analyze_facets_from_response(response_data: Dict[str, Any]) -> Dict[str, Dict[str, int]]:
        """Prefer server-provided facet_counts when available; fallback to sampling hits."""
        facet_counts = response_data.get('facet_counts') or []
        if not facet_counts:
            return ResponseProcessor.analyze_facets(response_data.get('hits', []))

        facets = {
            "institutions": defaultdict(int),
            "types": defaultdict(int),
            "periods": defaultdict(int),
        }

        for fc in facet_counts:
            field = fc.get('field_name') or fc.get('field')
            counts = fc.get('counts', [])
            if field == 'dataProvider':
                for item in counts:
                    v = item.get('value')
                    c = item.get('count', 0)
                    if v:
                        facets['institutions'][v] += c
            elif field == 'edmType':
                for item in counts:
                    v = item.get('value')
                    c = item.get('count', 0)
                    if v:
                        facets['types'][v] += c
            elif field == 'dateMin':
                for item in counts:
                    v = item.get('value')
                    c = item.get('count', 0)
                    y = ResponseProcessor._to_year(v)
                    if y:
                        century = f"{((y - 1)//100) + 1}. Jahrhundert"
                        facets['periods'][century] += c

        return {
            key: dict(sorted(val.items(), key=lambda x: x[1], reverse=True)[:10])
            for key, val in facets.items()
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
            
            # Add date if available (dateMin, fallback dateMax)
            year = None
            if (dv := doc.get('dateMin')) is not None:
                year = ResponseProcessor._to_year(dv)
            if year is None and (dv := doc.get('dateMax')) is not None:
                year = ResponseProcessor._to_year(dv)
            sample["date"] = str(year) if year else "Unbekannt"
            
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
        elif name == "kulturpool_get_institutions":
            return await kulturpool_get_institutions_handler(arguments)
        elif name == "kulturpool_get_institution_details":
            return await kulturpool_get_institution_details_handler(arguments)
        elif name == "kulturpool_get_assets":
            return await kulturpool_get_assets_handler(arguments)
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
        'facet_by': 'dataProvider,edmType,dateMin,dateMax',
        'include_fields': 'id,title,creator,dataProvider,edmType,previewImage,isShownAt,isShownBy,object,iiifManifest,dateMin,dateMax,subject,description'
    }
    
    # Execute API call
    response_data = await asyncio.to_thread(api_client.search, api_params)
    
    # Process response
    total_found = response_data.get('found', 0)
    hits = response_data.get('hits', [])
    
    # Generate facets and samples (prefer facet_counts when present)
    facets = ResponseProcessor.analyze_facets_from_response(response_data)
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
    
    # Build API filters - OR within facet groups, AND between facets
    groups = []
    
    # Institutions (OR within group)
    inst_filters = [f"dataProvider:={v}" for v in (params.institutions or [])]
    if inst_filters:
        groups.append(f"({' || '.join(inst_filters)})" if len(inst_filters) > 1 else inst_filters[0])
    
    # Object types (OR within group)  
    type_filters = [f"edmType:={v}" for v in (params.object_types or [])]
    if type_filters:
        groups.append(f"({' || '.join(type_filters)})" if len(type_filters) > 1 else type_filters[0])
    
    # Creators (wildcard, OR within group)
    creator_filters = [f"creator:*{v}*" for v in (params.creators or [])]
    if creator_filters:
        groups.append(f"({' || '.join(creator_filters)})" if len(creator_filters) > 1 else creator_filters[0])
    
    # Subjects (exact matching, OR within group)
    subject_filters = [f"subject:={v}" for v in (params.subjects or [])]
    if subject_filters:
        groups.append(f"({' || '.join(subject_filters)})" if len(subject_filters) > 1 else subject_filters[0])
    
    # Media (exact matching, OR within group)
    media_filters = [f"medium:={v}" for v in (params.media or [])]
    if media_filters:
        groups.append(f"({' || '.join(media_filters)})" if len(media_filters) > 1 else media_filters[0])
    
    # DC Types (exact matching, OR within group)
    dc_filters = [f"dcType:={v}" for v in (params.dc_types or [])]
    if dc_filters:
        groups.append(f"({' || '.join(dc_filters)})" if len(dc_filters) > 1 else dc_filters[0])
    
    # Date range filters with interval-overlap semantics
    # Convert years to Unix timestamps for API compatibility
    # Overlap([dateMin,dateMax], [from,to]) => (dateMin <= to) && (dateMax >= from OR dateMin >= from)
    if params.date_from and params.date_to:
        # Convert years to Unix timestamps (Jan 1st)
        from_ts = int(datetime(params.date_from, 1, 1).timestamp())
        to_ts = int(datetime(params.date_to, 12, 31, 23, 59, 59).timestamp())
        
        # Only include objects with valid dates when filtering by date
        groups.append(f"dateMin:<={to_ts}")
        groups.append(f"(dateMax:>={from_ts} || dateMin:>={from_ts})")
        groups.append(f"(dateMin:>0 || dateMax:>0)")
    elif params.date_from and not params.date_to:
        from_ts = int(datetime(params.date_from, 1, 1).timestamp())
        groups.append(f"(dateMax:>={from_ts} || dateMin:>={from_ts})")
        groups.append(f"(dateMin:>0 || dateMax:>0)")
    elif params.date_to and not params.date_from:
        to_ts = int(datetime(params.date_to, 12, 31, 23, 59, 59).timestamp())
        groups.append(f"dateMin:<={to_ts}")
        groups.append(f"(dateMin:>0 || dateMax:>0)")
    
    # Build API parameters
    api_params = {
        'q': params.query,
        'per_page': params.limit,
        'include_fields': 'id,title,creator,dataProvider,edmType,previewImage,isShownAt,isShownBy,object,iiifManifest,dateMin,dateMax,subject,description'
    }
    
    # Debug: Log the groups and parameters
    debug_info = {
        'date_from': params.date_from,
        'date_to': params.date_to,
        'groups_count': len(groups),
        'groups': groups[:3],  # First 3 for debugging
        'groups_bool': bool(groups),
        'filter_by_set': False
    }
    
    # Force filter application if groups exist
    if len(groups) > 0:
        filter_string = ' && '.join(groups)
        api_params['filter_by'] = filter_string
        debug_info['final_filter_by'] = filter_string
        debug_info['filter_by_set'] = True
    
    if params.sort_by:
        api_params['sort_by'] = params.sort_by
    
    # Execute API call
    response_data = await asyncio.to_thread(api_client.search, api_params)
    
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
        
        # Add formatted date from dateMin, fallback to dateMax
        y = None
        if (dv := doc.get('dateMin')) is not None:
            y = ResponseProcessor._to_year(dv)
        if y is None and (dv := doc.get('dateMax')) is not None:
            y = ResponseProcessor._to_year(dv)
        result_obj["date"] = y
        
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
        "debug_filter_query": api_params.get('filter_by', 'No filters applied'),
        "debug_info": debug_info,
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
            
            response_data = await asyncio.to_thread(api_client.search, api_params)
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
                
                # Add date if available (dateMin, fallback dateMax)
                y = None
                if (dv := doc.get('dateMin')) is not None:
                    y = ResponseProcessor._to_year(dv)
                if y is None and (dv := doc.get('dateMax')) is not None:
                    y = ResponseProcessor._to_year(dv)
                if y is not None:
                    related_obj["date"] = y
                
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

# ==============================================================================
# INSTITUTION MANAGEMENT HANDLERS (Phase 5)
# ==============================================================================

async def kulturpool_get_institutions_handler(arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle kulturpool_get_institutions tool calls"""
    if not rate_limiter.is_allowed():
        raise ValueError("Rate limit exceeded. Please try again later.")
    
    include_locations = arguments.get('include_locations', True)
    language = arguments.get('language', 'de')
    
    if language not in ['de', 'en']:
        language = 'de'
    
    try:
        response_data = await asyncio.to_thread(
            api_client.get_institutions,
            include_locations=include_locations,
            language=language
        )
        
        response_data["request_params"] = {
            "include_locations": include_locations,
            "language": language
        }
        response_data["response_info"] = {
            "timestamp": datetime.now().isoformat(),
            "data_source": "Kulturpool API",
            "note": "Use kulturpool_get_institution_details for complete information"
        }
        
        return [TextContent(type="text", text=json.dumps(response_data, indent=2, ensure_ascii=False))]
        
    except Exception as e:
        raise ValueError(f"Failed to retrieve institutions: {str(e)}")

async def kulturpool_get_institution_details_handler(arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle kulturpool_get_institution_details tool calls"""
    if not rate_limiter.is_allowed():
        raise ValueError("Rate limit exceeded. Please try again later.")
    
    institution_id = arguments.get('institution_id')
    language = arguments.get('language', 'de')
    
    if not institution_id or institution_id < 1:
        raise ValueError("Valid institution_id is required")
    
    if language not in ['de', 'en']:
        language = 'de'
    
    try:
        institution_data = await asyncio.to_thread(
            api_client.get_institution_details,
            institution_id=institution_id,
            language=language
        )
        
        processed_data = {
            "institution_id": institution_id,
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
                "language": language,
                "timestamp": datetime.now().isoformat()
            }
        }
        
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
        
        processed_data["note"] = "For image assets, use kulturpool_get_assets with asset IDs"
        
        return [TextContent(type="text", text=json.dumps(processed_data, indent=2, ensure_ascii=False))]
        
    except Exception as e:
        raise ValueError(f"Failed to retrieve institution details for ID {institution_id}: {str(e)}")

async def kulturpool_get_assets_handler(arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle kulturpool_get_assets tool calls"""
    if not rate_limiter.is_allowed():
        raise ValueError("Rate limit exceeded. Please try again later.")
    
    asset_id = arguments.get('asset_id')
    if not asset_id:
        raise ValueError("asset_id is required")
    
    asset_id = SecurityValidator.sanitize_input(asset_id)
    
    width = arguments.get('width')
    height = arguments.get('height')
    format = arguments.get('format', 'webp')
    quality = arguments.get('quality', 85)
    fit = arguments.get('fit', 'inside')
    
    if format not in ['webp', 'jpeg', 'png']:
        format = 'webp'
    if not (1 <= quality <= 100):
        quality = 85
    if fit not in ['inside', 'outside', 'cover', 'fill']:
        fit = 'inside'
    if width and not (1 <= width <= 4000):
        width = None
    if height and not (1 <= height <= 4000):
        height = None
    
    try:
        asset_data = await asyncio.to_thread(
            api_client.get_asset,
            asset_id=asset_id,
            width=width,
            height=height,
            format=format,
            quality=quality,
            fit=fit
        )
        
        asset_data["usage_info"] = {
            "original_asset_id": asset_id,
            "transformation_applied": bool(width or height),
            "timestamp": datetime.now().isoformat(),
            "note": "This URL provides optimized image with specified transformations"
        }
        
        return [TextContent(type="text", text=json.dumps(asset_data, indent=2, ensure_ascii=False))]
        
    except Exception as e:
        raise ValueError(f"Failed to retrieve asset {asset_id}: {str(e)}")


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
            description="Filtered search with specific facets. Returns max 20 results with complete metadata. Date filters accept years and use interval overlap semantics: an object matches if its [dateMin,dateMax] overlaps [date_from,date_to]. Supports creators, subjects, media, and Dublin Core type filters.",
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
                        "description": "Filter by start year (interval overlaps)"
                    },
                    "date_to": {
                        "type": "integer",
                        "description": "Filter by end year (interval overlaps)"
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
            }        ),
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
    print("3. kulturpool_get_details - Complete metadata (≤ 3 objects)", file=sys.stderr)
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
