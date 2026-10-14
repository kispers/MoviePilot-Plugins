import importlib.util
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

from plugin_env import OwnerDelegator, register_mock

# 构造 mock 的基础依赖
register_mock("app")
register_mock("app.log", logger=MagicMock())
register_mock("app.core")
register_mock("app.core.config", settings=MagicMock(TZ="Asia/Shanghai"))

# 构造 mock 的 cloudsubscribe 包结构
register_mock("cloudsubscribe")
register_mock("cloudsubscribe.core", OwnerDelegator=OwnerDelegator)
register_mock("cloudsubscribe.core.checkin_manager")
register_mock("cloudsubscribe.core.definitions")
register_mock("cloudsubscribe.core.search")
register_mock("cloudsubscribe.core.services")
register_mock("cloudsubscribe.search")
register_mock("cloudsubscribe.search.hdhaven")
register_mock("cloudsubscribe.search.hdhaven.security")
register_mock("cloudsubscribe.search.cloudflare")
register_mock("cloudsubscribe.search.http_client")
register_mock("cloudsubscribe.utils")
register_mock("cloudsubscribe.utils.cache")
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
plugins_v2_path = os.path.join(project_root, "plugins.v2")

# 加载 hdhaven client
hdhaven_client_path = os.path.join(plugins_v2_path, "cloudsubscribe/search/hdhaven/client.py")
spec_h = importlib.util.spec_from_file_location("cloudsubscribe.search.hdhaven.client", hdhaven_client_path)
mod_h = importlib.util.module_from_spec(spec_h)
mod_h.__package__ = "cloudsubscribe.search.hdhaven"
sys.modules["cloudsubscribe.search.hdhaven.client"] = mod_h
spec_h.loader.exec_module(mod_h)
HDHavenClient = mod_h.HDHavenClient
HDHavenError = mod_h.HDHavenError

# 加载 checkin service
checkin_service_path = os.path.join(plugins_v2_path, "cloudsubscribe/core/services/checkin.py")
spec_c = importlib.util.spec_from_file_location("cloudsubscribe.core.services.checkin", checkin_service_path)
mod_c = importlib.util.module_from_spec(spec_c)
mod_c.__package__ = "cloudsubscribe.core.services"
sys.modules["cloudsubscribe.core.services.checkin"] = mod_c
mod_c.settings = MagicMock()
mod_c.settings.TZ = "Asia/Shanghai"
spec_c.loader.exec_module(mod_c)
CheckinService = mod_c.CheckinService

# 加载聚影 client（依赖已被 mock 的 cloudsubscribe.search.http_client）
juying_client_path = os.path.join(plugins_v2_path, "cloudsubscribe/search/juying/client.py")
spec_j = importlib.util.spec_from_file_location("cloudsubscribe.search.juying.client", juying_client_path)
mod_j = importlib.util.module_from_spec(spec_j)
mod_j.__package__ = "cloudsubscribe.search.juying"
sys.modules["cloudsubscribe.search.juying"] = register_mock("cloudsubscribe.search.juying")
sys.modules["cloudsubscribe.search.juying.client"] = mod_j
spec_j.loader.exec_module(mod_j)
JuyingClient = mod_j.JuyingClient
JuyingError = mod_j.JuyingError

# 加载核心规范模块（无宿主依赖），校验模式文案契约
definitions_path = os.path.join(plugins_v2_path, "cloudsubscribe/core/definitions.py")
spec_d = importlib.util.spec_from_file_location("cloudsubscribe_definitions_under_test", definitions_path)
mod_d = importlib.util.module_from_spec(spec_d)
sys.modules["cloudsubscribe_definitions_under_test"] = mod_d
spec_d.loader.exec_module(mod_d)


