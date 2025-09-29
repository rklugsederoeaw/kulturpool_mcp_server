 not large_image and preview_url:
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
    # Phase 1-4 filters
    creators: Optional[List[str]] = Field(None, max_length=5)
    subjects: Optional[List[str]] = Field(None, max_length=10)
    media: Optional[List[str]] = Field(None, max_length=5)
    dc_types: Optional[List[str]] = Field(None, max_length=3)
    
    # Known values for validation
    KNOWN_INSTITUTIONS: ClassVar[List[str]] = [
        "Albertina", "Belvedere", "Österreichische Nationalbibliothek",
        "Wiener Stadt- und Landesarchiv", "MAK", "Weltmuseum Wien",
        "Technisches Museum Wien", "Naturhistorisches Museum Wien"
    ]
    
    KNOWN_TYPES: ClassVar[List[str]] = ["IMAGE", "TEXT", "SOUND", "VIDEO", "3D"]
    
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
            sanitized = []
            for creator in v:
                sanitized_creator = SecurityValidator.sanitize_input(creator)
                if sanitized_creator:
                    sanitized.append(sanitized_creator)
            return sanitized
        return v
    
    @field_validator('subjects')
    @classmethod
    def validate_subjects(cls, v):
        if v:
            sanitized = []
            for subject in v:
                sanitized_subject = SecurityValidator.sanitize_input(subject)
                if sanitized_subject:
                    sanitized.append(sanitized_subject)
            return sanitized
        return v
    
    @field_validator('media')
    @classmethod
    def validate_media(cls, v):
        if v:
            sanitized = []
            for medium in v:
                sanitized_medium = SecurityValidator.sanitize_input(medium)
                if sanitized_medium:
                    sanitized.append(sanitized_medium)
            return sanitized
        return v
    
    @field_validator('dc_types')
    @classmethod
    def validate_dc_types(cls, v):
        if v:
            sanitized = []
            for dc_type in v:
                sanitized_dc_type = SecurityValidator.sanitize_input(dc_type)
                if sanitized_dc_type:
                    sanitized.append(sanitized_dc_type)
            return sanitized
        return v

class KulturpoolDetailsParams(BaseModel):
    """Parameters for kulturpool_get_details tool"""
    object_ids: List[str] = Field(..., min_length=1, max_length=3)
    
    @field_validator('object_ids')
    @classmethod  
    def validate_ids(cls, v):
        return [SecurityValidator.sanitize_input(id_val) for id_val in v]

# ==============================================================================
# NEW: INSTITUTION MANAGEMENT PARAMETER MODELS (Phase 5)
# ==============================================================================

class InstitutionsListParams(BaseModel):
    """Parameters for kulturpool_get_institutions tool"""
    include_locations: bool = Field(default=True, description="Include geographical coordinates")
    language: str = Field(default="de", pattern="^(de|en)$", description="Response language")

class InstitutionDetailsParams(BaseModel):
    """Parameters for kulturpool_get_institution_details tool"""
    institution_id: int = Field(..., ge=1, description="Institution ID")
    language: str = Field(default="de", pattern="^(de|en)$", description="Response language")

