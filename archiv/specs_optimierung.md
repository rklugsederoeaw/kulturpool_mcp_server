# Kulturerbe MCP Server - Enhancement Specifications

**Version:** 2.1 Status nach Phase 1-4  
**Datum:** 2025-01-13  
**Basis:** Aktueller Server v2.0 (server.py)  
**Status:** Phase 1-4 abgeschlossen, Phase 5+ offen

## 🎯 Übersicht

**Phase 1-4 erfolgreich implementiert:** Alle 4 sinnvollen Facetten sind funktional.
**Nächste Phase:** Zusätzliche API-Endpoints für Institution-Management.

## ✅ Abgeschlossene Implementierung (Phase 1-4)

### Implementierte Filter-Facetten

| Facette    | API-Syntax         | Limit | Performance | Status |
| ---------- | ------------------ | ----- | ----------- | ------ |
| `creators` | `creator:*name*`   | 5     | Gut         | ✅ Done |
| `subjects` | `subject:=topic`   | 10    | Gut         | ✅ Done |
| `media`    | `medium:=material` | 5     | Gut         | ✅ Done |
| `dc_types` | `dcType:=type`     | 3     | Vorsicht    | ✅ Done |

### Performance-Erkenntnisse

- **Einzelfilter:** < 2s Response-Zeit
- **Kombinierte Filter:** < 3s Response-Zeit
- **dcType-Filter:** Konservative Limits (max 3) wegen 124k+ Resultsets
- **Kombinationen reduzieren Risiko:** Mehrfachfilter performance-sicher

### Code-Struktur

```python
class KulturpoolSearchParams(BaseModel):
    # Existing base parameters...
    creators: Optional[List[str]] = Field(None, max_length=5)
    subjects: Optional[List[str]] = Field(None, max_length=10)
    media: Optional[List[str]] = Field(None, max_length=5)
    dc_types: Optional[List[str]] = Field(None, max_length=3)  # Performance-limited
```

### Validierung

- **creators/subjects/media:** SecurityValidator.sanitize_input()
- **dc_types:** Zusätzlich Whitelist-Validierung gegen KNOWN_DC_TYPES
- **Performance:** dcType-Filter nur mit bekannten Typen

### API-Verhalten (curl-verifiziert)

- **Kombinierte Filter:** AND-Logic zwischen verschiedenen Facetten-Typen
- **Multi-Werte:** OR-Logic innerhalb gleicher Facette
- **Filter-Syntax:** Exakte API-Konformität mit `&&` Separator
- **Leere Überschneidungen:** Normal (z.B. Mozart+Portrait = 0 Treffer)

## Nächste Phase: Institution-Management Tools

#### Important: Sehr umfangreiche Payloads, überfluten in ungefilterter Form Claudes Context Window. Vorsichtig testen. Vermutlich nur mit Ergebnis-Zwischenspeicherung in Redis möglich bzw. sinnvoll. Vor Development API gezielt mit curls testen.

#### Important: API-Dokumentation lesen:

1. API_documentation.json

2. server.py analysieren und verstehen

#### 2.1 Tool: `kulturpool_get_institutions`

**Zweck:** Vollständige Liste aller teilnehmenden Institutionen

#### API-Endpoint

- **URL:** `GET /institutions/`
- **Response:** Liste aller Institutionen mit Metadaten

#### Tool-Definition

```python
Tool(
    name="kulturpool_get_institutions",
    description="Get complete list of all participating cultural institutions with metadata, locations, and multilingual descriptions.",
    inputSchema={
        "type": "object",
        "properties": {
            "include_locations": {
                "type": "boolean",
                "description": "Include GeoJSON location data",
                "default": True
            },
            "language": {
                "type": "string", 
                "description": "Language for descriptions (de, en)",
                "default": "de",
                "enum": ["de", "en"]
            }
        }
    }
)
```

#### Handler-Implementation

