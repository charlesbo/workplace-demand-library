"""Tests for the scraper system: BaseScraper utilities and scraper instantiation."""

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# BaseScraper — heat score normalisation
# ---------------------------------------------------------------------------


class TestNormalizeHeatScore:
    """Tests for BaseScraper.normalize_heat_score."""

    @pytest.fixture(autouse=True)
    def _make_scraper(self):
        """Create a minimal BaseScraper subclass for testing."""
        with patch("src.scrapers.base.get_platform_config", return_value={}), \
             patch("src.scrapers.base.get_settings", return_value={"keywords": {"primary": ["职场"]}}), \
             patch("src.scrapers.base.HttpClient"), \
             patch("src.scrapers.base.get_rate_limiter"), \
             patch("src.scrapers.base.BlockDetector"), \
             patch("src.scrapers.base.get_logger"), \
             patch("src.scrapers.base.get_session"), \
             patch("src.scrapers.base.select"):

            from src.scrapers.base import BaseScraper

            class _Stub(BaseScraper):
                def get_hot_articles_list(self):
                    return []

                def get_article_detail(self, url):
                    return {}

            self.scraper = _Stub("test_platform")

    def test_normalize_heat_score(self):
        """Logarithmic normalisation produces a value in 0-100."""
        score = self.scraper.normalize_heat_score(
            view_count=5000,
            like_count=200,
            comment_count=50,
            share_count=10,
        )
        assert 0 < score <= 100

    def test_normalize_heat_score_zeros(self):
        """All-zero counts yield a score of 0."""
        score = self.scraper.normalize_heat_score(0, 0, 0, 0)
        assert score == 0

    def test_normalize_heat_score_high_values(self):
        """Very high counts still produce a finite score near 100."""
        score = self.scraper.normalize_heat_score(
            view_count=1_000_000,
            like_count=100_000,
            comment_count=10_000,
            share_count=50_000,
        )
        assert score == pytest.approx(100.0, abs=0.1)


# ---------------------------------------------------------------------------
# BaseScraper — URL dedup cache
# ---------------------------------------------------------------------------


class TestIsDuplicate:
    """Tests for BaseScraper.is_duplicate (in-memory URL cache)."""

    @pytest.fixture(autouse=True)
    def _make_scraper(self):
        with patch("src.scrapers.base.get_platform_config", return_value={}), \
             patch("src.scrapers.base.get_settings", return_value={"keywords": {"primary": ["职场"]}}), \
             patch("src.scrapers.base.HttpClient"), \
             patch("src.scrapers.base.get_rate_limiter"), \
             patch("src.scrapers.base.BlockDetector"), \
             patch("src.scrapers.base.get_logger"), \
             patch("src.scrapers.base.get_session"), \
             patch("src.scrapers.base.select"):

            from src.scrapers.base import BaseScraper

            class _Stub(BaseScraper):
                def get_hot_articles_list(self):
                    return []

                def get_article_detail(self, url):
                    return {}

            self.scraper = _Stub("test_platform")

    def test_is_duplicate_false_for_new_url(self):
        assert self.scraper.is_duplicate("https://example.com/new") is False

    def test_is_duplicate_true_after_adding(self):
        url = "https://example.com/seen"
        self.scraper._url_cache.add(url)
        assert self.scraper.is_duplicate(url) is True


# ---------------------------------------------------------------------------
# Individual scraper instantiation
# ---------------------------------------------------------------------------


_SCRAPER_PATCHES = [
    "src.scrapers.base.get_platform_config",
    "src.scrapers.base.get_settings",
    "src.scrapers.base.HttpClient",
    "src.scrapers.base.get_rate_limiter",
    "src.scrapers.base.BlockDetector",
    "src.scrapers.base.get_logger",
    "src.scrapers.base.get_session",
    "src.scrapers.base.select",
]


def _apply_patches():
    """Return a list of started mock patchers."""
    patchers = [patch(p, return_value={} if "config" in p or "settings" in p else MagicMock()) for p in _SCRAPER_PATCHES]
    # get_settings needs to return a dict
    for p in patchers:
        m = p.start()
        if "get_settings" in p.attribute:
            m.return_value = {"keywords": {"primary": ["职场"], "secondary": []}}
        elif "get_platform_config" in p.attribute:
            m.return_value = {}
    return patchers


def _stop_patches(patchers):
    for p in patchers:
        p.stop()


def test_kr36_scraper_init():
    patchers = _apply_patches()
    try:
        from src.scrapers.kr36 import Kr36Scraper
        scraper = Kr36Scraper()
        assert scraper.platform_name == "kr36"
    finally:
        _stop_patches(patchers)


