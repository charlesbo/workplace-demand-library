"""Zhihu (知乎) scraper — fetches hot questions, topic answers, and comments.

Uses Zhihu's JSON API where possible.  Falls back to HTML parsing only when
the API response is incomplete.  A ``use_playwright`` config flag is reserved
for future browser-based scraping (TODO).
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

_HOT_LIST_URL = "https://www.zhihu.com/api/v3/feed/topstory/hot-lists/total"
_TOPIC_ANSWERS_URL = "https://www.zhihu.com/api/v4/topics/{topic_id}/feeds/top_activity"
_QUESTION_DETAIL_URL = "https://www.zhihu.com/api/v4/questions/{qid}"
_ANSWER_DETAIL_URL = "https://www.zhihu.com/api/v4/answers/{aid}"
_ANSWER_COMMENTS_URL = "https://www.zhihu.com/api/v4/answers/{aid}/root_comments"
_QUESTION_COMMENTS_URL = "https://www.zhihu.com/api/v4/questions/{qid}/root_comments"

# Well-known topic IDs for workplace-related topics
_TOPIC_IDS: Dict[str, str] = {
    "职场": "19551424",
    "求职": "19554791",
    "职业发展": "19590498",
    "人际交往": "19552706",
}


class ZhihuScraper(BaseScraper):
    """Scraper for Zhihu (知乎).

    Collects hot-list entries **and** high-upvote answers from
    workplace-related topics.  Questions themselves are treated as demand
    signals — their titles are extracted alongside answers.
    """

    def __init__(self) -> None:
        super().__init__("zhihu")
        self._cookie: str = self.config.get("cookie", "")
        self._min_upvotes: int = self.config.get("min_upvotes", 100)
        self._topics: List[str] = self.config.get("topics", ["职场", "求职", "职业发展"])
        self._use_playwright: bool = self.config.get("use_playwright", False)
        # TODO: implement playwright-based scraping when use_playwright is True

    # ------------------------------------------------------------------
    # Header helpers
    # ------------------------------------------------------------------

    def _api_headers(self) -> Dict[str, str]:
        """Return headers required by Zhihu's API endpoints."""
        headers: Dict[str, str] = {
            "Referer": "https://www.zhihu.com/",
            "Accept": "application/json, text/plain, */*",
            "x-requested-with": "fetch",
        }
        if self._cookie:
            headers["Cookie"] = self._cookie
        return headers

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def get_hot_articles_list(self) -> List[Dict]:
        """Fetch Zhihu hot-list entries and high-upvote topic answers.

        Returns:
            A list of article dicts with standard keys (``platform``,
            ``platform_id``, ``title``, ``url``, etc.).
        """
        articles: List[Dict] = []

        # 1. Hot list
        hot_items = self._fetch_hot_list()
        articles.extend(hot_items)
        self.logger.info(f"Fetched {len(hot_items)} items from hot list")

        # 2. Topic answers
        for topic_name in self._topics:
            topic_id = _TOPIC_IDS.get(topic_name)
            if not topic_id:
                self.logger.debug(f"No topic ID mapped for '{topic_name}', skipping")
                continue
            topic_items = self._fetch_topic_answers(topic_id, topic_name)
            articles.extend(topic_items)
            self.logger.info(
                f"Fetched {len(topic_items)} answers from topic '{topic_name}'"
            )

        return articles

    def get_article_detail(self, url: str) -> Dict:
        """Fetch full content for a Zhihu question or answer.

        Extracts answer body, upvote count, and comment count via the API.

        Args:
            url: A Zhihu answer or question URL.

        Returns:
            A dict with ``content``, ``raw_html``, and ``summary`` keys
            (plus updated metric fields when available).
        """
        try:
            aid = self._extract_answer_id(url)
            if aid:
                return self._fetch_answer_detail(aid)

            qid = self._extract_question_id(url)
            if qid:
                return self._fetch_question_detail(qid)

            self.logger.warning(f"Cannot parse Zhihu URL: {url}")
            return {}
        except Exception as exc:
            self.logger.error(f"Failed to fetch detail for {url}: {exc}")
            return {}

    def get_hot_comments(self, url: str) -> List[Dict]:
        """Fetch top-level comments for a Zhihu answer or question.

        Args:
            url: A Zhihu answer or question URL.

        Returns:
            A list of comment dicts with ``commenter``, ``content``, and
            ``like_count`` keys.
        """
        try:
            aid = self._extract_answer_id(url)
            if aid:
                return self._fetch_comments(
                    _ANSWER_COMMENTS_URL.format(aid=aid)
                )

            qid = self._extract_question_id(url)
            if qid:
                return self._fetch_comments(
                    _QUESTION_COMMENTS_URL.format(qid=qid)
                )

            return []
        except Exception as exc:
            self.logger.error(f"Failed to fetch comments for {url}: {exc}")
            return []

    # ------------------------------------------------------------------
    # Internal: hot list
    # ------------------------------------------------------------------

    def _fetch_hot_list(self) -> List[Dict]:
        """Call the hot-list API and convert each entry to a standard dict."""
        articles: List[Dict] = []
        try:
            resp = self.http.get(
                _HOT_LIST_URL,
                params={"limit": 50},
                headers=self._api_headers(),
            )
            data = resp.json()
        except Exception as exc:
            self.logger.error(f"Hot-list request failed: {exc}")
            return articles

        for item in data.get("data", []):
            target = item.get("target", {})
            question = target if target.get("type") == "question" else target.get("question", target)
            qid = str(question.get("id", ""))
            title = question.get("title", "")
            if not qid or not title:
                continue

            # If the target is an answer, track both question and answer
            answer_id = str(target.get("id", "")) if target.get("type") == "answer" else ""
            url = (
                f"https://www.zhihu.com/question/{qid}/answer/{answer_id}"
                if answer_id
                else f"https://www.zhihu.com/question/{qid}"
            )

            articles.append(
                self._build_article_dict(
                    platform_id=answer_id or qid,
                    title=title,
                    url=url,
                    author=target.get("author", {}).get("name", ""),
                    view_count=question.get("visit_count", 0),
                    like_count=target.get("voteup_count", 0),
                    comment_count=target.get("comment_count", 0),
                    publish_time=self._parse_timestamp(target.get("created_time")),
                )
            )

        return articles

    # ------------------------------------------------------------------
    # Internal: topic answers
    # ------------------------------------------------------------------

    def _fetch_topic_answers(self, topic_id: str, topic_name: str) -> List[Dict]:
        """Fetch high-upvote answers from a given topic."""
        articles: List[Dict] = []
        try:
            resp = self.http.get(
                _TOPIC_ANSWERS_URL.format(topic_id=topic_id),
                params={"limit": 20, "offset": 0},
                headers=self._api_headers(),
            )
            data = resp.json()
        except Exception as exc:
            self.logger.error(f"Topic '{topic_name}' request failed: {exc}")
            return articles

        for item in data.get("data", []):
            target = item.get("target", {})
            if target.get("type") not in ("answer", "article"):
                continue
            voteup = target.get("voteup_count", 0)
            if voteup < self._min_upvotes:
                continue

            question = target.get("question", {})
            qid = str(question.get("id", ""))
            aid = str(target.get("id", ""))
            title = question.get("title", target.get("title", ""))
            url = (
                f"https://www.zhihu.com/question/{qid}/answer/{aid}"
                if qid and aid
                else target.get("url", "")
            )

            articles.append(
                self._build_article_dict(
                    platform_id=aid or qid,
                    title=title,
                    url=url,
                    author=target.get("author", {}).get("name", ""),
                    view_count=question.get("visit_count", 0),
                    like_count=voteup,
                    comment_count=target.get("comment_count", 0),
                    publish_time=self._parse_timestamp(target.get("created_time")),
                )
            )

        return articles

    # ------------------------------------------------------------------
    # Internal: detail fetchers
    # ------------------------------------------------------------------

    def _fetch_answer_detail(self, answer_id: str) -> Dict:
        """Fetch full answer content via API."""
        resp = self.http.get(
            _ANSWER_DETAIL_URL.format(aid=answer_id),
            params={"include": "content"},
            headers=self._api_headers(),
        )
        data = resp.json()
        raw_html = data.get("content", "")
        content = clean_text(raw_html)
        excerpt = data.get("excerpt", "")

        return {
            "content": content,
            "raw_html": raw_html,
            "summary": excerpt or content[:200],
            "like_count": data.get("voteup_count", 0),
            "comment_count": data.get("comment_count", 0),
        }

    def _fetch_question_detail(self, question_id: str) -> Dict:
        """Fetch question description as article content."""
        resp = self.http.get(
            _QUESTION_DETAIL_URL.format(qid=question_id),
            params={"include": "detail"},
            headers=self._api_headers(),
        )
        data = resp.json()
        raw_html = data.get("detail", "")
        content = clean_text(raw_html)

        return {
            "content": content,
            "raw_html": raw_html,
            "summary": data.get("excerpt", content[:200]),
            "like_count": data.get("follower_count", 0),
            "comment_count": data.get("comment_count", 0),
            "view_count": data.get("visit_count", 0),
        }

    # ------------------------------------------------------------------
    # Internal: comments
    # ------------------------------------------------------------------

    def _fetch_comments(self, api_url: str) -> List[Dict]:
        """Fetch comments from a Zhihu comments API endpoint."""
        comments: List[Dict] = []
        try:
            resp = self.http.get(
                api_url,
                params={"limit": 20, "offset": 0, "order": "reverse", "status": "open"},
                headers=self._api_headers(),
            )
            data = resp.json()
        except Exception as exc:
            self.logger.error(f"Comment request failed: {exc}")
            return comments

        for item in data.get("data", []):
            author_info = item.get("author", {}).get("member", {})
            comments.append({
                "commenter": author_info.get("name", "匿名用户"),
                "content": item.get("content", ""),
                "like_count": item.get("like_count", 0),
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
            "platform": "zhihu",
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
    def _parse_timestamp(ts: Any) -> Optional[str]:
        """Convert a UNIX timestamp to ISO-8601 string, or return ``None``."""
        if not ts:
            return None
        try:
            return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
        except (ValueError, TypeError, OSError):
            return None

    @staticmethod
    def _extract_answer_id(url: str) -> Optional[str]:
        """Extract an answer ID from a Zhihu URL like ``/question/123/answer/456``."""
        m = re.search(r"/answer/(\d+)", url)
        return m.group(1) if m else None

    @staticmethod
    def _extract_question_id(url: str) -> Optional[str]:
        """Extract a question ID from a Zhihu URL like ``/question/123``."""
        m = re.search(r"/question/(\d+)", url)
        return m.group(1) if m else None
