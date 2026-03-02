"""
脉脉爬虫 — 抓取「职言」板块热门话题与讨论。

Strategy
--------
1. 使用脉脉 Web API（需 Cookie 认证）获取职言热门列表。
2. 解析 JSON 响应，提取话题标题、讨论内容与互动数据。
3. 逐条获取话题详情与热门评论。

Notes
-----
* 脉脉需要登录态（Cookie），默认在配置中关闭 (``enabled: false``)。
* Cookie 通过 ``self.config.get('cookie', '')`` 获取。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.scrapers.base import BaseScraper
from src.utils.text_cleaner import clean_text


class MaimaiScraper(BaseScraper):
    """脉脉职言爬虫，抓取热门职场讨论话题。"""

    _GOSSIP_LIST_URL = "https://maimai.cn/sdk/web/gossip/list"
    _GOSSIP_DETAIL_URL = "https://maimai.cn/sdk/web/gossip/detail"
    _GOSSIP_COMMENTS_URL = "https://maimai.cn/sdk/web/gossip/comments"

    def __init__(self) -> None:
        super().__init__("maimai")
        self._cookie: str = self.config.get("cookie", "")

    # ------------------------------------------------------------------
    # Keyword helpers
    # ------------------------------------------------------------------

    def get_keywords(self) -> List[str]:
        """Return combined primary + secondary keywords from global settings."""
        kw_conf: Dict[str, Any] = self.settings.get("keywords", {})
        primary: List[str] = kw_conf.get("primary", [])
        secondary: List[str] = kw_conf.get("secondary", [])
        return primary + secondary

    # ------------------------------------------------------------------
    # Auth helpers
    # ------------------------------------------------------------------

    def _build_headers(self) -> Dict[str, str]:
        """构建带 Cookie 的请求头。

        Returns:
            包含认证信息的 HTTP 请求头字典。
        """
        headers: Dict[str, str] = {
            "Accept": "application/json",
            "Referer": "https://maimai.cn/",
        }
        if self._cookie:
            headers["Cookie"] = self._cookie
        else:
            self.logger.warning("No cookie configured for maimai — requests may fail")
        return headers

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_hot_articles_list(self) -> List[Dict]:
        """获取脉脉「职言」热门话题列表。

        Returns:
            包含话题元数据的字典列表。
        """
        articles: List[Dict] = []
        self.logger.info("Fetching maimai gossip (职言) hot list")

        try:
            resp = self.http.get(
                self._GOSSIP_LIST_URL,
                headers=self._build_headers(),
                params={"page": 0},
            )
            data = resp.json()

            gossip_list: List[Dict] = data.get("data", {}).get("gossip_list", [])
            if not gossip_list:
                self.logger.warning("Empty gossip list returned from maimai API")
                return articles

            for item in gossip_list:
                try:
                    article = self._parse_gossip_item(item)
                    if article:
                        articles.append(article)
                except Exception as exc:
                    self.logger.debug(f"Failed to parse gossip item: {exc}")

        except Exception as exc:
            self.logger.error(f"Failed to fetch maimai gossip list: {exc}")
            self._record_failure()

        self.logger.info(f"Collected {len(articles)} topics from maimai 职言")
        return articles

    def get_article_detail(self, url: str) -> Dict:
        """获取单条职言话题的详细内容。

        Args:
            url: 话题页面链接或包含 gossip_id 的 URL。

        Returns:
            包含 content、raw_html、summary 的字典。
        """
        gossip_id = self._extract_gossip_id(url)
        if not gossip_id:
            self.logger.warning(f"Cannot extract gossip_id from URL: {url}")
            return {}

        self.logger.debug(f"Fetching maimai gossip detail: {gossip_id}")

        try:
            resp = self.http.get(
                self._GOSSIP_DETAIL_URL,
                headers=self._build_headers(),
                params={"gossip_id": gossip_id},
            )
            data = resp.json()

            gossip: Dict = data.get("data", {}).get("gossip", {})
            if not gossip:
                self.logger.warning(f"No detail returned for gossip_id={gossip_id}")
                return {}

            text = clean_text(gossip.get("text", ""))
            summary = text[:200].strip() if text else ""

            return {
                "content": text,
                "raw_html": gossip.get("text", ""),
                "summary": summary,
            }

        except Exception as exc:
            self.logger.error(
                f"Failed to fetch gossip detail (id={gossip_id}): {exc}"
            )
            return {}

    def get_hot_comments(self, url: str) -> List[Dict]:
        """获取职言话题的热门评论。

        Args:
            url: 话题链接。

        Returns:
            评论字典列表，每条包含 commenter、content、like_count。
        """
        gossip_id = self._extract_gossip_id(url)
        if not gossip_id:
            return []

        self.logger.debug(f"Fetching comments for gossip_id={gossip_id}")

        try:
            resp = self.http.get(
                self._GOSSIP_COMMENTS_URL,
                headers=self._build_headers(),
                params={"gossip_id": gossip_id, "page": 0},
            )
            data = resp.json()

            raw_comments: List[Dict] = data.get("data", {}).get("comments", [])
            comments: List[Dict] = []

            for c in raw_comments:
                try:
                    comment = self._parse_comment(c)
                    if comment:
                        comments.append(comment)
                except Exception as exc:
                    self.logger.debug(f"Failed to parse comment: {exc}")

            return comments

        except Exception as exc:
            self.logger.error(
                f"Failed to fetch comments (gossip_id={gossip_id}): {exc}"
            )
            return []

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _parse_gossip_item(self, item: Dict) -> Optional[Dict]:
        """解析单条职言数据。

        Args:
            item: API 返回的单条职言 JSON 对象。

        Returns:
            标准化的文章元数据字典，解析失败返回 ``None``。
        """
        gossip_id = str(item.get("id", ""))
        if not gossip_id:
            return None

        text = item.get("text", "")
        # 标题取首行或前 50 字
        title = clean_text(text.split("\n")[0][:50]) if text else ""
        if not title:
            return None

        url = f"https://maimai.cn/gossip_detail?gid={gossip_id}"

        # 作者信息
        user_info: Dict = item.get("user", {})
        author = user_info.get("name", "匿名用户")

        like_count = int(item.get("likes", 0))
        comment_count = int(item.get("comment_count", 0))

        # 脉脉 API 中 publish_time 通常为 Unix 时间戳
        publish_time = item.get("created_at", "")

        return {
            "platform": self.platform_name,
            "platform_id": gossip_id,
            "title": title,
            "url": url,
            "author": author,
            "view_count": 0,
            "like_count": like_count,
            "comment_count": comment_count,
            "share_count": 0,
            "publish_time": str(publish_time),
        }

    def _parse_comment(self, comment_data: Dict) -> Optional[Dict]:
        """解析单条评论数据。

        Args:
            comment_data: API 返回的评论 JSON 对象。

        Returns:
            标准化评论字典，解析失败返回 ``None``。
        """
        text = comment_data.get("text", "")
        if not text:
            return None

        user_info: Dict = comment_data.get("user", {})
        commenter = user_info.get("name", "匿名用户")
        like_count = int(comment_data.get("likes", 0))

        return {
            "commenter": commenter,
            "content": clean_text(text),
            "like_count": like_count,
        }

    @staticmethod
    def _extract_gossip_id(url: str) -> Optional[str]:
        """从 URL 中提取 gossip_id。

        支持格式:
        - ``https://maimai.cn/gossip_detail?gid=123``
        - 纯数字 ID 字符串

        Args:
            url: 话题链接或 ID。

        Returns:
            gossip_id 字符串，无法提取时返回 ``None``。
        """
        if not url:
            return None

        # 纯数字直接返回
        if url.isdigit():
            return url

        # 从 URL 参数中提取 gid
        from urllib.parse import parse_qs, urlparse

        try:
            parsed = urlparse(url)
            params = parse_qs(parsed.query)
            gid = params.get("gid", [None])[0]
            if gid:
                return gid

            # 尝试从路径中提取数字 ID
            parts = parsed.path.strip("/").split("/")
            for part in reversed(parts):
                if part.isdigit():
                    return part
        except Exception:
            pass

        return None
