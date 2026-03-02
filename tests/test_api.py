"""Tests for FastAPI API endpoints using TestClient."""

import pytest


class TestHealthEndpoint:
    def test_health_endpoint(self, test_client):
        """GET /health returns 200 with status 'ok'."""
        resp = test_client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"


class TestArticlesEndpoint:
    def test_articles_list(self, test_client):
        """GET /api/articles returns a paginated list."""
        resp = test_client.get("/api/articles")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert isinstance(data["items"], list)


class TestDemandsEndpoints:
    def test_demands_list(self, test_client):
        """GET /api/demands returns a paginated list."""
        resp = test_client.get("/api/demands")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert isinstance(data["items"], list)

    def test_demands_categories(self, test_client):
        """GET /api/demands/categories returns category counts."""
        resp = test_client.get("/api/demands/categories")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)


class TestAnalyticsEndpoint:
    def test_analytics_overview(self, test_client):
        """GET /api/analytics/overview returns dashboard data."""
        resp = test_client.get("/api/analytics/overview")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_articles" in data
        assert "total_demands" in data


class TestSearchEndpoint:
    def test_search(self, test_client):
        """GET /api/search?q=职场 returns search results."""
        resp = test_client.get("/api/search", params={"q": "职场"})
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert "total" in data


class TestCrawlLogsEndpoint:
    def test_crawl_logs(self, test_client):
        """GET /api/crawl/logs returns paginated crawl logs."""
        resp = test_client.get("/api/crawl/logs")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert isinstance(data["items"], list)
