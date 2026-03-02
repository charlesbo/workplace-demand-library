"""Shared pytest fixtures for the workplace demand library test suite."""

import os
import tempfile
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.storage.models import Article, Base, CrawlLog, Demand


@pytest.fixture()
def tmp_db(tmp_path):
    """Create a temporary SQLite database with all tables and return the engine."""
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture()
def db_session(tmp_db):
    """Provide a transactional SQLAlchemy session bound to the temp DB."""
    Session = sessionmaker(bind=tmp_db, expire_on_commit=False)
    session = Session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@pytest.fixture()
def sample_articles(db_session):
    """Insert sample articles into the test database and return them."""
    articles = [
        Article(
            platform="kr36",
            platform_id="kr36_001",
            title="职场沟通技巧：如何高效汇报工作",
            author="张三",
            url="https://36kr.com/p/001",
            content="本文介绍了职场中高效沟通和汇报工作的技巧...",
            heat_score=75.0,
            view_count=10000,
            like_count=500,
            comment_count=100,
            share_count=50,
            is_analyzed=False,
        ),
        Article(
            platform="huxiu",
            platform_id="huxiu_002",
            title="跳槽季来临：程序员如何准备面试",
            author="李四",
            url="https://huxiu.com/article/002",
            content="金三银四跳槽季，程序员面试准备指南...",
            heat_score=88.5,
            view_count=50000,
            like_count=2000,
            comment_count=300,
            share_count=150,
            is_analyzed=True,
        ),
        Article(
            platform="juejin",
            platform_id="juejin_003",
            title="35岁程序员的职业规划",
            author="王五",
            url="https://juejin.cn/post/003",
            content="35岁是程序员职业生涯的重要转折点...",
            heat_score=92.0,
            view_count=80000,
            like_count=5000,
            comment_count=800,
            share_count=300,
            is_analyzed=False,
        ),
    ]
    for a in articles:
        db_session.add(a)
    db_session.flush()
    return articles


@pytest.fixture()
def sample_demands(db_session):
    """Insert sample demands into the test database and return them."""
    demands = [
        Demand(
            title="职场沟通效率低下",
            description="跨部门沟通困难，信息传递不及时",
            category="沟通协作",
            subcategory="跨部门沟通",
            tags='["沟通", "协作", "效率"]',
            frequency=5,
            importance_score=8.0,
            trend="rising",
        ),
        Demand(
            title="程序员职业发展瓶颈",
            description="35岁后面临职业天花板",
            category="职业发展",
            subcategory="职业规划",
            tags='["程序员", "35岁", "职业规划"]',
            frequency=12,
            importance_score=9.0,
            trend="rising",
        ),
        Demand(
            title="面试准备不足",
            description="缺乏系统的面试准备方法和资源",
            category="求职面试",
            subcategory="面试技巧",
            tags='["面试", "求职", "技巧"]',
            frequency=8,
            importance_score=7.5,
            trend="stable",
        ),
    ]
    for d in demands:
        db_session.add(d)
    db_session.flush()
    return demands


@pytest.fixture()
def test_client(tmp_db, monkeypatch):
    """Create a FastAPI TestClient with a temporary database.

    Patches the database module so the API uses the temp DB engine/session.
    """
    import src.storage.database as db_mod

    _Session = sessionmaker(bind=tmp_db, expire_on_commit=False)

    # Patch module-level engine and session factory
    monkeypatch.setattr(db_mod, "_engine", tmp_db)
    monkeypatch.setattr(db_mod, "_SessionFactory", _Session)

    # Seed some data so endpoints return non-empty results
    session = _Session()
    session.add(
        Article(
            platform="kr36",
            platform_id="test_001",
            title="职场测试文章",
            author="测试",
            url="https://example.com/1",
            content="测试内容",
            heat_score=50.0,
            view_count=1000,
            like_count=100,
            comment_count=10,
            share_count=5,
            is_analyzed=True,
        )
    )
    session.add(
        Demand(
            title="测试职场需求",
            description="用于测试的需求",
            category="职业发展",
            subcategory="职业规划",
            tags='["测试"]',
            frequency=1,
            importance_score=5.0,
        )
    )
    session.add(
        CrawlLog(
            platform="kr36",
            start_time=datetime.now(),
            status="completed",
            articles_found=10,
            articles_new=5,
        )
    )
    session.commit()
    session.close()

    from fastapi.testclient import TestClient
    from src.api.server import app

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
