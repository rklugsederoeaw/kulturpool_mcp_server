import copy
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

# Add parent directory to path for server import
sys.path.insert(0, str(Path(__file__).parent.parent))
import server


class DummyResponse:
    def __init__(self, payload: Dict[str, Any], url: str = "https://api.kulturpool.at/search/") -> None:
        self._payload = copy.deepcopy(payload)
        self.url = url
        encoded = json.dumps(self._payload)
        self.headers = {
            "content-type": "application/json",
            "content-length": str(len(encoded)),
        }

    def raise_for_status(self) -> None:  # pylint: disable=unused-argument
        return None

    def json(self) -> Dict[str, Any]:
        return copy.deepcopy(self._payload)


class DummySession:
    def __init__(self, responses: List[Dict[str, Any]]) -> None:
        self._responses = responses
        self.calls = 0
        self.last_call: Dict[str, Any] = {}

    def get(self, url: str, params: Dict[str, Any] | None = None, timeout: int | None = None) -> DummyResponse:  # noqa: ARG002
        self.last_call = {"url": url, "params": copy.deepcopy(params)}
        index = min(self.calls, len(self._responses) - 1)
        self.calls += 1
        return DummyResponse(self._responses[index], url=url)


def _build_institution_payload() -> Dict[str, Any]:
    return {
        "data": [
            {
                "id": 1,
                "name": "Testmuseum",
                "web_collection_url": "https://example.com/collection",
                "website_url": "https://example.com",
                "location": {
                    "coordinates": [[16.3725, 48.2082]]
                },
            }
        ]
    }


def test_get_institutions_cache_consistency(monkeypatch: pytest.MonkeyPatch) -> None:
    local_cache = server.ResponseCache(max_size=10, cleanup_interval=0)
    monkeypatch.setattr(server, "response_cache", local_cache, raising=False)

    client = server.KulturpoolClient()
    session = DummySession([_build_institution_payload()])
    client.session = session

    first = client.get_institutions(include_locations=True)
    second = client.get_institutions(include_locations=True)

    assert first == second
    assert session.calls == 1, "Expected cache hit to skip second network call"
    assert first["institutions"][0]["location"]["lat"] == pytest.approx(48.2082)


def test_get_institutions_cache_respects_include_locations(monkeypatch: pytest.MonkeyPatch) -> None:
    local_cache = server.ResponseCache(max_size=10, cleanup_interval=0)
    monkeypatch.setattr(server, "response_cache", local_cache, raising=False)

    client = server.KulturpoolClient()
    payload = _build_institution_payload()
    session = DummySession([payload, payload])
    client.session = session

    with_locations = client.get_institutions(include_locations=True)
    without_locations = client.get_institutions(include_locations=False)

    assert session.calls == 2, "Different include_locations flags should bypass cache reuse"
    assert "location" in with_locations["institutions"][0]
    assert "location" not in without_locations["institutions"][0]


def test_search_preserves_params(monkeypatch: pytest.MonkeyPatch) -> None:
    local_cache = server.ResponseCache(max_size=10, cleanup_interval=0)
    monkeypatch.setattr(server, "response_cache", local_cache, raising=False)

    client = server.KulturpoolClient()
    session = DummySession([
        {
            "hits": [],
            "found": 0,
            "facet_counts": [],
        }
    ])
    client.session = session

    params = {
        "q": "wasser",
        "filter_by": "dataProvider:=Albertina",
        "sort_by": "dateMin:asc",
    }
    params_snapshot = copy.deepcopy(params)

    result = client.search(params)

    assert params == params_snapshot, "search must not mutate caller-supplied params"
    assert result["found"] == 0
    assert session.last_call["params"] is None
    assert "filter_by" in session.last_call["url"], "filter_by should be in request URL"


def test_response_cache_lru_eviction() -> None:
    cache = server.ResponseCache(max_size=2, cleanup_interval=0)

    cache.set("url1", {"a": 1}, {"value": 1}, 60)
    cache.set("url2", {"b": 2}, {"value": 2}, 60)

    # Access url1 to mark it as recently used, then insert a third item
    assert cache.get("url1", {"a": 1})["value"] == 1

    cache.set("url3", {"c": 3}, {"value": 3}, 60)

    # url2 should have been evicted (least recently used)
    assert cache.get("url2", {"b": 2}) is None
    assert cache.get("url1", {"a": 1})["value"] == 1
    assert cache.get("url3", {"c": 3})["value"] == 3
