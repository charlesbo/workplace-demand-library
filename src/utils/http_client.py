"""Unified HTTP client wrapper around httpx with retry, proxy, and anti-crawl support."""

from __future__ import annotations

import asyncio
import random
import time
from typing import Any

import httpx

from src.utils.logger import get_logger

logger = get_logger(__name__)


class HttpClient:
    """Unified HTTP client with retry, proxy rotation, rate limiting, and header management.

    Wraps httpx for both synchronous and asynchronous requests, providing:
    - Automatic retry with exponential backoff
    - Configurable timeout and proxy support (HTTP/SOCKS)
    - User-Agent rotation via anti_crawl module
    - Full request headers (Referer, Accept-Language, Accept, etc.)
    - Cookie injection
    - Rate limiting integration

    Args:
        platform: Name of the platform being scraped (used for logging and rate limiting).
        config: Platform-specific configuration dict. Expected keys:
            - ``max_retries`` (int): Maximum retry attempts (default 3).
            - ``retry_base`` (float): Base seconds for exponential backoff (default 1.0).
            - ``timeout`` (int | float): Request timeout in seconds (default 30).
            - ``proxy_list`` (list[str]): List of proxy URLs (HTTP or SOCKS).
            - ``cookies`` (dict): Cookies to inject into every request.
            - ``headers`` (dict): Extra headers merged into defaults.
            - ``rate_limit`` (dict): Passed to the rate limiter (e.g. ``requests_per_second``).
    """

    # Status codes that signal we should back off or stop
    _RATE_LIMIT_CODES = {429}
    _BLOCK_CODES = {403, 503}
    _RETRYABLE_CODES = _RATE_LIMIT_CODES | _BLOCK_CODES | {500, 502, 504}

    def __init__(self, platform: str, config: dict[str, Any]) -> None:
        self.platform = platform
        self.config = config

        self.max_retries: int = config.get("max_retries", 3)
        self.retry_base: float = config.get("retry_base", 1.0)
        self.timeout: float = config.get("timeout", 30)
        self.proxy_list: list[str] = config.get("proxy_list", [])
        self.cookies: dict[str, str] = config.get("cookies", {})
        self.extra_headers: dict[str, str] = config.get("headers", {})
        self.rate_limit_config: dict[str, Any] = config.get("rate_limit", {})

        self._rate_limiter: Any | None = None
        self._anti_crawl: Any | None = None
        self._init_optional_modules()

    # ------------------------------------------------------------------
    # Optional module integration
    # ------------------------------------------------------------------

    def _init_optional_modules(self) -> None:
        """Lazily import optional anti_crawl and rate_limiter modules."""
        try:
            from src.utils.rate_limiter import RateLimiter  # type: ignore[import-untyped]

            self._rate_limiter = RateLimiter()
            interval = (self.rate_limit_config or {}).get("interval", 2)
            self._rate_limiter.configure(self.platform, interval)
            logger.debug("Rate limiter initialised for {}", self.platform)
        except ImportError:
            logger.debug("rate_limiter module not available — skipping rate limiting")

        try:
            from src.utils.anti_crawl import get_user_agent  # type: ignore[import-untyped]

            self._anti_crawl = get_user_agent
            logger.debug("anti_crawl module loaded for User-Agent rotation")
        except ImportError:
            logger.debug("anti_crawl module not available — using default User-Agent")

    # ------------------------------------------------------------------
    # Header helpers
    # ------------------------------------------------------------------

    def _build_headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        """Build a full set of request headers.

        Merges default browser-like headers, platform-level overrides,
        per-request overrides, and a rotated User-Agent.

        Args:
            extra: Per-request header overrides.

        Returns:
            Merged header dict ready for use with httpx.
        """
        user_agent = (
            self._anti_crawl()
            if self._anti_crawl is not None
            else "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        )

        headers: dict[str, str] = {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Cache-Control": "no-cache",
        }
        # Platform-level overrides
        headers.update(self.extra_headers)
        # Per-request overrides
        if extra:
            headers.update(extra)
        return headers

    # ------------------------------------------------------------------
    # Proxy helpers
    # ------------------------------------------------------------------

    def _pick_proxy(self) -> str | None:
        """Randomly select a proxy from the configured proxy list.

        Returns:
            A proxy URL string, or ``None`` if no proxies are configured.
        """
        if not self.proxy_list:
            return None
        return random.choice(self.proxy_list)  # noqa: S311

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    def _wait_for_rate_limit(self) -> None:
        """Block until the rate limiter allows the next request (sync)."""
        if self._rate_limiter is not None:
            self._rate_limiter.wait(self.platform)

    async def _async_wait_for_rate_limit(self) -> None:
        """Await until the rate limiter allows the next request (async)."""
        if self._rate_limiter is not None:
            if asyncio.iscoroutinefunction(getattr(self._rate_limiter, "async_wait", None)):
                await self._rate_limiter.async_wait(self.platform)
            else:
                self._rate_limiter.wait(self.platform)

    # ------------------------------------------------------------------
    # Retry / back-off helpers
    # ------------------------------------------------------------------

    def _backoff_delay(self, attempt: int) -> float:
        """Calculate exponential backoff delay with jitter.

        Args:
            attempt: Zero-based retry attempt number.

        Returns:
            Delay in seconds before the next retry.
        """
        delay = self.retry_base * (2 ** attempt) + random.uniform(0, 1)  # noqa: S311
        return min(delay, 60.0)

    def _should_retry(self, status_code: int) -> bool:
        """Decide whether a response status code warrants a retry.

        Args:
            status_code: HTTP status code from the response.

        Returns:
            ``True`` if the request should be retried.
        """
        return status_code in self._RETRYABLE_CODES

    # ------------------------------------------------------------------
    # Core request (sync)
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """Execute an HTTP request with retry, proxy, headers, and rate limiting.

        Args:
            method: HTTP method (``GET``, ``POST``, etc.).
            url: Target URL.
            **kwargs: Extra arguments forwarded to ``httpx.Client.request``.
                The ``headers`` key is merged with built-in defaults.

        Returns:
            The :class:`httpx.Response` from a successful request.

        Raises:
            httpx.HTTPStatusError: If all retries are exhausted and the last
                response had an error status code.
            httpx.RequestError: If a connection-level error persists after retries.
        """
        request_headers = self._build_headers(kwargs.pop("headers", None))
        cookies = {**self.cookies, **kwargs.pop("cookies", {})}

        last_exc: BaseException | None = None

        for attempt in range(self.max_retries + 1):
            self._wait_for_rate_limit()

            proxy = self._pick_proxy()
            transport_kwargs: dict[str, Any] = {}
            if proxy:
                transport_kwargs["proxy"] = proxy

            try:
                with httpx.Client(
                    timeout=self.timeout,
                    cookies=cookies,
                    follow_redirects=True,
                    **transport_kwargs,
                ) as client:
                    logger.debug(
                        "[{}] {} {} (attempt {}/{}{})",
                        self.platform,
                        method.upper(),
                        url,
                        attempt + 1,
                        self.max_retries + 1,
                        f" proxy={proxy}" if proxy else "",
                    )
                    response = client.request(method, url, headers=request_headers, **kwargs)

                if response.status_code in self._RATE_LIMIT_CODES:
                    retry_after = float(response.headers.get("Retry-After", self._backoff_delay(attempt)))
                    logger.warning(
                        "[{}] 429 rate-limited on {} — backing off {:.1f}s",
                        self.platform, url, retry_after,
                    )
                    time.sleep(retry_after)
                    continue

                if response.status_code in self._BLOCK_CODES:
                    logger.warning(
                        "[{}] {} possible block on {} — retrying",
                        self.platform, response.status_code, url,
                    )
                    time.sleep(self._backoff_delay(attempt))
                    continue

                if self._should_retry(response.status_code):
                    logger.warning(
                        "[{}] HTTP {} on {} — retrying",
                        self.platform, response.status_code, url,
                    )
                    time.sleep(self._backoff_delay(attempt))
                    continue

                response.raise_for_status()
                return response

            except httpx.RequestError as exc:
                last_exc = exc
                logger.warning(
                    "[{}] Connection error on {} — {} (attempt {}/{})",
                    self.platform, url, exc, attempt + 1, self.max_retries + 1,
                )
                if attempt < self.max_retries:
                    time.sleep(self._backoff_delay(attempt))
                    continue
                raise

        # All retries exhausted — return last response or re-raise
        if last_exc is not None:
            raise last_exc  # pragma: no cover
        logger.error("[{}] All {} retries exhausted for {}", self.platform, self.max_retries, url)
        response.raise_for_status()  # type: ignore[possibly-undefined]
        return response  # type: ignore[possibly-undefined]

    # ------------------------------------------------------------------
    # Core request (async)
    # ------------------------------------------------------------------

    async def _async_request(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """Execute an async HTTP request with retry, proxy, headers, and rate limiting.

        Args:
            method: HTTP method (``GET``, ``POST``, etc.).
            url: Target URL.
            **kwargs: Extra arguments forwarded to ``httpx.AsyncClient.request``.
                The ``headers`` key is merged with built-in defaults.

        Returns:
            The :class:`httpx.Response` from a successful request.

        Raises:
            httpx.HTTPStatusError: If all retries are exhausted and the last
                response had an error status code.
            httpx.RequestError: If a connection-level error persists after retries.
        """
        request_headers = self._build_headers(kwargs.pop("headers", None))
        cookies = {**self.cookies, **kwargs.pop("cookies", {})}

        last_exc: BaseException | None = None

        for attempt in range(self.max_retries + 1):
            await self._async_wait_for_rate_limit()

            proxy = self._pick_proxy()
            transport_kwargs: dict[str, Any] = {}
            if proxy:
                transport_kwargs["proxy"] = proxy

            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout,
                    cookies=cookies,
                    follow_redirects=True,
                    **transport_kwargs,
                ) as client:
                    logger.debug(
                        "[{}] async {} {} (attempt {}/{}{})",
                        self.platform,
                        method.upper(),
                        url,
                        attempt + 1,
                        self.max_retries + 1,
                        f" proxy={proxy}" if proxy else "",
                    )
                    response = await client.request(method, url, headers=request_headers, **kwargs)

                if response.status_code in self._RATE_LIMIT_CODES:
                    retry_after = float(response.headers.get("Retry-After", self._backoff_delay(attempt)))
                    logger.warning(
                        "[{}] 429 rate-limited on {} — backing off {:.1f}s",
                        self.platform, url, retry_after,
                    )
                    await asyncio.sleep(retry_after)
                    continue

                if response.status_code in self._BLOCK_CODES:
                    logger.warning(
                        "[{}] {} possible block on {} — retrying",
                        self.platform, response.status_code, url,
                    )
                    await asyncio.sleep(self._backoff_delay(attempt))
                    continue

                if self._should_retry(response.status_code):
                    logger.warning(
                        "[{}] HTTP {} on {} — retrying",
                        self.platform, response.status_code, url,
                    )
                    await asyncio.sleep(self._backoff_delay(attempt))
                    continue

                response.raise_for_status()
                return response

            except httpx.RequestError as exc:
                last_exc = exc
                logger.warning(
                    "[{}] Connection error on {} — {} (attempt {}/{})",
                    self.platform, url, exc, attempt + 1, self.max_retries + 1,
                )
                if attempt < self.max_retries:
                    await asyncio.sleep(self._backoff_delay(attempt))
                    continue
                raise

        if last_exc is not None:
            raise last_exc  # pragma: no cover
        logger.error("[{}] All {} retries exhausted for {}", self.platform, self.max_retries, url)
        response.raise_for_status()  # type: ignore[possibly-undefined]
        return response  # type: ignore[possibly-undefined]

    # ------------------------------------------------------------------
    # Public sync API
    # ------------------------------------------------------------------

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        """Send a synchronous GET request.

        Args:
            url: Target URL.
            **kwargs: Extra arguments forwarded to ``httpx.Client.request``
                (e.g. ``params``, ``headers``, ``cookies``).

        Returns:
            :class:`httpx.Response` on success.
        """
        return self._request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        """Send a synchronous POST request.

        Args:
            url: Target URL.
            **kwargs: Extra arguments forwarded to ``httpx.Client.request``
                (e.g. ``data``, ``json``, ``headers``, ``cookies``).

        Returns:
            :class:`httpx.Response` on success.
        """
        return self._request("POST", url, **kwargs)

    # ------------------------------------------------------------------
    # Public async API
    # ------------------------------------------------------------------

    async def async_get(self, url: str, **kwargs: Any) -> httpx.Response:
        """Send an asynchronous GET request.

        Args:
            url: Target URL.
            **kwargs: Extra arguments forwarded to ``httpx.AsyncClient.request``.

        Returns:
            :class:`httpx.Response` on success.
        """
        return await self._async_request("GET", url, **kwargs)

    async def async_post(self, url: str, **kwargs: Any) -> httpx.Response:
        """Send an asynchronous POST request.

        Args:
            url: Target URL.
            **kwargs: Extra arguments forwarded to ``httpx.AsyncClient.request``.

        Returns:
            :class:`httpx.Response` on success.
        """
        return await self._async_request("POST", url, **kwargs)
