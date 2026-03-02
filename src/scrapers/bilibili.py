"""
B站专栏 (Bilibili Read / Articles) scraper.

Strategy: Uses Bilibili's well-documented public web API for searching
articles (``type=article``) and fetching article detail / viewinfo.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from src.scrapers.base import BaseScraper


class BilibiliScraper(BaseScraper):
    """Scraper for Bilibili 专栏 (column / read articles).

    Bilibili exposes a public search API that supports ``type=article``
    and a viewinfo endpoint for per-article metadata.  Article body HTML
    is fetched directly from ``bilibili.com/read/cv{id}``.
    """

    # API endpoints
    _SEARCH_API = "https://api.bilibili.com/x/web-interface/search/type"
    _VIEW_INFO_API = "https://api.bilibili.com/x/article/viewinfo"
    _ARTICLE_URL_TPL = "https://www.bilibili.com/read/cv{id}"
    _COMMENT_API = "https://api.bilibili.com/x/v2/reply"

    # Reply type for articles (see Bilibili API docs)
    _REPLY_TYPE_ARTICLE = 12

    # Pagination defaults
    _PAGE_SIZE = 30
    _MAX_PAGES = 3  # per keyword

    def __init__(self) -> None:
        super().__init__("bilibili")

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

    @staticmethod
    def _extract_article_id(cv_url: str) -> str:
        """Extract the numeric article id from a ``cv`` URL or id string.

        Args:
            cv_url: A URL like ``https://www.bilibili.com/read/cv12345``
                    or just ``"12345"``.

        Returns:
            The numeric id as a string, or an empty string on failure.
        """
        match = re.search(r"cv(\d+)", cv_url)
        if match:
            return match.group(1)
        # Fallback: the input may already be a bare numeric id
        if cv_url.strip().isdigit():
            return cv_url.strip()
        return ""

    def _build_article_url(self, article_id: str) -> str:
        """Build the canonical article URL.

        Args:
            article_id: Numeric Bilibili article identifier.

        Returns:
            Full URL string.
        """
        return self._ARTICLE_URL_TPL.format(id=article_id)

    # ------------------------------------------------------------------
    # Abstract method implementations
    # ------------------------------------------------------------------

    def get_hot_articles_list(self) -> List[Dict]:
        """Search Bilibili articles for workplace-related keywords.

        Iterates over keywords, paginates through the search API
        (``type=article``), and returns a flat list of article metadata.

        Returns:
            A list of article-metadata dicts.
        """
        articles: List[Dict] = []
        seen_ids: set[str] = set()
        keywords = self._get_keywords()

        for keyword in keywords:
            self.logger.info(f"Searching bilibili articles for keyword: {keyword}")

            for page in range(1, self._MAX_PAGES + 1):
                if self.should_stop():
                    break

                self.rate_limiter.wait(self.platform_name)

                params: Dict[str, Any] = {
                    "search_type": "article",
                    "keyword": keyword,
                    "page": page,
                    "page_size": self._PAGE_SIZE,
                    "order": "totalrank",  # relevance
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

                    if data.get("code", -1) != 0:
                        self.logger.warning(
                            f"API error for keyword='{keyword}': "
                            f"code={data.get('code')}, "
                            f"message={data.get('message', '')}"
                        )
                        self._record_failure()
                        break

                    result: Dict = data.get("data", {})
                    items: List[Dict] = result.get("result", [])

                    if not items:
                        self.logger.debug(
                            f"No more results for keyword='{keyword}' at page={page}"
                        )
                        break

                    for item in items:
                        article_id: str = str(item.get("id", ""))
                        if not article_id or article_id in seen_ids:
                            continue
                        seen_ids.add(article_id)

                        # Strip HTML tags from the title that Bilibili
                        # highlights with <em> in search results
                        raw_title: str = item.get("title", "")
                        clean_title: str = re.sub(r"<[^>]+>", "", raw_title)

                        articles.append(
                            {
                                "platform": self.platform_name,
                                "platform_id": f"bilibili_{article_id}",
                                "title": clean_title,
                                "url": self._build_article_url(article_id),
                                "author": item.get("author", ""),
                                "view_count": int(item.get("view", 0)),
                                "like_count": int(item.get("like", 0)),
                                "comment_count": int(item.get("reply", 0)),
                                "share_count": int(item.get("coin", 0)),
                                "publish_time": item.get("pub_date", ""),
                            }
                        )

                except Exception as exc:
                    self.logger.error(
                        f"Failed to search keyword='{keyword}' page={page}: {exc}"
                    )
                    self._record_failure()
                    break

        self.logger.info(
            f"Collected {len(articles)} bilibili articles across "
            f"{len(keywords)} keywords"
        )
        return articles

    def get_article_detail(self, url: str) -> Dict:
        """Fetch full content and metadata for a Bilibili article.

        Makes two requests:

        1. ``/x/article/viewinfo`` — structured metadata (stats, summary).
        2. ``bilibili.com/read/cv{id}`` — full HTML body.

        Args:
            url: Canonical article URL (e.g.
                 ``https://www.bilibili.com/read/cv12345``).

        Returns:
            A dict with ``content``, ``raw_html``, and ``summary`` keys,
            or an empty dict on failure.
        """
        article_id = self._extract_article_id(url)
        if not article_id:
            self.logger.warning(f"Cannot extract article id from URL: {url}")
            return {}

        content: str = ""
        raw_html: str = ""
        summary: str = ""

        # ---- Step 1: viewinfo (metadata + summary) ----
        try:
            params: Dict[str, Any] = {"id": article_id}
            resp = self.http.get(self._VIEW_INFO_API, params=params)

            if resp is not None:
                data = resp.json() if hasattr(resp, "json") else {}
                if data.get("code") == 0:
                    info: Dict = data.get("data", {})
                    summary = info.get("summary", "")
                else:
                    self.logger.debug(
                        f"viewinfo non-zero code for cv{article_id}: "
                        f"{data.get('code')}"
                    )
        except Exception as exc:
            self.logger.warning(
                f"Failed to fetch viewinfo for cv{article_id}: {exc}"
            )

        # ---- Step 2: full HTML body ----
        try:
            self.rate_limiter.wait(self.platform_name)
            page_resp = self.http.get(url)

            if page_resp is not None:
                html_text: str = (
                    page_resp.text
                    if hasattr(page_resp, "text")
                    else str(page_resp)
                )
                raw_html = html_text

                # Extract article body from the known wrapper
                body_match = re.search(
                    r'<div\s+class="article-content"[^>]*>(.*?)</div>',
                    html_text,
                    re.DOTALL,
                )
                if body_match:
                    body_html = body_match.group(1)
                    # Strip tags for plain-text content
                    content = re.sub(r"<[^>]+>", "", body_html).strip()
                else:
                    # Fallback: try to get any readable text from the page
                    content = re.sub(r"<[^>]+>", "", html_text).strip()
                    content = content[:5000]  # cap length for safety
        except Exception as exc:
            self.logger.error(
                f"Failed to fetch article body for cv{article_id}: {exc}"
            )

        if not content and not summary:
            return {}

        # Derive summary from content if viewinfo didn't provide one
        if not summary and content:
            summary = (
                content[:200] + "..." if len(content) > 200 else content
            )

        return {
            "content": content,
            "raw_html": raw_html,
            "summary": summary,
        }

    def get_hot_comments(self, url: str) -> List[Dict]:
        """Fetch hot/top comments for a Bilibili article.

        Uses the reply API with ``type=12`` (article reply type).

        Args:
            url: Canonical article URL.

        Returns:
            A list of comment dicts with ``commenter``, ``content``,
            and ``like_count`` keys.
        """
        article_id = self._extract_article_id(url)
        if not article_id:
            return []

        try:
            params: Dict[str, Any] = {
                "type": self._REPLY_TYPE_ARTICLE,
                "oid": article_id,
                "sort": 1,  # 1 = by like count
                "pn": 1,
                "ps": 20,
            }

            resp = self.http.get(self._COMMENT_API, params=params)
            if resp is None:
                return []

            data = resp.json() if hasattr(resp, "json") else {}
            if data.get("code", -1) != 0:
                self.logger.debug(
                    f"Comment API error for cv{article_id}: "
                    f"code={data.get('code')}"
                )
                return []

            replies: List[Dict] = (
                data.get("data", {}).get("replies", []) or []
            )

            comments: List[Dict] = []
            for r in replies:
                member: Dict = r.get("member", {})
                comment_content: Dict = r.get("content", {})
                comments.append(
                    {
                        "commenter": member.get("uname", ""),
                        "content": comment_content.get("message", ""),
                        "like_count": int(r.get("like", 0)),
                    }
                )

            self.logger.debug(
                f"Fetched {len(comments)} comments for cv{article_id}"
            )
            return comments

        except Exception as exc:
            self.logger.error(
                f"Failed to fetch comments for cv{article_id}: {exc}"
            )
            return []
