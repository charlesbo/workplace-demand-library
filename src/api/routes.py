"""API route definitions for the workplace demand library.

Provides endpoints for articles, demands, analytics, operations,
search, and health checks.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select

from src.storage.database import get_session, init_db
from src.storage.models import (
    Article,
    ArticleDemandRelation,
    CrawlLog,
    Demand,
    DemandRelation,
    TrendSnapshot,
    ArticleResponse,
    DemandResponse,
    CrawlLogResponse,
)
from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


# ===========================================================================
# Response schemas
# ===========================================================================

class PaginatedArticles(BaseModel):
    """Paginated list of articles."""
    items: List[ArticleResponse]
    total: int


class ArticleDetail(ArticleResponse):
    """Article detail with related demands."""
    demands: List[DemandResponse] = []


class ArticleStats(BaseModel):
    """Article statistics."""
    total: int = 0
    by_platform: Dict[str, int] = {}
    by_date: Dict[str, int] = {}
    analyzed: int = 0
    unanalyzed: int = 0


class PaginatedDemands(BaseModel):
    """Paginated list of demands."""
    items: List[DemandResponse]
    total: int


class DemandDetail(DemandResponse):
    """Demand detail with related articles and demands."""
    related_articles: List[ArticleResponse] = []
    related_demands: List[DemandResponse] = []


class DemandUpdate(BaseModel):
    """Schema for updating a demand."""
    category: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[str] = None


class StatusUpdate(BaseModel):
    """Schema for changing demand status."""
    status: str


class AnnotationRequest(BaseModel):
    """Schema for user annotation on a demand."""
    action: str = Field(..., description="confirm, reject, or merge")
    notes: Optional[str] = None
    target_demand_id: Optional[int] = Field(
        None, description="Target demand ID for merge action"
    )


class CategoryCount(BaseModel):
    """Category with article/demand count."""
    name: str
    count: int


class TagCount(BaseModel):
    """Tag with count for word cloud."""
    tag: str
    count: int


class OverviewData(BaseModel):
    """Dashboard overview data."""
    total_articles: int = 0
    total_demands: int = 0
    week_new_demands: int = 0
    analysis_rate: float = 0.0
    category_distribution: List[CategoryCount] = []
    recent_demands: List[DemandResponse] = []
    trending_demands: List[DemandResponse] = []


class TrendPoint(BaseModel):
    """Single data point in a trend series."""
    date: str
    frequency: int = 0
    heat_score: float = 0.0


class TrendSeries(BaseModel):
    """Trend data for a single demand."""
    demand_id: int
    title: str
    data: List[TrendPoint] = []


class TrendChartData(BaseModel):
    """Trend chart data for multiple demands."""
    series: List[TrendSeries] = []


class CategoryDistItem(BaseModel):
    """Category distribution item."""
    name: str
    count: int
    percentage: float


class WeeklyReport(BaseModel):
    """Weekly report in markdown."""
    content: str
    generated_at: str


class GraphNode(BaseModel):
    """Node in the demand relation graph."""
    id: int
    label: str
    category: Optional[str] = None
    frequency: int = 0


class GraphEdge(BaseModel):
    """Edge in the demand relation graph."""
    from_id: int = Field(..., alias="from")
    to_id: int = Field(..., alias="to")
    similarity: float = 0.0
    model_config = ConfigDict(populate_by_name=True)


class DemandGraph(BaseModel):
    """Demand relation graph for vis.js."""
    nodes: List[GraphNode] = []
    edges: List[GraphEdge] = []


class TriggerResponse(BaseModel):
    """Response for background task triggers."""
    message: str
    status: str = "started"


class PaginatedCrawlLogs(BaseModel):
    """Paginated list of crawl logs."""
    items: List[CrawlLogResponse]
    total: int


class ExportResponse(BaseModel):
    """Export result with download URL."""
    format: str
    file_path: str
    download_url: str


class ConfigResponse(BaseModel):
    """Current configuration (API keys masked)."""
    settings: Dict[str, Any]


class SearchResult(BaseModel):
    """Search result item."""
    type: str
    id: int
    title: str
    snippet: Optional[str] = None
    platform: Optional[str] = None


class SearchResults(BaseModel):
    """Full-text search results."""
    results: List[SearchResult]
    total: int


class PlatformHealth(BaseModel):
    """Per-platform health info."""
    platform: str
    last_crawl: Optional[str] = None
    status: Optional[str] = None
    articles_found: int = 0


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = "ok"
    db_status: str = "ok"
    platforms: List[PlatformHealth] = []
    total_articles: int = 0
    total_demands: int = 0
    db_size_mb: float = 0.0


# ===========================================================================
# Articles
# ===========================================================================

@router.get("/api/articles", response_model=PaginatedArticles)
def list_articles(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    platform: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    sort_by: str = Query("crawl_time", pattern="^(crawl_time|heat_score|publish_time|title)$"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
):
    """List articles with pagination, filtering, and sorting."""
    with get_session() as session:
        stmt = select(Article)

        if platform:
            stmt = stmt.where(Article.platform == platform)
        if date_from:
            stmt = stmt.where(Article.crawl_time >= datetime.fromisoformat(date_from))
        if date_to:
            stmt = stmt.where(Article.crawl_time <= datetime.fromisoformat(date_to))

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = session.execute(count_stmt).scalar() or 0

        col = getattr(Article, sort_by, Article.crawl_time)
        order = col.desc() if sort_order == "desc" else col.asc()
        stmt = stmt.order_by(order).offset((page - 1) * page_size).limit(page_size)

        articles = session.execute(stmt).scalars().all()
        return PaginatedArticles(
            items=[ArticleResponse.model_validate(a) for a in articles],
            total=total,
        )


@router.get("/api/articles/stats", response_model=ArticleStats)
def article_stats():
    """Get article statistics: counts by platform, by date, analysis progress."""
    with get_session() as session:
        total = session.scalar(select(func.count()).select_from(Article)) or 0
        analyzed = session.scalar(
            select(func.count()).select_from(Article).where(Article.is_analyzed.is_(True))
        ) or 0

        platform_rows = session.execute(
            select(Article.platform, func.count())
            .group_by(Article.platform)
        ).all()
        by_platform = {row[0]: row[1] for row in platform_rows}

        date_rows = session.execute(
            select(func.date(Article.crawl_time), func.count())
            .group_by(func.date(Article.crawl_time))
            .order_by(func.date(Article.crawl_time).desc())
            .limit(30)
        ).all()
        by_date = {str(row[0]): row[1] for row in date_rows if row[0]}

        return ArticleStats(
            total=total,
            by_platform=by_platform,
            by_date=by_date,
            analyzed=analyzed,
            unanalyzed=total - analyzed,
        )


@router.get("/api/articles/{article_id}", response_model=ArticleDetail)
def get_article(article_id: int):
    """Get article detail with related demands."""
    with get_session() as session:
        article = session.get(Article, article_id)
        if not article:
            raise HTTPException(status_code=404, detail="Article not found")

        relations = session.execute(
            select(ArticleDemandRelation).where(
                ArticleDemandRelation.article_id == article_id
            )
        ).scalars().all()
        demand_ids = [r.demand_id for r in relations]
        demands = []
        if demand_ids:
            demands = session.execute(
                select(Demand).where(Demand.id.in_(demand_ids))
            ).scalars().all()

        detail = ArticleDetail.model_validate(article)
        detail.demands = [DemandResponse.model_validate(d) for d in demands]
        return detail


# ===========================================================================
# Demands
# ===========================================================================

@router.get("/api/demands", response_model=PaginatedDemands)
def list_demands(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: Optional[str] = None,
    status: Optional[str] = None,
    trend: Optional[str] = None,
    q: Optional[str] = None,
    sort_by: str = Query("importance_score", pattern="^(importance_score|frequency|first_seen|last_seen|title)$"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
):
    """List demands with pagination, filtering, search, and sorting."""
    with get_session() as session:
        stmt = select(Demand)

        if category:
            stmt = stmt.where(Demand.category == category)
        if status:
            stmt = stmt.where(Demand.status == status)
        if trend:
            stmt = stmt.where(Demand.trend == trend)
        if q:
            pattern = f"%{q}%"
            stmt = stmt.where(
                or_(Demand.title.ilike(pattern), Demand.description.ilike(pattern))
            )

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = session.execute(count_stmt).scalar() or 0

        col = getattr(Demand, sort_by, Demand.importance_score)
        order = col.desc() if sort_order == "desc" else col.asc()
        stmt = stmt.order_by(order).offset((page - 1) * page_size).limit(page_size)

        demands = session.execute(stmt).scalars().all()
        return PaginatedDemands(
            items=[DemandResponse.model_validate(d) for d in demands],
            total=total,
        )


@router.get("/api/demands/categories", response_model=List[CategoryCount])
def demand_categories():
    """List all demand categories with counts."""
    with get_session() as session:
        rows = session.execute(
            select(Demand.category, func.count())
            .where(Demand.category.isnot(None))
            .group_by(Demand.category)
            .order_by(func.count().desc())
        ).all()
        return [CategoryCount(name=row[0], count=row[1]) for row in rows]


@router.get("/api/demands/tags", response_model=List[TagCount])
def demand_tags():
    """Get all tags with counts for word cloud."""
    with get_session() as session:
        demands = session.execute(
            select(Demand.tags).where(Demand.tags.isnot(None))
        ).scalars().all()

    tag_counts: Dict[str, int] = {}
    for tags_str in demands:
        try:
            tags = json.loads(tags_str)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(tags, list):
            for tag in tags:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1

    return [TagCount(tag=t, count=c) for t, c in sorted(tag_counts.items(), key=lambda x: -x[1])]


@router.get("/api/demands/trending", response_model=List[DemandResponse])
def trending_demands():
    """Get demands with trend='rising', sorted by frequency."""
    with get_session() as session:
        demands = session.execute(
            select(Demand)
            .where(Demand.trend == "rising")
            .order_by(Demand.frequency.desc())
        ).scalars().all()
        return [DemandResponse.model_validate(d) for d in demands]


@router.get("/api/demands/{demand_id}", response_model=DemandDetail)
def get_demand(demand_id: int):
    """Get demand detail with related articles and related demands."""
    with get_session() as session:
        demand = session.get(Demand, demand_id)
        if not demand:
            raise HTTPException(status_code=404, detail="Demand not found")

        # Related articles
        relations = session.execute(
            select(ArticleDemandRelation).where(
                ArticleDemandRelation.demand_id == demand_id
            )
        ).scalars().all()
        article_ids = [r.article_id for r in relations]
        articles = []
        if article_ids:
            articles = session.execute(
                select(Article).where(Article.id.in_(article_ids))
            ).scalars().all()

        # Related demands via demand_relations
        rel_stmt = select(DemandRelation).where(
            or_(
                DemandRelation.demand_id_a == demand_id,
                DemandRelation.demand_id_b == demand_id,
            )
        )
        demand_rels = session.execute(rel_stmt).scalars().all()
        related_ids = set()
        for r in demand_rels:
            related_ids.add(r.demand_id_b if r.demand_id_a == demand_id else r.demand_id_a)
        related_demands = []
        if related_ids:
            related_demands = session.execute(
                select(Demand).where(Demand.id.in_(related_ids))
            ).scalars().all()

        detail = DemandDetail.model_validate(demand)
        detail.related_articles = [ArticleResponse.model_validate(a) for a in articles]
        detail.related_demands = [DemandResponse.model_validate(d) for d in related_demands]
        return detail


@router.put("/api/demands/{demand_id}", response_model=DemandResponse)
def update_demand(demand_id: int, body: DemandUpdate):
    """Update demand fields (category, status, notes, tags)."""
    with get_session() as session:
        demand = session.get(Demand, demand_id)
        if not demand:
            raise HTTPException(status_code=404, detail="Demand not found")

        update_data = body.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if value is not None:
                setattr(demand, field, value)

        session.flush()
        session.refresh(demand)
        return DemandResponse.model_validate(demand)


@router.put("/api/demands/{demand_id}/status", response_model=DemandResponse)
def change_demand_status(demand_id: int, body: StatusUpdate):
    """Change demand status only."""
    with get_session() as session:
        demand = session.get(Demand, demand_id)
        if not demand:
            raise HTTPException(status_code=404, detail="Demand not found")

        demand.status = body.status
        session.flush()
        session.refresh(demand)
        return DemandResponse.model_validate(demand)


@router.put("/api/demands/{demand_id}/annotate", response_model=DemandResponse)
def annotate_demand(demand_id: int, body: AnnotationRequest):
    """User annotation: confirm, reject, or merge a demand."""
    with get_session() as session:
        demand = session.get(Demand, demand_id)
        if not demand:
            raise HTTPException(status_code=404, detail="Demand not found")

        if body.action == "confirm":
            demand.status = "confirmed"
            if body.notes:
                demand.notes = body.notes
        elif body.action == "reject":
            demand.status = "rejected"
            if body.notes:
                demand.notes = body.notes
        elif body.action == "merge":
            if not body.target_demand_id:
                raise HTTPException(
                    status_code=400, detail="target_demand_id required for merge"
                )
            target = session.get(Demand, body.target_demand_id)
            if not target:
                raise HTTPException(status_code=404, detail="Target demand not found")

            # Transfer article relations to target
            rels = session.execute(
                select(ArticleDemandRelation).where(
                    ArticleDemandRelation.demand_id == demand_id
                )
            ).scalars().all()
            for rel in rels:
                existing = session.execute(
                    select(ArticleDemandRelation).where(
                        ArticleDemandRelation.article_id == rel.article_id,
                        ArticleDemandRelation.demand_id == body.target_demand_id,
                    )
                ).scalar_one_or_none()
                if not existing:
                    rel.demand_id = body.target_demand_id
                else:
                    session.delete(rel)

            target.frequency = target.frequency + demand.frequency
            demand.status = "merged"
            demand.notes = f"Merged into demand #{body.target_demand_id}"
            if body.notes:
                demand.notes += f" — {body.notes}"
        else:
            raise HTTPException(
                status_code=400, detail="action must be confirm, reject, or merge"
            )

        session.flush()
        session.refresh(demand)
        return DemandResponse.model_validate(demand)


# ===========================================================================
# Analytics
# ===========================================================================

@router.get("/api/analytics/overview", response_model=OverviewData)
def analytics_overview():
    """Dashboard data: totals, week new demands, analysis rate, distributions."""
    with get_session() as session:
        total_articles = session.scalar(select(func.count()).select_from(Article)) or 0
        total_demands = session.scalar(select(func.count()).select_from(Demand)) or 0
        analyzed = session.scalar(
            select(func.count()).select_from(Article).where(Article.is_analyzed.is_(True))
        ) or 0

        week_ago = datetime.utcnow() - timedelta(days=7)
        week_new = session.scalar(
            select(func.count()).select_from(Demand).where(Demand.first_seen >= week_ago)
        ) or 0

        analysis_rate = (analyzed / total_articles * 100) if total_articles else 0.0

        cat_rows = session.execute(
            select(Demand.category, func.count())
            .where(Demand.category.isnot(None))
            .group_by(Demand.category)
            .order_by(func.count().desc())
        ).all()
        category_distribution = [
            CategoryCount(name=r[0], count=r[1]) for r in cat_rows
        ]

        recent = session.execute(
            select(Demand).order_by(Demand.first_seen.desc()).limit(10)
        ).scalars().all()

        trending = session.execute(
            select(Demand)
            .where(Demand.trend == "rising")
            .order_by(Demand.frequency.desc())
            .limit(10)
        ).scalars().all()

        return OverviewData(
            total_articles=total_articles,
            total_demands=total_demands,
            week_new_demands=week_new,
            analysis_rate=round(analysis_rate, 1),
            category_distribution=category_distribution,
            recent_demands=[DemandResponse.model_validate(d) for d in recent],
            trending_demands=[DemandResponse.model_validate(d) for d in trending],
        )


@router.get("/api/analytics/trends", response_model=TrendChartData)
def analytics_trends():
    """Trend chart data: last 12 weeks of snapshots grouped by demand."""
    with get_session() as session:
        cutoff = datetime.utcnow() - timedelta(weeks=12)
        snapshots = session.execute(
            select(TrendSnapshot)
            .where(TrendSnapshot.snapshot_date >= cutoff.date())
            .order_by(TrendSnapshot.snapshot_date.asc())
        ).scalars().all()

        # Group by demand_id
        groups: Dict[int, list] = {}
        for s in snapshots:
            groups.setdefault(s.demand_id, []).append(s)

        demand_ids = list(groups.keys())
        demands_map: Dict[int, Demand] = {}
        if demand_ids:
            rows = session.execute(
                select(Demand).where(Demand.id.in_(demand_ids))
            ).scalars().all()
            demands_map = {d.id: d for d in rows}

        series = []
        for did, snaps in groups.items():
            demand = demands_map.get(did)
            series.append(TrendSeries(
                demand_id=did,
                title=demand.title if demand else f"Demand #{did}",
                data=[
                    TrendPoint(
                        date=s.snapshot_date.isoformat(),
                        frequency=s.frequency,
                        heat_score=s.heat_score,
                    )
                    for s in snaps
                ],
            ))

        return TrendChartData(series=series)


@router.get("/api/analytics/category-dist", response_model=List[CategoryDistItem])
def category_distribution():
    """Category distribution with name, count, and percentage."""
    with get_session() as session:
        total = session.scalar(select(func.count()).select_from(Demand)) or 0
        rows = session.execute(
            select(Demand.category, func.count())
            .where(Demand.category.isnot(None))
            .group_by(Demand.category)
            .order_by(func.count().desc())
        ).all()

        return [
            CategoryDistItem(
                name=row[0],
                count=row[1],
                percentage=round(row[1] / total * 100, 1) if total else 0.0,
            )
            for row in rows
        ]


@router.get("/api/analytics/weekly-report", response_model=WeeklyReport)
def weekly_report():
    """Get the latest markdown weekly report."""
    settings = get_settings()
    export_dir = settings.get("export", {}).get("output_dir", "./data/exports")
    export_path = os.path.join(export_dir, "")

    # Find the most recent weekly report file
    from pathlib import Path
    reports = sorted(Path(export_dir).glob("weekly_report_*.md"), reverse=True)
    if not reports:
        return WeeklyReport(content="No weekly report available yet.", generated_at="")

    content = reports[0].read_text(encoding="utf-8")
    return WeeklyReport(
        content=content,
        generated_at=reports[0].stat().st_mtime.__str__(),
    )


@router.get("/api/analytics/demand-graph", response_model=DemandGraph)
def demand_graph():
    """Demand relation graph data (nodes + edges) for vis.js."""
    with get_session() as session:
        relations = session.execute(select(DemandRelation)).scalars().all()

        demand_ids = set()
        for r in relations:
            demand_ids.add(r.demand_id_a)
            demand_ids.add(r.demand_id_b)

        demands_map: Dict[int, Demand] = {}
        if demand_ids:
            rows = session.execute(
                select(Demand).where(Demand.id.in_(demand_ids))
            ).scalars().all()
            demands_map = {d.id: d for d in rows}

        nodes = [
            GraphNode(
                id=d.id,
                label=d.title,
                category=d.category,
                frequency=d.frequency,
            )
            for d in demands_map.values()
        ]
        edges = [
            GraphEdge(**{"from": r.demand_id_a, "to": r.demand_id_b, "similarity": r.similarity_score})
            for r in relations
        ]
        return DemandGraph(nodes=nodes, edges=edges)


# ===========================================================================
# Operations
# ===========================================================================

@router.post("/api/crawl/trigger", response_model=TriggerResponse)
def trigger_crawl(platform: Optional[str] = None):
    """Trigger a crawl job in a background thread."""
    def _run_crawl():
        try:
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
            from src.utils.config import get_platform_config as gpc

            registry: dict[str, type] = {
                "kr36": Kr36Scraper, "huxiu": HuxiuScraper,
                "zhihu": ZhihuScraper, "juejin": JuejinScraper,
                "toutiao": ToutiaoScraper, "douban": DoubanScraper,
                "xiaohongshu": XiaohongshuScraper, "bilibili": BilibiliScraper,
                "weixin_sogou": WeixinSogouScraper, "maimai": MaimaiScraper,
                "baidu_baijiahao": BaiduBaijiahaoScraper, "rss_generic": RssGenericScraper,
            }

            platforms = [platform] if platform else [
                n for n in registry if gpc(n).get("enabled", False)
            ]
            for name in platforms:
                cls = registry.get(name)
                if cls:
                    cls().run()
            logger.info("Background crawl completed for: %s", platforms)
        except Exception:
            logger.exception("Background crawl failed")

    threading.Thread(target=_run_crawl, daemon=True).start()
    msg = f"Crawl triggered for {'all platforms' if not platform else platform}"
    return TriggerResponse(message=msg)


@router.post("/api/analyze/trigger", response_model=TriggerResponse)
def trigger_analyze():
    """Trigger AI analysis in a background thread."""
    def _run_analyze():
        try:
            from src.analyzer.extractor import DemandExtractor
            extractor = DemandExtractor()
            processed = extractor.analyze_batch()
            logger.info("Background analysis completed: %d articles", processed)
        except Exception:
            logger.exception("Background analysis failed")

    threading.Thread(target=_run_analyze, daemon=True).start()
    return TriggerResponse(message="Analysis triggered")


@router.get("/api/crawl/logs", response_model=PaginatedCrawlLogs)
def crawl_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """List crawl logs with pagination."""
    with get_session() as session:
        total = session.scalar(select(func.count()).select_from(CrawlLog)) or 0
        logs = session.execute(
            select(CrawlLog)
            .order_by(CrawlLog.start_time.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).scalars().all()
        return PaginatedCrawlLogs(
            items=[CrawlLogResponse.model_validate(lg) for lg in logs],
            total=total,
        )


@router.post("/api/export/{fmt}", response_model=ExportResponse)
def trigger_export(fmt: str):
    """Trigger export (excel/csv/markdown) and return file download URL."""
    from src.exporter import ExcelExporter, CsvExporter, MarkdownExporter

    exporters = {
        "excel": ExcelExporter,
        "csv": CsvExporter,
        "markdown": MarkdownExporter,
    }
    cls = exporters.get(fmt)
    if not cls:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {fmt}")

    exporter = cls()
    file_path = exporter.export()
    return ExportResponse(
        format=fmt,
        file_path=file_path,
        download_url=f"/api/export/download?path={file_path}",
    )


@router.get("/api/config", response_model=ConfigResponse)
def get_config():
    """Get current settings with API keys masked."""
    settings = get_settings()
    raw = dict(settings.settings)

    def _mask(d: dict) -> dict:
        masked = {}
        for k, v in d.items():
            if isinstance(v, dict):
                masked[k] = _mask(v)
            elif isinstance(v, str) and any(s in k.lower() for s in ("key", "secret", "token", "password")):
                masked[k] = "***" if v else ""
            else:
                masked[k] = v
        return masked

    return ConfigResponse(settings=_mask(raw))


@router.put("/api/config", response_model=ConfigResponse)
def update_config(body: Dict[str, Any]):
    """Update settings and write to yaml."""
    import yaml
    settings = get_settings()
    root = settings._root
    config_path = root / "config" / "settings.yaml"

    current = dict(settings.settings)
    current.update(body)

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(current, f, allow_unicode=True, default_flow_style=False)

    # Reload
    from src.utils.config import Settings
    Settings.reset()

    return get_config()


# ===========================================================================
# Search
# ===========================================================================

@router.get("/api/search", response_model=SearchResults)
def search(q: str = Query(..., min_length=1)):
    """Full text search across articles and demands."""
    pattern = f"%{q}%"
    results: List[SearchResult] = []

    with get_session() as session:
        articles = session.execute(
            select(Article).where(
                or_(Article.title.ilike(pattern), Article.content.ilike(pattern))
            ).limit(50)
        ).scalars().all()
        for a in articles:
            snippet = a.summary or (a.content[:200] if a.content else None)
            results.append(SearchResult(
                type="article", id=a.id, title=a.title,
                snippet=snippet, platform=a.platform,
            ))

        demands = session.execute(
            select(Demand).where(
                or_(Demand.title.ilike(pattern), Demand.description.ilike(pattern))
            ).limit(50)
        ).scalars().all()
        for d in demands:
            results.append(SearchResult(
                type="demand", id=d.id, title=d.title,
                snippet=d.description,
            ))

    return SearchResults(results=results, total=len(results))


# ===========================================================================
# Health
# ===========================================================================

@router.get("/health", response_model=HealthResponse)
def health_check():
    """Health check: DB status, per-platform last crawl info, system stats."""
    db_status = "ok"
    total_articles = 0
    total_demands = 0
    platforms: List[PlatformHealth] = []

    try:
        with get_session() as session:
            total_articles = session.scalar(select(func.count()).select_from(Article)) or 0
            total_demands = session.scalar(select(func.count()).select_from(Demand)) or 0

            # Last crawl per platform
            subq = (
                select(
                    CrawlLog.platform,
                    func.max(CrawlLog.start_time).label("last_crawl"),
                )
                .group_by(CrawlLog.platform)
                .subquery()
            )
            rows = session.execute(
                select(CrawlLog)
                .join(subq, (CrawlLog.platform == subq.c.platform) & (CrawlLog.start_time == subq.c.last_crawl))
            ).scalars().all()
            for log in rows:
                platforms.append(PlatformHealth(
                    platform=log.platform,
                    last_crawl=log.start_time.isoformat() if log.start_time else None,
                    status=log.status,
                    articles_found=log.articles_found,
                ))
    except Exception:
        logger.exception("Health check DB error")
        db_status = "error"

    # DB file size
    db_size_mb = 0.0
    settings = get_settings()
    data_dir = settings.get("app", {}).get("data_dir", "./data")
    db_file = os.path.join(data_dir, "workplace_demand.db")
    if os.path.exists(db_file):
        db_size_mb = round(os.path.getsize(db_file) / (1024 * 1024), 2)

    return HealthResponse(
        status="ok" if db_status == "ok" else "degraded",
        db_status=db_status,
        platforms=platforms,
        total_articles=total_articles,
        total_demands=total_demands,
        db_size_mb=db_size_mb,
    )
