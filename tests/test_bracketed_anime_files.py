"""方括号发布组命名仍须准确匹配目标作品和单集。"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from plugin_env import install_app_mocks, load_module, register_package

install_app_mocks("app.core", "app.core.metainfo")
register_package("cloudsubscribe")
register_package("cloudsubscribe.utils")
register_package("cloudsubscribe.search")

matching = load_module(
    "cloudsubscribe.search.matching",
    "plugins.v2/cloudsubscribe/search/matching.py",
)
parser = load_module(
    "cloudsubscribe.utils.file_parser",
    "plugins.v2/cloudsubscribe/utils/file_parser.py",
)
matcher = load_module(
    "cloudsubscribe.utils.file_matcher",
    "plugins.v2/cloudsubscribe/utils/file_matcher.py",
)
FileMatcher = matcher.FileMatcher


class TestBracketedAnimeFiles(unittest.TestCase):
    def setUp(self):
        self.media = SimpleNamespace(
            title="青之箱", en_title="Blue Box", original_title=None,
            original_name=None, names=[], year="2024", season_years={}, type="电视剧",
        )

    def test_matching_single_episode_and_rejecting_pack_marker(self):
        cases = (
            ("[DBD-Raws][青之箱][01][1080P][BDRip][HEVC-10bit].mkv", 1),
            ("[DBD-Raws][青之箱][25][1080P][BDRip][HEVC-10bit].mkv", 25),
            ("[DBD-Raws][别的作品][01][1080P].mkv", None),
            ("[DBD-Raws][青之箱][01-25TV全集+特典映像][1080P].mkv", None),
            ("[DBD-Raws][青之箱][01][1080P].srt", None),
        )
        # The bracket path must work even when MoviePilot's MetaInfo fails to
        # parse the release group's title (as it does for this naming style).
        with patch.object(FileMatcher, "_platform_meta", return_value=None):
            for filename, expected in cases:
                with self.subTest(filename=filename):
                    self.assertEqual(
                        FileMatcher.episode_from_file({"name": filename}, 1, self.media),
                        expected,
                    )


if __name__ == "__main__":
    unittest.main()
