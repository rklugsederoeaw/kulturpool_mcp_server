#!/bin/bash
# Phase 5 Implementation Script - Add Institution Management Tools

echo "=== Kulturerbe MCP Server v2.2 - Phase 5 Implementation ==="
echo "Adding 3 Institution Management Tools to existing server.py"

# Backup current server
cp server.py server_v2.1_backup.py
echo "✓ Backup created: server_v2.1_backup.py"

# Create temp working file
cp server.py server_working.py

# Step 1: Add new API methods to KulturpoolAPIClient class
echo "Step 1: Adding new API methods..."

# Find the line with "# Global API client" and insert new methods before it
sed -i '/# Global API client/i\
\
    def get_institutions(self, include_locations: bool = True, language: str = "de") -> Dict[str, Any]:\
        """Get list of all institutions"""\
        url = f"{self.base_url}/institutions/"\
        params = {}\
        \
        if language in ["de", "en"]:\
            params["language"] = language\
        \
        try:\
            response = self.session.get(url, params=params, timeout=30)\
            response.raise_for_status()\
            data = response.json()\
            \
            institutions = data.get("data", [])\
            processed_institutions = []\
            \
            for inst in institutions:\
                processed_inst = {\
                    "id": inst.get("id"),\
                    "name": inst.get("name"),\
                    "web_collection_url": inst.get("web_collection_url"),\
                    "website_url": inst.get("website_url")\
                }\
                \
                if include_locations and inst.get("location"):\
                    location = inst.get("location", {})\
                    if location.get("coordinates"):\
                        coords = location["coordinates"]\
                        if coords and len(coords) > 0 and len(coords[0]) >= 2:\
                            processed_inst["location"] = {\
                                "lat": coords[0][1],\
                                "lng": coords[0][0]\
                            }\
                \
                processed_institutions.append(processed_inst)\
            \
            return {\
                "institutions": processed_institutions,\
                "total_count": len(processed_institutions)\
            }\
            \
        except requests.Timeout:\
            raise ValueError("API request timed out")\
        except requests.RequestException as e:\
            raise ValueError(f"API request failed: {str(e)}")\
    \
    def get_institution_details(self, institution_id: int, language: str = "de") -> Dict[str, Any]:\
        """Get detailed information about a specific institution"""\
        url = f"{self.base_url}/institutions/{institution_id}"\
        params = {}\
        \
        if language in ["de", "en"]:\
            params["language"] = language\
        \
        try:\
            response = self.session.get(url, params=params, timeout=30)\
            response.raise_for_status()\
            data = response.json()\
            return data.get("data", {})\
        except requests.Timeout:\
            raise ValueError("API request timed out")\
        except requests.RequestException as e:\
            raise ValueError(f"API request failed: {str(e)}")\
    \
    def get_asset(self, asset_id: str, width: Optional[int] = None, height: Optional[int] = None, format: str = "webp", quality: int = 85, fit: str = "inside") -> Dict[str, Any]:\
        """Get optimized asset with transformations"""\
        url = f"{self.base_url}/assets/{asset_id}"\
        params = {}\
        \
        if width:\
            params["width"] = width\
        if height:\
            params["height"] = height\
        if format in ["webp", "jpeg", "png"]:\
            params["format"] = format\
        if 1 <= quality <= 100:\
            params["quality"] = quality\
        if fit in ["inside", "outside", "cover", "fill"]:\
            params["fit"] = fit\
        \
        try:\
            response = self.session.get(url, params=params, timeout=30)\
            response.raise_for_status()\
            return {\
                "asset_id": asset_id,\
                "url": response.url,\
                "content_type": response.headers.get("content-type", ""),\
                "content_length": response.headers.get("content-length", ""),\
                "transformations": params\
            }\
        except requests.Timeout:\
            raise ValueError("API request timed out")\
        except requests.RequestException as e:\
            raise ValueError(f"API request failed: {str(e)}")\
' server_working.py

echo "✓ API methods added"

