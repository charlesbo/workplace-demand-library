"""CLI entry-point for the Workplace Demand Library.

Usage::

    python -m src.main <command> [options]

Run ``python -m src.main --help`` for the full list of commands.
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table
from sqlalchemy import func, select

from src.analyzer.extractor import DemandExtractor
from src.analyzer.trend_detector import TrendDetector
from src.scrapers import (
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
from src.storage.database import get_session, init_db
from src.storage.migrations import run_migrations
from src.storage.models import Article, CrawlLog, Demand
from src.utils.config import get_platform_config, get_settings
from src.utils.logger import get_logger, setup_logging

console = Console()
logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Scraper registry — maps platform name to its scraper class
# ---------------------------------------------------------------------------

SCRAPER_REGISTRY: dict[str, type] = {
    "kr36": Kr36Scraper,
    "huxiu": HuxiuScraper,
    "zhihu": ZhihuScraper,
    "juejin": JuejinScraper,
    "toutiao": ToutiaoScraper,
    "douban": DoubanScraper,
    "xiaohongshu": XiaohongshuScraper,
    "bilibili": BilibiliScraper,
    "weixin_sogou": WeixinSogouScraper,
    "maimai": MaimaiScraper,
    "baidu_baijiahao": BaiduBaijiahaoScraper,
    "rss_generic": RssGenericScraper,
}


def _setup() -> None:
    """Initialise logging from global settings."""
    settings = get_settings()
    log_level: str = settings.get("app.log_level", "INFO")
    log_dir: str = settings.get("app.log_dir", "./logs")
    setup_logging(log_level, log_dir)


# ---------------------------------------------------------------------------
# Root CLI group
# ---------------------------------------------------------------------------


@click.group()
@click.version_option(package_name="workplace-demand-library")
def cli() -> None:
    """Workplace Demand Library — crawl, analyse, and export workplace demands."""
    _setup()


# ---------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------


@cli.command()
def serve() -> None:
    """Start the full service (scheduler + web API)."""
    from src.api.server import start_server
    from src.scheduler.cron import start_scheduler

    console.print("[bold green]Starting scheduler …[/bold green]")
    start_scheduler()

    console.print("[bold green]Starting web server …[/bold green]")
    start_server()


# ---------------------------------------------------------------------------
# crawl
# ---------------------------------------------------------------------------


@cli.command()
@click.option(
    "--platform",
    type=click.Choice(list(SCRAPER_REGISTRY.keys()), case_sensitive=False),
    default=None,
    help="Crawl only this platform (default: all enabled).",
)
@click.option("--limit", type=int, default=None, help="Max articles to crawl.")
def crawl(platform: Optional[str], limit: Optional[int]) -> None:
    """Crawl articles from enabled platforms (or a specific one)."""
    settings = get_settings()

    if platform:
        platforms = [platform]
    else:
        # Iterate all registered platforms that are enabled in config.
        platforms = []
        for name in SCRAPER_REGISTRY:
            cfg = get_platform_config(name)
            if cfg and cfg.get("enabled", False):
                platforms.append(name)

    if not platforms:
        console.print("[yellow]No enabled platforms found.[/yellow]")
        return

    console.print(f"[bold]Crawling {len(platforms)} platform(s) …[/bold]")

    for name in platforms:
        scraper_cls = SCRAPER_REGISTRY[name]
        try:
            scraper = scraper_cls()
            console.print(f"  ▸ [cyan]{name}[/cyan] …", end=" ")
            result = scraper.run(limit=limit)
            console.print(
                f"found [green]{result.get('articles_found', 0)}[/green], "
                f"new [green]{result.get('articles_new', 0)}[/green]"
            )
        except Exception as exc:
            logger.exception("Crawl failed for %s", name)
            console.print(f"[red]ERROR: {exc}[/red]")


# ---------------------------------------------------------------------------
# analyze
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--batch-size", type=int, default=None, help="Articles per batch.")
def analyze(batch_size: Optional[int]) -> None:
    """Analyse unanalysed articles with AI demand extraction."""
    console.print("[bold]Running demand extraction …[/bold]")
    try:
        extractor = DemandExtractor()
        processed = extractor.analyze_batch(batch_size=batch_size)
        console.print(f"[green]Processed {processed} article(s).[/green]")
    except Exception as exc:
        logger.exception("Analysis failed")
        console.print(f"[red]ERROR: {exc}[/red]")


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


@cli.group()
def export() -> None:
    """Export demands to various formats."""


@export.command("excel")
def export_excel() -> None:
    """Export demands to an Excel file."""
    from src.exporter import ExcelExporter

    console.print("[bold]Exporting to Excel …[/bold]")
    exporter = ExcelExporter()
    path = exporter.export()
    console.print(f"[green]Saved to {path}[/green]")


@export.command("csv")
def export_csv() -> None:
    """Export demands to a CSV file."""
    from src.exporter import CsvExporter

    console.print("[bold]Exporting to CSV …[/bold]")
    exporter = CsvExporter()
    path = exporter.export()
    console.print(f"[green]Saved to {path}[/green]")


@export.command("markdown")
def export_markdown() -> None:
    """Export demands to a Markdown file."""
    from src.exporter import MarkdownExporter

    console.print("[bold]Exporting to Markdown …[/bold]")
    exporter = MarkdownExporter()
    path = exporter.export()
    console.print(f"[green]Saved to {path}[/green]")


@export.command("notion")
def export_notion() -> None:
    """Export demands to Notion."""
    from src.exporter import NotionExporter

    console.print("[bold]Exporting to Notion …[/bold]")
    exporter = NotionExporter()
    path = exporter.export()
    console.print(f"[green]Saved to {path}[/green]")


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------


@cli.command()
def stats() -> None:
    """Show database statistics."""
    with get_session() as session:
        total_articles: int = session.scalar(
            select(func.count()).select_from(Article)
        ) or 0
        analyzed_articles: int = session.scalar(
            select(func.count()).select_from(Article).where(Article.is_analyzed.is_(True))
        ) or 0
        total_demands: int = session.scalar(
            select(func.count()).select_from(Demand)
        ) or 0

        # Per-platform breakdown
        platform_rows = session.execute(
            select(Article.platform, func.count())
            .group_by(Article.platform)
            .order_by(func.count().desc())
        ).all()

    # Summary table
    summary = Table(title="Database Statistics", show_lines=True)
    summary.add_column("Metric", style="cyan")
    summary.add_column("Value", justify="right", style="green")
    summary.add_row("Total articles", str(total_articles))
    summary.add_row("Analysed articles", str(analyzed_articles))
    summary.add_row("Un-analysed articles", str(total_articles - analyzed_articles))
    summary.add_row("Total demands", str(total_demands))
    console.print(summary)

    # Platform breakdown
    if platform_rows:
        plat_table = Table(title="Articles by Platform", show_lines=True)
        plat_table.add_column("Platform", style="cyan")
        plat_table.add_column("Count", justify="right", style="green")
        for name, count in platform_rows:
            plat_table.add_row(name, str(count))
        console.print(plat_table)


# ---------------------------------------------------------------------------
# cleanup
# ---------------------------------------------------------------------------


@cli.command()
def cleanup() -> None:
    """Clean raw_html data older than N days (from config)."""
    settings = get_settings()
    days: int = settings.get("scheduler.cleanup_days", 90)
    cutoff = datetime.utcnow() - timedelta(days=days)

    console.print(f"[bold]Cleaning raw_html older than {days} days …[/bold]")

    with get_session() as session:
        rows = (
            session.query(Article)
            .filter(Article.crawl_time < cutoff, Article.raw_html.isnot(None))
            .all()
        )
        count = 0
        for article in rows:
            article.raw_html = None
            count += 1
        session.commit()

    console.print(f"[green]Cleaned {count} article(s).[/green]")


# ---------------------------------------------------------------------------
# init-db
# ---------------------------------------------------------------------------


@cli.command("init-db")
def init_db_cmd() -> None:
    """Initialise (or migrate) the database."""
    settings = get_settings()
    db_path: str = os.path.join(
        settings.get("app.data_dir", "./data"), "workplace_demand.db"
    )

    console.print(f"[bold]Initialising database at {db_path} …[/bold]")
    engine = init_db(db_path)
    run_migrations(engine)
    console.print("[green]Database ready.[/green]")


# ---------------------------------------------------------------------------
# trends
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--snapshot", is_flag=True, help="Create a new snapshot before reporting.")
def trends(snapshot: bool) -> None:
    """Display the trend report (optionally create a snapshot first)."""
    detector = TrendDetector()

    if snapshot:
        console.print("[bold]Creating trend snapshot …[/bold]")
        n = detector.create_snapshot()
        console.print(f"[green]Snapshot created with {n} demand(s).[/green]")

    console.print("[bold]Detecting trends …[/bold]")
    trend_data = detector.detect_trends()

    # Quick summary table
    table = Table(title="Trend Summary", show_lines=True)
    table.add_column("Category", style="cyan")
    table.add_column("Count", justify="right", style="green")
    table.add_row("Rising", str(len(trend_data.get("rising", []))))
    table.add_row("Declining", str(len(trend_data.get("declining", []))))
    table.add_row("Stable", str(len(trend_data.get("stable", []))))
    table.add_row("New demands", str(len(trend_data.get("new_demands", []))))
    console.print(table)

    # Full markdown report
    report = detector.generate_trend_report()
    console.print()
    console.print(report)


# ---------------------------------------------------------------------------
# backup
# ---------------------------------------------------------------------------


@cli.command()
def backup() -> None:
    """Create a manual backup of the SQLite database."""
    settings = get_settings()
    data_dir: str = settings.get("app.data_dir", "./data")
    backup_dir: str = settings.get("backup.backup_dir", "./data/backups")
    max_backups: int = settings.get("backup.max_backups", 4)
    db_file = Path(data_dir) / "workplace_demand.db"

    if not db_file.exists():
        console.print("[red]Database file not found.[/red]")
        return

    backup_path = Path(backup_dir)
    backup_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = backup_path / f"workplace_demand_{timestamp}.db"
    shutil.copy2(db_file, dest)
    console.print(f"[green]Backup saved to {dest}[/green]")

    # Prune old backups — keep only the most recent N files.
    backups = sorted(backup_path.glob("workplace_demand_*.db"), reverse=True)
    for old in backups[max_backups:]:
        old.unlink()
        logger.info("Removed old backup: %s", old)

    if len(backups) > max_backups:
        console.print(
            f"[yellow]Pruned {len(backups) - max_backups} old backup(s).[/yellow]"
        )


# ---------------------------------------------------------------------------
# Entry-point for ``python -m src.main``
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cli()
