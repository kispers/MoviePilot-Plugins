"""小雅免 Docker 本地索引与网盘分享搜索渠道单元测试。"""

import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from plugin_env import OwnerDelegator, ensure_package, install_app_mocks, load_module, set_media_type

# 注入 app 运行期 mock
install_app_mocks(
    "app.core", "app.core.config", "app.core.context", "app.core.metainfo", "app.core.cache",
    "app.db", "app.log", "app.utils",
)
MediaType = set_media_type(movie="movie", tv="tv")

# 加载 cloudsubscribe 基础包
ensure_package("cloudsubscribe")
cloudsubscribe_core = ensure_package("cloudsubscribe.core")
cloudsubscribe_core.OwnerDelegator = OwnerDelegator

# 加载 core/definitions.py
definitions_mod = load_module(
    "cloudsubscribe.core.definitions",
    "plugins.v2/cloudsubscribe/core/definitions.py",
)
cloudsubscribe_core.SearchSourceDefinition = definitions_mod.SearchSourceDefinition
cloudsubscribe_core.FieldSpec = definitions_mod.FieldSpec
cloudsubscribe_core.GroupSpec = definitions_mod.GroupSpec

# 加载 core/search.py
search_core_mod = load_module(
    "cloudsubscribe.core.search",
    "plugins.v2/cloudsubscribe/core/search.py",
)
cloudsubscribe_core.SearchQuery = search_core_mod.SearchQuery
cloudsubscribe_core.SearchCapability = search_core_mod.SearchCapability
cloudsubscribe_core.SearchPolicy = search_core_mod.SearchPolicy
cloudsubscribe_core.SearchProvider = search_core_mod.SearchProvider

# 桩化 utils.cache 避免跨测试污染
cache_pkg = ensure_package("cloudsubscribe.utils.cache")
cache_pkg.create_platform_ttl_cache = lambda *args, **kwargs: {}
cache_pkg.normalize_platform_cache_key = lambda key: str(key)

# 加载 utils 模块
load_module(
    "cloudsubscribe.utils.file_parser",
    "plugins.v2/cloudsubscribe/utils/file_parser.py",
)
load_module(
    "cloudsubscribe.utils.magnet",
    "plugins.v2/cloudsubscribe/utils/magnet.py",
)
load_module(
    "cloudsubscribe.utils.http_client",
    "plugins.v2/cloudsubscribe/utils/http_client.py",
)

# 加载 search/matching.py 与 search/magnet.py
matching_mod = load_module(
    "cloudsubscribe.search.matching",
    "plugins.v2/cloudsubscribe/search/matching.py",
)
magnet_mod = load_module(
    "cloudsubscribe.search.magnet",
    "plugins.v2/cloudsubscribe/search/magnet.py",
)

# 加载 search/scanner.py
scanner_mod = load_module(
    "cloudsubscribe.search.scanner",
    "plugins.v2/cloudsubscribe/search/scanner.py",
)
SearchSourceRegistry = scanner_mod.SearchSourceRegistry

# 加载 search/types.py（xiaoya 依赖其中的公共网盘定义与直链工具）
load_module(
    "cloudsubscribe.search.types",
    "plugins.v2/cloudsubscribe/search/types.py",
)

# 加载 search/xiaoya 模块
client_mod = load_module(
    "cloudsubscribe.search.xiaoya.client",
    "plugins.v2/cloudsubscribe/search/xiaoya/client.py",
)
resource_mod = load_module(
    "cloudsubscribe.search.xiaoya.resource",
    "plugins.v2/cloudsubscribe/search/xiaoya/resource.py",
)
preview_mod = load_module(
    "cloudsubscribe.search.xiaoya.preview",
    "plugins.v2/cloudsubscribe/search/xiaoya/preview.py",
)
provider_mod = load_module(
    "cloudsubscribe.search.xiaoya.provider",
    "plugins.v2/cloudsubscribe/search/xiaoya/provider.py",
)
service_mod = load_module(
    "cloudsubscribe.search.xiaoya.service",
    "plugins.v2/cloudsubscribe/search/xiaoya/service.py",
)
definition_mod = load_module(
    "cloudsubscribe.search.xiaoya.definition",
    "plugins.v2/cloudsubscribe/search/xiaoya/definition.py",
)

