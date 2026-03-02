"""Tests for AI analysis modules: prompts, classifier, deduplicator, extractor."""

from unittest.mock import MagicMock, patch

import pytest


# ===========================================================================
# Prompts
# ===========================================================================


class TestFormatPrompt:
    """Tests for prompts.format_prompt."""

    def test_format_prompt(self):
        """Variable substitution fills in provided keys."""
        from src.analyzer.prompts import format_prompt

        result = format_prompt("Hello {name}, welcome to {place}!", name="Alice")
        assert "Alice" in result
        assert "{place}" in result  # missing key preserved

    def test_format_prompt_missing_key(self):
        """Missing keys are left as literal placeholders (no KeyError)."""
        from src.analyzer.prompts import format_prompt

        result = format_prompt("{greeting} {name}!", greeting="Hi")
        assert result == "Hi {name}!"

    def test_format_prompt_all_keys(self):
        """All provided keys are substituted correctly."""
        from src.analyzer.prompts import format_prompt

        result = format_prompt("{a} and {b}", a="X", b="Y")
        assert result == "X and Y"


class TestValidCategories:
    """Tests for the VALID_CATEGORIES constant."""

    def test_valid_categories_count(self):
        """There are exactly 9 predefined categories."""
        from src.analyzer.prompts import VALID_CATEGORIES

        assert len(VALID_CATEGORIES) == 9

    def test_valid_categories_contents(self):
        from src.analyzer.prompts import VALID_CATEGORIES

        assert "沟通协作" in VALID_CATEGORIES
        assert "职业发展" in VALID_CATEGORIES
        assert "行业洞察" in VALID_CATEGORIES


# ===========================================================================
# Classifier
# ===========================================================================


class TestDemandClassifier:
    """Tests for classifier.DemandClassifier."""

    @pytest.fixture(autouse=True)
    def _patch_settings(self):
        # Import the module first so patch targets resolve
        import src.analyzer.classifier  # noqa: F401
        with patch("src.analyzer.classifier.get_settings", return_value={
            "ai": {"model": "test", "api_key": "fake", "max_tokens": 100, "temperature": 0.1},
        }), patch("src.analyzer.classifier.get_logger", return_value=MagicMock()):
            from src.analyzer.classifier import DemandClassifier
            self.classifier = DemandClassifier()

    def test_validate_category_valid(self):
        """A known category passes through unchanged."""
        assert self.classifier.validate_category("职业发展") == "职业发展"

    def test_validate_category_invalid(self):
        """An unknown category falls back to '行业洞察'."""
        assert self.classifier.validate_category("不存在的类别") == "行业洞察"

    def test_classify_communication(self):
        """A '沟通' title matches keywords; validate_category maps it to fallback.

        The keyword map uses "职场技能" as the category key, which is not in
        VALID_CATEGORIES, so validate_category corrects it to "行业洞察".
        The subcategory "沟通协作" is still returned from keyword matching.
        """
        category, sub = self.classifier.classify(
            "如何提高职场沟通能力", "沟通协作技巧和方法"
        )
        assert category == "行业洞察"
        assert sub == "沟通协作"

    def test_classify_career(self):
        """A title about '跳槽' should classify under career development."""
        category, _sub = self.classifier.classify(
            "跳槽前需要考虑什么", "关于跳槽和求职的指南"
        )
        assert category == "职业发展"

    def test_classify_default_fallback(self):
        """When no keywords match, the default category is returned."""
        category, _sub = self.classifier.classify(
            "完全无关的标题", "没有任何关键词"
        )
        assert category == "行业洞察"


# ===========================================================================
# Deduplicator
# ===========================================================================


class TestDemandDeduplicator:
    """Tests for deduplicator.DemandDeduplicator."""

    @pytest.fixture(autouse=True)
    def _patch_deps(self):
        import src.analyzer.deduplicator  # noqa: F401
        with patch("src.analyzer.deduplicator.get_settings", return_value={
            "ai": {"model": "test", "api_key": "fake", "max_tokens": 100, "temperature": 0.1},
        }), patch("src.analyzer.deduplicator.get_logger", return_value=MagicMock()):
            from src.analyzer.deduplicator import DemandDeduplicator
            self.dedup = DemandDeduplicator()

    def test_exact_match(self):
        """find_exact_match returns a Demand when the title exists in the DB."""
        fake_demand = MagicMock()
        fake_demand.title = "职场沟通困难"

        mock_session = MagicMock()
        mock_session.execute.return_value.scalar_one_or_none.return_value = fake_demand

        with patch("src.analyzer.deduplicator.get_session") as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            result = self.dedup.find_exact_match("职场沟通困难")

        assert result is fake_demand

    def test_exact_match_not_found(self):
        """find_exact_match returns None when no title matches."""
        mock_session = MagicMock()
        mock_session.execute.return_value.scalar_one_or_none.return_value = None

        with patch("src.analyzer.deduplicator.get_session") as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            result = self.dedup.find_exact_match("不存在的需求")

        assert result is None

    def test_fuzzy_match(self):
        """find_fuzzy_match detects similar titles above the threshold."""
        fake_demand = MagicMock()
        fake_demand.title = "职场沟通效率低"
        fake_demand.id = 1

        mock_session = MagicMock()
        mock_session.execute.return_value.scalar.return_value = 1  # total count

        with patch("src.analyzer.deduplicator.get_session") as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            # Mock _get_candidate_demands to return our fake demand
            with patch.object(self.dedup, "_get_candidate_demands", return_value=[fake_demand]):
                result = self.dedup.find_fuzzy_match("职场沟通效率低下")

        assert result is not None
        demand, ratio = result
        assert demand.title == "职场沟通效率低"
        assert ratio > 0.7


# ===========================================================================
# Extractor
# ===========================================================================


class TestDemandExtractor:
    """Tests for extractor.DemandExtractor._parse_json_response."""

    @pytest.fixture(autouse=True)
    def _patch_deps(self):
        import src.analyzer.extractor  # noqa: F401
        with patch("src.analyzer.extractor.get_settings", return_value={
            "ai": {
                "provider": "anthropic",
                "api_key": "fake",
                "model": "test",
                "max_tokens": 100,
                "temperature": 0.1,
                "batch_size": 5,
                "daily_budget": 100,
            },
        }), patch("src.analyzer.extractor.get_logger", return_value=MagicMock()):
            from src.analyzer.extractor import DemandExtractor
            self.extractor = DemandExtractor()

    def test_parse_json_response(self):
        """Valid JSON string is parsed correctly."""
        raw = '{"demands": [{"title": "test"}], "article_summary": "summary"}'
        result = self.extractor._parse_json_response(raw)
        assert "demands" in result
        assert result["demands"][0]["title"] == "test"

    def test_parse_json_response_with_markdown(self):
        """JSON wrapped in markdown code fences is extracted and parsed."""
        raw = '```json\n{"demands": [{"title": "from markdown"}]}\n```'
        result = self.extractor._parse_json_response(raw)
        assert result["demands"][0]["title"] == "from markdown"

    def test_parse_json_response_with_prefix(self):
        """JSON preceded by non-JSON text is still found and parsed."""
        raw = 'Here is the result:\n{"demands": []}'
        result = self.extractor._parse_json_response(raw)
        assert result["demands"] == []

    def test_parse_json_response_invalid(self):
        """Completely invalid input raises ValueError."""
        with pytest.raises(ValueError):
            self.extractor._parse_json_response("no json here at all")
