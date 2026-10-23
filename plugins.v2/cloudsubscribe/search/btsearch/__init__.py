"""BTSearch 磁力搜索渠道。"""

from .client import BTSearchClient, BTSearchError
from .provider import create_btsearch_provider
from .service import BTSearchSearchService

__all__ = [
    "BTSearchClient",
    "BTSearchError",
    "BTSearchSearchService",
    "create_btsearch_provider",
]
