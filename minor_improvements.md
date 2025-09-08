# Minor Improvements for server.py

This document outlines pragmatic improvements that would genuinely enhance the MCP server without over-engineering.

## 1. Replace requests with httpx (High Impact)

**Problem**: Synchronous `requests` blocks the async event loop
**Solution**: Replace with `httpx` for true async I/O

```python
import httpx

class KulturpoolClient:
    def __init__(self):
        self.client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=10.0,
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
        )

    async def search(self, params: Dict[str, Any]) -> Dict[str, Any]:
        response = await self.client.get("", params=params)
        response.raise_for_status()
        return response.json()
```

**Benefits**: 

- True concurrent request handling
- Better resource utilization
- Maintains existing retry/connection pooling patterns

## 2. Improve Logging (Medium Impact)

**Problem**: `print` to stderr lacks control and structure
**Solution**: Standard Python logging with structured output

```python
import logging

# At module level
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Usage examples
logger.info("Starting Kulturerbe MCP Server...")
logger.warning(f"Rate limit exceeded for request")
logger.error(f"API call failed: {e}", exc_info=True)
```

**Benefits**:

- Production-ready error tracking
- Configurable log levels
- Better debugging capabilities

## 3. Enhance Input Validation (Medium Impact)

**Current Issue**: Some facet parameters lack validation
**Solution**: Add validation for institution and object_type arrays

```python
class KulturpoolSearchFilteredParams(BaseModel):
    # ... existing fields ...
    institutions: Optional[List[str]] = Field(
        None, 
        max_items=10,
        description="Filter by institutions"
    )
    object_types: Optional[List[str]] = Field(
        None, 
        max_items=5,
        description="Filter by object types (IMAGE, TEXT, SOUND, VIDEO, 3D)"
    )

    @field_validator('object_types')
    @classmethod
    def validate_object_types(cls, v):
        if v:
            valid_types = {"IMAGE", "TEXT", "SOUND", "VIDEO", "3D"}
            invalid = set(v) - valid_types
            if invalid:
                raise ValueError(f"Invalid object types: {invalid}")
        return v
```

## 4. Fix Potential Race Condition in RateLimiter (Low Impact)

**Problem**: Non-atomic operations could cause race conditions under high concurrency
**Solution**: Use threading.Lock for thread safety

```python
import threading
from collections import defaultdict, deque

class RateLimiter:
    def __init__(self, max_requests: int = 100, time_window: int = 3600):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = defaultdict(deque)
        self._lock = threading.Lock()

    def is_allowed(self, identifier: str = "default") -> bool:
        with self._lock:
            now = time.time()
            # Remove old requests
            while (self.requests[identifier] and 
                   now - self.requests[identifier][0] > self.time_window):
                self.requests[identifier].popleft()

            # Check if under limit
            if len(self.requests[identifier]) >= self.max_requests:
                return False

            # Add current request
            self.requests[identifier].append(now)
            return True
```

## 5. Improve Error Granularity (Low Impact)

**Enhancement**: Provide more specific error types for better client handling

```python
class KulturpoolError(Exception):
    """Base exception for Kulturpool API errors"""
    pass

class KulturpoolRateLimitError(KulturpoolError):
    """Rate limit exceeded"""
    pass

class KulturpoolValidationError(KulturpoolError):
    """Input validation failed"""
    pass

# In handlers
if not rate_limiter.is_allowed():
    raise KulturpoolRateLimitError("Rate limit exceeded. Try again later.")
```

## Implementation Priority

1. **httpx migration** - Highest impact, essential for production scalability
2. **Logging implementation** - Medium impact, important for operations
3. **Input validation enhancement** - Medium impact, improves robustness
4. **RateLimiter thread safety** - Low impact, defensive programming
5. **Error granularity** - Low impact, nice-to-have for API consumers

## Conclusion

These improvements focus on genuine quality enhancements rather than architectural changes. The existing code structure is solid and doesn't require major refactoring.