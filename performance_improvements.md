# Performance Improvements for server.py

Pragmatic, high-impact improvements without over-engineering.

## 1. Response Microcaching (High Impact)

**Goal:** Reduce latency and API load for repeated identical requests.

- In-memory TTL cache with key = complete request signature (URL + all query parameters)
- TTL: `/search/` 30–120s (e.g., 60s); `/institutions` and `/institutions/{id}` 6–24h
- Cache only 200 JSON responses (no errors/timeouts)
- Thread-safe access (Lock) since HTTP calls run via `asyncio.to_thread`

**Implementation Sketch:**

```python
from time import time
from threading import Lock

_CACHE: dict[str, tuple[float, dict]] = {}
_LOCK = Lock()

def cache_get(key: str):
    now = time()
    with _LOCK:
        entry = _CACHE.get(key)
        if not entry:
            return None
        exp, data = entry
        if now > exp:
            _CACHE.pop(key, None)
            return None
        return data

def cache_set(key: str, data: dict, ttl: float):
    with _LOCK:
        _CACHE[key] = (time() + ttl, data)
```

## 2. Asset Retrieval via HEAD/stream (High Impact)

**Problem:** `get_asset` currently loads the body via GET, although only headers/URL are needed.

**Solution:**
- Use `HEAD` if the endpoint supports it; otherwise `GET(stream=True)` and close response immediately.

**Implementation Sketch:**

```python
try:
    resp = self.session.head(url, params=params, timeout=30)
    resp.raise_for_status()
    headers = resp.headers
except:
    # Fallback
    resp = self.session.get(url, params=params, timeout=30, stream=True)
    resp.raise_for_status()
    headers = resp.headers
    resp.close()
```

**Benefits:** Significantly less bandwidth and faster responses for large media files.

## 3. Reduce Explore per_page (Medium Impact)

**Rationale:** Facets are delivered via `facet_counts`; the number of loaded hits does not affect the facets.

- `kulturpool_explore`: `per_page = 10` (instead of 50)
- Keep `include_fields` to maintain slim sample hits

**Trade-off:** Fewer sample entries, same facet quality, better latency.

## Implementation Priority

1. **Response Microcaching (High)**
2. **Asset Retrieval via HEAD/stream (High)**
3. **Reduce Explore per_page (Medium)**

## Technical Context

### Current Code Analysis

**Response Microcaching:**
- No caching mechanisms currently implemented
- Every request goes directly to API (server.py:212-217, 235-237, 281-283, 307-308)
- Rate limiter exists (100 req/h) but no response cache

**Asset Retrieval:**
- Currently uses full GET request for metadata only (server.py:307-315)
- Only headers are used: `content_type`, `content_length`
- Unnecessary bandwidth usage for large media files

**Explore per_page:**
- Current setting: `per_page: 50` (server.py:657)
- Facets come from `facet_by` parameter, not sample count
- 50 sample results are excessive for facet analysis

## Expected Benefits

- **Latency Reduction:** 30-80% for cached requests
- **API Load Reduction:** Significant decrease in redundant calls
- **Bandwidth Savings:** Major improvement for asset metadata requests
- **Better User Experience:** Faster response times for repeated queries

## Risk Assessment

- **Low Risk:** All improvements are additive and backwards compatible
- **Graceful Degradation:** Fallback mechanisms included
- **No Breaking Changes:** Existing functionality remains intact