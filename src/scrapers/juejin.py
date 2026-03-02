"""Juejin (掘金) scraper — fetches career-growth articles via JSON API.

All data is obtained through Juejin's public REST API; no HTML parsing is
needed.  Article bodies are returned as Markdown by the API and converted to
plain text for storage.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.scrapers.base import BaseScraper
from src.utils.text_cleaner import clean_text

# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

_RECOMMEND_FEED_URL = "https://api.juejin.cn/recommend_api/v1/article/recommend_all_feed"
_ARTICLE_DETAIL_URL = "https://api.juejin.cn/content_api/v1/article/detail"
_COMMENT_LIST_URL = "https://api.juejin.cn/interact_api/v1/comment/list"

# Category / tag IDs used by Juejin for career-related content
_CAREER_CATEGORY_ID = "6809637769959178254"  # 代码人生 (Code Life / Career)


class JuejinScraper(BaseScraper):
    """Scraper for Juejin (掘金).

    Fetches recommended articles in the career-growth category and retrieves
    full article details (Markdown content, metrics) via the content API.
    """

    def __init__(self) -> None:
        super().__init__("juejin")
        self._categories: List[str] = self.config.get("categories", ["career"])

    # ------------------------------------------------------------------
    # Header helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _api_headers() -> Dict[str, str]:
        """Return headers expected by Juejin's API."""
        return {
            "Referer": "https://juejin.cn/",
            "Origin": "https://juejin.cn",
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
        }

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def get_hot_articles_list(self) -> List[Dict]:
        """Fetch recommended articles from Juejin's career-growth feed.

        Returns:
            A list of article dicts with standard keys (``platform``,
            ``platform_id``, ``title``, ``url``, etc.).
        """
        articles: List[Dict] = []

        payload = {
            "id_type": 2,
            "sort_type": 200,  # hot / recommended
            "cate_id": _CAREER_CATEGORY_ID,
            "cursor": "0",
            "limit": 30,
        }

        try:
            resp = self.http.post(
                _RECOMMEND_FEED_URL,
                json=payload,
                headers=self._api_headers(),
            )
            data = resp.json()
        except Exception as exc:
            self.logger.error(f"Recommend feed request failed: {exc}")
            return articles

        for item in data.get("data", []):
            article_info = item.get("article_info", {})
            article_id = article_info.get("article_id", "")
            if not article_id:
                continue

            author_info = item.get("author_user_info", {})
            counters = item.get("article_info", {})

            articles.append(
                self._build_article_dict(
                    platform_id=article_id,
                    title=article_info.get("title", ""),
                    url=f"https://juejin.cn/post/{article_id}",
                    author=author_info.get("user_name", ""),
                    view_count=int(counters.get("view_count", 0)),
                    like_count=int(counters.get("digg_count", 0)),
                    comment_count=int(counters.get("comment_count", 0)),
                    share_count=int(counters.get("collect_count", 0)),
                    publish_time=self._parse_ctime(article_info.get("ctime")),
                )
            )

        self.logger.info(f"Fetched {len(articles)} articles from recommend feed")
        return articles

    def get_article_detail(self, url: str) -> Dict:
        """Fetch full article content from Juejin's content API.

        Extracts Markdown body, converts to plain text, and returns updated
        metrics.

        Args:
            url: A Juejin article URL (e.g. ``https://juejin.cn/post/123``).

        Returns:
            A dict with ``content``, ``raw_html``, and ``summary`` keys
            (plus updated metric fields).
        """
        article_id = self._extract_article_id(url)
        if not article_id:
            self.logger.warning(f"Cannot parse Juejin article ID from URL: {url}")
            return {}

        try:
            resp = self.http.post(
                _ARTICLE_DETAIL_URL,
                json={"article_id": article_id},
                headers=self._api_headers(),
            )
            data = resp.json()
        except Exception as exc:
            self.logger.error(f"Article detail request failed for {url}: {exc}")
            return {}

        article_info = data.get("data", {}).get("article_info", {})
        markdown_body = article_info.get("mark_content", "")
        content = self._markdown_to_text(markdown_body)
        brief = article_info.get("brief_content", "")

        return {
            "content": content,
            "raw_html": markdown_body,
            "summary": brief or content[:200],
            "view_count": int(article_info.get("view_count", 0)),
            "like_count": int(article_info.get("digg_count", 0)),
            "comment_count": int(article_info.get("comment_count", 0)),
            "share_count": int(article_info.get("collect_count", 0)),
        }

    def get_hot_comments(self, url: str) -> List[Dict]:
        """Fetch hot comments for a Juejin article.

        Args:
            url: A Juejin article URL.

        Returns:
            A list of comment dicts with ``commenter``, ``content``, and
            ``like_count`` keys.
        """
        article_id = self._extract_article_id(url)
        if not article_id:
            return []

        try:
            resp = self.http.post(
                _COMMENT_LIST_URL,
                json={
                    "item_id": article_id,
                    "item_type": 2,
                    "cursor": "0",
                    "limit": 20,
                    "sort": 0,  # hot
                },
                headers=self._api_headers(),
            )
            data = resp.json()
        except Exception as exc:
            self.logger.error(f"Comment request failed for {url}: {exc}")
            return []

        comments: List[Dict] = []
        for item in data.get("data", []):
            comment_info = item.get("comment_info", {})
            user_info = item.get("user_info", {})
            comments.append({
                "commenter": user_info.get("user_name", "匿名用户"),
                "content": comment_info.get("comment_content", ""),
                "like_count": int(comment_info.get("digg_count", 0)),
            })

        return comments

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_article_dict(
        *,
        platform_id: str,
        title: str,
        url: str,
        author: str = "",
        view_count: int = 0,
        like_count: int = 0,
        comment_count: int = 0,
        share_count: int = 0,
        publish_time: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Construct a standardised article dict."""
        return {
            "platform": "juejin",
            "platform_id": platform_id,
            "title": title,
            "url": url,
            "author": author,
            "view_count": view_count,
            "like_count": like_count,
            "comment_count": comment_count,
            "share_count": share_count,
            "publish_time": publish_time,
        }

    @staticmethod
    def _extract_article_id(url: str) -> Optional[str]:
        """Extract the numeric article ID from a Juejin URL."""
        m = re.search(r"/post/(\d+)", url)
        return m.group(1) if m else None

    @staticmethod
    def _parse_ctime(ctime: Any) -> Optional[str]:
        """Convert a UNIX-seconds string to ISO-8601, or return ``None``."""
        if not ctime:
            return None
        try:
            return datetime.fromtimestamp(int(ctime), tz=timezone.utc).isoformat()
        except (ValueError, TypeError, OSError):
            return None

    @staticmethod
    def _markdown_to_text(md: str) -> str:
        """Perform a basic Markdown-to-plain-text conversion.

        Strips common Markdown syntax (headings, links, images, emphasis,
        code fences) and collapses whitespace.  The result is suitable for
        full-text indexing and AI summarisation.
        """
        if not md:
            return ""
        text = md
        # Remove code fences
        text = re.sub(r"```[\s\S]*?```", "", text)
        # Remove inline code
        text = re.sub(r"`[^`]+`", "", text)
        # Remove images
        text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
        # Convert links to text
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        # Remove headings markers
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
        # Remove emphasis
        text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)
        text = re.sub(r"_{1,3}([^_]+)_{1,3}", r"\1", text)
        # Remove blockquote markers
        text = re.sub(r"^>\s?", "", text, flags=re.MULTILINE)
        # Remove horizontal rules
        text = re.sub(r"^[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)
        # Collapse whitespace
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