class AssetParams(BaseModel):
    """Parameters for kulturpool_get_assets tool"""
    asset_id: str = Field(..., min_length=1, description="Asset ID")
    width: Optional[int] = Field(None, ge=1, le=4000, description="Target width in pixels")
    height: Optional[int] = Field(None, ge=1, le=4000, description="Target height in pixels") 
    format: str = Field(default="webp", pattern="^(webp|jpeg|png)$", description="Output format")
    quality: int = Field(default=85, ge=1, le=100, description="Quality percentage")
    fit: str = Field(default="inside", pattern="^(inside|outside|cover|fill)$", description="Resize behavior")
    
    @field_validator('asset_id')
    @classmethod  
    def validate_asset_id(cls, v):
        return SecurityValidator.sanitize_input(v)

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
        # NEW Phase 5: Institution Management Tools
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
    if not rate_limiter.is_allowed():
        raise ValueError("Rate limit exceeded. Please try again later.")
    
    params = KulturpoolExploreParams(**arguments)
    
    api_params = {
        'q': params.query,
        'per_page': 50,
        'facet_by': 'dataProvider,edmType,dateMin'
    }
    
    response_data = api_client.search(api_params)
    total_found = response_data.get('found', 0)
    hits = response_data.get('hits', [])
    
    facets = ResponseProcessor.analyze_facets(hits)
    sample_results = ResponseProcessor.format_sample_results(hits, params.max_examples)
    
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
    if not rate_limiter.is_allowed():
        raise ValueError("Rate limit exceeded. Please try again later.")
    
    params = KulturpoolSearchParams(**arguments)
    
    # Build API filters
    filters = []
    
    if params.institutions:
        for institution in params.institutions:
            filters.append(f"dataProvider:={institution}")
    
    if params.object_types:
        for obj_type in params.object_types:
            filters.append(f"edmType:={obj_type}")
    
    if params.date_from:
        filters.append(f"dateMin:>={params.date_from}")
    
    if params.date_to:
        filters.append(f"dateMax:<={params.date_to}")
    
    # Phase 1-4 filters
    if params.creators:
        for creator in params.creators:
            filters.append(f"creator:*{creator}*")
    
    if params.subjects:
        for subject in params.subjects:
            filters.append(f"subject:={subject}")
    
    if params.media:
        for medium in params.media:
            filters.append(f"medium:={medium}")
    
    if params.dc_types:
        for dc_type in params.dc_types:
            filters.append(f"dcType:={dc_type}")
    
    # Build API request
    api_params = {
        'q': params.query,
        'per_page': params.limit,
        'facet_by': 'dataProvider,edmType,creator,subject,medium'
    }
    
    if filters:
        api_params['filter_by'] = '&&'.join(filters)
    
    if params.sort_by:
        sort_field, sort_order = params.sort_by.split(':')
        api_params['sort_by'] = f"{sort_field}:{sort_order}"
    
    response_data = api_client.search(api_params)
    hits = response_data.get('hits', [])
    
    # Format results
    results = []
    for hit in hits:
        doc = hit.get('document', {})
        images = ResponseProcessor.extract_image_urls(doc)
        
        result = {
            "id": doc.get('id', ''),
            "title": doc.get('title', 'Untitled'),
            "creator": doc.get('creator', 'Unknown'),
            "institution": doc.get('dataProvider', ''),
            "type": doc.get('edmType', ''),
            "date_min": doc.get('dateMin', ''),
            "date_max": doc.get('dateMax', ''),
            "description": doc.get('description', ''),
            "subject": doc.get('subject', []),
            "medium": doc.get('medium', ''),
            "images": images,
            "web_url": doc.get('isShownAt', '')
        }
        results.append(result)
    
    response = {
        "total_found": response_data.get('found', 0),
        "results_returned": len(results),
        "query": params.query,
        "filters_applied": filters,
        "results": results
    }
    
    return [TextContent(type="text", text=json.dumps(response, indent=2, ensure_ascii=False))]

async def kulturpool_get_details_handler(arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle kulturpool_get_details tool calls"""
    if not rate_limiter.is_allowed():
        raise ValueError("Rate limit exceeded. Please try again later.")
    
    params = KulturpoolDetailsParams(**arguments)
    
    # Use object IDs as search terms to find related content
    search_query = ' OR '.join(params.object_ids)
    
    api_params = {
        'q': search_query,
        'per_page': 50,
        'facet_by': 'dataProvider,creator,subject'
    }
    
    response_data = api_client.search(api_params)
    hits = response_data.get('hits', [])
    
    # Process related objects
    related_objects = []
    for hit in hits:
        doc = hit.get('document', {})
        
        obj = {
            "id": doc.get('id', ''),
            "title": doc.get('title', 'Untitled'),
            "creator": doc.get('creator', 'Unknown'),
            "institution": doc.get('dataProvider', ''),
            "type": doc.get('edmType', ''),
            "date_range": f"{doc.get('dateMin', '')} - {doc.get('dateMax', '')}",
            "description": doc.get('description', ''),
            "subject": doc.get('subject', []),
            "medium": doc.get('medium', ''),
            "images": ResponseProcessor.extract_image_urls(doc),
            "web_url": doc.get('isShownAt', ''),
            "relevance_score": hit.get('text_match', 0)
        }
        related_objects.append(obj)
    
    # Sort by relevance
    related_objects.sort(key=lambda x: x['relevance_score'], reverse=True)
    
    response = {
        "search_ids": params.object_ids,
        "total_related_found": len(related_objects),
        "related_objects": related_objects[:20]  # Limit to top 20 related objects
    }
    
    return [TextContent(type="text", text=json.dumps(response, indent=2, ensure_ascii=False))]

# ==============================================================================
# NEW Phase 5: INSTITUTION MANAGEMENT HANDLERS
# ==============================================================================

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
        
        # Add metadata
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
        
        # Process and enrich the response
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
        
        # Add usage note
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
        
        # Add usage information
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
        ),                    "language": {
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
