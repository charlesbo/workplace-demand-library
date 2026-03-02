"""
小红书 (Xiaohongshu / RED) scraper.

Strategy: API-based note search and detail fetching.

.. warning::

   Xiaohongshu has **very strict** anti-crawl mechanisms.  This scraper is
   **disabled by default** in ``platforms.yaml``.  For production use consider
   a Playwright-based renderer or an officially sanctioned data channel.

.. todo::

   Add Playwright integration for JS-rendered pages when the API endpoints
   are blocked or return incomplete data.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, List, Optional

from src.scrapers.base import BaseScraper


class XiaohongshuScraper(BaseScraper):
    """Scraper for 小红书 notes (short-form UGC content).

    Notes on Xiaohongshu are typically short, so the ``run()`` pipeline
    collects multiple notes per keyword for later aggregation / analysis.
    """

    # API endpoints
    _SEARCH_API = "https://edith.xiaohongshu.com/api/sns/web/v1/search/notes"
    _NOTE_DETAIL_API = "https://edith.xiaohongshu.com/api/sns/web/v1/feed"
    _COMMENT_API = "https://edith.xiaohongshu.com/api/sns/web/v2/comment/page"

    # Pagination defaults
    _PAGE_SIZE = 20
    _MAX_PAGES = 3  # per keyword, keep volume manageable

    def __init__(self) -> None:
        super().__init__("xiaohongshu")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_keywords(self) -> List[str]:
        """Return workplace-related search keywords from global settings.

        Returns:
            Combined list of primary and secondary keywords.
        """
        kw_cfg: Dict[str, Any] = self.settings.get("keywords", {})
        primary: List[str] = kw_cfg.get("primary", [])
        secondary: List[str] = kw_cfg.get("secondary", [])
        return primary + secondary

    def _build_note_url(self, note_id: str) -> str:
        """Build the canonical web URL for a note.

        Args:
            note_id: Xiaohongshu note identifier.

        Returns:
            Full URL string.
        """
        return f"https://www.xiaohongshu.com/explore/{note_id}"

    def _generate_platform_id(self, note_id: str) -> str:
        """Derive a stable platform-scoped identifier.

        Args:
            note_id: Raw note id from the API.

        Returns:
            Prefixed identifier string.
        """
        return f"xhs_{note_id}"

    # ------------------------------------------------------------------
    # Abstract method implementations
    # ------------------------------------------------------------------

    def get_hot_articles_list(self) -> List[Dict]:
        """Search for workplace-related notes across all configured keywords.

        Iterates over keywords from global settings, paginates through
        the search API, and returns a flat list of note metadata dicts.

        Returns:
            A list of article-metadata dicts ready for detail fetching.
        """
        articles: List[Dict] = []
        seen_ids: set[str] = set()
        keywords = self._get_keywords()

        for keyword in keywords:
            self.logger.info(f"Searching xiaohongshu for keyword: {keyword}")

            for page in range(1, self._MAX_PAGES + 1):
                if self.should_stop():
                    break

                self.rate_limiter.wait(self.platform_name)

                params: Dict[str, Any] = {
                    "keyword": keyword,
                    "page": page,
                    "page_size": self._PAGE_SIZE,
                    "sort": "general",
                    "note_type": 0,  # 0 = all types
                }

                try:
                    resp = self.http.get(self._SEARCH_API, params=params)
                    if resp is None:
                        self.logger.warning(
                            f"Empty response for keyword='{keyword}' page={page}"
                        )
                        self._record_failure()
                        break

                    data = resp.json() if hasattr(resp, "json") else {}
                    items: List[Dict] = (
                        data.get("data", {}).get("items", [])
                    )

                    if not items:
                        self.logger.debug(
                            f"No more results for keyword='{keyword}' at page={page}"
                        )
                        break

                    for item in items:
                        note_card: Dict = item.get("note_card", {})
                        note_id: str = item.get("id", "")

                        if not note_id or note_id in seen_ids:
                            continue
                        seen_ids.add(note_id)

                        interact_info: Dict = note_card.get(
                            "interact_info", {}
                        )
                        user_info: Dict = note_card.get("user", {})

                        articles.append(
                            {
                                "platform": self.platform_name,
                                "platform_id": self._generate_platform_id(
                                    note_id
                                ),
                                "title": note_card.get("display_title", ""),
                                "url": self._build_note_url(note_id),
                                "author": user_info.get("nickname", ""),
                                "view_count": int(
                                    interact_info.get("view_count", 0)
                                ),
                                "like_count": int(
                                    interact_info.get("liked_count", 0)
                                ),
                                "comment_count": int(
                                    interact_info.get("comment_count", 0)
                                ),
                                "share_count": int(
                                    interact_info.get("collected_count", 0)
                                ),
                                "publish_time": note_card.get("time", ""),
                            }
                        )

                except Exception as exc:
                    self.logger.error(
                        f"Failed to search keyword='{keyword}' page={page}: {exc}"
                    )
                    self._record_failure()
                    break

        self.logger.info(
            f"Collected {len(articles)} xiaohongshu notes across "
            f"{len(keywords)} keywords"
        )
        return articles

    def get_article_detail(self, url: str) -> Dict:
        """Fetch full content for a single xiaohongshu note.

        Args:
            url: Canonical note URL
                 (e.g. ``https://www.xiaohongshu.com/explore/<id>``).

        Returns:
            A dict with ``content``, ``raw_html``, and ``summary`` keys,
            or an empty dict on failure.
        """
        # Extract note_id from URL path
        note_id = url.rstrip("/").split("/")[-1]
        if not note_id:
            self.logger.warning(f"Cannot extract note_id from URL: {url}")
            return {}

        try:
            # TODO: Switch to Playwright rendering when API is blocked.
            #       The feed endpoint often requires valid cookies / X-s
            #       signatures that are hard to reproduce programmatically.
            params: Dict[str, Any] = {
                "source_note_id": note_id,
                "image_formats": "jpg,webp",
            }

            resp = self.http.get(self._NOTE_DETAIL_API, params=params)
            if resp is None:
                self.logger.warning(f"Empty response for note detail: {url}")
                return {}

            data = resp.json() if hasattr(resp, "json") else {}
            items: List[Dict] = data.get("data", {}).get("items", [])

            if not items:
                self.logger.warning(f"No detail items returned for: {url}")
                return {}

            note_card: Dict = items[0].get("note_card", {})
            content: str = note_card.get("desc", "")
            title: str = note_card.get("title", "")
            raw_html: str = note_card.get("desc", "")

            # For short notes, the title + content together serve as the body
            full_text = f"{title}\n\n{content}" if title else content
            # Truncate as a simple summary (notes are usually short)
            summary = full_text[:200] + "..." if len(full_text) > 200 else full_text

            return {
                "content": full_text,
                "raw_html": raw_html,
                "summary": summary,
            }

        except Exception as exc:
            self.logger.error(f"Failed to fetch note detail {url}: {exc}")
            return {}

    def get_hot_comments(self, url: str) -> List[Dict]:
        """Fetch top comments for a xiaohongshu note.

        Args:
            url: Canonical note URL.

        Returns:
            A list of comment dicts with ``commenter``, ``content``,
            and ``like_count`` keys.
        """
        note_id = url.rstrip("/").split("/")[-1]
        if not note_id:
            return []

        try:
            params: Dict[str, Any] = {
                "note_id": note_id,
                "cursor": "",
                "top_comment_id": "",
                "image_formats": "jpg,webp",
            }

            resp = self.http.get(self._COMMENT_API, params=params)
            if resp is None:
                return []

            data = resp.json() if hasattr(resp, "json") else {}
            comments_raw: List[Dict] = data.get("data", {}).get("comments", [])

            comments: List[Dict] = []
            for c in comments_raw:
                user_info: Dict = c.get("user_info", {})
                comments.append(
                    {
                        "commenter": user_info.get("nickname", ""),
                        "content": c.get("content", ""),
                        "like_count": int(c.get("like_count", 0)),
                    }
                )

            self.logger.debug(
                f"Fetched {len(comments)} comments for note {note_id}"
            )
            return comments

        except Exception as exc:
            self.logger.error(
                f"Failed to fetch comments for note {note_id}: {exc}"
            )
            return []