```python
async def kulturpool_get_institutions_handler(arguments: Dict[str, Any]) -> List[TextContent]:
    """Fetch all institutions from /institutions/ endpoint"""
    # Rate limiting
    if not rate_limiter.is_allowed():
        raise ValueError("Rate limit exceeded")

    # API Call
    response = api_client.session.get(
        "https://api.kulturpool.at/institutions/",
        timeout=api_client.TIMEOUT
    )
    response.raise_for_status()
    data = response.json()

    # Process institutions
    institutions = []
    for inst in data.get('data', []):
        institution = {
            "id": inst.get('id'),
            "name": inst.get('name'),
            "website": inst.get('website_url'),
            "collection_url": inst.get('web_collection_url')
        }

        # Add location if requested
        if arguments.get('include_locations', True):
            if location := inst.get('location'):
                institution["location"] = location

        # Add translations
        lang = arguments.get('language', 'de')
        for translation in inst.get('translations', []):
            if translation.get('languages_code') == lang:
                institution.update({
                    "title": translation.get('title'),
                    "place": translation.get('place'), 
                    "summary": translation.get('summary'),
                    "description": translation.get('content')
                })
                break

        institutions.append(institution)

    result = {
        "total_institutions": len(institutions),
        "language": arguments.get('language', 'de'),
        "institutions": institutions
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]
```

### 2.2 Tool: `kulturpool_get_institution_details`

**Zweck:** Detaillierte Informationen zu spezifischer Institution

#### API-Endpoint

- **URL:** `GET /institutions/{institution_id}`
- **Response:** Vollständige Institution-Details

#### Tool-Definition

```python
Tool(
    name="kulturpool_get_institution_details", 
    description="Get detailed information about a specific cultural institution including location, images, and multilingual content.",
    inputSchema={
        "type": "object",
        "properties": {
            "institution_id": {
                "type": "integer",
                "description": "Unique institution ID",
                "minimum": 1
            },
            "language": {
                "type": "string",
                "description": "Language for content (de, en)", 
                "default": "de",
                "enum": ["de", "en"]
            }
        },
        "required": ["institution_id"]
    }
)
```

### 2.3 Tool: `kulturpool_get_assets`

**Zweck:** Optimierte Bild-Transformationen und Asset-Management

#### API-Endpoint

- **URL:** `GET /assets/{asset_id}`
- **Features:** Bildtransformation mit Parametern

#### Tool-Definition

```python
Tool(
    name="kulturpool_get_assets",
    description="Get optimized images and assets with transformation parameters (resize, format conversion, quality adjustment).",
    inputSchema={
        "type": "object", 
        "properties": {
            "asset_id": {
                "type": "string",
                "description": "Asset UUID from institution data"
            },
            "width": {
                "type": "integer",
                "description": "Target width in pixels",
                "minimum": 50,
                "maximum": 2048
            },
            "height": {
                "type": "integer", 
                "description": "Target height in pixels",
                "minimum": 50,
                "maximum": 2048
            },
            "format": {
                "type": "string",
                "description": "Output format",
                "enum": ["auto", "avif", "jpg", "png", "webp", "tiff"],
                "default": "auto"
            },
            "quality": {
                "type": "integer",
                "description": "Image quality (1-100)",
                "minimum": 1,
                "maximum": 100,
                "default": 80
            },
            "fit": {
                "type": "string",
                "description": "How to fit image to dimensions",
                "enum": ["cover", "contain", "inside", "outside"],
                "default": "cover"
            }
        },
        "required": ["asset_id"]
    }
)
```

## 📊 Aktueller Status

**Phase 1-4 abgeschlossen:** Alle 4 funktionalen Facetten implementiert ✅  
**Performance-Ziele erreicht:** < 3s für komplexe Multi-Filter ✅  
**API-Konformität:** Vollständige Filter-Unterstützung ✅  
**Nächste Phase:** Institution-Tools für vollständige API-Abdeckung

**Wichtige Hinweise für nächste Implementierung:**

- curl-Tests vor Development
- Performance-Monitoring bei neuen Endpoints  
- Context-Window-Management für große Institution-Listen