XiaoyaClient = client_mod.XiaoyaClient
XiaoyaPreviewResolver = preview_mod.XiaoyaPreviewResolver
XiaoyaResourceService = resource_mod.XiaoyaResourceService
XiaoyaSearchService = service_mod.XiaoyaSearchService
XiaoyaSourceDefinition = definition_mod.XiaoyaSourceDefinition
clean_xiaoya_path = resource_mod.clean_xiaoya_path
SearchQuery = search_core_mod.SearchQuery


class TestXiaoyaSearch(unittest.TestCase):
    """测试小雅免 Docker 本地索引、数据清洗、动态分类过滤与网盘反解。"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        self.client = XiaoyaClient(timeout=5)
        self.resources = XiaoyaResourceService(
            client=self.client,
            data_dir=self.data_dir,
            auto_sync_days=7,
        )
        self.client.bind_resources(self.resources)
        # 插入清洗入库测试数据
        with self.resources._get_connection() as conn:
            conn.execute("""
                INSERT INTO xiaoya_shares (prefix, drive_type, share_code, folder_id, password)
                VALUES 
                    ('电影/合集/经典电影', 'quark', 'quark_code_123', 'folder_1', ''),
                    ('电视剧/国产剧/繁花', '115', '115_code_456', 'folder_2', '8888'),
                    ('4KRemux', 'quark', 'quark_4k_789', '', ''),
                    ('动漫/经典动画', 'pikpak', 'pik_code_999', '', '');
            """)
            conn.execute("""
                INSERT INTO xiaoya_resources (path, root_folder, title, clean_title, douban_id, category, updated_at)
                VALUES
                    ('电影/合集/经典电影/肖申克的救赎.mp4', '电影', '肖申克的救赎', '肖申克的救赎', '1292052', 'movie', 1700000000),
                    ('电影/合集/经典电影/肖申克的救赎-预告片.mp4', '电影', '肖申克的救赎-预告片', '肖申克的救赎预告片', '1292052', 'movie', 1700000000),
                    ('电视剧/国产剧/繁花/繁花.S01E01.mp4', '电视剧', '繁花', '繁花', '30228394', 'tv', 1700000010),
                    ('4KRemux/奥本海默 (2023)/奥本海默.4k.mkv', '4KRemux', '奥本海默', '奥本海默', '35789123', 'movie', 1700000020),
                    ('动漫/经典动画/灌篮高手.mkv', '动漫', '灌篮高手', '灌篮高手', '1234567', 'tv', 1700000030);
            """)
            conn.execute(
                "INSERT OR REPLACE INTO xiaoya_meta (key, value) VALUES ('last_sync', ?);",
                (str(int(time.time())),),
            )
            conn.commit()

        self.resources._load_share_cache()

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_clean_xiaoya_path_normalization(self):
        """测试入库路径清洗：彻底剥离虚拟网盘容器层并提取一级分类。"""
        # 1. 夸克带 Emoji 前缀清洗
        raw1 = "./🌀我的夸克分享/动漫/动漫电影合集/功夫熊猫.mp4"
        clean1, root1 = clean_xiaoya_path(raw1)
        self.assertEqual(clean1, "动漫/动漫电影合集/功夫熊猫.mp4")
        self.assertEqual(root1, "动漫")

        # 2. 115 容器前缀清洗
        raw2 = "./🏷️ 我的115分享/4KRemux/奥本海默.mkv"
        clean2, root2 = clean_xiaoya_path(raw2)
        self.assertEqual(clean2, "4KRemux/奥本海默.mkv")
        self.assertEqual(root2, "4KRemux")

        # 3. 正常相对路径清洗
        raw3 = "./每日更新/电视剧/国产剧/繁花.mp4"
        clean3, root3 = clean_xiaoya_path(raw3)
        self.assertEqual(clean3, "每日更新/电视剧/国产剧/繁花.mp4")
        self.assertEqual(root3, "每日更新")

        # 4. 未在任何硬编码名单中的未知网盘容器也应被通用剥离（证明无网盘名硬编码）
        raw4 = "./☁️我的天翼19分享/纪录片/世界历史/罗马.mp4"
        clean4, root4 = clean_xiaoya_path(raw4)
        self.assertEqual(clean4, "纪录片/世界历史/罗马.mp4")
        self.assertEqual(root4, "纪录片")

        # 5. 无斜杠的根级路径保持原样
        clean5, root5 = clean_xiaoya_path("4KRemux")
        self.assertEqual((clean5, root5), ("4KRemux", "4KRemux"))

    def test_xiaoya_resolve_share(self):
        """测试小雅最长前缀匹配反解真实网盘分享链接。"""
        res1 = self.resources.resolve_share("电影/合集/经典电影/肖申克的救赎.mp4")
        self.assertIsNotNone(res1)
        self.assertEqual(res1["drive_type"], "quark")
        self.assertEqual(res1["share_url"], "https://pan.quark.cn/s/quark_code_123")

        # 即使传入带容器前缀的脏路径，也应被通用清洗后成功反解
        res_dirty = self.resources.resolve_share("./🏷️ 我的115分享/电视剧/国产剧/繁花/繁花.S01E01.mp4")
        self.assertIsNotNone(res_dirty)
        self.assertEqual(res_dirty["drive_type"], "115")
        self.assertEqual(res_dirty["password"], "8888")
        self.assertEqual(res_dirty["share_url"], "https://115.com/s/115_code_456?password=8888")

    def test_xiaoya_search_returns_candidates(self):
        """检索命中索引并输出带预览能力的标准候选。"""
        mediainfo = MagicMock()
        mediainfo.title = "肖申克"
        mediainfo.original_title = ""

        service = XiaoyaSearchService(
            resources=self.resources,
            resource_types=("quark", "115"),
            result_limit=10,
        )
        query = SearchQuery(mediainfo=mediainfo, media_type=MediaType.MOVIE, keyword="肖申克")
        candidates = service.search(query)

        self.assertGreaterEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["title"], "肖申克的救赎")
        self.assertEqual(candidates[0]["resource_type"], "quark")
        self.assertTrue(candidates[0].get("supports_file_preview"))
        self.assertTrue(candidates[0].get("can_preview"))

    def test_xiaoya_search_never_fetches_remote(self):
        """搜索必须纯本地读取，不得触发任何远程索引拉取。"""
        mediainfo = MagicMock()
        mediainfo.title = "肖申克"
        mediainfo.original_title = ""
        mediainfo.douban_id = "1292052"

        calls = []
        self.client.fetch_data_file = lambda *a, **kw: calls.append(a) or (None, None, None)

        service = XiaoyaSearchService(
            resources=self.resources,
            resource_types=("quark", "115"),
            result_limit=10,
        )
        query = SearchQuery(mediainfo=mediainfo, media_type=MediaType.MOVIE, keyword="肖申克")
        candidates = service.search(query)

        self.assertEqual(calls, [])                       # 搜索路径上没有网络拉取
        self.assertGreaterEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["title"], "肖申克的救赎")

    def test_xiaoya_definition_schema(self):
        """表单两段式：连接配置（信息卡片含清空重建 + 服务地址 + 测试）与搜索与限速。"""
        SearchSourceRegistry.register(XiaoyaSourceDefinition)
        groups = XiaoyaSourceDefinition.get_config_groups()
        self.assertEqual([g.title for g in groups], ["连接配置", "搜索与限速"])

        conn_fields = {f.key: f for f in groups[0].fields}
        self.assertEqual(
            list(conn_fields),
            ["xiaoya_account_info", "xiaoya_sync_url", "test_xiaoya"],
        )
        # 清空重建按钮挂在信息卡片上；地址字段内嵌测试按钮
        self.assertTrue(conn_fields["xiaoya_account_info"].extra.get("rebuild"))
        self.assertEqual(conn_fields["xiaoya_sync_url"].label, "服务地址")
        self.assertEqual(conn_fields["xiaoya_sync_url"].test_source, "xiaoya")

        limit_fields = {f.key: f for f in groups[1].fields}
        self.assertEqual(
            list(limit_fields),
            ["xiaoya_result_limit", "xiaoya_auto_sync_days", "xiaoya_timeout"],
        )
        for field in limit_fields.values():
            self.assertEqual(field.cols, 4)   # 同排显示

        # 已移除的配置项不再出现
        for removed in ("xiaoya_include_folders", "xiaoya_drive_types", "xiaoya_filter_exclude", "xiaoya_enabled"):
            self.assertNotIn(removed, conn_fields)
            self.assertNotIn(removed, limit_fields)

    def test_refresh_account_card_syncs_index_and_contract(self):
        """测试刷新小雅信息卡片处理索引数据库同步与状态汇报。"""
        provider = XiaoyaSourceDefinition.create_provider(
            service=XiaoyaSearchService(resources=self.resources, resource_types=("quark", "115")),
            client=self.client,
            config={},
            context={"resource_types": ("quark", "115")},
        )
        self.assertIsNotNone(provider)
        account_service = provider.services.get(cloudsubscribe_core.SearchCapability.ACCOUNT)
        self.assertIsNotNone(account_service)

        # 1. 验证常规卡片读取（不触发网络更新）
        info = account_service.get_account_info(force=False, refresh=False)
        self.assertTrue(info["connected"])
        self.assertEqual(info["points_label"], "已收录影视")
        self.assertIn("details", info)
        labels = {d["label"] for d in info["details"]}
        self.assertEqual(labels, {"数据库", "最近更新"})

        # 2. 模拟前端点击卡片刷新（force=True）：验证真实触发数据库同步入库
        mock_fetch = MagicMock()
        # 模拟返回空数据避免真实网络请求
        mock_fetch.return_value = (None, None, None)
        self.client.fetch_data_file = mock_fetch

        # 直接调用同步入口，任何内部异常都必须暴露（不允许被静默吞掉）
        sync_result = self.resources.sync_index(force=True)
        self.assertEqual(sync_result.get("status"), "success")
        self.assertTrue(mock_fetch.called)

        refreshed_info = account_service.get_account_info(force=True, refresh=True)
        self.assertTrue(refreshed_info["connected"])
        self.assertTrue(mock_fetch.called)  # 证实真正触发了拉取与写库流程！

    def test_sync_parses_share_lists_and_index_zip(self):
        """真实解析校验：分享列表 txt 与 index.zip 内容按预期合并入库。"""
        import io as _io
        import zipfile as _zip

        share_quark = "电影/测试区   quarkcode1   folderid1\n"
        share_115 = "电视剧/测试区   swabc123   2628478209787264315   8888\n"
        index_movie = (
            "./🏷️我的115分享/电视剧/测试区/我的剧集#我的剧集#30228394#8.7#https://img/x.jpg\n"
            "./🏷️我的115分享/电视剧/测试区/我的剧集#我的剧集#30228394#8.7#https://img/x.jpg\n"  # 重复行应被去重
        )
        index_tv = "./🌀我的夸克分享/电影/测试区/某电影 2024#某电影#1234567#9.1#https://img/y.jpg\n"
        buf = _io.BytesIO()
        with _zip.ZipFile(buf, "w") as zf:
            zf.writestr("index.movie.western.txt", index_movie)
            zf.writestr("index.tv.china.txt", index_tv)
        zip_bytes = buf.getvalue()

        def fake_fetch(filename, etag=None, last_modified=None):
            return {
                "quarkshare_list.txt": share_quark.encode(),
                "115share_list.txt": share_115.encode(),
                "pikpakshare_list.txt": None,
                "index.zip": zip_bytes,
            }[filename], None, None

        self.client.fetch_data_file = fake_fetch
        result = self.resources.sync_index(force=True)
        self.assertEqual(result["status"], "success")

        with self.resources._get_connection() as conn:
            shares = conn.execute(
                "SELECT prefix, drive_type, share_code, password FROM xiaoya_shares ORDER BY drive_type"
            ).fetchall()
            rows = conn.execute(
                "SELECT path, root_folder, title, douban_id, category FROM xiaoya_resources ORDER BY path"
            ).fetchall()

        # 分享映射按 drive_type 增量替换：115 带提取码、夸克无提取码
        by_drive = {s["drive_type"]: s for s in shares}
        self.assertEqual(by_drive["115"]["password"], "8888")
        self.assertEqual(by_drive["115"]["share_code"], "swabc123")
        self.assertEqual(by_drive["quark"]["password"], "")
        self.assertEqual(by_drive["quark"]["prefix"], "电影/测试区")
        # 未变更（304/未返回）的 pikpak 保留库内既有映射，不被清空
        self.assertIn("pikpak", by_drive)

        # 资源：容器前缀已剥离、重复行去重、category 由文件名推导
        by_path = {r["path"]: r for r in rows}
        self.assertIn("电视剧/测试区/我的剧集", by_path)      # 重复行已去重为 1 条
        self.assertIn("电影/测试区/某电影 2024", by_path)
        tv = by_path["电视剧/测试区/我的剧集"]
        self.assertEqual(tv["root_folder"], "电视剧")
        self.assertEqual(tv["douban_id"], "30228394")
        self.assertEqual(tv["category"], "movie")
        mv = by_path["电影/测试区/某电影 2024"]
        self.assertEqual(mv["root_folder"], "电影")
        self.assertEqual(mv["category"], "tv")
        self.assertNotIn("分享", tv["path"].split("/")[0])   # 容器层已剥离

        # 落库后应能反解出真实分享直链
        resolved = self.resources.resolve_share("电视剧/测试区/我的剧集")
        self.assertEqual(resolved["drive_type"], "115")
        self.assertEqual(resolved["share_url"], "https://115.com/s/swabc123?password=8888")

    def test_rebuild_index_clears_and_rebuilds(self):
        """清空重建：旧数据被清除，随后按最新远程数据重建。"""
        import io as _io
        import zipfile as _zip

        # 第一次重建：写入一条记录
        buf1 = _io.BytesIO()
        with _zip.ZipFile(buf1, "w") as zf:
            zf.writestr("index.movie.txt", "./🏷️我的115分享/电影/测试区/旧片#旧片#111#8.0#http://p/1.jpg\n")
        first_zip = buf1.getvalue()

        self.client.fetch_data_file = lambda filename, etag=None, last_modified=None: (
            ("电影/测试区  codeA  fidA\n".encode() if filename == "115share_list.txt" else None),
            None,
            None,
        ) if filename != "index.zip" else (first_zip, None, None)
        self.resources.rebuild_index()

        with self.resources._get_connection() as conn:
            paths_after_first = [r["path"] for r in conn.execute("SELECT path FROM xiaoya_resources").fetchall()]
        # setUp 预置的 5 条记录已被清空，只剩本次重建写入的 1 条
        self.assertEqual(paths_after_first, ["电影/测试区/旧片"])

        # 第二次重建：镜像源换成全新内容，旧记录必须消失
        buf2 = _io.BytesIO()
        with _zip.ZipFile(buf2, "w") as zf:
            zf.writestr("index.movie.txt", "./🏷️我的115分享/电影/测试区/新片#新片#222#9.0#http://p/2.jpg\n")
        second_zip = buf2.getvalue()
        self.client.fetch_data_file = lambda filename, etag=None, last_modified=None: (
            ("电影/测试区  codeA  fidA\n".encode() if filename == "115share_list.txt" else None),
            None,
            None,
        ) if filename != "index.zip" else (second_zip, None, None)
        self.resources.rebuild_index()

        with self.resources._get_connection() as conn:
            paths = [r["path"] for r in conn.execute("SELECT path FROM xiaoya_resources").fetchall()]
        self.assertIn("电影/测试区/新片", paths)
        self.assertNotIn("电影/测试区/旧片", paths)  # 旧库已被清空

    def test_search_by_douban_id_and_category(self):
        """测试通过豆瓣ID精准直达检索及媒体类型过滤。"""
        service = XiaoyaSearchService(
            resources=self.resources,
            resource_types=("quark", "115"),
            result_limit=10,
        )

        # 1. 通过豆瓣ID精确直达检索繁花 (30228394)
        mediainfo = MagicMock()
        mediainfo.title = "其他无关名字"
        mediainfo.original_title = ""
        mediainfo.douban_id = "30228394"

        query = SearchQuery(mediainfo=mediainfo, media_type=MediaType.TV)
        candidates = service.search(query)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["title"], "繁花")
        self.assertEqual(candidates[0]["resource_type"], "115")

        # 2. 媒体类型过滤：电视剧过滤下，不应返回电影
        mediainfo_movie = MagicMock()
        mediainfo_movie.title = "肖申克的救赎"
        mediainfo_movie.original_title = ""
        mediainfo_movie.douban_id = "1292052"

        query_tv_filter = SearchQuery(mediainfo=mediainfo_movie, media_type=MediaType.TV, keyword="肖申克")
        candidates_tv = service.search(query_tv_filter)
        # 肖申克是 movie，在 TV 检索模式下被类型过滤拦截
        self.assertEqual(len(candidates_tv), 0)


class _FakeDriveService:
    """按 parent_id 返回预设目录树的网盘分享服务桩。"""

    def __init__(self, tree, search_hits=None):
        self._tree = tree
        self._search_hits = list(search_hits or [])
        self.listed = []

    def list_share_directory(self, url, parent_id=""):
        self.listed.append(str(parent_id))
        return list(self._tree.get(str(parent_id), []))

    def search_share_files(self, url, keyword):
        return list(self._search_hits)


class _FakeDriveRegistry:
    """只提供分享读取服务的网盘注册表桩。"""

    def __init__(self, service, label="115网盘"):
        self._service = service
        self._label = label

    def require_share_transfer(self, key):
        return self._label, self._service


class TestXiaoyaPreviewNavigation(unittest.TestCase):
    """测试小雅预览下发的目录链，前端据此提供「上一级」回退。"""

    def _resolver(self, service):
        return XiaoyaPreviewResolver(
            resources=MagicMock(),
            drive_registry=_FakeDriveRegistry(service),
        )

    def test_descent_reports_breadcrumb_chain(self):
        """按索引路径下钻时，目录链需覆盖分享根目录到目标目录，并回传所在目录标识。"""
        service = _FakeDriveService({
            "": [{"id": "f1", "name": "动漫", "is_dir": True}],
            "f1": [{"id": "f2", "name": "九门", "is_dir": True}],
            "f2": [
                {"id": "x1", "name": "九门.S01E01.mkv", "size": 1024, "is_dir": False},
                {"id": "x2", "name": "九门.S01E02.mkv", "size": 2048, "is_dir": False},
            ],
        })
        result = self._resolver(service).preview_files({
            "url": "https://115.com/s/abc",
            "provider_data": {
                "drive_type": "115", "sub_path": "动漫/九门",
                "target_name": "九门", "title": "九门",
            },
        })

        self.assertTrue(result["success"])
        data = result["data"]
        self.assertEqual([item["name"] for item in data["items"]],
                         ["九门.S01E01.mkv", "九门.S01E02.mkv"])
        # 目录链每层都带真实目录标识，最后一项即当前所在目录
        self.assertEqual(data["breadcrumbs"], [
            {"id": "", "name": "分享根目录"},
            {"id": "f1", "name": "动漫"},
            {"id": "f2", "name": "九门"},
        ])
        self.assertEqual(data["parent_id"], "f2")

    def test_search_hit_directory_reports_breadcrumbs(self):
        """分享内搜索命中目录并展开其内容时，目录链需可上溯到分享根目录。"""
        service = _FakeDriveService(
            {"d9": [{"id": "y1", "name": "九门.S01E01.mkv", "size": 1024, "is_dir": False}]},
            search_hits=[{"id": "d9", "name": "九门 (2026)", "is_dir": True}],
        )
        result = self._resolver(service).preview_files({
            "url": "https://115.com/s/abc",
            "provider_data": {
                "drive_type": "115", "sub_path": "动漫/九门/九门 (2026)",
                "target_name": "九门", "title": "九门",
            },
        })

        self.assertTrue(result["success"])
        data = result["data"]
        self.assertEqual([item["name"] for item in data["items"]], ["九门.S01E01.mkv"])
        self.assertEqual(data["breadcrumbs"], [
            {"id": "", "name": "分享根目录"},
            {"id": "d9", "name": "九门 (2026)"},
        ])
        self.assertEqual(data["parent_id"], "d9")

    def test_file_hits_report_parent_directory(self):
        """搜索直接命中文件时，用文件父目录标识补出可回退的“上一级”层级。"""
        hits = [
            {"id": "y1", "parent_id": "d9", "name": "九门.S01E01.mkv", "size": 1024, "is_dir": False},
            {"id": "y2", "parent_id": "d9", "name": "九门.S01E02.mkv", "size": 2048, "is_dir": False},
        ]
        service = _FakeDriveService({}, search_hits=hits)
        result = self._resolver(service).preview_files({
            "url": "https://115.com/s/abc",
            "provider_data": {
                "drive_type": "115", "sub_path": "动漫/九门",
                "target_name": "九门", "title": "九门",
            },
        })

        self.assertTrue(result["success"])
        data = result["data"]
        self.assertEqual([item["name"] for item in data["items"]],
                         ["九门.S01E01.mkv", "九门.S01E02.mkv"])
        self.assertEqual(data["breadcrumbs"], [
            {"id": "", "name": "分享根目录"},
            {"id": "d9", "name": "九门"},
        ])
        self.assertEqual(data["parent_id"], "d9")

    def test_conflicting_parents_do_not_fake_a_level(self):
        """命中项父目录不一致时不得伪造回退层级，避免上一级跳到错误目录。"""
        service = _FakeDriveService({}, search_hits=[
            {"id": "y1", "parent_id": "d9", "name": "九门.S01E01.mkv", "is_dir": False},
            {"id": "y2", "parent_id": "d10", "name": "九门.S01E02.mkv", "is_dir": False},
        ])
        result = self._resolver(service).preview_files({
            "url": "https://115.com/s/abc",
            "provider_data": {
                "drive_type": "115", "sub_path": "动漫/九门",
                "target_name": "九门", "title": "九门",
            },
        })

        data = result["data"]
        self.assertEqual(data["breadcrumbs"], [])
        self.assertEqual(data["parent_id"], "")


if __name__ == "__main__":
    unittest.main()
