"""
Scraper for 今日头条 (Toutiao).

Strategy: API-based search with fallback to HTML parsing.
Note: Toutiao has heavy anti-crawling measures; disabled by default in config.
"""

from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.scrapers.base import BaseScraper

# Toutiao search API endpoint
_SEARCH_API = "https://www.toutiao.com/api/search/content/"

# Toutiao article content API (by group_id / item_id)
_CONTENT_API = "https://www.toutiao.com/api/pc/feed/"


class ToutiaoScraper(BaseScraper):
    """Scraper for the Toutiao (今日头条) platform.

    Uses the Toutiao search content API to find workplace-related articles,
    with a fallback to HTML parsing when the API is unavailable.

    Config keys (``platforms.yaml`` → ``toutiao``):
        - ``enabled``: Whether this scraper is active (default ``false``).
        - ``interval``: Request interval in seconds.
        - ``use_playwright``: If ``true``, use Playwright for rendering
          (not yet implemented — API-first approach is used).
    """

    def __init__(self) -> None:
        super().__init__("toutiao")
        self._use_playwright: bool = self.config.get("use_playwright", False)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_hot_articles_list(self) -> List[Dict]:
        """Fetch workplace-related articles via keyword search.

        Iterates over configured keywords and queries the Toutiao search API
        for each one.  Falls back to HTML parsing when the API response is
        not valid JSON.

        Returns:
            A list of article dicts with standard metadata keys.
        """
        keywords = self.get_keywords()
        articles: List[Dict] = []
        seen_ids: set[str] = set()

        for keyword in keywords:
            self.logger.info(f"Searching Toutiao for keyword: {keyword}")
            try:
                items = self._search_by_keyword(keyword)
                for item in items:
                    pid = item.get("platform_id", "")
                    if pid and pid not in seen_ids:
                        seen_ids.add(pid)
                        articles.append(item)
            except Exception as exc:
                self.logger.error(
                    f"Failed to search keyword '{keyword}': {exc}"
                )
                self._record_failure()

            self.rate_limiter.wait(self.platform_name)

        self.logger.info(f"Collected {len(articles)} unique articles from Toutiao")
        return articles

    def get_article_detail(self, url: str) -> Dict:
        """Fetch full content for a single Toutiao article.

        Attempts the content API first; falls back to parsing the article
        page HTML.

        Args:
            url: The article URL.

        Returns:
            A dict with ``content``, ``raw_html``, and ``summary`` keys,
            or an empty dict on failure.
        """
        try:
            item_id = self._extract_item_id(url)
            if item_id:
                detail = self._fetch_detail_api(item_id)
                if detail:
                    return detail

            # Fallback: parse HTML page directly
            return self._fetch_detail_html(url)
        except Exception as exc:
            self.logger.error(f"Failed to get article detail for {url}: {exc}")
            return {}

    def get_hot_comments(self, url: str) -> List[Dict]:
        """Fetch top comments for a Toutiao article.

        Args:
            url: The article URL.

        Returns:
            A list of comment dicts with ``commenter``, ``content``, and
            ``like_count`` keys.
        """
        item_id = self._extract_item_id(url)
        if not item_id:
            return []

        comments_url = (
            f"https://www.toutiao.com/api/comment/list/"
            f"?group_id={item_id}&item_id={item_id}&count=20"
        )
        try:
            resp = self.http.get(comments_url)
            data = resp.json()
            if data.get("message") != "success":
                return []

            results: List[Dict] = []
            for comment in data.get("data", {}).get("comments", []):
                results.append({
                    "commenter": comment.get("user", {}).get("name", ""),
                    "content": comment.get("text", ""),
                    "like_count": int(comment.get("digg_count", 0)),
                })
            return results
        except Exception as exc:
            self.logger.debug(f"Failed to fetch comments for {url}: {exc}")
            return []

    # ------------------------------------------------------------------
    # Keyword helpers
    # ------------------------------------------------------------------

    def get_keywords(self) -> List[str]:
        """Return the combined list of primary and secondary keywords.

        Reads from ``settings.yaml`` → ``keywords``.

        Returns:
            A flat list of keyword strings.
        """
        kw_config = self.settings.get("keywords", {})
        primary = kw_config.get("primary", [])
        secondary = kw_config.get("secondary", [])
        return primary + secondary

    # ------------------------------------------------------------------
    # Private helpers — search
    # ------------------------------------------------------------------

    def _search_by_keyword(self, keyword: str) -> List[Dict]:
        """Query the Toutiao search API for a single keyword.

        Falls back to :meth:`_search_by_keyword_html` if the API returns
        a non-JSON response (e.g. anti-crawl redirect).

        Args:
            keyword: The search term.

        Returns:
            A list of article metadata dicts.
        """
        params: Dict[str, Any] = {
            "aid": "24",
            "app_name": "web_search",
            "offset": 0,
            "format": "json",
            "keyword": keyword,
            "autoload": "true",
            "count": 20,
            "cur_tab": 1,
            "from": "search_tab",
        }
        try:
            resp = self.http.get(_SEARCH_API, params=params)
            data = resp.json()
        except (ValueError, AttributeError):
            self.logger.warning(
                "Toutiao search API returned non-JSON — falling back to HTML"
            )
            return self._search_by_keyword_html(keyword)

        articles: List[Dict] = []
        for item in data.get("data", []):
            article = self._parse_search_item(item)
            if article:
                articles.append(article)
        return articles

    def _search_by_keyword_html(self, keyword: str) -> List[Dict]:
        """Fallback HTML-based search when the API is blocked.

        Args:
            keyword: The search term.

        Returns:
            A list of article metadata dicts (may be empty).
        """
        # TODO: implement Playwright-based rendering if use_playwright is True
        search_url = f"https://so.toutiao.com/search?keyword={keyword}"
        try:
            resp = self.http.get(search_url)
            html = resp.text
        except Exception as exc:
            self.logger.error(f"HTML fallback search failed: {exc}")
            return []

        articles: List[Dict] = []
        # Look for article data embedded in <script> tags
        pattern = re.compile(
            r'"article_url"\s*:\s*"(.*?)".*?'
            r'"title"\s*:\s*"(.*?)".*?'
            r'"media_name"\s*:\s*"(.*?)"',
            re.DOTALL,
        )
        for match in pattern.finditer(html):
            url_raw, title, author = match.groups()
            url_clean = url_raw.replace("\\u002F", "/").replace("\\/", "/")
            if not url_clean.startswith("http"):
                url_clean = f"https://www.toutiao.com{url_clean}"

            platform_id = self._extract_item_id(url_clean) or hashlib.md5(
                url_clean.encode()
            ).hexdigest()

            articles.append({
                "platform": "toutiao",
                "platform_id": platform_id,
                "title": title,
                "url": url_clean,
                "author": author,
                "view_count": 0,
                "like_count": 0,
                "comment_count": 0,
                "share_count": 0,
                "publish_time": None,
            })
        return articles

    def _parse_search_item(self, item: Dict) -> Optional[Dict]:
        """Convert a single search-API result item to a standard article dict.

        Args:
            item: Raw item dict from the Toutiao search response.

        Returns:
            A normalised article dict, or ``None`` if the item is unusable.
        """
        title = item.get("title", "").strip()
        article_url = item.get("article_url", "") or item.get("url", "")
        if not title or not article_url:
            return None

        if not article_url.startswith("http"):
            article_url = f"https://www.toutiao.com{article_url}"

        group_id = str(item.get("group_id", "") or item.get("item_id", ""))
        publish_ts = item.get("publish_time") or item.get("behot_time")
        publish_time: Optional[datetime] = None
        if publish_ts:
            try:
                publish_time = datetime.fromtimestamp(int(publish_ts))
            except (ValueError, OSError):
                pass

        return {
            "platform": "toutiao",
            "platform_id": group_id or hashlib.md5(
                article_url.encode()
            ).hexdigest(),
            "title": title,
            "url": article_url,
            "author": item.get("media_name", ""),
            "view_count": int(item.get("read_count", 0) or 0),
            "like_count": int(item.get("like_count", 0) or 0),
            "comment_count": int(item.get("comment_count", 0) or 0),
            "share_count": int(item.get("share_count", 0) or 0),
            "publish_time": publish_time,
        }

    # ------------------------------------------------------------------
    # Private helpers — article detail
    # ------------------------------------------------------------------

    def _fetch_detail_api(self, item_id: str) -> Optional[Dict]:
        """Fetch article content via the Toutiao content API.

        Args:
            item_id: The article / group ID.

        Returns:
            A detail dict, or ``None`` on failure.
        """
        params = {"category": "article", "utm_source": "toutiao", "id": item_id}
        try:
            resp = self.http.get(_CONTENT_API, params=params)
            data = resp.json()
        except (ValueError, AttributeError):
            return None

        article_data = data.get("data", {})
        content = article_data.get("content", "")
        if not content:
            return None

        # Strip HTML tags for a plain-text summary
        text_content = re.sub(r"<[^>]+>", "", content).strip()
        summary = text_content[:200] + "..." if len(text_content) > 200 else text_content

        return {
            "content": text_content,
            "raw_html": content,
            "summary": summary,
        }

    def _fetch_detail_html(self, url: str) -> Dict:
        """Parse article content from the HTML page as a fallback.

        Args:
            url: The article URL.

        Returns:
            A detail dict (may contain empty strings on parse failure).
        """
        # TODO: use Playwright if self._use_playwright is True
        try:
            resp = self.http.get(url)
            html = resp.text
        except Exception as exc:
            self.logger.error(f"Failed to fetch article HTML: {exc}")
            return {}

        content = ""
        raw_html = ""

        # Try extracting content from embedded SSR data
        ssr_match = re.search(
            r'articleInfo.*?"content"\s*:\s*"(.*?)"', html, re.DOTALL
        )
        if ssr_match:
            raw_html = (
                ssr_match.group(1)
                .replace("\\u003C", "<")
                .replace("\\u003E", ">")
                .replace("\\u0026", "&")
                .replace('\\"', '"')
            )
            content = re.sub(r"<[^>]+>", "", raw_html).strip()

        if not content:
            # Fallback: try <article> tag
            article_match = re.search(
                r"<article[^>]*>(.*?)</article>", html, re.DOTALL
            )
            if article_match:
                raw_html = article_match.group(1)
                content = re.sub(r"<[^>]+>", "", raw_html).strip()

        summary = content[:200] + "..." if len(content) > 200 else content
        return {
            "content": content,
            "raw_html": raw_html,
            "summary": summary,
        }

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_item_id(url: str) -> Optional[str]:
        """Extract the numeric article/group ID from a Toutiao URL.

        Args:
            url: A Toutiao article URL, e.g.
                 ``https://www.toutiao.com/article/7123456789012345678/``.

        Returns:
            The ID string, or ``None`` if extraction fails.
        """
        match = re.search(r"/(?:article|a|i|group)/(\d+)", url)
        return match.group(1) if match else None
