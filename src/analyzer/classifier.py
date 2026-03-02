"""Demand classifier with keyword matching and AI-assisted reclassification.

Classifies workplace demands into categories and subcategories using:
1. Keyword-based matching (fast, offline)
2. AI-powered reclassification (Claude API) when keyword matching is uncertain
"""

from __future__ import annotations

import json
from typing import Dict, List, Tuple

from src.analyzer.prompts import CLASSIFY_DEMAND_PROMPT, VALID_CATEGORIES, format_prompt
from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Fallback category when validation or classification fails
_DEFAULT_CATEGORY = "行业洞察"
_DEFAULT_SUBCATEGORY = "综合"


class DemandClassifier:
    """Classify workplace demands into categories and subcategories."""

    def __init__(self) -> None:
        """Initialise the classifier with AI config and keyword mappings."""
        settings = get_settings()
        ai_config = settings.get("ai", {})
        self.model = ai_config.get("model", "claude-sonnet-4-20250514")
        self.max_tokens = ai_config.get("max_tokens", 4096)
        self.temperature = ai_config.get("temperature", 0.3)
        self.api_key = ai_config.get("api_key", "")
        self._keywords = self.get_category_keywords()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate_category(self, category: str) -> str:
        """Validate a category string against the known category list.

        Args:
            category: The category to validate.

        Returns:
            The original category if valid, otherwise the fallback
            ``"行业洞察"``.
        """
        if category in VALID_CATEGORIES:
            return category
        # Try a case-insensitive / whitespace-stripped match
        stripped = category.strip()
        for valid in VALID_CATEGORIES:
            if stripped == valid:
                return valid
        logger.warning("Invalid category '{}', falling back to '{}'", category, _DEFAULT_CATEGORY)
        return _DEFAULT_CATEGORY

    def classify(self, title: str, description: str) -> Tuple[str, str]:
        """Classify a demand using keyword matching.

        Scans the title and description for representative keywords and
        returns the best-matching category and subcategory.

        Args:
            title: The demand title.
            description: The demand description.

        Returns:
            A tuple ``(category, subcategory)``.
        """
        text = f"{title} {description}".lower()
        best_category = _DEFAULT_CATEGORY
        best_subcategory = _DEFAULT_SUBCATEGORY
        best_score = 0

        for category, subcategories in self._keywords.items():
            for subcategory, keywords in subcategories.items():
                score = sum(1 for kw in keywords if kw in text)
                if score > best_score:
                    best_score = score
                    best_category = category
                    best_subcategory = subcategory

        if best_score == 0:
            logger.debug("No keyword match for '{}', using default", title)

        return self.validate_category(best_category), best_subcategory

    def reclassify_with_ai(self, title: str, description: str) -> Tuple[str, str]:
        """Use the Claude API to classify a demand when keyword matching is uncertain.

        Args:
            title: The demand title.
            description: The demand description.

        Returns:
            A tuple ``(category, subcategory)`` determined by the AI model.
            Falls back to keyword-based classification on failure.
        """
        import anthropic

        prompt = format_prompt(
            CLASSIFY_DEMAND_PROMPT,
            title=title,
            description=description,
            categories=json.dumps(
                list(VALID_CATEGORIES), ensure_ascii=False
            ),
        )

        try:
            client = anthropic.Anthropic(api_key=self.api_key)
            response = client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                messages=[{"role": "user", "content": prompt}],
            )

            result_text = response.content[0].text
            result = json.loads(result_text)
            category = self.validate_category(result.get("category", ""))
            subcategory = result.get("subcategory", _DEFAULT_SUBCATEGORY)
            logger.info(
                "AI classified '{}' -> ({}, {})", title, category, subcategory
            )
            return category, subcategory

        except Exception:
            logger.warning(
                "AI reclassification failed for '{}', falling back to keywords",
                title,
            )
            return self.classify(title, description)

    def get_category_keywords(self) -> Dict[str, Dict[str, List[str]]]:
        """Return the mapping of categories to subcategories and their keywords.

        Returns:
            A nested dict: ``{category: {subcategory: [keywords]}}``.
        """
        return {
            "职业发展": {
                "晋升加薪": ["升职", "加薪", "晋升", "涨薪", "薪资", "薪酬", "待遇"],
                "跳槽求职": ["跳槽", "求职", "面试", "简历", "offer", "招聘", "转行"],
                "职业规划": ["职业规划", "职业发展", "职业路径", "发展方向", "转型"],
            },
            "职场技能": {
                "沟通协作": ["沟通", "协作", "汇报", "表达", "演讲", "谈判", "人际"],
                "管理领导": ["管理", "领导力", "团队管理", "带团队", "下属", "leader"],
                "专业技能": ["技能", "学习", "培训", "考证", "提升", "能力"],
            },
            "职场文化": {
                "办公室政治": ["办公室政治", "站队", "派系", "关系", "背锅", "甩锅"],
                "企业文化": ["企业文化", "价值观", "使命", "加班文化", "狼性", "内卷"],
                "职场关系": ["同事关系", "上下级", "职场社交", "人脉", "圈子"],
            },
            "工作生活": {
                "工作压力": ["压力", "焦虑", "倦怠", "burnout", "996", "加班", "过劳"],
                "工作生活平衡": ["work-life", "平衡", "休假", "远程办公", "居家办公", "灵活"],
                "心理健康": ["心理", "情绪", "抑郁", "心态", "调节", "减压"],
            },
            "行业洞察": {
                "行业趋势": ["趋势", "风口", "赛道", "行业", "市场", "前景"],
                "裁员就业": ["裁员", "失业", "就业", "优化", "毕业", "35岁"],
                "综合": ["职场", "工作", "打工"],
            },
        }

    def batch_validate(self, demands: List[Dict]) -> List[Dict]:
        """Validate and fix categories for a batch of demands.

        Each demand dict is expected to have ``title``, ``description``,
        and ``category`` keys. Invalid categories are corrected using
        keyword-based classification.

        Args:
            demands: A list of demand dictionaries.

        Returns:
            The same list with corrected ``category`` and ``subcategory``
            fields.
        """
        for demand in demands:
            category = demand.get("category", "")
            if category not in VALID_CATEGORIES:
                title = demand.get("title", "")
                description = demand.get("description", "")
                new_category, new_subcategory = self.classify(title, description)
                demand["category"] = new_category
                demand["subcategory"] = new_subcategory
                logger.debug(
                    "Batch fix: '{}' -> ({}, {})",
                    title,
                    new_category,
                    new_subcategory,
                )
            else:
                demand["category"] = self.validate_category(category)

        return demands
