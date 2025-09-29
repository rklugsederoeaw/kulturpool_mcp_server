# Add these new handler functions to server.py right before the existing handlers

async def kulturpool_get_institutions_handler(arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle kulturpool_get_institutions tool calls"""
    if not rate_limiter.is_allowed():
        raise ValueError("Rate limit exceeded. Please try again later.")
    
    # Simple parameter validation
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
        
        # Process location if available
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
    
    # Sanitize asset_id
    asset_id = SecurityValidator.sanitize_input(asset_id)
    
    # Optional parameters with defaults
    width = arguments.get('width')
    height = arguments.get('height')
    format = arguments.get('format', 'webp')
    quality = arguments.get('quality', 85)
    fit = arguments.get('fit', 'inside')
    
    # Validate parameters
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