# This is getting complex - let me create a simple Python script instead
cat > apply_phase5.py << 'EOF'
#!/usr/bin/env python3
"""
Apply Phase 5 changes to server.py
"""

import re

def apply_phase5():
    """Apply all Phase 5 changes to server.py"""
    
    print("=== Kulturerbe MCP Server v2.2 - Phase 5 Implementation ===")
    
    # Read current server.py
    with open('server.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Backup
    with open('server_v2.1_backup.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("✓ Backup created: server_v2.1_backup.py")
    
    # Add new API methods before "# Global API client"
    api_methods = '''
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

'''
    
    content = content.replace('# Global API client', api_methods + '\n# Global API client')
    print("✓ API methods added")
    
    # Add new handlers before @server.list_tools()
    handlers = '''
async def kulturpool_get_institutions_handler(arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle kulturpool_get_institutions tool calls"""
    if not rate_limiter.is_allowed():
        raise ValueError("Rate limit exceeded. Please try again later.")
    
    include_locations = arguments.get('include_locations', True)
    language = arguments.get('language', 'de')
    
    if language not in ['de', 'en']:
        language = 'de'
    
    try:
        response_data = api_client.get_institutions(
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
        institution_data = api_client.get_institution_details(
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
        asset_data = api_client.get_asset(
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

'''
    
    content = content.replace('@server.list_tools()', handlers + '\n@server.list_tools()')
    print("✓ Handlers added")
    
    # Add tool calls to handle_call_tool function
    # Find the elif chain and add new cases
    old_handle = '''        elif name == "kulturpool_get_details":
            return await kulturpool_get_details_handler(arguments)
        else:'''
    
    new_handle = '''        elif name == "kulturpool_get_details":
            return await kulturpool_get_details_handler(arguments)
        elif name == "kulturpool_get_institutions":
            return await kulturpool_get_institutions_handler(arguments)
        elif name == "kulturpool_get_institution_details":
            return await kulturpool_get_institution_details_handler(arguments)
        elif name == "kulturpool_get_assets":
            return await kulturpool_get_assets_handler(arguments)
        else:'''
    
    content = content.replace(old_handle, new_handle)
    print("✓ Tool routing added")
    
    # Add new tools to the tool list in list_tools()
    # Find the closing of kulturpool_get_details tool and add new ones
    new_tools = '''        ),
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
        )'''
    
    # Find the last tool definition and replace the closing
    old_closing = '''                "required": ["object_ids"]
            }
        )
    ]'''
    
    new_closing = '''                "required": ["object_ids"]
            }''' + new_tools + '''
    ]'''
    
    content = content.replace(old_closing, new_closing)
    print("✓ Tool definitions added")
    
    # Update version info in main()
    content = content.replace('Kulturerbe MCP Server...', 'Kulturerbe MCP Server v2.2...')
    content = content.replace('3-Tool Progressive Disclosure Architecture:', '6-Tool Progressive Disclosure Architecture:')
    content = content.replace('Rate limit: 100 requests/hour per client', '''4. kulturpool_get_institutions - Institution list
    print("5. kulturpool_get_institution_details - Institution details", file=sys.stderr)
    print("6. kulturpool_get_assets - Optimized image assets", file=sys.stderr)
    print("Rate limit: 100 requests/hour per client", file=sys.stderr''')
    
    # Write the updated server
    with open('server.py', 'w', encoding='utf-8') as f:
        f.write(content)
    
    print("✓ Updated version info")
    print("\n=== Phase 5 Implementation Complete ===")
    print("✓ 3 new Institution Management Tools added:")
    print("  - kulturpool_get_institutions")
    print("  - kulturpool_get_institution_details") 
    print("  - kulturpool_get_assets")
    print("✓ Server upgraded to v2.2")
    print("✓ All changes applied to server.py")
    print("✓ Backup saved as server_v2.1_backup.py")

if __name__ == "__main__":
    apply_phase5()
EOF

python3 apply_phase5.py
rm apply_phase5.py

echo "Phase 5 implementation complete!"
