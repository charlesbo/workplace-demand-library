"""Markdown weekly-report exporter for workplace demands."""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from sqlalchemy import func

from src.storage.database import get_session
from src.storage.models import Article, Demand
from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


class MarkdownExporter:
    """Generate a weekly Markdown report summarising workplace demands."""

    def __init__(self) -> None:
        self.settings = get_settings()

    def export(self, output_path: Optional[str] = None) -> str:
        """Generate the weekly report and write it to a Markdown file.

        Args:
            output_path: Destination file path.  Defaults to
                ``<export.output_dir>/weekly_report_YYYYMMDD.md``.

        Returns:
            The absolute path of the generated Markdown file.
        """
        if output_path is None:
            output_dir = Path(self.settings.get("export.output_dir", "output"))
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = str(
                output_dir / f"weekly_report_{datetime.now():%Y%m%d}.md"
            )
        else:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        now = datetime.now()
        week_ago = now - timedelta(days=7)

        with get_session() as session:
            all_demands: list[Demand] = session.query(Demand).all()
            all_articles: list[Article] = session.query(Article).all()

            new_demands = [
                d for d in all_demands if d.first_seen and d.first_seen >= week_ago
            ]
            new_articles = [
                a for a in all_articles if a.crawl_time and a.crawl_time >= week_ago
            ]

            rising = sorted(
                [d for d in all_demands if d.trend == "rising"],
                key=lambda d: d.frequency,
                reverse=True,
            )[:10]

            hot_articles = sorted(
                [a for a in all_articles if a.crawl_time and a.crawl_time >= week_ago],
                key=lambda a: a.heat_score,
                reverse=True,
            )[:10]

            # Category stats
            cat_counts: dict[str, int] = {}
            for d in all_demands:
                cat = d.category or "未分类"
                cat_counts[cat] = cat_counts.get(cat, 0) + 1

            session.expunge_all()

        total_demands = len(all_demands)
        total_articles = len(all_articles)

        sections: list[str] = [
            f"# 职场需求周报 ({now:%Y-%m-%d})\n",
            self._overview(len(new_demands), len(new_articles), total_demands, total_articles),
            self._new_demands(new_demands),
            self._rising_top10(rising),
            self._hot_articles_top10(hot_articles),
            self._category_stats(cat_counts, total_demands),
            self._ai_insights(),
        ]

        content = "\n".join(sections)
        Path(output_path).write_text(content, encoding="utf-8")
        logger.info(f"Markdown report exported: {output_path}")
        return output_path

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------

    @staticmethod
    def _overview(
        new_demands: int, new_articles: int, total_demands: int, total_articles: int
    ) -> str:
        """本周概览 section."""
        return (
            "## 本周概览\n\n"
            f"| 指标 | 数量 |\n"
            f"|------|------|\n"
            f"| 新发现需求 | {new_demands} |\n"
            f"| 新增文章 | {new_articles} |\n"
            f"| 需求总数 | {total_demands} |\n"
            f"| 文章总数 | {total_articles} |\n"
        )

    @staticmethod
    def _new_demands(demands: list[Demand]) -> str:
        """新发现的需求 section."""
        lines = ["## 新发现的需求\n"]
        if not demands:
            lines.append("本周暂无新发现的需求。\n")
            return "\n".join(lines)
        lines.append("| 标题 | 分类 | 频次 | 重要性 |")
        lines.append("|------|------|------|--------|")
        for d in demands:
            lines.append(
                f"| {d.title} | {d.category or '-'} | {d.frequency} | {d.importance_score:.1f} |"
            )
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _rising_top10(demands: list[Demand]) -> str:
        """趋势上升 TOP 10 section."""
        lines = ["## 趋势上升 TOP 10\n"]
        if not demands:
            lines.append("暂无趋势上升的需求。\n")
            return "\n".join(lines)
        lines.append("| 排名 | 标题 | 分类 | 频次 | 重要性 |")
        lines.append("|------|------|------|------|--------|")
        for i, d in enumerate(demands, 1):
            lines.append(
                f"| {i} | {d.title} | {d.category or '-'} | {d.frequency} | {d.importance_score:.1f} |"
            )
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _hot_articles_top10(articles: list[Article]) -> str:
        """热门文章 TOP 10 section."""
        lines = ["## 热门文章 TOP 10\n"]
        if not articles:
            lines.append("本周暂无热门文章。\n")
            return "\n".join(lines)
        lines.append("| 排名 | 标题 | 平台 | 热度 |")
        lines.append("|------|------|------|------|")
        for i, a in enumerate(articles, 1):
            lines.append(
                f"| {i} | {a.title} | {a.platform} | {a.heat_score:.1f} |"
            )
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _category_stats(cat_counts: dict[str, int], total: int) -> str:
        """分类统计 section."""
        lines = ["## 分类统计\n"]
        lines.append("| 分类 | 数量 | 占比 |")
        lines.append("|------|------|------|")
        for cat, count in sorted(cat_counts.items(), key=lambda x: -x[1]):
            pct = f"{count / total * 100:.1f}%" if total else "0%"
            lines.append(f"| {cat} | {count} | {pct} |")
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _ai_insights() -> str:
        """AI 洞察 section — delegates to TrendDetector if available."""
        lines = ["## AI 洞察\n"]
        try:
            from src.analyzer.trend_detector import TrendDetector

            detector = TrendDetector()
            report = detector.generate_trend_report()
            lines.append(report if report else "AI 洞察暂不可用。\n")
        except Exception as exc:
            logger.warning(f"AI insights unavailable: {exc}")
            lines.append("AI 洞察生成失败，请检查配置。\n")
        return "\n".join(lines)
