# Add these methods to the KulturpoolAPIClient class in server.py

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
