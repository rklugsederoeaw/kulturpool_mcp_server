# Minor Improvements for server.py

Pragmatische, wirklich wirksame Verbesserungen – ohne Over‑Engineering.

## 1. Response Microcaching (High Impact)

Ziel: Latenz und API‑Last bei wiederholten identischen Requests reduzieren.

- In‑Memory TTL‑Cache, Key = vollständige Request‑Signatur (URL + alle Query‑Parameter)
- TTL: `/search/` 30–120s (z. B. 60s); `/institutions` und `/institutions/{id}` 6–24h
- Nur 200‑JSON Antworten cachen (keine Fehler/T​​imeouts)
- Thread‑safe Zugriff (Lock), da HTTP‑Calls via `asyncio.to_thread` laufen

Skizze:

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

Problem: `get_asset` lädt aktuell den Body per GET, obwohl nur Header/URL benötigt werden.

Lösung:

- `HEAD` verwenden, wenn der Endpoint dies unterstützt; andernfalls `GET(stream=True)` und Response sofort schließen.

Skizze:

```python
resp = self.session.head(url, params=params, timeout=30)
resp.raise_for_status()
headers = resp.headers
# Fallback
resp = self.session.get(url, params=params, timeout=30, stream=True)
resp.raise_for_status()
headers = resp.headers
resp.close()
```

Nutzen: Deutlich weniger Bandbreite und schnellere Antworten bei großen Medien.

## 3. Explore per_page reduzieren (Medium Impact)

Rationale: Facetten werden über `facet_counts` geliefert; die Anzahl geladener Hits beeinflusst die Facetten nicht.

- `kulturpool_explore`: `per_page = 10` (statt 50)
- `include_fields` beibehalten, um Sample‑Treffer schlank zu halten

Trade‑off: Weniger Sample‑Einträge, gleiche Facettenqualität, bessere Latenz.

## Umsetzung‑Priorität

1. Response Microcaching (High)
2. Asset Retrieval via HEAD/stream (High)
3. Explore per_page reduzieren (Medium)
