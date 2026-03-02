"""
Database management module for the workplace demand library.

Provides engine/session factories, table initialisation, and common query helpers
for articles, demands and crawl logs.
"""

from contextlib import contextmanager
from datetime import datetime
from typing import Any, Generator, Optional

from sqlalchemy import create_engine, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .models import (
    Article,
    ArticleCreate,
    Base,
    CrawlLog,
    CrawlLogCreate,
    Demand,
    DemandCreate,
)

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_engine: Optional[Engine] = None
_SessionFactory: Optional[sessionmaker[Session]] = None


# ---------------------------------------------------------------------------
# Engine / Session helpers
# ---------------------------------------------------------------------------

def _default_db_path() -> str:
    """Derive the default database path from config or fall back to ``./data/workplace_demand.db``."""
    try:
        from src.utils.config import get_settings
        settings = get_settings()
        data_dir = settings.get("app", {}).get("data_dir", "./data")
    except Exception:
        data_dir = "./data"
    import os
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "workplace_demand.db")


def get_engine(db_path: Optional[str] = None) -> Engine:
    """Create (or return the cached) SQLAlchemy engine for a SQLite database.

    Args:
        db_path: Path to the SQLite database file.  When *None*, the path is
                 read from ``config/settings.yaml`` (``app.data_dir``) or
                 defaults to ``./data/workplace_demand.db``.

    Returns:
        A SQLAlchemy ``Engine`` instance.
    """
    global _engine
    if _engine is None:
        if db_path is None:
            db_path = _default_db_path()
        url = f"sqlite:///{db_path}"
        _engine = create_engine(url, echo=False, future=True)
    return _engine


@contextmanager
def get_session(engine: Optional[Engine] = None) -> Generator[Session, None, None]:
    """Provide a transactional database session as a context manager.

    Usage::

        with get_session() as session:
            session.add(obj)

    Args:
        engine: An optional engine; uses the module-level engine when *None*.

    Yields:
        A SQLAlchemy ``Session`` that is committed on clean exit and
        rolled back on exception.
    """
    global _SessionFactory
    eng = engine or get_engine()
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=eng, expire_on_commit=False)

    session = _SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db(db_path: Optional[str] = None) -> Engine:
    """Initialise the database: create engine and all tables.

    Args:
        db_path: Path to the SQLite database file.  When *None*, the path is
                 resolved from config (same as ``get_engine``).

    Returns:
        The SQLAlchemy ``Engine`` used for the database.
    """
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)
    return engine


# ---------------------------------------------------------------------------
# Query helpers — Articles
# ---------------------------------------------------------------------------

def get_article_by_platform_id(
    platform: str,
    platform_id: str,
    engine: Optional[Engine] = None,
) -> Optional[Article]:
    """Look up an article by its platform-specific identifier (for dedup).

    Args:
        platform: Platform name (e.g. ``"zhihu"``).
        platform_id: The platform-specific article ID.
        engine: Optional engine override.

    Returns:
        The matching ``Article`` or *None*.
    """
    with get_session(engine) as session:
        stmt = select(Article).where(
            Article.platform == platform,
            Article.platform_id == platform_id,
        )
        return session.execute(stmt).scalar_one_or_none()


def save_article(
    article_data: dict[str, Any],
    engine: Optional[Engine] = None,
) -> Article:
    """Insert a new article or update an existing one (upsert by platform + platform_id).

    Args:
        article_data: Dictionary of article fields (matching ``ArticleCreate``).
        engine: Optional engine override.

    Returns:
        The persisted ``Article`` instance.
    """
    validated = ArticleCreate(**article_data)

    with get_session(engine) as session:
        existing: Optional[Article] = None
        if validated.platform_id:
            stmt = select(Article).where(
                Article.platform == validated.platform,
                Article.platform_id == validated.platform_id,
            )
            existing = session.execute(stmt).scalar_one_or_none()

        if existing is not None:
            for field, value in validated.model_dump(exclude_unset=True).items():
                setattr(existing, field, value)
            article = existing
        else:
            article = Article(**validated.model_dump())
            session.add(article)

        session.flush()
        session.refresh(article)
        return article


def get_unanalyzed_articles(
    limit: int = 50,
    engine: Optional[Engine] = None,
) -> list[Article]:
    """Fetch articles that have not been analyzed yet (for AI batch processing).

    Args:
        limit: Maximum number of articles to return.
        engine: Optional engine override.

    Returns:
        A list of ``Article`` instances with ``is_analyzed == False``.
    """
    with get_session(engine) as session:
        stmt = (
            select(Article)
            .where(Article.is_analyzed == False)  # noqa: E712
            .order_by(Article.crawl_time.desc())
            .limit(limit)
        )
        return list(session.execute(stmt).scalars().all())


# ---------------------------------------------------------------------------
# Query helpers — Demands
# ---------------------------------------------------------------------------

def save_demand(
    demand_data: dict[str, Any],
    engine: Optional[Engine] = None,
) -> Demand:
    """Insert a new demand record.

    Args:
        demand_data: Dictionary of demand fields (matching ``DemandCreate``).
        engine: Optional engine override.

    Returns:
        The persisted ``Demand`` instance.
    """
    validated = DemandCreate(**demand_data)

    with get_session(engine) as session:
        demand = Demand(**validated.model_dump())
        session.add(demand)
        session.flush()
        session.refresh(demand)
        return demand


def get_demands(
    filters: Optional[dict[str, Any]] = None,
    page: int = 1,
    page_size: int = 20,
    engine: Optional[Engine] = None,
) -> list[Demand]:
    """Query demands with optional filtering and pagination.

    Supported filter keys: ``category``, ``subcategory``, ``status``,
    ``trend``, ``min_frequency``, ``min_importance``.

    Args:
        filters: Optional dictionary of filter parameters.
        page: 1-based page number.
        page_size: Number of results per page.
        engine: Optional engine override.

    Returns:
        A list of ``Demand`` instances matching the criteria.
    """
    filters = filters or {}

    with get_session(engine) as session:
        stmt = select(Demand)

        if "category" in filters:
            stmt = stmt.where(Demand.category == filters["category"])
        if "subcategory" in filters:
            stmt = stmt.where(Demand.subcategory == filters["subcategory"])
        if "status" in filters:
            stmt = stmt.where(Demand.status == filters["status"])
        if "trend" in filters:
            stmt = stmt.where(Demand.trend == filters["trend"])
        if "min_frequency" in filters:
            stmt = stmt.where(Demand.frequency >= filters["min_frequency"])
        if "min_importance" in filters:
            stmt = stmt.where(Demand.importance_score >= filters["min_importance"])

        stmt = (
            stmt.order_by(Demand.importance_score.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(session.execute(stmt).scalars().all())


# ---------------------------------------------------------------------------
# Query helpers — Crawl Logs
# ---------------------------------------------------------------------------

def save_crawl_log(
    log_data: dict[str, Any],
    engine: Optional[Engine] = None,
) -> CrawlLog:
    """Record a crawl run result.

    Args:
        log_data: Dictionary of crawl log fields (matching ``CrawlLogCreate``).
        engine: Optional engine override.

    Returns:
        The persisted ``CrawlLog`` instance.
    """
    validated = CrawlLogCreate(**log_data)

    with get_session(engine) as session:
        log = CrawlLog(**validated.model_dump())
        session.add(log)
        session.flush()
        session.refresh(log)
        return log
