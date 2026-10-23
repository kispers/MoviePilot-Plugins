"""BTSearch 已签名搜索接口客户端。"""

from __future__ import annotations

import hashlib
import html
import re
import secrets
import threading
import time
from typing import Any, Dict, List, Optional

from ..magnet import build_magnet_url
from ...utils.cache import create_platform_ttl_cache
from ...utils.http_client import (
    RequestGate, gated_request, normalize_proxies, normalize_proxy_address, requests,
)


class BTSearchError(RuntimeError):
    """BTSearch 请求或解析失败。"""


class BTSearchClient:
    """调用 BTSearch 的公开搜索接口。"""

    DEFAULT_BASE_URL = "https://www.btsearch.love"
    _SIGN_KEY = "long2ice"
    _HEADERS = {
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "MoviePilot-CloudSubscribe-BTSearch/1.0",
    }

    def __init__(self, base_url: str = DEFAULT_BASE_URL, proxy: Optional[str] = None,
                 timeout: int = 30, request_interval: float = 3.0) -> None:
        self.base_url = str(base_url or self.DEFAULT_BASE_URL).strip().rstrip("/") or self.DEFAULT_BASE_URL
        self._proxy = normalize_proxy_address(proxy)
        self.timeout = max(5, min(int(timeout or 30), 120))
        self.request_interval = max(2.0, float(request_interval or 3.0))
        self._gate = RequestGate.shared(
            "BTSearch", f"{self.base_url}|{self._proxy}", request_interval=self.request_interval,
            minimum_interval=2.0, serial_requests=True,
        )
        self._cache = create_platform_ttl_cache("btsearch_search", ttl=1800, maxsize=500)
        self._cache_lock = threading.Lock()

    @staticmethod
    def _signature(params: Dict[str, Any], timestamp: str, nonce: str) -> str:
        entries = [f"timestamp={timestamp}", f"nonce={nonce}"]
        entries.extend(f"{key}={value}" for key, value in params.items())
        material = "&".join(sorted(entries)) + f"&key={BTSearchClient._SIGN_KEY}"
        return hashlib.md5(material.encode("utf-8")).hexdigest().upper()

    def search(self, query: str, cat: int = 0) -> List[Dict[str, Any]]:
        del cat
        keyword = str(query or "").strip()
        if not keyword:
            return []
        with self._cache_lock:
            cached = self._cache.get(keyword.casefold())
            if cached is not None:
                return [dict(item) for item in cached]

        params: Dict[str, Any] = {
            "keyword": keyword, "limit": 20, "offset": 0, "mode": "", "time": "",
            "sort": "", "sort_type": "asc", "size": "",
        }
        timestamp = str(int(time.time()))
        nonce = secrets.token_urlsafe(8)[:8]
        headers = dict(self._HEADERS)
        headers.update({"x-timestamp": timestamp, "x-nonce": nonce,
                        "x-sign": self._signature(params, timestamp, nonce)})

        def _requester() -> Any:
            return requests.get(f"{self.base_url}/api/search", params=params, headers=headers,
                                proxies=normalize_proxies(self._proxy), timeout=self.timeout)

        try:
            response = gated_request(self._gate, _requester, max_retries=1, initial_delay=2.0)
            if response.status_code != 200:
                raise BTSearchError(f"HTTP {response.status_code}")
            payload = response.json()
        except Exception as error:
            raise BTSearchError(f"BTSearch 请求失败: {error}") from error

        results = []
        for item in payload.get("data", []) if isinstance(payload, dict) else []:
            if not isinstance(item, dict):
                continue
            info_hash = str(item.get("hash") or "").strip().lower()
            if not re.fullmatch(r"[0-9a-f]{40}", info_hash):
                continue
            title = html.unescape(re.sub(r"<[^>]+>", "", str(item.get("name") or "")).strip())
            if not title:
                continue
            try:
                size = int(item.get("size") or 0)
            except (TypeError, ValueError):
                size = 0
            try:
                seeders = int(item.get("count") or 0)
            except (TypeError, ValueError):
                seeders = 0
            results.append({
                "url": build_magnet_url(info_hash, title), "title": title, "size": size,
                "seeders": seeders, "leechers": 0, "info_hash": info_hash.upper(),
                "resource_type": "magnet", "source": "btsearch", "source_url": "",
                "added": str(item.get("created_at") or ""),
            })
        with self._cache_lock:
            self._cache[keyword.casefold()] = results
        return [dict(item) for item in results]

    def clear_cache(self) -> int:
        with self._cache_lock:
            count = len(self._cache)
            self._cache.clear()
            return count
