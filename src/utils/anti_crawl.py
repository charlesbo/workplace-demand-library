"""Anti-anti-crawling strategies module.

Provides utilities to mitigate common anti-crawling mechanisms including
User-Agent rotation, request throttling, cookie management, proxy pooling,
header construction, captcha detection, and IP block detection.
"""

import random
import re
import time
from typing import Dict, List, Optional
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# 1. User-Agent Pool
# ---------------------------------------------------------------------------

_USER_AGENTS: List[str] = [
    # Chrome on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36",
    # Chrome on Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    # Chrome on Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    # Firefox on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
    # Firefox on Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:122.0) Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
    # Firefox on Linux
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:122.0) Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0",
    # Safari on Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15",
    # Edge on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    # Edge on Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
    # Edge on Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
]


def get_random_ua() -> str:
    """Return a randomly selected User-Agent string from the pool.

    Returns:
        A User-Agent string mimicking a real desktop browser.
    """
    return random.choice(_USER_AGENTS)


# ---------------------------------------------------------------------------
# 2. Request interval randomization
# ---------------------------------------------------------------------------


def get_random_delay(base_interval: float) -> float:
    """Calculate a randomized delay based on the given base interval.

    The returned value is uniformly distributed between 0.5x and 1.5x of
    *base_interval*, providing natural-looking request timing.

    Args:
        base_interval: The base delay in seconds.

    Returns:
        A randomized delay in seconds.
    """
    return base_interval * random.uniform(0.5, 1.5)


# ---------------------------------------------------------------------------
# 3. Cookie Manager
# ---------------------------------------------------------------------------


class CookieManager:
    """Manage cookies on a per-platform basis.

    Cookies are stored internally as ``dict[str, str]`` keyed by platform
    name so that each crawling target can maintain its own session state.
    """

    def __init__(self) -> None:
        """Initialise an empty cookie store."""
        self._cookies: Dict[str, Dict[str, str]] = {}

    def set_cookies(self, platform: str, cookies_str: str) -> None:
        """Parse a cookie string and store it for *platform*.

        The *cookies_str* should be in the standard HTTP ``Cookie`` header
        format, e.g. ``"key1=value1; key2=value2"``.

        Args:
            platform: Identifier for the target platform.
            cookies_str: Raw cookie string to parse.
        """
        cookies: Dict[str, str] = {}
        for pair in cookies_str.split(";"):
            pair = pair.strip()
            if "=" in pair:
                key, value = pair.split("=", 1)
                cookies[key.strip()] = value.strip()
        self._cookies[platform] = cookies

    def get_cookies(self, platform: str) -> Dict[str, str]:
        """Return stored cookies for *platform*.

        Args:
            platform: Identifier for the target platform.

        Returns:
            A dictionary of cookie key-value pairs, or an empty dict if
            no cookies have been set for the platform.
        """
        return self._cookies.get(platform, {})


# ---------------------------------------------------------------------------
# 4. Proxy Pool
# ---------------------------------------------------------------------------


class ProxyPool:
    """Round-robin proxy pool with failure tracking.

    Proxies that are marked as failed are temporarily skipped. A failed
    proxy is reconsidered after *retry_after* seconds have elapsed.

    Args:
        proxies: Initial list of proxy URLs
            (e.g. ``["http://1.2.3.4:8080", "socks5://5.6.7.8:1080"]``).
        retry_after: Seconds before a failed proxy is retried (default 300).
    """

    def __init__(
        self, proxies: Optional[List[str]] = None, retry_after: float = 300
    ) -> None:
        """Initialise the proxy pool.

        Args:
            proxies: List of proxy URL strings.
            retry_after: Seconds until a failed proxy becomes available again.
        """
        self._proxies: List[str] = list(proxies) if proxies else []
        self._index: int = 0
        self._failed: Dict[str, float] = {}
        self._retry_after: float = retry_after

    def get_proxy(self) -> Optional[str]:
        """Return the next available proxy using round-robin selection.

        Proxies marked as failed within the *retry_after* window are
        skipped. Returns ``None`` if no proxies are available.

        Returns:
            A proxy URL string, or ``None``.
        """
        if not self._proxies:
            return None

        now = time.time()
        tried = 0
        while tried < len(self._proxies):
            proxy = self._proxies[self._index % len(self._proxies)]
            self._index += 1
            failed_at = self._failed.get(proxy)
            if failed_at is None or (now - failed_at) >= self._retry_after:
                # Clear stale failure record
                self._failed.pop(proxy, None)
                return proxy
            tried += 1

        return None

    def mark_failed(self, proxy: str) -> None:
        """Mark a proxy as temporarily failed.

        The proxy will be skipped by :meth:`get_proxy` until
        *retry_after* seconds have elapsed.

        Args:
            proxy: The proxy URL string to mark as failed.
        """
        self._failed[proxy] = time.time()


