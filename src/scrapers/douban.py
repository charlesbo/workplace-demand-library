"""
Scraper for 豆瓣 (Douban) workplace-related groups.

Strategy: requests + Cookie session.
Targets configured discussion groups and extracts topic lists and content.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, List, Optional

from src.scrapers.base import BaseScraper

# URL templates
_GROUP_DISCUSSION_URL = "https://www.douban.com/group/{group_id}/discussion"
_TOPIC_DETAIL_URL = "https://www.douban.com/group/topic/{topic_id}/"

# Well-known group slugs → display names (for logging)
_GROUP_NAMES: Dict[str, str] = {
    "shangban": "上班这件事",
    "985waste": "985废物引进计划",
    "zhaowork": "找工作互助",
}


class DoubanScraper(BaseScraper):
    """Scraper for Douban (豆瓣) workplace discussion groups.

    Fetches topic lists from configured groups, then parses individual
    topic pages for full content.

    Config keys (``platforms.yaml`` → ``douban``):
        - ``enabled``: Whether this scraper is active.
        - ``interval``: Request interval in seconds.
        - ``groups``: List of group ID slugs to crawl.
        - ``cookie``: Douban login cookie string for authenticated access.
    """

    def __init__(self) -> None:
        super().__init__("douban")
        self._cookie: str = self.config.get("cookie", "")
        self._groups: List[str] = self.config.get("groups", [])

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_hot_articles_list(self) -> List[Dict]:
        """Fetch topic lists from all configured Douban groups.

        Iterates over each group, paginates through its discussion list,
        and returns normalised article metadata.

        Returns:
            A list of article dicts with standard metadata keys.
        """
        articles: List[Dict] = []
        seen_ids: set[str] = set()

        for group_id in self._groups:
            group_label = _GROUP_NAMES.get(group_id, group_id)
            self.logger.info(f"Fetching topics from Douban group: {group_label}")

            try:
                topics = self._fetch_group_topics(group_id)
                for topic in topics:
                    pid = topic.get("platform_id", "")
                    if pid and pid not in seen_ids:
                        seen_ids.add(pid)
                        articles.append(topic)
            except Exception as exc:
                self.logger.error(
                    f"Failed to fetch group '{group_label}': {exc}"
                )
                self._record_failure()

            self.rate_limiter.wait(self.platform_name)

        self.logger.info(f"Collected {len(articles)} unique topics from Douban")
        return articles

    def get_article_detail(self, url: str) -> Dict:
        """Fetch full content for a single Douban group topic.

        Parses the topic HTML page to extract post content.

        Args:
            url: The topic URL.

        Returns:
            A dict with ``content``, ``raw_html``, and ``summary`` keys,
            or an empty dict on failure.
        """
        try:
            resp = self.http.get(url, headers=self._build_headers())
            html = resp.text
        except Exception as exc:
            self.logger.error(f"Failed to fetch topic detail for {url}: {exc}")
            return {}

        return self._parse_topic_detail(html)

    def get_hot_comments(self, url: str) -> List[Dict]:
        """Fetch popular comments/replies for a Douban group topic.

        Parses reply entries from the topic page HTML.

        Args:
            url: The topic URL.

        Returns:
            A list of comment dicts with ``commenter``, ``content``, and
            ``like_count`` keys.
        """
        try:
            resp = self.http.get(url, headers=self._build_headers())
            html = resp.text
        except Exception as exc:
            self.logger.debug(f"Failed to fetch comments for {url}: {exc}")
            return []

        return self._parse_comments(html)

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
    # Private helpers — group topic list
    # ------------------------------------------------------------------

    def _fetch_group_topics(
        self, group_id: str, start: int = 0
    ) -> List[Dict]:
        """Fetch one page of topics from a Douban group's discussion list.

        Args:
            group_id: The group slug / ID.
            start: Pagination offset.

        Returns:
            A list of normalised article metadata dicts.
        """
        url = _GROUP_DISCUSSION_URL.format(group_id=group_id)
        params = {"start": start}
        resp = self.http.get(url, params=params, headers=self._build_headers())
        html = resp.text
        return self._parse_topic_list(html, group_id)

    def _parse_topic_list(self, html: str, group_id: str) -> List[Dict]:
        """Parse the group discussion page HTML into article dicts.

        Args:
            html: Raw HTML of the discussion list page.
            group_id: The group slug (for context in logs).

        Returns:
            A list of article metadata dicts.
        """
        articles: List[Dict] = []

        # Each topic row lives inside a <tr class=""> in the discussion table
        row_pattern = re.compile(
            r'<tr\s[^>]*class=""[^>]*>(.*?)</tr>', re.DOTALL
        )
        for row_match in row_pattern.finditer(html):
            row_html = row_match.group(1)
            article = self._parse_topic_row(row_html, group_id)
            if article:
                articles.append(article)

        return articles

    def _parse_topic_row(self, row_html: str, group_id: str) -> Optional[Dict]:
        """Extract article metadata from a single topic table row.

        Args:
            row_html: Inner HTML of a ``<tr>`` element.
            group_id: The parent group slug.

        Returns:
            An article metadata dict, or ``None`` if parsing fails.
        """
        # Title and URL
        title_match = re.search(
            r'<a[^>]+href="(https://www\.douban\.com/group/topic/(\d+)/)"'
            r'[^>]*title="([^"]*)"',
            row_html,
        )
        if not title_match:
            return None

        topic_url, topic_id, title = title_match.groups()

        # Author
        author_match = re.search(
            r'<a[^>]+href="https://www\.douban\.com/people/[^"]*"[^>]*>'
            r"([^<]+)</a>",
            row_html,
        )
        author = author_match.group(1).strip() if author_match else ""

        # Reply count
        reply_match = re.search(r"<td[^>]*>\s*(\d+)\s*</td>", row_html)
        reply_count = int(reply_match.group(1)) if reply_match else 0

        # Publish / last-reply time
        time_match = re.search(r"<td[^>]*nowrap[^>]*>\s*([^<]+)\s*</td>", row_html)
        publish_time = self._parse_douban_time(
            time_match.group(1).strip() if time_match else ""
        )

        return {
            "platform": "douban",
            "platform_id": topic_id,
            "title": title.strip(),
            "url": topic_url,
            "author": author,
            "view_count": 0,
            "like_count": 0,
            "comment_count": reply_count,
            "share_count": 0,
            "publish_time": publish_time,
        }

    # ------------------------------------------------------------------
    # Private helpers — topic detail
    # ------------------------------------------------------------------

    def _parse_topic_detail(self, html: str) -> Dict:
        """Extract post content from a topic detail page.

        Args:
            html: Raw HTML of the topic page.

        Returns:
            A dict with ``content``, ``raw_html``, and ``summary``.
        """
        content = ""
        raw_html = ""

        # Main post content lives in <div class="topic-content">
        content_match = re.search(
            r'<div\s+class="topic-content"[^>]*>(.*?)</div>',
            html,
            re.DOTALL,
        )
        if content_match:
            raw_html = content_match.group(1).strip()
            content = re.sub(r"<[^>]+>", "", raw_html).strip()
            # Normalise whitespace
            content = re.sub(r"\s+", " ", content)

        if not content:
            # Fallback: try rich-text container
            rich_match = re.search(
                r'<div\s+class="rich-content"[^>]*>(.*?)</div>',
                html,
                re.DOTALL,
            )
            if rich_match:
                raw_html = rich_match.group(1).strip()
                content = re.sub(r"<[^>]+>", "", raw_html).strip()
                content = re.sub(r"\s+", " ", content)

        # Update view/like counts from the detail page if available
        # (these are not always present in the list view)

        summary = content[:200] + "..." if len(content) > 200 else content
        return {
            "content": content,
            "raw_html": raw_html,
            "summary": summary,
        }

    # ------------------------------------------------------------------
    # Private helpers — comments
    # ------------------------------------------------------------------

    def _parse_comments(self, html: str) -> List[Dict]:
        """Parse reply entries from a topic detail page.

        Args:
            html: Raw HTML of the topic page.

        Returns:
            A list of comment dicts.
        """
        comments: List[Dict] = []

        # Each reply is in <li class="comment-item" ...>
        item_pattern = re.compile(
            r'<li[^>]+class="[^"]*comment-item[^"]*"[^>]*>(.*?)</li>',
            re.DOTALL,
        )
        for match in item_pattern.finditer(html):
            comment_html = match.group(1)
            comment = self._parse_single_comment(comment_html)
            if comment:
                comments.append(comment)

        return comments

    def _parse_single_comment(self, comment_html: str) -> Optional[Dict]:
        """Extract data from a single comment ``<li>`` block.

        Args:
            comment_html: Inner HTML of the comment list item.

        Returns:
            A comment dict, or ``None`` if parsing fails.
        """
        # Commenter name
        name_match = re.search(
            r'<a[^>]+class="[^"]*reply-doc[^"]*"[^>]*>.*?'
            r"<span[^>]*>([^<]+)</span>",
            comment_html,
            re.DOTALL,
        )
        commenter = name_match.group(1).strip() if name_match else ""

        # Comment text
        text_match = re.search(
            r'<p\s+class="[^"]*reply-content[^"]*"[^>]*>(.*?)</p>',
            comment_html,
            re.DOTALL,
        )
        if not text_match:
            return None
        content = re.sub(r"<[^>]+>", "", text_match.group(1)).strip()

        # Like count
        like_match = re.search(
            r'<span\s+class="[^"]*comment-vote[^"]*"[^>]*>\s*(\d+)',
            comment_html,
        )
        like_count = int(like_match.group(1)) if like_match else 0

        return {
            "commenter": commenter,
            "content": content,
            "like_count": like_count,
        }

    # ------------------------------------------------------------------
    # Request helpers
    # ------------------------------------------------------------------

    def _build_headers(self) -> Dict[str, str]:
        """Build HTTP headers with cookie authentication.

        Returns:
            A headers dict suitable for passing to ``self.http.get()``.
        """
        headers: Dict[str, str] = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": "https://www.douban.com/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        if self._cookie:
            headers["Cookie"] = self._cookie
        return headers

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_douban_time(time_str: str) -> Optional[datetime]:
        """Parse a Douban-style timestamp string into a :class:`datetime`.

        Douban uses formats like ``2024-01-15 14:30`` or ``01-15 14:30``
        (current year implied).

        Args:
            time_str: The raw time string from the page.

        Returns:
            A :class:`datetime` object, or ``None`` if parsing fails.
        """
        if not time_str:
            return None

        formats = ["%Y-%m-%d %H:%M", "%m-%d %H:%M", "%Y-%m-%d"]
        for fmt in formats:
            try:
                dt = datetime.strptime(time_str.strip(), fmt)
                # If year is 1900 (no year in format), assume current year
                if dt.year == 1900:
                    dt = dt.replace(year=datetime.now().year)
                return dt
            except ValueError:
                continue
        return None
