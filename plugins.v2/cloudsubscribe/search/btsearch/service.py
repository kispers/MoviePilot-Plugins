"""BTSearch 的资源过滤服务。"""

from ..piratebay.service import PirateBaySearchService


class BTSearchSearchService(PirateBaySearchService):
    """复用磁力搜索的标题、季号和年份匹配逻辑。"""

    pass
