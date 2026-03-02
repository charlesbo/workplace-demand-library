"""Notion exporter — syncs workplace demands to a Notion database."""

import json
import os
import time
from typing import Any

import requests

from src.storage.database import get_session
from src.storage.models import Demand
from src.utils.config import get_settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
RATE_LIMIT_WAIT = 1.0  # seconds between requests to stay under Notion limits


class NotionExporter:
    """Sync workplace demands to a Notion database via the Notion API v1."""

    def __init__(self) -> None:
        self.token = os.environ.get("NOTION_TOKEN", "")
        if not self.token:
            raise EnvironmentError(
                "NOTION_TOKEN environment variable is not set. "
                "Please set it to your Notion integration token."
            )

        settings = get_settings()
        self.database_id: str = settings.get("export.notion_database_id", "")
        if not self.database_id:
            raise ValueError(
                "Notion database_id is not configured. "
                "Set 'export.notion_database_id' in settings.yaml."
            )

        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Notion-Version": NOTION_VERSION,
        }

    def export(self) -> int:
        """Sync all demands to the Notion database.

        Creates new pages for demands not yet present and updates existing
        ones.  Matching is done by demand title.

        Returns:
            The number of demands synced (created + updated).
        """
        demands = self._load_demands()
        existing = self._fetch_existing_pages()

        synced = 0
        for d in demands:
            props = self._build_properties(d)
            page_id = existing.get(d.title)

            if page_id:
                self._update_page(page_id, props)
            else:
                self._create_page(props)

            synced += 1
            time.sleep(RATE_LIMIT_WAIT)

        logger.info(f"Notion sync complete: {synced} demands synced")
        return synced

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    @staticmethod
    def _load_demands() -> list[Demand]:
        """Load all demands from the database."""
        with get_session() as session:
            demands = (
                session.query(Demand).order_by(Demand.frequency.desc()).all()
            )
            session.expunge_all()
        return demands

    # ------------------------------------------------------------------
    # Notion API helpers
    # ------------------------------------------------------------------

    def _fetch_existing_pages(self) -> dict[str, str]:
        """Fetch all pages in the Notion database, returning {title: page_id}.

        Handles Notion pagination (max 100 results per request).
        """
        pages: dict[str, str] = {}
        url = f"{NOTION_API}/databases/{self.database_id}/query"
        has_more = True
        start_cursor: str | None = None

        while has_more:
            payload: dict[str, Any] = {"page_size": 100}
            if start_cursor:
                payload["start_cursor"] = start_cursor

            resp = requests.post(url, headers=self.headers, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            for page in data.get("results", []):
                title_prop = (
                    page.get("properties", {}).get("Title", {}).get("title", [])
                )
                if title_prop:
                    title_text = title_prop[0].get("plain_text", "")
                    if title_text:
                        pages[title_text] = page["id"]

            has_more = data.get("has_more", False)
            start_cursor = data.get("next_cursor")

        return pages

    def _create_page(self, properties: dict[str, Any]) -> None:
        """Create a new page in the Notion database."""
        url = f"{NOTION_API}/pages"
        payload = {
            "parent": {"database_id": self.database_id},
            "properties": properties,
        }
        resp = requests.post(url, headers=self.headers, json=payload, timeout=30)
        resp.raise_for_status()

    def _update_page(self, page_id: str, properties: dict[str, Any]) -> None:
        """Update an existing Notion page."""
        url = f"{NOTION_API}/pages/{page_id}"
        resp = requests.patch(
            url, headers=self.headers, json={"properties": properties}, timeout=30
        )
        resp.raise_for_status()

    # ------------------------------------------------------------------
    # Property mapping
    # ------------------------------------------------------------------

    @staticmethod
    def _build_properties(d: Demand) -> dict[str, Any]:
        """Map a Demand to Notion database properties."""
        tags: list[str] = []
        if d.tags:
            try:
                tags = json.loads(d.tags)
            except (json.JSONDecodeError, TypeError):
                tags = [t.strip() for t in d.tags.split(",") if t.strip()]

        return {
            "Title": {
                "title": [{"text": {"content": d.title}}],
            },
            "Category": {
                "select": {"name": d.category or "未分类"},
            },
            "Frequency": {
                "number": d.frequency,
            },
            "Importance": {
                "number": round(d.importance_score, 2),
            },
            "Trend": {
                "select": {"name": d.trend},
            },
            "Status": {
                "select": {"name": d.status},
            },
            "Tags": {
                "multi_select": [{"name": t} for t in tags],
            },
        }