class TestHDHavenClientCheckin(unittest.TestCase):
    """测试 HDHaven 客户端签到天数返回值是否彻底去除硬编码 1。"""

    def setUp(self):
        self.client = HDHavenClient(
            username="testuser",
            password="testpassword",
            base_url="https://hdhaven.org",
        )

    def test_hdhaven_checkin_success_no_hardcoded_days(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "success": True,
            "data": {
                "earned": 10,
                "points": 100,
                "outcome": "抽中大奖",
            },
        }

        with patch.object(self.client, "request", return_value=mock_resp):
            res = self.client.checkin(mode="normal")
            self.assertTrue(res["success"])
            self.assertEqual(res["signin_points"], 10)
            self.assertIsNone(res["signin_days"], "HDHaven 签到成功未下发天数时 signin_days 应为 None 而非写死 1")

    def test_hdhaven_checkin_409_already_checked_in(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 409

        with patch.object(self.client, "request", return_value=mock_resp):
            res = self.client.checkin(mode="normal")
            self.assertTrue(res["success"])
            self.assertTrue(res["already_checked_in"])
            self.assertIsNone(res["signin_days"], "HDHaven 409 已签到时 signin_days 应为 None")

    def test_hdhaven_checkin_error_with_already_message(self):
        with patch.object(
                self.client,
                "request",
                side_effect=HDHavenError("今日已签到", status_code=400),
        ):
            res = self.client.checkin(mode="normal")
            self.assertTrue(res["success"])
            self.assertTrue(res["already_checked_in"])
            self.assertIsNone(res["signin_days"], "HDHaven 异常包含今日已签到时 signin_days 应为 None")


class _FakeJuyingTransport:
    """按 (方法, 路径) 返回预设响应并记录调用的聚影传输桩。"""

    def __init__(self, responses):
        self.responses = dict(responses)
        self.calls = []

    def __call__(self, method, path, **kwargs):
        self.calls.append(
            {"method": method, "path": path, "json": kwargs.get("json"), "headers": kwargs.get("headers") or {}})
        key = (method, path)
        if key not in self.responses:
            raise AssertionError(f"未预设的聚影请求：{method} {path}")
        value = self.responses[key]
        if isinstance(value, list):
            return value.pop(0)
        return value

    def paths(self):
        return [item["path"] for item in self.calls]

    def post_calls(self, path):
        return [item for item in self.calls if item["method"] == "POST" and item["path"] == path]


class _DemoDefinition:
    """最小渠道定义桩，用于校验签到契约工厂。"""

    id = "demo"
    name = "示例渠道"
    icon = ""


class TestCheckinModeLabels(unittest.TestCase):
    """模式文案由渠道自描述，框架不再维护全局写死映射。"""

    def test_mode_label_falls_back_to_mode_key(self):
        definition = mod_d.CheckinDefinition(
            key="demo",
            name="示例渠道",
            modes=("normal", "lucky"),
            mode_labels={"lucky": "幸运签到"},
        )
        self.assertEqual(definition.mode_label("lucky"), "幸运签到")
        self.assertEqual(definition.mode_label("LUcky"), "幸运签到", "模式文案应忽略大小写")
        self.assertEqual(definition.mode_label("normal"), "normal", "未声明文案时展示模式标识")

    def test_mode_options_use_channel_labels(self):
        options = mod_d.checkin_mode_options(
            ("normal", "lucky"), {"lucky": "幸运签到"}
        )
        self.assertEqual(
            options,
            [{"title": "normal", "value": "normal"}, {"title": "幸运签到", "value": "lucky"}],
        )

    def test_mode_field_shares_row_with_switch(self):
        """开关与模式选择列宽必须互补：错行会让 outlined 标签被上一行压住。"""
        for enable_cols in (4, 6, 12):
            definition = mod_d.build_checkin_definition(
                _DemoDefinition,
                group_title="示例签到",
                modes=("normal", "lucky"),
                enable_cols=enable_cols,
            )
            cols = {field.key: field.cols for field in definition.group.fields}
            self.assertEqual(
                cols["demo_checkin_enabled"] + cols["demo_checkin_mode"],
                12,
                f"enable_cols={enable_cols} 时两列未占满一行",
            )
            self.assertLessEqual(cols["demo_checkin_enabled"], 8)

    def test_single_mode_keeps_enable_cols(self):
        """仅一种模式（无选择框）时保留渠道声明的开关列宽。"""
        definition = mod_d.build_checkin_definition(
            _DemoDefinition,
            group_title="示例签到",
            enable_cols=12,
        )
        self.assertEqual(definition.modes, ("normal",))
        self.assertEqual(definition.group.fields[0].cols, 12)

    def test_factory_keeps_declared_labels(self):
        definition = mod_d.build_checkin_definition(
            _DemoDefinition,
            group_title="示例签到",
            modes=("normal", "lucky"),
            mode_labels={"normal": "普通签到", "lucky": "幸运签到", "": "忽略"},
        )
        self.assertEqual(definition.modes, ("normal", "lucky"))
        self.assertEqual(definition.mode_label("lucky"), "幸运签到")
        self.assertEqual(definition.mode_label("normal"), "普通签到")


class TestJuyingClientCheckin(unittest.TestCase):
    """测试聚影幸运签到与签到幸运奖池领取链路。"""

    def _client(self, responses, points=(100, 149)):
        client = JuyingClient(username="user", password="pass", base_url="https://www.jying.top")
        transport = _FakeJuyingTransport(responses)
        client.request_json = transport
        balances = list(points)
        client.get_account_info = lambda: {"points": balances.pop(0) if len(balances) > 1 else balances[0]}
        return client, transport

    def test_luck_mode_draws_and_claims_bonus_pool(self):
        """幸运签到成功后应自动领取当日奖池，并把奖池收益计入积分变化。"""
        responses = {
            ("GET", "/api/app/checkin/luck/"): {"status": "success", "enabled": True, "can_draw": True,
                                                "consent_required": True},
            ("GET", "/api/app/profile/"): {"status": "success", "user": {"id": 5554, "points": 100}},
            ("POST", "/api/app/checkin/luck/draw/"): {
                "status": "success",
                "message": "今日结果已记录",
                "user_points": 112,
                "draw": {"delta": 12, "date": "2026-10-14"},
            },
            ("GET", "/api/app/checkin/bonus-pool/"): {
                "status": "success",
                "pool": {"id": 4, "title": "每日50W签到幸运奖池", "can_draw": True, "remaining_points": 3000},
            },
            ("POST", "/api/app/checkin/bonus-pool/draw/"): {
                "status": "success",
                "message": "幸运积分已到账",
                "pool": {"id": 4, "title": "每日50W签到幸运奖池",
                         "my_draw": {"reward_points": 37, "balance_after": 149}},
            },
        }
        client, transport = self._client(responses, points=(100, 149))
        result = client.checkin(mode="lucky")

        self.assertTrue(result["success"])
        self.assertEqual(result["mode"], "lucky")
        self.assertEqual(result["signin_points"], 12, "幸运签到收益应取抽奖 delta")
        self.assertEqual(result["points_change"], 49, "积分变化应包含奖池收益")
        self.assertIn("签到奖池 +37", result["message"])

        luck_post = transport.post_calls("/api/app/checkin/luck/draw/")
        self.assertEqual(len(luck_post), 1)
        self.assertTrue(luck_post[0]["json"]["accept_risk"], "幸运签到必须显式接受风险")
        self.assertEqual(luck_post[0]["headers"].get("X-Expected-App-User-Id"), "5554")
        pool_post = transport.post_calls("/api/app/checkin/bonus-pool/draw/")
        self.assertEqual(len(pool_post), 1)
        self.assertEqual(pool_post[0]["json"]["pool_id"], 4)

    def test_luck_mode_when_normal_already_chosen(self):
        """今日已选普通签到时不得发起幸运签到写入，也不得重复计分。"""
        responses = {
            ("GET", "/api/app/checkin/luck/"): {
                "status": "success", "enabled": True, "can_draw": False,
                "can_draw_reason": "今日已选择普通签到，明天可再选择", "daily_checked_today": True,
            },
            ("GET", "/api/app/checkin/bonus-pool/"): {
                "status": "success", "pool": {"id": 4, "can_draw": False, "can_draw_reason": "本期积分已抽完"},
            },
        }
        client, transport = self._client(responses, points=(133, 133))
        result = client.checkin(mode="lucky")

        self.assertTrue(result["success"])
        self.assertTrue(result["already_checked_in"])
        self.assertEqual(result["points_change"], 0)
        self.assertEqual(result["signin_points"], 0)
        self.assertEqual(transport.post_calls("/api/app/checkin/luck/draw/"), [])
        self.assertEqual(transport.post_calls("/api/app/checkin/bonus-pool/draw/"), [])
        self.assertNotIn("奖池 +", result["message"])

    def test_bonus_pool_exhausted_is_skipped_silently(self):
        """奖池抽完时只跳过，不影响普通签到成功结论。"""
        responses = {
            ("GET", "/api/app/checkin/stats/"): [
                {"status": "success", "checked_today": False, "reward_points": 5, "my_total_days": 76},
                {"status": "success", "checked_today": True, "reward_points": 5, "my_total_days": 77},
            ],
            ("POST", "/api/app/checkin/do/"): {"status": "success", "message": "签到成功"},
            ("GET", "/api/app/checkin/bonus-pool/"): {
                "status": "success", "pool": {"id": 4, "can_draw": False, "can_draw_reason": "本期积分已抽完"},
            },
        }
        client, transport = self._client(responses, points=(100, 105))
        result = client.checkin(mode="normal")

        self.assertTrue(result["success"])
        self.assertFalse(result["already_checked_in"])
        self.assertEqual(result["signin_points"], 5)
        self.assertEqual(transport.post_calls("/api/app/checkin/bonus-pool/draw/"), [])
        self.assertNotIn("奖池未领取", result["message"])

    def test_invalid_mode_rejected(self):
        client, _ = self._client({})
        with self.assertRaises(JuyingError):
            client.checkin(mode="unknown")


class TestCheckinDaysCalculation(unittest.TestCase):
    """测试 CheckinService._calculate_signin_days 的统计与融合算法。"""

    def test_empty_history_and_no_remote(self):
        res = CheckinService._calculate_signin_days(history=[], raw_signin_days=None)
        self.assertIsNone(res)

    def test_local_distinct_dates_counting(self):
        # 6 天成功打卡历史，其中一天有 2 次记录（重试或多次打卡）
        history = [
            {"executed_at": "2026-09-19 08:00:00", "success": True},
            {"executed_at": "2026-09-20 08:00:00", "success": True},
            {"executed_at": "2026-09-20 12:00:00", "success": True},  # 同一天多次打卡
            {"executed_at": "2026-09-21 08:00:00", "success": True},
            {"executed_at": "2026-09-22 08:00:00", "success": True},
            {"executed_at": "2026-09-23 08:00:00", "success": True},
            {"executed_at": "2026-09-24 08:00:00", "success": True},
            {"executed_at": "2026-09-18 08:00:00", "success": False},  # 失败记录不计入
        ]
        # 本地成功日期共 6 天：9/19, 9/20, 9/21, 9/22, 9/23, 9/24
        res = CheckinService._calculate_signin_days(history=history, raw_signin_days=None)
        self.assertEqual(res, 6)

    def test_p115_leaf_reset_use_local_days(self):
        # 115 枫叶周期重置为 2 天，但本地历史连续签到了 7 天
        history = [
            {"executed_at": f"2026-09-{day:02d} 09:00:00", "success": True, "signin_days": day}
            for day in range(18, 25)
        ]
        # 此时本地有 7 天打卡成功，而本次 115 官方返回枫叶周期天数 2
        res = CheckinService._calculate_signin_days(
            history=history,
            raw_signin_days=2,
            provider_key="p115",
        )
        self.assertEqual(res, 7, "115 网盘在本地签到 7 天而远端枫叶返回 2 天时，应展示 7 天")

    def test_remote_larger_days_preserved(self):
        # 聚影 / Dian115 远端累计天数大于本地打卡天数
        history = [
            {"executed_at": f"2026-09-{day:02d} 09:00:00", "success": True}
            for day in range(18, 25)
        ]
        # 本地 7 天，聚影返回 56 天
        res = CheckinService._calculate_signin_days(
            history=history,
            raw_signin_days=56,
            provider_key="juying",
        )
        self.assertEqual(res, 56, "远端累计天数 56 大于本地 7 天时，应保留 56 天")

    def test_hdhaven_legacy_one_day_filtered(self):
        # HDHaven 历史记录中遗留了硬编码的 signin_days: 1
        history = [
            {"executed_at": f"2026-09-{day:02d} 09:00:00", "success": True, "signin_days": 1}
            for day in range(19, 25)
        ]
        # 本地 6 天，上报/历史遗留值为 1
        res = CheckinService._calculate_signin_days(
            history=history,
            raw_signin_days=1,
            provider_key="hdhaven",
        )
        self.assertEqual(res, 6, "HDHaven 历史遗留的硬编码 1 应被过滤，正确采用本地累计的 6 天")

    def test_current_execution_increment(self):
        history = [
            {"executed_at": "2026-09-23 09:00:00", "success": True},
        ]
        # 今天 2026-09-24 成功签到
        res = CheckinService._calculate_signin_days(
            history=history,
            current_date_key="2026-09-24",
            current_success=True,
            raw_signin_days=None,
        )
        self.assertEqual(res, 2, "今日成功签到后累计天数应从 1 递增为 2")


class TestCheckinReturnStructure(unittest.TestCase):
    """测试 get_checkin_history 与 list_checkin_details 的返回结构。"""

    def test_get_checkin_history_contains_signin_days(self):
        owner = MagicMock()
        service = CheckinService(owner)
        history = [
            {"executed_at": f"2026-09-{day:02d} 09:00:00", "success": True}
            for day in range(20, 25)
        ]
        with patch.object(CheckinService, "_load_history", return_value=history), \
                patch.object(CheckinService, "_resolve_provider", return_value=MagicMock(key="hdhaven")):
            res = service.get_checkin_history("hdhaven")
            self.assertIsNotNone(res)
            self.assertEqual(res.get("signin_days"), 5)

    def test_list_checkin_details_contains_signin_days(self):
        owner = MagicMock()
        service = CheckinService(owner)
        provider = MagicMock(key="p115", name="115 网盘", points_label="枫叶")
        history = [
            {"executed_at": f"2026-09-{day:02d} 09:00:00", "success": True}
            for day in range(18, 25)
        ]
        with patch.object(CheckinService, "_enabled_providers", return_value=[provider]), \
                patch.object(CheckinService, "_checkin_histories", return_value={"p115": history}):
            res = service.list_checkin_details()
            self.assertTrue(res["success"])
            channels = res["data"]["channels"]
            self.assertEqual(len(channels), 1)
            self.assertEqual(channels[0]["signin_days"], 7)


class TestP115ClientCheckin(unittest.TestCase):
    """测试 115 网盘签到正确累积当前积分与显示数量。"""

    def setUp(self):
        import types
        for p in ["cloudsubscribe.drive", "cloudsubscribe.drive.p115"]:
            if p not in sys.modules:
                m = types.ModuleType(p)
                m.__path__ = []
                sys.modules[p] = m
        sys.modules.setdefault("cloudsubscribe.drive.p115.files", MagicMock())
        sys.modules.setdefault("cloudsubscribe.drive.p115.share", MagicMock())
        sys.modules.setdefault("cloudsubscribe.drive.p115.offline", MagicMock())
        sys.modules.setdefault("cloudsubscribe.drive.p115.upload", MagicMock())
        sys.modules.setdefault("cloudsubscribe.drive.common", MagicMock())
        p115_client_path = os.path.join(plugins_v2_path, "cloudsubscribe/drive/p115/client.py")
        spec_115 = importlib.util.spec_from_file_location("cloudsubscribe.drive.p115.client", p115_client_path)
        mod_115 = importlib.util.module_from_spec(spec_115)
        mod_115.__package__ = "cloudsubscribe.drive.p115"
        sys.modules["cloudsubscribe.drive.p115.client"] = mod_115
        spec_115.loader.exec_module(mod_115)
        self.P115ClientManager = mod_115.P115ClientManager

    def test_p115_checkin_already_checked_in_accumulates_points(self):
        manager = self.P115ClientManager("fake_cookie_value")
        manager.client = MagicMock()
        manager.client.user_points_sign.return_value = {"state": True,
                                                        "data": {"is_sign_today": 1, "continuous_day": 15}}
        manager.client.user_points_balance.return_value = {"state": True, "data": {"balance": 1234}}

        res = manager.checkin()
        self.assertTrue(res["success"])
        self.assertTrue(res["already_checked_in"])
        self.assertEqual(res["points_after"], 1234)
        self.assertIn("1234", res["message"])
        self.assertEqual(res["details"]["current_points"], 1234)

    def test_p115_checkin_success_accumulates_points(self):
        manager = self.P115ClientManager("fake_cookie_value")
        manager.client = MagicMock()
        manager.client.user_points_sign.return_value = {"state": True,
                                                        "data": {"is_sign_today": 0, "continuous_day": 15}}
        manager.client.user_points_sign_post.return_value = {
            "state": True,
            "data": {"points_num": 5, "continuous_day": 16, "total_points": 1239}
        }

        res = manager.checkin()
        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "签到成功")
        self.assertEqual(res["signin_points"], 5)
        self.assertEqual(res["points_after"], 1239)
        self.assertIn("1239", res["message"])
        self.assertEqual(res["details"]["current_points"], 1239)
        self.assertEqual(res["details"]["reward_points"], 5)


if __name__ == "__main__":
    unittest.main()
