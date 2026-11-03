"""Magnet 整包的发布信息应参与真实文件的规则筛选。"""

import unittest

from plugin_env import (
    OwnerDelegator,
    install_app_mocks,
    load_module,
    register_module,
    register_package,
)

install_app_mocks("app.utils", "app.utils.string")
register_package("cloudsubscribe")
register_package("cloudsubscribe.core", OwnerDelegator=OwnerDelegator)
register_package("cloudsubscribe.search")
register_module("cloudsubscribe.search.matching", positive_ints=lambda values: set(values))
register_package("cloudsubscribe.handlers")
register_package("cloudsubscribe.handlers.search")

PlatformRuleService = load_module(
    "cloudsubscribe.handlers.search.platform_rules",
    "plugins.v2/cloudsubscribe/handlers/search/platform_rules.py",
).PlatformRuleService
MediaFileParser = load_module(
    "cloudsubscribe.utils.file_parser",
    "plugins.v2/cloudsubscribe/utils/file_parser.py",
).MediaFileParser


class NativeFile(dict):
    def __init__(self, name, relative_path):
        super().__init__(name=name)
        self.native = {"_relative_path": relative_path}


class TestMagnetFilterTitle(unittest.TestCase):
    def test_vivy_episode_uses_package_quality_without_special_episode_marker(self):
        release = "Vivy -Fluorite Eye's Song- S01+SP 1080p Dual Audio BD Remux FLAC-TTGA"
        episode = "S01E01-My Code Name - To Make Everyone Happy With My Singing.mkv"
        candidate = next(MediaFileParser.iter_files([
            NativeFile(episode, f"{release}/{episode}")
        ]))

        title = PlatformRuleService._file_filter_title(candidate, 0)

        self.assertIn("Vivy -Fluorite Eye's Song- S01 1080p", title)
        self.assertIn(episode, title)
        self.assertNotIn("S01+SP", title)


if __name__ == "__main__":
    unittest.main()
