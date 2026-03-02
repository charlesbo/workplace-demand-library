"""
SQLAlchemy ORM models and Pydantic schemas for the workplace demand library.

Defines 7 tables: articles, demands, article_demand_relations, hot_comments,
crawl_logs, trend_snapshots, demand_relations.
"""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    ForeignKey,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


# ===========================================================================
# ORM Models
# ===========================================================================

class Article(Base):
    """Crawled articles from various platforms."""

    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    platform_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    publish_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    crawl_time: Mapped[Optional[datetime]] = mapped_column(DateTime, default=func.now())
    heat_score: Mapped[float] = mapped_column(Float, default=0)
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    comment_count: Mapped[int] = mapped_column(Integer, default=0)
    share_count: Mapped[int] = mapped_column(Integer, default=0)
    is_analyzed: Mapped[bool] = mapped_column(Boolean, default=False)
    raw_html: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    language: Mapped[str] = mapped_column(String(10), default="zh")

    # Relationships
    demand_relations: Mapped[list["ArticleDemandRelation"]] = relationship(
        back_populates="article", cascade="all, delete-orphan"
    )
    hot_comments: Mapped[list["HotComment"]] = relationship(
        back_populates="article", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("platform", "platform_id", name="uq_articles_platform_pid"),
        Index("idx_articles_platform", "platform"),
        Index("idx_articles_crawl_time", "crawl_time"),
        Index("idx_articles_heat", heat_score.desc()),
    )


class Demand(Base):
    """AI-extracted workplace demands."""

    __tablename__ = "demands"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    subcategory: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    tags: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON array
    frequency: Mapped[int] = mapped_column(Integer, default=1)
    importance_score: Mapped[float] = mapped_column(Float, default=0)
    trend: Mapped[str] = mapped_column(String(20), default="stable")
    first_seen: Mapped[Optional[datetime]] = mapped_column(DateTime, default=func.now())
    last_seen: Mapped[Optional[datetime]] = mapped_column(DateTime, default=func.now())
    status: Mapped[str] = mapped_column(String(20), default="new")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    semantic_vector: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    language: Mapped[str] = mapped_column(String(10), default="zh")

    # Relationships
    article_relations: Mapped[list["ArticleDemandRelation"]] = relationship(
        back_populates="demand", cascade="all, delete-orphan"
    )
    trend_snapshots: Mapped[list["TrendSnapshot"]] = relationship(
        back_populates="demand", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_demands_category", "category"),
        Index("idx_demands_frequency", frequency.desc()),
        Index("idx_demands_trend", "trend"),
    )


class ArticleDemandRelation(Base):
    """Many-to-many relationship between articles and demands."""

    __tablename__ = "article_demand_relations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    article_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("articles.id", ondelete="CASCADE"), nullable=False
    )
    demand_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("demands.id", ondelete="CASCADE"), nullable=False
    )
    relevance_score: Mapped[float] = mapped_column(Float, default=0)
    context_snippet: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    article: Mapped["Article"] = relationship(back_populates="demand_relations")
    demand: Mapped["Demand"] = relationship(back_populates="article_relations")

    __table_args__ = (
        UniqueConstraint("article_id", "demand_id", name="uq_article_demand"),
    )


class HotComment(Base):
    """High-liked comments from articles."""

    __tablename__ = "hot_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    article_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("articles.id", ondelete="CASCADE"), nullable=False
    )
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    commenter: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    crawl_time: Mapped[Optional[datetime]] = mapped_column(DateTime, default=func.now())
    is_analyzed: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relationships
    article: Mapped["Article"] = relationship(back_populates="hot_comments")


class CrawlLog(Base):
    """Scraping / crawl run logs."""

    __tablename__ = "crawl_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    articles_found: Mapped[int] = mapped_column(Integer, default=0)
    articles_new: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_position: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON


class TrendSnapshot(Base):
    """Weekly demand trend snapshots."""

    __tablename__ = "trend_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    demand_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("demands.id", ondelete="CASCADE"), nullable=False
    )
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    frequency: Mapped[int] = mapped_column(Integer, default=0)
    heat_score: Mapped[float] = mapped_column(Float, default=0)

    # Relationships
    demand: Mapped["Demand"] = relationship(back_populates="trend_snapshots")


