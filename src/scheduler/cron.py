"""Scheduled task manager for the workplace demand library.

Uses APScheduler's BackgroundScheduler to run periodic crawling, analysis,
trend detection, data cleanup and database backup jobs.
"""

from __future__ import annotations

import glob as _glob
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import update

from src.storage.database import get_engine, get_session
from src.storage.models import Article
from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger("scheduler")

# ---------------------------------------------------------------------------
# Scraper registry — maps platform name to its scraper class.
# ---------------------------------------------------------------------------

SCRAPER_REGISTRY: Dict[str, type] = {}


def _build_scraper_registry() -> Dict[str, type]:
    """Lazily import all scraper classes and build the registry."""
    if SCRAPER_REGISTRY:
        return SCRAPER_REGISTRY

    from src.scrapers.baidu_baijiahao import BaiduBaijiahaoScraper
    from src.scrapers.bilibili import BilibiliScraper
    from src.scrapers.douban import DoubanScraper
    from src.scrapers.huxiu import HuxiuScraper
    from src.scrapers.juejin import JuejinScraper
    from src.scrapers.kr36 import Kr36Scraper
    from src.scrapers.maimai import MaimaiScraper
    from src.scrapers.toutiao import ToutiaoScraper
    from src.scrapers.weixin_sogou import WeixinSogouScraper
    from src.scrapers.xiaohongshu import XiaohongshuScraper
    from src.scrapers.zhihu import ZhihuScraper

    registry: Dict[str, type] = {
        "zhihu": ZhihuScraper,
        "kr36": Kr36Scraper,
        "douban": DoubanScraper,
        "toutiao": ToutiaoScraper,
        "juejin": JuejinScraper,
        "huxiu": HuxiuScraper,
        "maimai": MaimaiScraper,
        "weixin_sogou": WeixinSogouScraper,
        "xiaohongshu": XiaohongshuScraper,
        "bilibili": BilibiliScraper,
        "baidu_baijiahao": BaiduBaijiahaoScraper,
    }
    SCRAPER_REGISTRY.update(registry)
    return SCRAPER_REGISTRY


# ---------------------------------------------------------------------------
# Job implementations
# ---------------------------------------------------------------------------


def job_crawl_all() -> None:
    """Import all enabled scrapers from the registry and run each one."""
    logger.info("=== 定时任务: crawl_all 开始 ===")
    settings = get_settings()
    platforms = settings.platforms
    registry = _build_scraper_registry()

    for name, scraper_cls in registry.items():
        platform_cfg = platforms.get(name, {})
        if not platform_cfg.get("enabled", False):
            logger.debug(f"跳过已禁用平台: {name}")
            continue
        try:
            logger.info(f"开始抓取平台: {name}")
            scraper = scraper_cls()
            result = scraper.run()
            logger.info(f"平台 {name} 抓取完成: {result}")
        except Exception:
            logger.exception(f"平台 {name} 抓取失败")

    logger.info("=== 定时任务: crawl_all 结束 ===")


def job_analyze_all() -> None:
    """Run DemandExtractor.analyze_batch() on unanalyzed articles."""
    logger.info("=== 定时任务: analyze_all 开始 ===")
    try:
        from src.analyzer.extractor import DemandExtractor

        extractor = DemandExtractor()
        count = extractor.analyze_batch()
        logger.info(f"分析完成，共处理 {count} 篇文章")
    except Exception:
        logger.exception("analyze_all 任务失败")
    logger.info("=== 定时任务: analyze_all 结束 ===")


def job_trend_snapshot() -> None:
    """Create a weekly trend snapshot, detect trends, and generate a report."""
    logger.info("=== 定时任务: trend_snapshot 开始 ===")
    try:
        from src.analyzer.trend_detector import TrendDetector

        detector = TrendDetector()
        snapshot_count = detector.create_snapshot()
        logger.info(f"快照创建完成，记录 {snapshot_count} 条需求")

        trends = detector.detect_trends()
        logger.info(f"趋势检测完成: {trends}")

        report = detector.generate_trend_report()
        logger.info(f"趋势报告已生成 (长度: {len(report)} 字符)")
    except Exception:
        logger.exception("trend_snapshot 任务失败")
    logger.info("=== 定时任务: trend_snapshot 结束 ===")


def job_cleanup() -> None:
    """Delete raw_html from articles older than the configured number of days."""
    logger.info("=== 定时任务: cleanup_old_data 开始 ===")
    try:
        settings = get_settings()
        cleanup_days: int = settings.get("scheduler", {}).get("cleanup_days", 90)
        cutoff = datetime.utcnow() - timedelta(days=cleanup_days)

        with get_session() as session:
            stmt = (
                update(Article)
                .where(Article.crawl_time < cutoff)
                .where(Article.raw_html.isnot(None))
                .values(raw_html=None)
            )
            result = session.execute(stmt)
            count = result.rowcount
            logger.info(f"已清理 {count} 篇文章的 raw_html (早于 {cutoff.date()})")
    except Exception:
        logger.exception("cleanup_old_data 任务失败")
    logger.info("=== 定时任务: cleanup_old_data 结束 ===")


