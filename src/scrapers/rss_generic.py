"""Generic RSS/Atom feed scraper.

Parses any standard RSS 2.0 or Atom feed using ``feedparser`` and normalises
entries into the common article schema.  Full article content is taken from
the feed entry when available; otherwise the linked page is fetched and
parsed with BeautifulSoup.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from time import mktime, struct_time
from typing import Dict, List, Optional

from src.scrapers.base import BaseScraper

try:
    import feedparser
except ImportError:  # pragma: no cover
    feedparser = None  # type: ignore[assignment]

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover
    BeautifulSoup = None  # type: ignore[assignment,misc]


class RssGenericScraper(BaseScraper):
    """Scrape articles from one or more RSS / Atom feeds.

    Feed URLs are read from the platform configuration key ``feeds``
    (a list of URL strings).

    Because RSS feeds do not expose engagement metrics, ``view_count``,
    ``like_count``, ``comment_count``, and ``share_count`` default to ``0``.
    """

    def __init__(self) -> None:
        super().__init__("rss_feeds")
        # Cache for full content extracted from feed entries, keyed by URL
        self._content_cache: Dict[str, Dict] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_hot_articles_list(self) -> List[Dict]:
        """Parse all configured RSS/Atom feeds and collect article entries.

        Returns:
            A list of article metadata dicts with keys: ``platform``,
            ``platform_id``, ``title``, ``url``, ``author``,
            ``view_count``, ``like_count``, ``comment_count``,
            ``share_count``, ``publish_time``.
        """
        if feedparser is None:
            self.logger.error(
                "feedparser is not installed – cannot parse RSS feeds"
            )
            return []

        feed_urls: List[str] = self.config.get("feeds", []) or []
        if not feed_urls:
            self.logger.warning("No feed URLs configured – nothing to scrape")
            return []

        articles: List[Dict] = []
        seen_urls: set[str] = set()

        for feed_url in feed_urls:
            try:
                feed_articles = self._parse_feed(feed_url, seen_urls)
                articles.extend(feed_articles)
                self.logger.debug(
                    f"Feed {feed_url}: {len(feed_articles)} entries"
                )
            except Exception as exc:
                self.logger.error(f"Failed to parse feed {feed_url}: {exc}")

        self.logger.info(
            f"Collected {len(articles)} articles from {len(feed_urls)} feeds"
        )
        return articles

    def get_article_detail(self, url: str) -> Dict:
        """Fetch full content for an RSS article.

        If the feed entry already provided full content (cached during
        ``get_hot_articles_list``), that content is returned directly.
        Otherwise the article URL is fetched and its HTML is parsed.

        Args:
            url: Full URL of the article.

        Returns:
            A dict with keys ``content``, ``raw_html``, and ``summary``.
            Returns an empty dict on failure.
        """
        # Check the in-memory content cache first
        cached = self._content_cache.get(url)
        if cached:
            return cached

        # Fetch the page and extract content
        return self._fetch_and_parse_article(url)

    def get_hot_comments(self, url: str) -> List[Dict]:
        """Return comments for an RSS article.

        RSS/Atom feeds do not include comment data, so this method always
        returns an empty list.

        Args:
            url: Article URL (unused).

        Returns:
            An empty list.
        """
        return []

    # ------------------------------------------------------------------
    # Private helpers – feed parsing
    # ------------------------------------------------------------------

    def _parse_feed(
        self, feed_url: str, seen_urls: set[str]
    ) -> List[Dict]:
        """Download and parse a single feed URL.

        Args:
            feed_url: URL of the RSS/Atom feed.
            seen_urls: Mutable set for cross-feed deduplication.

        Returns:
            List of article metadata dicts from this feed.
        """
        feed = feedparser.parse(feed_url)

        if feed.bozo and not feed.entries:
            self.logger.warning(
                f"Feed parse error for {feed_url}: {feed.bozo_exception}"
            )
            return []

        articles: List[Dict] = []
        feed_title = getattr(feed.feed, "title", feed_url)

        for entry in feed.entries:
            try:
                article = self._parse_entry(entry, feed_title)
                if article is None:
                    continue

                url = article["url"]
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                # Cache full content when available in the feed entry
                content, raw_html, summary = self._extract_entry_content(entry)
                if content:
                    self._content_cache[url] = {
                        "content": content,
                        "raw_html": raw_html,
                        "summary": summary,
                    }

                articles.append(article)
            except Exception as exc:
                self.logger.debug(f"Failed to parse feed entry: {exc}")

        return articles

    def _parse_entry(self, entry, feed_title: str) -> Optional[Dict]:
        """Convert a single feed entry into an article metadata dict.

        Args:
            entry: A ``feedparser`` entry object.
            feed_title: Title of the parent feed (used as fallback author).

        Returns:
            An article dict, or ``None`` if the entry is unusable.
        """
        title = getattr(entry, "title", "").strip()
        link = getattr(entry, "link", "").strip()
        if not title or not link:
            return None

        author = (
            getattr(entry, "author", "")
            or getattr(entry, "creator", "")
            or feed_title
        )

        publish_time = self._parse_published_date(entry)
        platform_id = hashlib.md5(link.encode()).hexdigest()

        return {
            "platform": self.platform_name,
            "platform_id": platform_id,
            "title": title,
            "url": link,
            "author": author.strip() if isinstance(author, str) else str(author),
            "view_count": 0,
            "like_count": 0,
            "comment_count": 0,
            "share_count": 0,
            "publish_time": publish_time,
        }

    # ------------------------------------------------------------------
    # Private helpers – content extraction
    # ------------------------------------------------------------------

    def _extract_entry_content(self, entry) -> tuple[str, str, str]:
        """Pull content and summary from a feed entry.

        Args:
            entry: A ``feedparser`` entry object.

        Returns:
            Tuple of (cleaned text content, raw HTML content, summary).
        """
        raw_html = ""
        # Prefer content field (Atom full-content)
        if hasattr(entry, "content") and entry.content:
            raw_html = entry.content[0].get("value", "")
        elif hasattr(entry, "summary_detail"):
            raw_html = getattr(entry.summary_detail, "value", "")

        content = self._html_to_text(raw_html) if raw_html else ""

        summary = getattr(entry, "summary", "").strip()
        if not summary and content:
            summary = content[:200]

        return content, raw_html, summary

    def _fetch_and_parse_article(self, url: str) -> Dict:
        """Fetch an article page by URL and extract its content.

        Args:
            url: The article URL.

        Returns:
            A dict with ``content``, ``raw_html``, and ``summary``,
            or an empty dict on failure.
        """
        try:
            resp = self.http.get(url)
            if resp is None:
                self.logger.warning(f"Empty response for article: {url}")
                return {}

            html = resp.text if hasattr(resp, "text") else str(resp)
            content = self._extract_page_content(html)
            summary = self._extract_page_summary(html, content)

            return {
                "content": content,
                "raw_html": html,
                "summary": summary,
            }
        except Exception as exc:
            self.logger.error(f"Error fetching article {url}: {exc}")
            return {}

    def _extract_page_content(self, html: str) -> str:
        """Extract main text from an HTML page.

        Args:
            html: Raw HTML string.

        Returns:
            Cleaned text content.
        """
        soup = self._make_soup(html)
        if soup is None:
            return ""

        # Remove script and style elements
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()

        # Try common article containers
        selectors = [
            "article",
            "[role=main]",
            ".post-content",
            ".article-content",
            ".entry-content",
            "#content",
            "main",
        ]
        for selector in selectors:
            node = soup.select_one(selector)
            if node:
                text = node.get_text(separator="\n", strip=True)
                if len(text) > 100:
                    return text

        # Fallback: body text
        body = soup.find("body")
        if body:
            return body.get_text(separator="\n", strip=True)

        return soup.get_text(separator="\n", strip=True)

    def _extract_page_summary(self, html: str, content: str) -> str:
        """Extract or generate a summary from an HTML page.

        Args:
            html: Raw HTML string.
            content: Full article text (fallback).

        Returns:
            A summary string.
        """
        soup = self._make_soup(html)
        if soup is not None:
            meta = soup.find("meta", attrs={"name": "description"})
            if meta and meta.get("content"):
                return meta["content"].strip()

        if content:
            return content[:200].strip()

        return ""

    # ------------------------------------------------------------------
    # Private helpers – date parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_published_date(entry) -> str:
        """Extract a publication date string from a feed entry.

        Args:
            entry: A ``feedparser`` entry object.

        Returns:
            An ISO-format date string, or an empty string if unavailable.
        """
        # feedparser normalises dates into *_parsed (struct_time)
        for attr in ("published_parsed", "updated_parsed", "created_parsed"):
            parsed = getattr(entry, attr, None)
            if isinstance(parsed, struct_time):
                try:
                    return datetime.fromtimestamp(mktime(parsed)).isoformat()
                except (OverflowError, OSError, ValueError):
                    continue

        # Fall back to the raw string fields
        for attr in ("published", "updated", "created"):
            raw = getattr(entry, attr, "")
            if raw:
                return str(raw).strip()

        return ""

    # ------------------------------------------------------------------
    # Private helpers – utilities
    # ------------------------------------------------------------------

    def _html_to_text(self, html: str) -> str:
        """Convert an HTML fragment to plain text.

        Args:
            html: HTML string.

        Returns:
            Stripped text content.
        """
        soup = self._make_soup(html)
        if soup is None:
            return html  # best-effort: return raw string
        return soup.get_text(separator="\n", strip=True)

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
