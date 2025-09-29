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
