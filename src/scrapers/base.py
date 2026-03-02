"""
Abstract base class for all platform scrapers.

Provides shared infrastructure — HTTP client, rate limiting, dedup cache,
block detection, crawl logging, and a standard ``run()`` pipeline — so that
concrete scrapers only need to implement platform-specific fetching logic.
"""

from __future__ import annotations

import math
import urllib.parse
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, List, Optional, Set

from src.storage.database import (
    get_article_by_platform_id,
    get_session,
    save_article as db_save_article,
    save_crawl_log,
)
from src.storage.models import Article, CrawlLog
from src.utils.anti_crawl import BlockDetector
from src.utils.config import get_platform_config, get_settings
from src.utils.http_client import HttpClient
from src.utils.logger import get_logger, highlight_important
from src.utils.rate_limiter import get_rate_limiter
from src.utils.text_cleaner import clean_text

from sqlalchemy import select


class BaseScraper(ABC):
    """Abstract base class that every platform scraper must extend.

    Subclasses **must** implement:
    * :meth:`get_hot_articles_list`
    * :meth:`get_article_detail`

    And **may** override:
    * :meth:`get_hot_comments`
    """

    # Default max values for heat-score normalisation
    _DEFAULT_MAX_VIEW: int = 1_000_000
    _DEFAULT_MAX_LIKE: int = 100_000
    _DEFAULT_MAX_COMMENT: int = 10_000
    _DEFAULT_MAX_SHARE: int = 50_000

    # Weights for heat-score components
    _WEIGHT_VIEW: float = 0.3
    _WEIGHT_LIKE: float = 0.4
    _WEIGHT_COMMENT: float = 0.2
    _WEIGHT_SHARE: float = 0.1

    # Number of consecutive failures before the scraper should stop
    _MAX_CONSECUTIVE_FAILURES: int = 5

    def __init__(self, platform_name: str) -> None:
        """Initialise common scraper infrastructure.

        Args:
            platform_name: Identifier used across config, logging and storage
                           (e.g. ``"zhihu"``, ``"weibo"``).
        """
        self.platform_name: str = platform_name
        self.config: dict = get_platform_config(platform_name)
        self.settings = get_settings()
        self.logger = get_logger(f"scraper.{platform_name}")
        self.http: HttpClient = HttpClient(platform_name, self.config)
        self.rate_limiter = get_rate_limiter()
        self.block_detector: BlockDetector = BlockDetector()

        # URL dedup cache — pre-loaded from the database for this platform
        self._url_cache: Set[str] = self._load_url_cache()

        # Resume position from the latest crawl log
        self._last_position: Optional[str] = self._load_last_position()

        # Counters updated during a run
        self._articles_found: int = 0
        self._articles_new: int = 0
        self._consecutive_failures: int = 0

    # ------------------------------------------------------------------
    # Abstract methods
    # ------------------------------------------------------------------

    @abstractmethod
    def get_hot_articles_list(self) -> List[Dict]:
        """Fetch the platform's hot/trending article list.

        Returns:
            A list of dicts, each containing at least ``title``, ``url``,
            and basic metrics (``view_count``, ``like_count``, etc.).
        """

    @abstractmethod
    def get_article_detail(self, url: str) -> Dict:
        """Fetch full content and metadata for a single article.

        Args:
            url: The article URL.

        Returns:
            A dict suitable for passing to :func:`save_article`.
        """

    def get_hot_comments(self, url: str) -> List[Dict]:
        """Fetch top/hot comments for an article (optional).

        The default implementation returns an empty list.  Override in
        subclasses that support comment scraping.

        Args:
            url: The article URL.

        Returns:
            A list of comment dicts.
        """
        return []

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(self, limit: Optional[int] = None) -> Dict:
        """Execute a full scraping run: list → filter → detail → save.

        Args:
            limit: Maximum number of *new* articles to fetch.  ``None`` means
                   no limit (scrape everything returned by the list endpoint).

        Returns:
            A summary dict with ``articles_found``, ``articles_new``, and
            ``status``.
        """
        self.logger.info(f"Starting scrape run for {self.platform_name}")

        crawl_log_data = {
            "platform": self.platform_name,
            "start_time": datetime.now(),
            "status": "running",
        }
        crawl_log = save_crawl_log(crawl_log_data)

        self._articles_found = 0
        self._articles_new = 0
        self._consecutive_failures = 0
        status = "completed"
        error_message: Optional[str] = None

        try:
            # 1. Get article list
            self.logger.info("Fetching hot articles list...")
            articles_list = self.get_hot_articles_list()
            self._articles_found = len(articles_list)
            self.logger.info(f"Found {self._articles_found} articles")

            # 2. Filter & fetch details
            new_count = 0
            for article_meta in articles_list:
                if self.should_stop():
                    self.logger.warning("Block detector triggered — stopping early")
                    status = "stopped_blocked"
                    break

                if limit is not None and new_count >= limit:
                    self.logger.info(f"Reached limit of {limit} new articles")
                    break

                url = article_meta.get("url", "")
                if self.is_duplicate(url):
                    self.logger.debug(f"Skipping duplicate: {url}")
                    continue

                # Rate-limit before each detail request
                self.rate_limiter.wait(self.platform_name)

                try:
                    detail = self.get_article_detail(url)
                    if not detail:
                        self._record_failure()
                        continue

                    # Merge list-level metadata with detail
                    merged = {**article_meta, **detail}
                    merged.setdefault("platform", self.platform_name)

                    # Compute heat score if not provided
                    if "heat_score" not in merged or merged["heat_score"] is None:
                        merged["heat_score"] = self.normalize_heat_score(
                            view_count=merged.get("view_count", 0),
                            like_count=merged.get("like_count", 0),
                            comment_count=merged.get("comment_count", 0),
                            share_count=merged.get("share_count", 0),
                        )

                    # Optionally fetch comments
                    try:
                        comments = self.get_hot_comments(url)
                        if comments:
                            merged["hot_comments"] = comments
                    except Exception as exc:
                        self.logger.debug(f"Failed to fetch comments for {url}: {exc}")

                    saved = self.save_article(merged)
                    if saved:
                        new_count += 1
                        self._articles_new = new_count
                        self._consecutive_failures = 0

                except Exception as exc:
                    self.logger.error(f"Error fetching detail for {url}: {exc}")
                    self._record_failure()

        except Exception as exc:
            status = "failed"
            error_message = str(exc)
            self.logger.error(f"Scrape run failed: {exc}")
            highlight_important(f"Scrape run failed for {self.platform_name}: {exc}", 9)

        finally:
            # Update crawl log
            end_time = datetime.now()
            with get_session() as session:
                log = session.get(CrawlLog, crawl_log.id)
                if log is not None:
                    log.end_time = end_time
                    log.status = status
                    log.articles_found = self._articles_found
                    log.articles_new = self._articles_new
                    log.error_message = error_message

            self.logger.info(
                f"Scrape run finished: status={status}, "
                f"found={self._articles_found}, new={self._articles_new}"
            )

        return {
            "status": status,
            "articles_found": self._articles_found,
            "articles_new": self._articles_new,
        }

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def save_article(self, article_data: dict) -> bool:
        """Save an article to the database with dedup check.

        Args:
            article_data: Article fields dict.

        Returns:
            ``True`` if a *new* article was inserted, ``False`` if it was a
            duplicate or the save failed.
        """
        url = article_data.get("url", "")
        platform_id = article_data.get("platform_id")

        # Check dedup via platform_id
        if platform_id and get_article_by_platform_id(self.platform_name, platform_id):
            self.logger.debug(f"Article already exists (platform_id={platform_id})")
            self._url_cache.add(url)
            return False

        try:
            db_save_article(article_data)
            self._url_cache.add(url)
            self.logger.debug(f"Saved article: {article_data.get('title', url)}")
            return True
        except Exception as exc:
            self.logger.error(f"Failed to save article {url}: {exc}")
            return False

    def is_duplicate(self, url: str) -> bool:
        """Check whether *url* is already in the in-memory cache.

        Args:
            url: Article URL to check.

        Returns:
            ``True`` if the URL has been seen before.
        """
        return url in self._url_cache

    # ------------------------------------------------------------------
    # Robots.txt compliance
    # ------------------------------------------------------------------

    def check_robots_txt(self, url: str) -> bool:
        """Perform a basic robots.txt compliance check.

        Fetches ``/robots.txt`` from the URL's host and checks whether the
        given path is disallowed for ``*`` user-agent.

        Args:
            url: The target URL to verify.

        Returns:
            ``True`` if the URL is **allowed** (or robots.txt is unavailable),
            ``False`` if it is disallowed.
        """
        try:
            parsed = urllib.parse.urlparse(url)
            robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
            resp = self.http.get(robots_url)
            if resp is None or not hasattr(resp, "text"):
                return True

            text = resp.text if hasattr(resp, "text") else str(resp)
            path = parsed.path or "/"

            # Simple parser: look for Disallow rules under User-agent: *
            in_star_block = False
            for line in text.splitlines():
                line = line.strip()
                if line.lower().startswith("user-agent:"):
                    agent = line.split(":", 1)[1].strip()
                    in_star_block = agent == "*"
                elif in_star_block and line.lower().startswith("disallow:"):
                    disallowed = line.split(":", 1)[1].strip()
                    if disallowed and path.startswith(disallowed):
                        self.logger.debug(f"URL disallowed by robots.txt: {url}")
                        return False

            return True
        except Exception as exc:
            self.logger.debug(f"robots.txt check failed for {url}: {exc}")
            return True  # permissive on failure

    # ------------------------------------------------------------------
    # Heat-score normalisation
    # ------------------------------------------------------------------

    def normalize_heat_score(
        self,
        view_count: int = 0,
        like_count: int = 0,
        comment_count: int = 0,
        share_count: int = 0,
        *,
        max_view: int | None = None,
        max_like: int | None = None,
        max_comment: int | None = None,
        max_share: int | None = None,
    ) -> float:
        """Compute a logarithmic heat score normalised to 0–100.

        Formula per component::

            component_score = weight * log(1 + count) / log(1 + max_val) * 100

        Final score is the weighted sum (already includes × 100 in each term,
        and weights sum to 1.0, so the result is in 0–100).

        Args:
            view_count: Number of views.
            like_count: Number of likes.
            comment_count: Number of comments.
            share_count: Number of shares.
            max_view: Upper reference for views (default 1 000 000).
            max_like: Upper reference for likes (default 100 000).
            max_comment: Upper reference for comments (default 10 000).
            max_share: Upper reference for shares (default 50 000).

        Returns:
            A float between 0 and ~100 (can slightly exceed 100 if counts
            surpass the max reference values).
        """
        mv = max_view if max_view is not None else self._DEFAULT_MAX_VIEW
        ml = max_like if max_like is not None else self._DEFAULT_MAX_LIKE
        mc = max_comment if max_comment is not None else self._DEFAULT_MAX_COMMENT
        ms = max_share if max_share is not None else self._DEFAULT_MAX_SHARE

        def _norm(count: int, max_val: int) -> float:
            if max_val <= 0:
                return 0.0
            return math.log(1 + count) / math.log(1 + max_val) * 100

        score = (
            self._WEIGHT_VIEW * _norm(view_count, mv)
            + self._WEIGHT_LIKE * _norm(like_count, ml)
            + self._WEIGHT_COMMENT * _norm(comment_count, mc)
            + self._WEIGHT_SHARE * _norm(share_count, ms)
        )
        return round(score, 2)

    # ------------------------------------------------------------------
    # Block / failure detection
    # ------------------------------------------------------------------

    def should_stop(self) -> bool:
        """Return ``True`` if the scraper should abort the current run.

        Currently checks whether the number of consecutive failures has
        reached :attr:`_MAX_CONSECUTIVE_FAILURES`.

        Returns:
            Whether the scraper should stop.
        """
        return self._consecutive_failures >= self._MAX_CONSECUTIVE_FAILURES

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _record_failure(self) -> None:
        """Increment the consecutive failure counter and notify the block detector."""
        self._consecutive_failures += 1
        self.block_detector.record_failure(self.platform_name)
        self.logger.warning(
            f"Consecutive failure #{self._consecutive_failures} "
            f"on {self.platform_name}"
        )

    def _load_url_cache(self) -> Set[str]:
        """Load all known article URLs for this platform from the database."""
        urls: Set[str] = set()
        try:
            with get_session() as session:
                stmt = select(Article.url).where(
                    Article.platform == self.platform_name
                )
                rows = session.execute(stmt).scalars().all()
                urls = set(rows)
            self.logger.debug(f"Loaded {len(urls)} cached URLs for {self.platform_name}")
        except Exception as exc:
            self.logger.warning(f"Failed to load URL cache: {exc}")
        return urls

    def _load_last_position(self) -> Optional[str]:
        """Read ``last_position`` from the most recent completed crawl log."""
        try:
            with get_session() as session:
                stmt = (
                    select(CrawlLog.last_position)
                    .where(
                        CrawlLog.platform == self.platform_name,
                        CrawlLog.status == "completed",
                    )
                    .order_by(CrawlLog.start_time.desc())
                    .limit(1)
                )
                pos = session.execute(stmt).scalar_one_or_none()
            if pos:
                self.logger.info(f"Resuming from last position: {pos}")
            return pos
        except Exception as exc:
            self.logger.warning(f"Failed to load last position: {exc}")
            return None