def job_backup() -> None:
    """Copy the SQLite database to data/backups/ with a timestamp suffix.

    Rotates old backups to keep at most ``backup.max_backups`` copies.
    """
    logger.info("=== 定时任务: backup_database 开始 ===")
    try:
        settings = get_settings()
        backup_cfg = settings.get("backup", {})
        max_backups: int = backup_cfg.get("max_backups", 4)
        backup_dir = Path(backup_cfg.get("backup_dir", "./data/backups"))
        backup_dir.mkdir(parents=True, exist_ok=True)

        # Resolve the source database file from the engine URL
        engine = get_engine()
        db_url: str = str(engine.url)
        # sqlite:///path/to/db → path/to/db
        db_path = Path(db_url.split("///", 1)[-1])

        if not db_path.is_file():
            logger.warning(f"数据库文件不存在: {db_path}")
            return

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        dest = backup_dir / f"workplace_demand_{timestamp}.db"
        shutil.copy2(str(db_path), str(dest))
        logger.info(f"数据库已备份至: {dest}")

        # Rotate: keep only the most recent max_backups files
        backups = sorted(
            backup_dir.glob("workplace_demand_*.db"),
            key=lambda p: p.stat().st_mtime,
        )
        while len(backups) > max_backups:
            oldest = backups.pop(0)
            oldest.unlink()
            logger.info(f"已删除旧备份: {oldest}")

    except Exception:
        logger.exception("backup_database 任务失败")
    logger.info("=== 定时任务: backup_database 结束 ===")


# ---------------------------------------------------------------------------
# WorkplaceScheduler
# ---------------------------------------------------------------------------


class WorkplaceScheduler:
    """Manage all periodic jobs via APScheduler's BackgroundScheduler."""

    def __init__(self) -> None:
        """Create the scheduler and load configuration."""
        self.settings = get_settings()
        self.scheduler = BackgroundScheduler()
        self._job_map: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def setup_jobs(self) -> None:
        """Register all scheduled jobs based on the current configuration."""
        sched_cfg = self.settings.get("scheduler", {})
        backup_cfg = self.settings.get("backup", {})

        crawl_hours: int = sched_cfg.get("crawl_interval_hours", 6)
        analyze_hours: int = sched_cfg.get("analyze_interval_hours", 12)
        trend_cron: str = sched_cfg.get("trend_snapshot", "0 0 * * 1")

        # crawl_all — every N hours
        self._job_map["crawl_all"] = self.scheduler.add_job(
            job_crawl_all,
            trigger=IntervalTrigger(hours=crawl_hours),
            id="crawl_all",
            name="抓取所有启用平台",
            replace_existing=True,
        )

        # analyze_all — every N hours
        self._job_map["analyze_all"] = self.scheduler.add_job(
            job_analyze_all,
            trigger=IntervalTrigger(hours=analyze_hours),
            id="analyze_all",
            name="AI 需求分析",
            replace_existing=True,
        )

        # trend_snapshot — cron expression (default: weekly Monday 00:00)
        cron_parts = trend_cron.split()
        self._job_map["trend_snapshot"] = self.scheduler.add_job(
            job_trend_snapshot,
            trigger=CronTrigger(
                minute=cron_parts[0] if len(cron_parts) > 0 else "0",
                hour=cron_parts[1] if len(cron_parts) > 1 else "0",
                day=cron_parts[2] if len(cron_parts) > 2 else "*",
                month=cron_parts[3] if len(cron_parts) > 3 else "*",
                day_of_week=cron_parts[4] if len(cron_parts) > 4 else "*",
            ),
            id="trend_snapshot",
            name="趋势快照与周报",
            replace_existing=True,
        )

        # cleanup_old_data — daily at 03:00
        self._job_map["cleanup_old_data"] = self.scheduler.add_job(
            job_cleanup,
            trigger=CronTrigger(hour=3, minute=0),
            id="cleanup_old_data",
            name="清理旧 raw_html",
            replace_existing=True,
        )

        # backup_database — weekly Sunday 02:00
        if backup_cfg.get("enabled", True):
            self._job_map["backup_database"] = self.scheduler.add_job(
                job_backup,
                trigger=CronTrigger(day_of_week="sun", hour=2, minute=0),
                id="backup_database",
                name="数据库备份",
                replace_existing=True,
            )

        logger.info(f"已注册 {len(self._job_map)} 个定时任务")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background scheduler."""
        self.setup_jobs()
        self.scheduler.start()
        logger.info("调度器已启动")

    def stop(self) -> None:
        """Gracefully shut down the scheduler."""
        self.scheduler.shutdown(wait=True)
        logger.info("调度器已停止")

    # ------------------------------------------------------------------
    # Manual trigger & status
    # ------------------------------------------------------------------

    def trigger_job(self, job_name: str) -> None:
        """Manually trigger a specific job by name.

        Args:
            job_name: One of the registered job names (e.g. ``"crawl_all"``).

        Raises:
            KeyError: If *job_name* is not a registered job.
        """
        if job_name not in self._job_map:
            raise KeyError(
                f"未知任务: {job_name}，可用任务: {list(self._job_map.keys())}"
            )
        job = self.scheduler.get_job(job_name)
        if job is not None:
            job.modify(next_run_time=datetime.now())
            logger.info(f"已手动触发任务: {job_name}")
        else:
            raise KeyError(f"任务 {job_name} 未在调度器中找到")

    def get_job_status(self) -> List[Dict[str, Any]]:
        """Return status information for every registered job.

        Returns:
            A list of dicts, each containing ``name``, ``id``, ``next_run_time``
            and ``trigger`` fields.
        """
        statuses: List[Dict[str, Any]] = []
        for job in self.scheduler.get_jobs():
            statuses.append(
                {
                    "id": job.id,
                    "name": job.name,
                    "next_run_time": (
                        str(job.next_run_time) if job.next_run_time else None
                    ),
                    "trigger": str(job.trigger),
                }
            )
        return statuses


# ---------------------------------------------------------------------------
# Convenience entry-point
# ---------------------------------------------------------------------------


def start_scheduler() -> WorkplaceScheduler:
    """Create, configure, and start the workplace scheduler.

    Returns:
        The running :class:`WorkplaceScheduler` instance.
    """
    scheduler = WorkplaceScheduler()
    scheduler.start()
    return scheduler
