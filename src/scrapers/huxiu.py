"""
Scraper for 虎嗅 (Huxiu) — a prominent Chinese tech and business news platform.

Fetches hot/trending articles and workplace-related content from huxiu.com
using its web API and HTML article pages parsed with BeautifulSoup.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

from src.scrapers.base import BaseScraper


class HuxiuScraper(BaseScraper):
    """Scraper implementation for the Huxiu platform.

    Uses Huxiu's web APIs for article search and listing, and parses
    individual article pages with BeautifulSoup to extract full content.
    """

    _BASE_URL = "https://www.huxiu.com"
    _SEARCH_URL = "https://search-api.huxiu.com/api/article"
    _ARTICLE_LIST_URL = "https://www.huxiu.com/article"
    _MOMENT_URL = "https://moment-api.huxiu.com/web/moment/feed"
    _ARTICLE_URL_PREFIX = "https://www.huxiu.com/article/"

    _COMMON_HEADERS: Dict[str, str] = {
        "Referer": "https://www.huxiu.com/",
        "Origin": "https://www.huxiu.com",
    }

    def __init__(self) -> None:
        """Initialise the Huxiu scraper with platform-specific configuration."""
        super().__init__("huxiu")

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
        """Fetch hot and workplace-related articles from Huxiu.

        Combines results from the front-page hot list with keyword-based
        search results across multiple pages.  Duplicates (by ``platform_id``)
        are removed and only articles matching workplace keywords are returned.

        Returns:
            A deduplicated list of article metadata dicts.
        """
        articles: List[Dict] = []
        seen_ids: set[str] = set()

        # 1. Fetch front-page / hot articles
        hot_articles = self._fetch_hot_articles()
        for article in hot_articles:
            pid = article.get("platform_id", "")
            if pid and pid not in seen_ids:
                seen_ids.add(pid)
                articles.append(article)

        # 2. Keyword-based search with pagination
        max_pages = self.config.get("search_pages", 2)
        for keyword in self.get_keywords():
            for page in range(1, max_pages + 1):
                try:
                    results = self._search_articles(keyword, page=page)
                    if not results:
                        break
                    for article in results:
                        pid = article.get("platform_id", "")
                        if pid and pid not in seen_ids:
                            seen_ids.add(pid)
                            articles.append(article)
                except Exception as exc:
                    self.logger.warning(
                        f"Search failed for keyword '{keyword}' page {page}: {exc}"
                    )
                    break

        self.logger.info(f"Collected {len(articles)} articles from Huxiu")
        return articles

    def get_article_detail(self, url: str) -> Dict:
        """Fetch and parse full article content from a Huxiu article page.

        Args:
            url: The article URL (e.g. ``https://www.huxiu.com/article/12345.html``).

        Returns:
            A dict with ``content``, ``raw_html``, and ``summary`` keys.
            Returns an empty dict on failure.
        """
        try:
            resp = self.http.get(url, headers=self._COMMON_HEADERS)
            html = resp.text
            soup = BeautifulSoup(html, "html.parser")

            content = ""
            raw_html = ""
            summary = ""

            # Try embedded JSON data first
            script_data = self._extract_script_data(soup)
            if script_data:
                content = script_data.get("content", "")
                summary = script_data.get("summary", "")
                raw_html = content

            # Fallback: parse article body from DOM
            if not content:
                content_div = soup.select_one(
                    "div.article-content-wrap, "
                    "div.article__content, "
                    "div#article_content, "
                    "div.text-content"
                )
                if content_div:
                    raw_html = str(content_div)
                    content = content_div.get_text(separator="\n", strip=True)

            # Extract summary from meta description if still empty
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
        """Fetch hot comments for a Huxiu article.

        Extracts the article ID from the URL and queries the Huxiu comments
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
            comments_url = f"{self._BASE_URL}/api/comment/list"
            params = {
                "objectid": article_id,
                "object_type": "article",
                "page": 1,
                "per_page": 20,
                "order_by": "like_count",
            }
            resp = self.http.get(
                comments_url,
                params=params,
                headers=self._COMMON_HEADERS,
            )
            data = resp.json()

            items = data.get("data", {}).get("data", [])
            if not items and isinstance(data.get("data"), list):
                items = data["data"]

            for item in items:
                user_info = item.get("user", {}) if isinstance(item.get("user"), dict) else {}
                comments.append({
                    "commenter": (
                        item.get("username")
                        or user_info.get("username")
                        or user_info.get("nick_name", "")
                    ),
                    "content": item.get("content", ""),
                    "like_count": int(item.get("like_count", 0) or 0),
                })

        except Exception as exc:
            self.logger.warning(f"Failed to fetch comments for {url}: {exc}")

        return comments

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_hot_articles(self) -> List[Dict]:
        """Fetch hot/trending articles from the Huxiu homepage.

        Attempts to load the front page and extract article data from
        embedded JSON or DOM elements.

        Returns:
            A list of normalised, workplace-filtered article dicts.
        """
        articles: List[Dict] = []
        try:
            resp = self.http.get(self._BASE_URL, headers=self._COMMON_HEADERS)
            html = resp.text
            soup = BeautifulSoup(html, "html.parser")

            # Try to extract from embedded JSON state
            for script in soup.find_all("script"):
                text = script.string or ""
                if "__NUXT__" in text or "__INITIAL_STATE__" in text:
                    articles.extend(self._parse_embedded_articles(text))
                    break

            # Fallback: parse article cards from DOM
            if not articles:
                article_cards = soup.select(
                    "div.article-item, a.article-item, "
                    "div.recommend-article-item, div.mob-ctt"
                )
                for card in article_cards:
                    article = self._parse_article_card(card)
                    if article and self._is_workplace_related(
                        article.get("title", ""),
                        article.get("summary", ""),
                    ):
                        articles.append(article)

        except Exception as exc:
            self.logger.error(f"Failed to fetch Huxiu hot articles: {exc}")

        self.logger.debug(
            f"Hot page returned {len(articles)} workplace-related articles"
        )
        return articles

    def _search_articles(self, keyword: str, page: int = 1) -> List[Dict]:
        """Search Huxiu articles by keyword.

        Args:
            keyword: The search term.
            page: Page number for pagination (1-based).

        Returns:
            A list of normalised article metadata dicts.
        """
        articles: List[Dict] = []
        try:
            params = {
                "s": keyword,
                "sort": "",
                "page": page,
                "per_page": 20,
            }
            resp = self.http.get(
                self._SEARCH_URL,
                params=params,
                headers=self._COMMON_HEADERS,
            )
            data = resp.json()

            items = data.get("data", {}).get("datalist", [])
            if not items:
                items = data.get("data", {}).get("data", [])
            if not items and isinstance(data.get("data"), list):
                items = data["data"]

            for item in items:
                article = self._normalize_article(item)
                if article:
                    articles.append(article)

        except Exception as exc:
            self.logger.error(f"Huxiu search failed for '{keyword}': {exc}")

        return articles

    def _normalize_article(self, raw: Dict[str, Any]) -> Optional[Dict]:
        """Convert a raw Huxiu API/DOM item into a standardised article dict.

        Args:
            raw: A single item dict from the Huxiu API or page data.

        Returns:
            A normalised article dict, or ``None`` if essential data is missing.
        """
        article_id = str(
            raw.get("aid")
            or raw.get("article_id")
            or raw.get("id")
            or ""
        )
        title = raw.get("title", "").strip()
        if not article_id or not title:
            return None

        url = raw.get("url") or f"{self._ARTICLE_URL_PREFIX}{article_id}.html"
        if url and not url.startswith("http"):
            url = f"{self._BASE_URL}{url}" if url.startswith("/") else f"{self._ARTICLE_URL_PREFIX}{article_id}.html"

        # Parse publish time
        publish_time = None
        raw_time = (
            raw.get("publish_time")
            or raw.get("formatDate")
            or raw.get("dateline")
        )
        if raw_time:
            try:
                if isinstance(raw_time, (int, float)):
                    publish_time = datetime.fromtimestamp(raw_time).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                else:
                    publish_time = str(raw_time)
            except (ValueError, OSError):
                publish_time = str(raw_time)

        # Author extraction
        author = ""
        author_field = raw.get("author")
        if isinstance(author_field, dict):
            author = author_field.get("username") or author_field.get("name", "")
        elif isinstance(author_field, str):
            author = author_field
        else:
            author = raw.get("user_info", {}).get("username", "") if isinstance(raw.get("user_info"), dict) else ""

        return {
            "platform": "huxiu",
            "platform_id": article_id,
            "title": title,
            "url": url,
            "author": author,
            "view_count": int(raw.get("view_count", 0) or 0),
            "like_count": int(raw.get("like_count", 0) or 0),
            "comment_count": int(raw.get("comment_count", 0) or 0),
            "share_count": int(raw.get("share_count", 0) or 0),
            "publish_time": publish_time,
            "summary": raw.get("summary", raw.get("description", "")),
        }

    def _parse_embedded_articles(self, script_text: str) -> List[Dict]:
        """Extract article data from embedded JavaScript state.

        Args:
            script_text: The inner text of a ``<script>`` tag containing
                serialised page state (e.g. ``__NUXT__`` or ``__INITIAL_STATE__``).

        Returns:
            A list of normalised, workplace-filtered article dicts.
        """
        articles: List[Dict] = []
        try:
            match = re.search(
                r'(?:__NUXT__|__INITIAL_STATE__)\s*=\s*(\{.+?\});?\s*$',
                script_text,
                re.DOTALL,
            )
            if not match:
                return articles

            data = json.loads(match.group(1))
            # Walk common state shapes to find article arrays
            candidates: List[Any] = []
            for key in ("data", "state", "articleList", "hotList"):
                val = data.get(key)
                if isinstance(val, list):
                    candidates = val
                    break
                if isinstance(val, dict):
                    for sub_key in ("articleList", "dataList", "list"):
                        sub = val.get(sub_key)
                        if isinstance(sub, list):
                            candidates = sub
                            break
                    if candidates:
                        break

            for item in candidates:
                article = self._normalize_article(item)
                if article and self._is_workplace_related(
                    article.get("title", ""),
                    article.get("summary", ""),
                ):
                    articles.append(article)

        except (json.JSONDecodeError, Exception) as exc:
            self.logger.debug(f"Embedded state parsing failed: {exc}")

        return articles

    def _parse_article_card(self, card: Any) -> Optional[Dict]:
        """Parse a single article card DOM element into an article dict.

        Args:
            card: A BeautifulSoup Tag representing an article card.

        Returns:
            A normalised article dict, or ``None`` if parsing fails.
        """
        try:
            # Title
            title_el = card.select_one("h2, h3, h4, a.article-title, .title")
            title = title_el.get_text(strip=True) if title_el else ""
            if not title:
                return None

            # URL and ID
            link = card.select_one("a[href*='/article/']") or card
            href = link.get("href", "")
            if not href:
                return None

            article_id = ""
            id_match = re.search(r"/article/(\d+)", href)
            if id_match:
                article_id = id_match.group(1)
            if not article_id:
                return None

            url = href
            if not url.startswith("http"):
                url = f"{self._BASE_URL}{url}"

            # Author
            author_el = card.select_one(".author-name, .author, .user-name")
            author = author_el.get_text(strip=True) if author_el else ""

            # Summary
            summary_el = card.select_one(".article-summary, .description, p")
            summary = summary_el.get_text(strip=True) if summary_el else ""

            return {
                "platform": "huxiu",
                "platform_id": article_id,
                "title": title,
                "url": url,
                "author": author,
                "view_count": 0,
                "like_count": 0,
                "comment_count": 0,
                "share_count": 0,
                "publish_time": None,
                "summary": summary,
            }

        except Exception as exc:
            self.logger.debug(f"Failed to parse article card: {exc}")
            return None

    def _extract_script_data(self, soup: BeautifulSoup) -> Optional[Dict]:
        """Extract article detail data from embedded ``<script>`` JSON.

        Args:
            soup: Parsed BeautifulSoup document of an article page.

        Returns:
            A dict with ``content`` and ``summary`` keys, or ``None``.
        """
        try:
            for script in soup.find_all("script"):
                text = script.string or ""
                if "__NUXT__" not in text and "__INITIAL_STATE__" not in text:
                    continue

                match = re.search(
                    r'(?:__NUXT__|__INITIAL_STATE__)\s*=\s*(\{.+?\});?\s*$',
                    text,
                    re.DOTALL,
                )
                if not match:
                    continue

                data = json.loads(match.group(1))
                # Navigate to article detail
                detail = (
                    data.get("data", {}).get("articleDetail", data.get("articleDetail", {}))
                )
                if not detail:
                    # Try deeper nesting
                    for key in ("state", "data"):
                        sub = data.get(key, {})
                        if isinstance(sub, dict) and "article" in sub:
                            detail = sub["article"]
                            break

                if detail:
                    return {
                        "content": detail.get("content", ""),
                        "summary": detail.get("summary", detail.get("description", "")),
                    }

        except Exception as exc:
            self.logger.debug(f"Script data extraction failed: {exc}")

        return None

    @staticmethod
    def _extract_article_id(url: str) -> Optional[str]:
        """Extract the numeric article ID from a Huxiu URL.

        Args:
            url: A Huxiu article URL
                (e.g. ``https://www.huxiu.com/article/12345.html``).

        Returns:
            The article ID string, or ``None`` if not found.
        """
        match = re.search(r"/article/(\d+)", url)
        return match.group(1) if match else None