class DemandRelation(Base):
    """Demand knowledge-graph edges (similarity between two demands)."""

    __tablename__ = "demand_relations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    demand_id_a: Mapped[int] = mapped_column(
        Integer, ForeignKey("demands.id", ondelete="CASCADE"), nullable=False
    )
    demand_id_b: Mapped[int] = mapped_column(
        Integer, ForeignKey("demands.id", ondelete="CASCADE"), nullable=False
    )
    similarity_score: Mapped[float] = mapped_column(Float, default=0)

    __table_args__ = (
        UniqueConstraint("demand_id_a", "demand_id_b", name="uq_demand_pair"),
    )


# ===========================================================================
# Pydantic Schemas
# ===========================================================================

# ---- Article ----

class ArticleBase(BaseModel):
    """Base schema for article data."""
    platform: str
    platform_id: Optional[str] = None
    title: str
    author: Optional[str] = None
    url: str
    content: Optional[str] = None
    summary: Optional[str] = None
    publish_time: Optional[datetime] = None
    heat_score: float = 0
    view_count: int = 0
    like_count: int = 0
    comment_count: int = 0
    share_count: int = 0
    raw_html: Optional[str] = None
    language: str = "zh"


class ArticleCreate(ArticleBase):
    """Schema for creating a new article."""
    pass


class ArticleResponse(ArticleBase):
    """Schema for article API responses."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    crawl_time: Optional[datetime] = None
    is_analyzed: bool = False


# ---- Demand ----

class DemandBase(BaseModel):
    """Base schema for demand data."""
    title: str
    description: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    tags: Optional[str] = None
    frequency: int = 1
    importance_score: float = 0
    trend: str = "stable"
    status: str = "new"
    notes: Optional[str] = None
    semantic_vector: Optional[str] = None
    language: str = "zh"


class DemandCreate(DemandBase):
    """Schema for creating a new demand."""
    pass


class DemandResponse(DemandBase):
    """Schema for demand API responses."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None


# ---- ArticleDemandRelation ----

class ArticleDemandRelationBase(BaseModel):
    """Base schema for article-demand relation."""
    article_id: int
    demand_id: int
    relevance_score: float = 0
    context_snippet: Optional[str] = None


class ArticleDemandRelationCreate(ArticleDemandRelationBase):
    """Schema for creating a new article-demand relation."""
    pass


class ArticleDemandRelationResponse(ArticleDemandRelationBase):
    """Schema for article-demand relation API responses."""
    model_config = ConfigDict(from_attributes=True)

    id: int


# ---- HotComment ----

class HotCommentBase(BaseModel):
    """Base schema for hot comment data."""
    article_id: int
    platform: str
    commenter: Optional[str] = None
    content: str
    like_count: int = 0


class HotCommentCreate(HotCommentBase):
    """Schema for creating a new hot comment."""
    pass


class HotCommentResponse(HotCommentBase):
    """Schema for hot comment API responses."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    crawl_time: Optional[datetime] = None
    is_analyzed: bool = False


# ---- CrawlLog ----

class CrawlLogBase(BaseModel):
    """Base schema for crawl log data."""
    platform: str
    start_time: datetime
    end_time: Optional[datetime] = None
    status: Optional[str] = None
    articles_found: int = 0
    articles_new: int = 0
    error_message: Optional[str] = None
    last_position: Optional[str] = None


class CrawlLogCreate(CrawlLogBase):
    """Schema for creating a new crawl log."""
    pass


class CrawlLogResponse(CrawlLogBase):
    """Schema for crawl log API responses."""
    model_config = ConfigDict(from_attributes=True)

    id: int


# ---- TrendSnapshot ----

class TrendSnapshotBase(BaseModel):
    """Base schema for trend snapshot data."""
    demand_id: int
    snapshot_date: date
    frequency: int = 0
    heat_score: float = 0


class TrendSnapshotCreate(TrendSnapshotBase):
    """Schema for creating a new trend snapshot."""
    pass


class TrendSnapshotResponse(TrendSnapshotBase):
    """Schema for trend snapshot API responses."""
    model_config = ConfigDict(from_attributes=True)

    id: int


# ---- DemandRelation ----

class DemandRelationBase(BaseModel):
    """Base schema for demand relation (knowledge graph edge)."""
    demand_id_a: int
    demand_id_b: int
    similarity_score: float = 0


class DemandRelationCreate(DemandRelationBase):
    """Schema for creating a new demand relation."""
    pass


class DemandRelationResponse(DemandRelationBase):
    """Schema for demand relation API responses."""
    model_config = ConfigDict(from_attributes=True)

    id: int
