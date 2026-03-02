"""
Scraper for 36氪 (36Kr) — a leading Chinese tech and business media platform.

Fetches hot/trending articles and workplace-related content via 36Kr's
gateway API and HTML article pages.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

from src.scrapers.base import BaseScraper


class Kr36Scraper(BaseScraper):
    """Scraper implementation for the 36Kr platform.

    Uses 36Kr's gateway API to fetch hot article rankings and keyword-based
    search results, then parses individual article pages with BeautifulSoup
    to extract full content and metadata.
    """

    # 36Kr API endpoints
    _HOT_RANK_URL = "https://gateway.36kr.com/api/mis/nav/home/nav/rank/hot"
    _SEARCH_URL = "https://gateway.36kr.com/api/mis/nav/search/home"
    _ARTICLE_BASE_URL = "https://www.36kr.com/p/"

    # Common headers for 36Kr API requests
    _API_HEADERS: Dict[str, str] = {
        "Content-Type": "application/json",
        "Referer": "https://www.36kr.com/",
        "Origin": "https://www.36kr.com",
    }

    def __init__(self) -> None:
        """Initialise the 36Kr scraper with platform-specific configuration."""
        super().__init__("kr36")

    # ------------------------------------------------------------------
    # Keyword helpers
    # ------------------------------------------------------------------

    def get_keywords(self) -> List[str]:
        """Return workplace-related keywords from global settings.

        Merges ``primary`` and ``secondary`` keyword lists defined in
        ``settings.yaml`` under the ``keywords`` section.

        Returns:
            Combined list of keyword strings.
        """
        kw_config = self.settings.get("keywords", {})
        primary: List[str] = kw_config.get("primary", []) if isinstance(kw_config, dict) else []
        secondary: List[str] = kw_config.get("secondary", []) if isinstance(kw_config, dict) else []
        return primary + secondary

    # ------------------------------------------------------------------
    # Content filtering
    # ------------------------------------------------------------------

    def _is_workplace_related(self, title: str, summary: str = "") -> bool:
        """Check whether an article is workplace-related by keyword matching.

        Args:
            title: Article title.
            summary: Article summary or description (optional).

        Returns:
            ``True`` if any keyword appears in the title or summary.
        """
        text = f"{title} {summary}".lower()
        return any(kw.lower() in text for kw in self.get_keywords())

    # ------------------------------------------------------------------
    # Public API — required by BaseScraper
    # ------------------------------------------------------------------

    def get_hot_articles_list(self) -> List[Dict]:
        """Fetch hot and workplace-related articles from 36Kr.

        Combines results from the hot-ranking API endpoint with keyword-based
        search results.  Duplicates (by ``platform_id``) are removed and only
        articles matching workplace keywords are returned.

        Returns:
            A deduplicated list of article metadata dicts.
        """
        articles: List[Dict] = []
        seen_ids: set[str] = set()

        # 1. Hot ranking articles
        hot_articles = self._fetch_hot_rank()
        for article in hot_articles:
            pid = article.get("platform_id", "")
            if pid and pid not in seen_ids:
                seen_ids.add(pid)
                articles.append(article)

        # 2. Keyword search
        for keyword in self.get_keywords():
            try:
                search_results = self._search_articles(keyword)
                for article in search_results:
                    pid = article.get("platform_id", "")
                    if pid and pid not in seen_ids:
                        seen_ids.add(pid)
                        articles.append(article)
            except Exception as exc:
                self.logger.warning(f"Search failed for keyword '{keyword}': {exc}")

        self.logger.info(f"Collected {len(articles)} articles from 36Kr")
        return articles

    def get_article_detail(self, url: str) -> Dict:
        """Fetch and parse full article content from a 36Kr article page.

        Args:
            url: The article URL (e.g. ``https://www.36kr.com/p/123456``).

        Returns:
            A dict with ``content``, ``raw_html``, and ``summary`` keys.
            Returns an empty dict on failure.
        """
        try:
            resp = self.http.get(url, headers={"Referer": "https://www.36kr.com/"})
            html = resp.text
            soup = BeautifulSoup(html, "html.parser")

            # Try to extract article content from the page
            content = ""
            raw_html = ""
            summary = ""

            # 36Kr embeds article data in a script tag as JSON
            article_data = self._extract_script_data(soup)
            if article_data:
                content = article_data.get("content", "")
                summary = article_data.get("summary", "")
                raw_html = content

            # Fallback: parse from DOM
            if not content:
                content_div = soup.select_one(
                    "div.article-content, div.articleDetailContent, "
                    "div.common-width.content"
                )
                if content_div:
                    raw_html = str(content_div)
                    content = content_div.get_text(separator="\n", strip=True)

            # Extract summary from meta if still empty
            if not summary:
                meta_desc = soup.find("meta", attrs={"name": "description"})
                if meta_desc and meta_desc.get("content"):
                    summary = meta_desc["content"]

            return {
                "content": content,
                "raw_html": raw_html,
                "summary": summary,
            }

        except Exception as exc:
            self.logger.error(f"Failed to fetch article detail from {url}: {exc}")
            return {}

    def get_hot_comments(self, url: str) -> List[Dict]:
        """Fetch hot comments for a 36Kr article.

        Extracts the article ID from the URL and queries the 36Kr comments
        API endpoint.

        Args:
            url: The article URL.

        Returns:
            A list of comment dicts with ``commenter``, ``content``, and
            ``like_count`` keys.
        """
        comments: List[Dict] = []
        article_id = self._extract_article_id(url)
        if not article_id:
            return comments

        try:
            comments_url = (
                f"https://gateway.36kr.com/api/mis/nav/comment/list"
            )
            payload = {
                "param": {
                    "entityId": article_id,
                    "entityType": 1,
                    "pageSize": 20,
                    "pageNo": 1,
                    "order": "hot",
                },
                "partner_id": "wap",
                "timestamp": int(datetime.now().timestamp() * 1000),
            }
            resp = self.http.post(
                comments_url,
                json=payload,
                headers=self._API_HEADERS,
            )
            data = resp.json()

            items = (
                data.get("data", {})
                .get("data", {})
                .get("commentList", [])
            )
            for item in items:
                comments.append({
                    "commenter": item.get("authorName", item.get("author", {}).get("name", "")),
                    "content": item.get("content", ""),
                    "like_count": int(item.get("likeCount", 0)),
                })
        except Exception as exc:
            self.logger.warning(f"Failed to fetch comments for {url}: {exc}")

        return comments

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_hot_rank(self) -> List[Dict]:
        """Fetch the hot-ranking article list from the 36Kr API.

        Returns:
            A list of normalised article metadata dicts.
        """
        articles: List[Dict] = []
        try:
            payload = {
                "partner_id": "wap",
                "param": {
                    "siteId": 1,
                    "platformId": 2,
                },
                "timestamp": int(datetime.now().timestamp() * 1000),
            }
            resp = self.http.post(
                self._HOT_RANK_URL,
                json=payload,
                headers=self._API_HEADERS,
            )
            data = resp.json()

            items = data.get("data", {}).get("hotRankList", [])
            if not items:
                # Alternative response structure
                items = data.get("data", {}).get("data", {}).get("hotRankList", [])

            for item in items:
                article = self._normalize_article(item)
                if article and self._is_workplace_related(
                    article.get("title", ""),
                    article.get("summary", ""),
                ):
                    articles.append(article)

        except Exception as exc:
            self.logger.error(f"Failed to fetch 36Kr hot rank: {exc}")

        self.logger.debug(f"Hot rank returned {len(articles)} workplace-related articles")
        return articles

    def _search_articles(self, keyword: str, page: int = 1) -> List[Dict]:
        """Search 36Kr articles by keyword via the gateway API.

        Args:
            keyword: The search term.
            page: Page number for pagination (1-based).

        Returns:
            A list of normalised article metadata dicts.
        """
        articles: List[Dict] = []
        try:
            payload = {
                "partner_id": "wap",
                "param": {
                    "searchWord": keyword,
                    "pageSize": 20,
                    "pageEvent": 0 if page == 1 else 1,
                    "pageNo": page,
                    "siteId": 1,
                    "platformId": 2,
                },
                "timestamp": int(datetime.now().timestamp() * 1000),
            }
            resp = self.http.post(
                self._SEARCH_URL,
                json=payload,
                headers=self._API_HEADERS,
            )
            data = resp.json()

            items = data.get("data", {}).get("itemList", [])
            if not items:
                items = data.get("data", {}).get("data", {}).get("itemList", [])

            for item in items:
                # Search results may nest article data inside "templateMaterial"
                material = item.get("templateMaterial", item)
                article = self._normalize_article(material)
                if article:
                    articles.append(article)

        except Exception as exc:
            self.logger.error(f"36Kr search failed for '{keyword}': {exc}")

        return articles

    def _normalize_article(self, raw: Dict[str, Any]) -> Optional[Dict]:
        """Convert a raw 36Kr API item into a standardised article dict.

        Args:
            raw: A single item dict from the 36Kr API response.

        Returns:
            A normalised article dict, or ``None`` if essential data is missing.
        """
        # Article ID may appear at different nesting levels
        article_id = str(
            raw.get("itemId")
            or raw.get("id")
            or raw.get("articleId")
            or ""
        )
        title = raw.get("title") or raw.get("widgetTitle", "")
        if not article_id or not title:
            return None

        url = raw.get("url") or f"{self._ARTICLE_BASE_URL}{article_id}"
        # Ensure absolute URL
        if url and not url.startswith("http"):
            url = f"https://www.36kr.com{url}" if url.startswith("/") else f"{self._ARTICLE_BASE_URL}{article_id}"

        # Parse publish time
        publish_time = None
        raw_time = raw.get("publishTime") or raw.get("publicTime") or raw.get("formatDate")
        if raw_time:
            try:
                if isinstance(raw_time, (int, float)):
                    publish_time = datetime.fromtimestamp(raw_time / 1000).strftime("%Y-%m-%d %H:%M:%S")
                else:
                    publish_time = str(raw_time)
            except (ValueError, OSError):
                publish_time = str(raw_time)

        return {
            "platform": "kr36",
            "platform_id": article_id,
            "title": title.strip(),
            "url": url,
            "author": raw.get("authorName") or raw.get("author", {}).get("name", "") if isinstance(raw.get("author"), dict) else str(raw.get("author", "")),
            "view_count": int(raw.get("viewCount", 0) or 0),
            "like_count": int(raw.get("likeCount", 0) or 0),
            "comment_count": int(raw.get("commentCount", 0) or 0),
            "share_count": int(raw.get("shareCount", 0) or 0),
            "publish_time": publish_time,
            "summary": raw.get("summary", ""),
        }

    def _extract_script_data(self, soup: BeautifulSoup) -> Optional[Dict]:
        """Extract article data from embedded ``<script>`` JSON in the page.

        36Kr server-renders article data inside a ``<script>`` tag containing
        ``window.initialState`` or similar global state objects.

        Args:
            soup: Parsed BeautifulSoup document.

        Returns:
            A dict with ``content`` and ``summary`` keys, or ``None``.
        """
        try:
            for script in soup.find_all("script"):
                text = script.string or ""
                if "initialState" not in text and "props" not in text:
                    continue

                # Try to find JSON within the script
                match = re.search(
                    r'(?:window\.__initialState__|window\.initialState)\s*=\s*(\{.+?\});?\s*(?:</script>|$)',
                    text,
                    re.DOTALL,
                )
                if not match:
                    match = re.search(r'("articleDetail":\{.+?\})', text, re.DOTALL)
                if match:
                    try:
                        raw = json.loads(match.group(1))
                    except json.JSONDecodeError:
                        raw = json.loads("{" + match.group(1) + "}")
                    # Navigate to article detail
                    detail = (
                        raw.get("articleDetail", {})
                        .get("articleDetailData", {})
                        .get("data", raw.get("articleDetail", {}))
                    )
                    if detail:
                        return {
                            "content": detail.get("widgetContent", detail.get("content", "")),
                            "summary": detail.get("summary", ""),
                        }
        except Exception as exc:
            self.logger.debug(f"Script data extraction failed: {exc}")

        return None

    @staticmethod
    def _extract_article_id(url: str) -> Optional[str]:
        """Extract the numeric article ID from a 36Kr URL.

        Args:
            url: A 36Kr article URL (e.g. ``https://www.36kr.com/p/123456``).

        Returns:
            The article ID string, or ``None`` if not found.
        """
        match = re.search(r"/p/(\d+)", url)
        return match.group(1) if match else None
