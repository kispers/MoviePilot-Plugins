"""BTSearch 自描述规范与配置表单。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .client import BTSearchClient
from .provider import create_btsearch_provider
from .service import BTSearchSearchService
from ...core.definitions import FieldSpec, GroupSpec, SearchSourceDefinition


class BTSearchSourceDefinition(SearchSourceDefinition):
    id = "btsearch"
    name = "BTSearch"
    icon = "mdi-magnet"
    color = "indigo"
    order = 95

    @classmethod
    def create_client(cls, config: Dict[str, Any], context: Optional[Any] = None) -> Any:
        return BTSearchClient(
            base_url=str(cls.config_value(config, "btsearch_base_url", BTSearchClient.DEFAULT_BASE_URL)
                         or BTSearchClient.DEFAULT_BASE_URL),
            proxy=(context or {}).get("proxy"),
            timeout=int(cls.config_value(config, "btsearch_timeout", 30) or 30),
            request_interval=float(cls.config_value(config, "btsearch_request_interval", 3.0) or 3.0),
        )

    @classmethod
    def get_config_groups(cls, context: Optional[Dict[str, Any]] = None) -> List[GroupSpec]:
        return [
            GroupSpec(tab="btsearch", title="BTSearch 磁力搜索", icon="mdi-magnet", fields=[
                FieldSpec(key="btsearch_base_url", label="服务地址", default=BTSearchClient.DEFAULT_BASE_URL,
                          placeholder=BTSearchClient.DEFAULT_BASE_URL, cols=12),
                FieldSpec(key="test_btsearch", label="测试搜索", type="test-source", source="btsearch", cols=12),
            ]),
            GroupSpec(tab="btsearch", title="搜索与限速", icon="mdi-shield-search", fields=[
                FieldSpec(key="btsearch_result_limit", label="候选上限", type="number", default=20,
                          min=1, max=80, cols=4),
                FieldSpec(key="btsearch_request_interval", label="请求间隔", type="number", default=3.0,
                          min=2.0, max=30, step=0.5, suffix="秒", cols=4),
                FieldSpec(key="btsearch_timeout", label="搜索超时", type="number", default=30,
                          min=5, max=120, suffix="秒", cols=4),
            ]),
        ]

    @classmethod
    def create_provider(cls, service: Any, client: Any, config: Dict[str, Any],
                        context: Optional[Any] = None) -> Any:
        if not client:
            return None
        limit = int(cls.config_value(config, "btsearch_result_limit", 20) or 20)
        return create_btsearch_provider(BTSearchSearchService(client, limit), {"result_limit": limit})
