"""
微信公众号爬虫 — 通过搜狗微信搜索抓取职场相关公众号文章。

Strategy
--------
1. 使用搜狗微信搜索 (weixin.sogou.com) 按关键词搜索公众号文章。
2. 解析搜索结果页 HTML，提取文章元数据与跳转链接。
3. 跟随链接到 mp.weixin.qq.com 获取文章正文。

Notes
-----
* 搜狗对爬虫限制严格（验证码），默认请求间隔 15 s。
* 配置 ``use_playwright: true`` 可启用浏览器渲染（尚未实现，标记为 TODO）。
"""

from __future__ import annotations

import hashlib
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup

from src.scrapers.base import BaseScraper
from src.utils.anti_crawl import is_captcha_page
from src.utils.text_cleaner import clean_text, extract_text_from_html


class WeixinSogouScraper(BaseScraper):
    """搜狗微信搜索爬虫，抓取职场类公众号文章。"""

    _SEARCH_URL = "https://weixin.sogou.com/weixin"

    def __init__(self) -> None:
        super().__init__("weixin_sogou")
        self._use_playwright: bool = self.config.get("use_playwright", False)

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
    # Public API
    # ------------------------------------------------------------------

    def get_hot_articles_list(self) -> List[Dict]:
        """搜索搜狗微信，按关键词聚合文章列表。

        Returns:
            包含基本元数据的文章字典列表。
        """
        articles: List[Dict] = []
        seen_urls: set[str] = set()

        for keyword in self.get_keywords():
            if self.should_stop():
                break

            self.logger.info(f"Searching Sogou Weixin for keyword: {keyword}")
            self.rate_limiter.wait(self.platform_name)

            try:
                page_articles = self._search_keyword(keyword)
                for art in page_articles:
                    url = art.get("url", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        articles.append(art)
            except Exception as exc:
                self.logger.error(f"Failed to search keyword '{keyword}': {exc}")
                self._record_failure()

        self.logger.info(f"Collected {len(articles)} articles from Sogou Weixin search")
        return articles

    def get_article_detail(self, url: str) -> Dict:
        """获取微信公众号文章正文。

        Args:
            url: mp.weixin.qq.com 文章链接。

        Returns:
            包含 content、raw_html、summary 的字典。
        """
        # TODO: 当 use_playwright 为 True 时，使用 Playwright 渲染页面
        if self._use_playwright:
            self.logger.debug(
                "Playwright rendering requested but not yet implemented; "
                "falling back to HTTP"
            )

        self.logger.debug(f"Fetching article detail: {url}")

        try:
            resp = self.http.get(url)
            html = resp.text

            if is_captcha_page(html):
                self.logger.warning("Captcha detected on article page, skipping")
                self._record_failure()
                return {}

            soup = BeautifulSoup(html, "html.parser")

            # 微信文章正文通常在 #js_content 容器内
            content_div = soup.select_one("#js_content")
            raw_html = str(content_div) if content_div else ""
            text = clean_text(content_div.get_text(separator="\n")) if content_div else ""

            # 摘要：取前 200 字
            summary = text[:200].strip() if text else ""

            return {
                "content": text,
                "raw_html": raw_html,
                "summary": summary,
            }

        except Exception as exc:
            self.logger.error(f"Failed to fetch article detail ({url}): {exc}")
            return {}

    def get_hot_comments(self, url: str) -> List[Dict]:
        """获取文章热门评论。

        微信文章评论需要登录态且通过 JS 加载，当前返回空列表。

        Args:
            url: 文章链接。

        Returns:
            评论字典列表（当前为空）。
        """
        # 微信评论接口需要登录态，暂不支持
        self.logger.debug("WeChat comment scraping is not supported yet")
        return []

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _search_keyword(self, keyword: str) -> List[Dict]:
        """执行单个关键词的搜狗微信搜索并解析结果。

        Args:
            keyword: 搜索关键词。

        Returns:
            该关键词搜索结果中的文章列表。
        """
        params = {
            "type": "2",  # 2 = 文章搜索
            "query": keyword,
        }
        resp = self.http.get(self._SEARCH_URL, params=params)
        html = resp.text

        if is_captcha_page(html):
            self.logger.warning(
                f"Captcha detected on search page for '{keyword}', aborting keyword"
            )
            self._record_failure()
            return []

        return self._parse_search_results(html, keyword)

    def _parse_search_results(self, html: str, keyword: str) -> List[Dict]:
        """解析搜狗微信搜索结果页面 HTML。

        Args:
            html: 搜索结果页面原始 HTML。
            keyword: 当前搜索使用的关键词（用于日志）。

        Returns:
            解析出的文章元数据列表。
        """
        articles: List[Dict] = []
        soup = BeautifulSoup(html, "html.parser")

        result_items = soup.select("ul.news-list > li") or soup.select(".news-list li")

        for item in result_items:
            try:
                article = self._parse_single_result(item)
                if article:
                    articles.append(article)
            except Exception as exc:
                self.logger.debug(f"Failed to parse a search result item: {exc}")

        self.logger.debug(
            f"Parsed {len(articles)} articles for keyword '{keyword}'"
        )
        return articles

    def _parse_single_result(self, item: BeautifulSoup) -> Optional[Dict]:
        """解析单条搜索结果 HTML 元素。

        Args:
            item: 搜索结果列表中的单个 ``<li>`` 元素。

        Returns:
            文章元数据字典，解析失败返回 ``None``。
        """
        # 标题与链接
        title_tag = item.select_one("h3 a") or item.select_one(".txt-box h3 a")
        if not title_tag:
            return None

        title = clean_text(title_tag.get_text())
        href = title_tag.get("href", "")
        url = urljoin(self._SEARCH_URL, href) if href else ""
        if not url:
            return None

        # 作者 / 公众号名称
        account_tag = item.select_one(".account") or item.select_one(".s-p a")
        author = clean_text(account_tag.get_text()) if account_tag else ""

        # 发布时间（搜狗页面中通常以时间戳存储在 data 属性中）
        publish_time = ""
        time_tag = item.select_one(".s-p") or item.select_one(".s2")
        if time_tag:
            ts = time_tag.get("t", "")
            if ts and ts.isdigit():
                try:
                    publish_time = time.strftime(
                        "%Y-%m-%d %H:%M:%S", time.localtime(int(ts))
                    )
                except (ValueError, OSError):
                    pass

        # 生成平台内唯一 ID（搜狗搜索链接的 MD5）
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