# ---------------------------------------------------------------------------
# 5. Request Headers
# ---------------------------------------------------------------------------


def get_full_headers(url: str, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Build a complete set of HTTP request headers for *url*.

    The ``Referer`` header is automatically derived from the URL's origin.
    A random ``User-Agent`` is selected from the built-in pool.

    Args:
        url: The target URL (used to derive Referer and Host).
        extra: Optional dictionary of additional headers to merge in.

    Returns:
        A dictionary of HTTP headers.
    """
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"

    headers: Dict[str, str] = {
        "User-Agent": get_random_ua(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-US;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": origin + "/",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    }

    if extra:
        headers.update(extra)

    return headers


# ---------------------------------------------------------------------------
# 6. Captcha Detection
# ---------------------------------------------------------------------------

_CAPTCHA_PATTERNS: List[str] = [
    r"验证码",
    r"captcha",
    r"安全验证",
    r"slide[\s_-]?verif",
    r"滑动验证",
    r"请完成安全验证",
    r"人机验证",
    r"点击验证",
    r"图形验证",
    r"请输入验证码",
    r"security[\s_-]?check",
    r"robot[\s_-]?check",
    r"are[\s_-]?you[\s_-]?human",
    r"recaptcha",
    r"hcaptcha",
    r"cf-challenge",
    r"challenge-platform",
    r"turnstile",
]

_CAPTCHA_RE = re.compile("|".join(_CAPTCHA_PATTERNS), re.IGNORECASE)


def is_captcha_page(html: str) -> bool:
    """Detect whether *html* contains common captcha / verification patterns.

    Checks for both Chinese and English captcha indicators used by
    popular anti-bot services (reCAPTCHA, hCaptcha, Cloudflare Turnstile,
    custom slide verification, etc.).

    Args:
        html: Raw HTML content of the page.

    Returns:
        ``True`` if a captcha pattern is detected, ``False`` otherwise.
    """
    return bool(_CAPTCHA_RE.search(html))


# ---------------------------------------------------------------------------
# 7. IP Block Detection
# ---------------------------------------------------------------------------


class BlockDetector:
    """Track consecutive request failures to detect IP-level blocks.

    Each platform maintains an independent failure counter that resets on
    success. When the counter reaches a configurable threshold the
    platform is considered blocked.
    """

    def __init__(self) -> None:
        """Initialise the detector with empty counters."""
        self._failures: Dict[str, int] = {}

    def record_failure(self, platform: str) -> None:
        """Record a consecutive failure for *platform*.

        Args:
            platform: Identifier for the target platform.
        """
        self._failures[platform] = self._failures.get(platform, 0) + 1

    def record_success(self, platform: str) -> None:
        """Reset the failure counter for *platform* upon a successful request.

        Args:
            platform: Identifier for the target platform.
        """
        self._failures[platform] = 0

    def is_blocked(self, platform: str, threshold: int = 5) -> bool:
        """Determine whether *platform* appears to be blocking requests.

        Args:
            platform: Identifier for the target platform.
            threshold: Number of consecutive failures that indicates a
                block (default ``5``).

        Returns:
            ``True`` if consecutive failures >= *threshold*.
        """
        return self._failures.get(platform, 0) >= threshold
