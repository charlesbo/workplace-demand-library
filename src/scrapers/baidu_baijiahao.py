"""Scraper for 百度百家号 (Baidu Baijiahao) articles.

Uses Baidu web search to discover Baijiahao articles matching workplace
keywords, then fetches and parses each article page for full content.
"""

from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import quote_plus, urljoin, urlparse

from src.scrapers.base import BaseScraper

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover
    BeautifulSoup = None  # type: ignore[assignment,misc]


class BaiduBaijiahaoScraper(BaseScraper):
    """Scrape workplace-related articles from Baidu Baijiahao.

    Discovery strategy:
        1. Build search queries from workplace keywords.
        2. Hit ``https://www.baidu.com/s`` and parse the result HTML.
        3. Filter results whose URL points to ``baijiahao.baidu.com``.
        4. For each hit, fetch the article page and extract content.
    """

    BAIDU_SEARCH_URL = "https://www.baidu.com/s"
    BAIJIAHAO_HOST = "baijiahao.baidu.com"

    def __init__(self) -> None:
        super().__init__("baidu_baijiahao")
        self.max_pages: int = self.config.get("max_pages", 3)
        self.results_per_page: int = self.config.get("results_per_page", 10)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_hot_articles_list(self) -> List[Dict]:
        """Search Baidu for workplace keywords and collect Baijiahao results.

        Returns:
            A list of article metadata dicts with keys: ``platform``,
            ``platform_id``, ``title``, ``url``, ``author``,
            ``view_count``, ``like_count``, ``comment_count``,
            ``share_count``, ``publish_time``.
        """
        keywords: List[str] = self.get_keywords()
        if not keywords:
            self.logger.warning("No keywords configured – nothing to search")
            return []

        articles: List[Dict] = []
        seen_urls: set[str] = set()

        for keyword in keywords:
            try:
                keyword_articles = self._search_keyword(keyword, seen_urls)
                articles.extend(keyword_articles)
            except Exception as exc:
                self.logger.error(
                    f"Failed to search keyword '{keyword}': {exc}"
                )

        self.logger.info(
            f"Collected {len(articles)} Baijiahao articles from "
            f"{len(keywords)} keywords"
        )
        return articles

    def get_article_detail(self, url: str) -> Dict:
        """Fetch a Baijiahao article page and extract its content.

        Args:
            url: Full URL of the Baijiahao article.

        Returns:
            A dict with keys ``content``, ``raw_html``, and ``summary``.
            Returns an empty dict on failure.
        """
        try:
            resp = self.http.get(url, headers=self._search_headers())
            if resp is None:
                self.logger.warning(f"Empty response for article: {url}")
                return {}

            html = resp.text if hasattr(resp, "text") else str(resp)
            soup = self._make_soup(html)
            if soup is None:
                return {}

            content = self._extract_article_content(soup)
            summary = self._extract_summary(soup, content)

            return {
                "content": content,
                "raw_html": html,
                "summary": summary,
            }
        except Exception as exc:
            self.logger.error(f"Error fetching article detail {url}: {exc}")
            return {}

    def get_hot_comments(self, url: str) -> List[Dict]:
        """Fetch hot comments for a Baijiahao article.

        Baijiahao comments are loaded dynamically and are difficult to
        obtain without a browser.  This implementation attempts to parse
        any server-rendered comment section present in the page HTML.

        Args:
            url: Full URL of the Baijiahao article.

        Returns:
            A list of comment dicts with keys ``commenter``, ``content``,
            and ``like_count``.  May be empty if no comments are found.
        """
        comments: List[Dict] = []
        try:
            resp = self.http.get(url, headers=self._search_headers())
            if resp is None:
                return comments

            html = resp.text if hasattr(resp, "text") else str(resp)
            soup = self._make_soup(html)
            if soup is None:
                return comments

            # Baijiahao comment sections vary; try common container selectors
            comment_containers = soup.select(
                ".comment-list .comment-item, "
                ".c-comment .comment-item, "
                "[class*=comment] .item"
            )
            for container in comment_containers:
                commenter_tag = container.select_one(
                    ".comment-user, .user-name, [class*=name]"
                )
                content_tag = container.select_one(
                    ".comment-content, .content, [class*=content]"
                )
                like_tag = container.select_one(
                    ".like-count, .praise, [class*=like]"
                )

                commenter = (
                    commenter_tag.get_text(strip=True) if commenter_tag else ""
                )
                content = (
                    content_tag.get_text(strip=True) if content_tag else ""
                )
                like_count = self._parse_count(
                    like_tag.get_text(strip=True) if like_tag else "0"
                )

                if content:
                    comments.append(
                        {
                            "commenter": commenter,
                            "content": content,
                            "like_count": like_count,
                        }
                    )
        except Exception as exc:
            self.logger.debug(f"Failed to fetch comments for {url}: {exc}")

        return comments

    # ------------------------------------------------------------------
    # Keyword helpers
    # ------------------------------------------------------------------

    def get_keywords(self) -> List[str]:
        """Return workplace search keywords from global settings.

        Returns:
            A list of keyword strings.
        """
        return self.settings.get("keywords", []) or []

    # ------------------------------------------------------------------
    # Private helpers – search
    # ------------------------------------------------------------------

    def _search_keyword(
        self, keyword: str, seen_urls: set[str]
    ) -> List[Dict]:
        """Run a paginated Baidu search for *keyword* and return articles.

        Args:
            keyword: Search term.
            seen_urls: Mutable set used for cross-keyword dedup.

        Returns:
            List of article metadata dicts found for this keyword.
        """
        articles: List[Dict] = []
        query = f"{keyword} site:baijiahao.baidu.com"

        for page in range(self.max_pages):
            self.rate_limiter.wait(self.platform_name)

            params = {
                "wd": query,
                "pn": page * self.results_per_page,
                "rn": self.results_per_page,
            }

            try:
                resp = self.http.get(
                    self.BAIDU_SEARCH_URL,
                    params=params,
                    headers=self._search_headers(),
                )
                if resp is None:
                    self.logger.warning(
                        f"No response for keyword '{keyword}' page {page}"
                    )
                    break

                html = resp.text if hasattr(resp, "text") else str(resp)
                page_articles = self._parse_search_results(html, seen_urls)
                if not page_articles:
                    break

                articles.extend(page_articles)
                self.logger.debug(
                    f"Keyword '{keyword}' page {page}: "
                    f"{len(page_articles)} articles"
                )
            except Exception as exc:
                self.logger.error(
                    f"Search request failed for '{keyword}' page {page}: {exc}"
                )
                break

        return articles

    def _parse_search_results(
        self, html: str, seen_urls: set[str]
    ) -> List[Dict]:
        """Parse Baidu search result HTML and extract Baijiahao entries.

        Args:
            html: Raw HTML of a Baidu search results page.
            seen_urls: Mutable set for deduplication.

        Returns:
            List of article metadata dicts.
        """
        soup = self._make_soup(html)
        if soup is None:
            return []

        articles: List[Dict] = []
        result_containers = soup.select(
            ".result.c-container, .c-container, [class*=result]"
        )

        for container in result_containers:
            try:
                article = self._parse_single_result(container)
                if article is None:
                    continue

                url = article["url"]
                if url in seen_urls:
                    continue

                # Only keep Baijiahao links
                if self.BAIJIAHAO_HOST not in urlparse(url).netloc:
                    continue

                seen_urls.add(url)
                articles.append(article)
            except Exception as exc:
                self.logger.debug(f"Failed to parse search result: {exc}")

        return articles

    def _parse_single_result(self, container) -> Optional[Dict]:
        """Extract article metadata from a single Baidu search result node.

        Args:
            container: A BeautifulSoup Tag representing one search result.

        Returns:
            An article metadata dict, or ``None`` if the result cannot be
            parsed.
        """
        # Title & URL
        link_tag = container.select_one("h3 a, .t a, a[href]")
        if link_tag is None:
            return None

        title = link_tag.get_text(strip=True)
        url = link_tag.get("href", "")
        if not title or not url:
            return None

        # Resolve Baidu redirect URLs
        url = self._resolve_baidu_url(url)

        # Author (often in a span near the source label)
        author = ""
        author_tag = container.select_one(
            ".c-color-gray, .source, [class*=author], [class*=source]"
        )
        if author_tag:
            author = author_tag.get_text(strip=True)

        # Publish time
        publish_time = ""
        time_tag = container.select_one(
            ".c-color-gray2, .newTimeFactor_before, [class*=time]"
        )
        if time_tag:
            publish_time = time_tag.get_text(strip=True)

        platform_id = hashlib.md5(url.encode()).hexdigest()

        return {
            "platform": self.platform_name,
            "platform_id": platform_id,
            "title": title,
            "url": url,
            "author": author,
            "view_count": 0,
            "like_count": 0,
            "comment_count": 0,
            "share_count": 0,
            "publish_time": publish_time,
        }

    # ------------------------------------------------------------------
    # Private helpers – article detail
    # ------------------------------------------------------------------

    def _extract_article_content(self, soup) -> str:
        """Extract the main text content from a Baijiahao article page.

        Args:
            soup: BeautifulSoup object of the article page.

        Returns:
            Cleaned article text.
        """
        # Try common Baijiahao content selectors
        selectors = [
            ".article-content",
            "#article-content",
            ".index-module_articleWrap",
            "[class*=article-content]",
            ".mainContent",
            "article",
        ]
        for selector in selectors:
            content_div = soup.select_one(selector)
            if content_div:
                return content_div.get_text(separator="\n", strip=True)

        # Fallback: largest text block in <div>
        divs = soup.find_all("div")
        best = ""
        for div in divs:
            text = div.get_text(separator="\n", strip=True)
            if len(text) > len(best):
                best = text
        return best

    def _extract_summary(self, soup, content: str) -> str:
        """Extract or generate a short summary for the article.

        Args:
            soup: BeautifulSoup object of the article page.
            content: Full article text (used as fallback).

        Returns:
            A summary string (up to ~200 characters).
        """
        # Try meta description
        meta = soup.find("meta", attrs={"name": "description"})
        if meta and meta.get("content"):
            return meta["content"].strip()

        # Fallback: first 200 chars of content
        if content:
            return content[:200].strip()

        return ""

    # ------------------------------------------------------------------
    # Private helpers – utilities
    # ------------------------------------------------------------------

    def _resolve_baidu_url(self, url: str) -> str:
        """Follow a Baidu redirect URL to obtain the real destination.

        Baidu search results use redirect links (``www.baidu.com/link?…``).
        This method follows the redirect once to get the actual URL.

        Args:
            url: Possibly-redirected Baidu search link.

        Returns:
            The resolved target URL, or the original URL on failure.
        """
        if "baidu.com/link" not in url:
            return url
        try:
            resp = self.http.get(
                url,
                headers=self._search_headers(),
            )
            if resp is not None and hasattr(resp, "url"):
                return str(resp.url)
        except Exception as exc:
            self.logger.debug(f"Failed to resolve redirect URL {url}: {exc}")
        return url

    def _search_headers(self) -> Dict[str, str]:
        """Return HTTP headers suitable for Baidu requests.

        Returns:
            A headers dict mimicking a regular browser.
        """
        return {
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;"
                "q=0.9,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://www.baidu.com/",
            "Connection": "keep-alive",
        }

    @staticmethod
    def _parse_count(text: str) -> int:
        """Parse a human-readable count string (e.g. '1.2万') into an int.

        Args:
            text: Count string, possibly with Chinese magnitude suffixes.

        Returns:
            Integer count value, or 0 if parsing fails.
        """
        if not text:
            return 0
        text = text.strip()
        try:
            if "万" in text:
                return int(float(text.replace("万", "")) * 10_000)
            if "亿" in text:
                return int(float(text.replace("亿", "")) * 100_000_000)
            return int(re.sub(r"[^\d]", "", text) or 0)
        except (ValueError, TypeError):
            return 0

    @staticmethod
    def _make_soup(html: str):
        """Create a BeautifulSoup object from *html*.

        Args:
            html: Raw HTML string.

        Returns:
            A BeautifulSoup instance, or ``None`` if bs4 is unavailable.
        """
        if BeautifulSoup is None:
            return None
        return BeautifulSoup(html, "html.parser")