def test_huxiu_scraper_init():
    patchers = _apply_patches()
    try:
        from src.scrapers.huxiu import HuxiuScraper
        scraper = HuxiuScraper()
        assert scraper.platform_name == "huxiu"
    finally:
        _stop_patches(patchers)


def test_juejin_scraper_init():
    patchers = _apply_patches()
    try:
        from src.scrapers.juejin import JuejinScraper
        scraper = JuejinScraper()
        assert scraper.platform_name == "juejin"
    finally:
        _stop_patches(patchers)


def test_bilibili_scraper_init():
    patchers = _apply_patches()
    try:
        from src.scrapers.bilibili import BilibiliScraper
        scraper = BilibiliScraper()
        assert scraper.platform_name == "bilibili"
    finally:
        _stop_patches(patchers)


def test_rss_scraper_init():
    patchers = _apply_patches()
    try:
        from src.scrapers.rss_generic import RssGenericScraper
        scraper = RssGenericScraper()
        assert scraper.platform_name == "rss_feeds"
    finally:
        _stop_patches(patchers)


# ---------------------------------------------------------------------------
# Keyword filtering
# ---------------------------------------------------------------------------


def test_scraper_get_keywords():
    """Kr36Scraper.get_keywords returns a non-empty list from settings."""
    patchers = _apply_patches()
    try:
        from src.scrapers.kr36 import Kr36Scraper
        scraper = Kr36Scraper()
        keywords = scraper.get_keywords()
        assert isinstance(keywords, list)
        assert len(keywords) > 0
    finally:
        _stop_patches(patchers)


# ---------------------------------------------------------------------------
# Package __init__.py imports
# ---------------------------------------------------------------------------


class TestPackageImports:
    """Verify that package-level imports work correctly after __init__.py fix."""

    def test_scrapers_package_imports(self):
        """All scraper classes should be importable from src.scrapers."""
        from src.scrapers import (
            BaseScraper,
            BaiduBaijiahaoScraper,
            BilibiliScraper,
            DoubanScraper,
            HuxiuScraper,
            JuejinScraper,
            Kr36Scraper,
            MaimaiScraper,
            RssGenericScraper,
            ToutiaoScraper,
            WeixinSogouScraper,
            XiaohongshuScraper,
            ZhihuScraper,
        )
        assert BaseScraper is not None
        assert Kr36Scraper is not None
        assert ZhihuScraper is not None
        assert BaiduBaijiahaoScraper is not None

    def test_exporter_package_imports(self):
        """All exporter classes should be importable from src.exporter."""
        from src.exporter import (
            CsvExporter,
            ExcelExporter,
            MarkdownExporter,
            NotionExporter,
        )
        assert ExcelExporter is not None
        assert CsvExporter is not None
        assert MarkdownExporter is not None
        assert NotionExporter is not None


# ---------------------------------------------------------------------------
# Database default path resolution
# ---------------------------------------------------------------------------


class TestDatabaseDefaultPath:
    """Verify that get_engine resolves the DB path from config by default."""

    def test_default_db_path_from_config(self):
        """_default_db_path should return a path under app.data_dir."""
        from src.storage.database import _default_db_path
        path = _default_db_path()
        assert "workplace_demand.db" in path
        assert "data" in path


# ---------------------------------------------------------------------------
# Scheduler scraper instantiation
# ---------------------------------------------------------------------------


class TestSchedulerScraperInit:
    """Verify scrapers are instantiated without extra arguments."""

    def test_all_scrapers_init_no_args(self):
        """Every concrete scraper must be instantiable with zero arguments."""
        patchers = _apply_patches()
        try:
            from src.scrapers import (
                Kr36Scraper, HuxiuScraper, ZhihuScraper, JuejinScraper,
                ToutiaoScraper, DoubanScraper, XiaohongshuScraper,
                BilibiliScraper, WeixinSogouScraper, MaimaiScraper,
                BaiduBaijiahaoScraper, RssGenericScraper,
            )
            for cls in [
                Kr36Scraper, HuxiuScraper, ZhihuScraper, JuejinScraper,
                ToutiaoScraper, DoubanScraper, XiaohongshuScraper,
                BilibiliScraper, WeixinSogouScraper, MaimaiScraper,
                BaiduBaijiahaoScraper, RssGenericScraper,
            ]:
                scraper = cls()  # must not raise TypeError
                assert scraper.platform_name
        finally:
            _stop_patches(patchers)
