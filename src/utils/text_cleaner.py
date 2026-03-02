"""Comprehensive text cleaning module for Chinese web content.

Provides utilities to strip HTML, remove ads/boilerplate, normalize whitespace,
and extract article body text from raw HTML pages.
"""

from __future__ import annotations

import html
import re
from typing import Optional

from bs4 import BeautifulSoup, Comment

# ---------------------------------------------------------------------------
# Ad / promotion patterns (Chinese web content)
# ---------------------------------------------------------------------------

_CTA_PATTERNS: list[re.Pattern[str]] = [
    # 关注/点赞/转发/收藏 call-to-action phrases
    re.compile(
        r"[★☆❤✦✧►▶→]?\s*"
        r"(点击)?(关注|点赞|转发|收藏|分享|订阅|在看|三连)"
        r"[一下我们本号吧哦呀啊!！\s]*",
    ),
    # 公众号推广
    re.compile(
        r"(关注|扫码关注|长按识别|搜索)(公众号|微信号|服务号|订阅号)[「【\s]*\S{0,20}[」】]?\s*",
    ),
    re.compile(r"扫[一]?码(关注|添加|领取|下载)[^\n]{0,30}"),
    # Course / product promotions
    re.compile(
        r"(限时(优惠|免费|特价|折扣)|点击(购买|领取|下载|报名)|"
        r"免费(领取|试[用听看]|课程)|立即(购买|报名|领取|下载)|"
        r"(优惠|活动|福利)(仅限|截止|即将|最后))[^\n]{0,40}",
    ),
    # App download prompts
    re.compile(
        r"(下载|安装|打开)\s*(APP|App|app|客户端|应用)[^\n]{0,30}",
    ),
    # Common ad markers
    re.compile(r"^[\s]*(广告|推广|赞助|商业推广|品牌合作)\s*$", re.MULTILINE),
    # URLs
    re.compile(r"https?://[^\s<>\"')\]]+"),
    # Social media handles (e.g., @xxx, 微博@xxx, 抖音号：xxx)
    re.compile(r"(微博|抖音号?|快手号?|小红书号?|B站)\s*[：:@]\s*\S{1,30}"),
    re.compile(r"@[\w\u4e00-\u9fff]{1,30}"),
]

# ---------------------------------------------------------------------------
# Boilerplate patterns
# ---------------------------------------------------------------------------

_BOILERPLATE_PATTERNS: list[re.Pattern[str]] = [
    # Copyright notices
    re.compile(
        r"(©|&copy;|版权所有|Copyright)\s*[\d\-—–\s]*\S{0,50}",
        re.IGNORECASE,
    ),
    re.compile(r"All [Rr]ights [Rr]eserved[.\s]*"),
    # 转载 / 来源
    re.compile(r"(本文(转载自|来自|来源[：:]|选自|摘自|首发[于在]))[^\n]{0,60}"),
    re.compile(r"(来源|出处|作者|编辑|责编|责任编辑)\s*[：:]\s*\S{1,30}"),
    # Disclaimer text
    re.compile(
        r"(免责声明|声明[：:]|侵权请联系|如有侵权|如需转载|转载请注明|"
        r"本[文平台号站]仅|不代表本[平台号站]|仅供(参考|学习|交流))[^\n]{0,100}",
    ),
    # Navigation text
    re.compile(r"(上一篇|下一篇|相关(文章|阅读|推荐)|猜你喜欢)\s*[：:]?\s*\S{0,50}"),
    # "阅读原文" / "查看原文"
    re.compile(r"(阅读|查看|点击)\s*原文[^\n]{0,20}"),
]

# ---------------------------------------------------------------------------
# Selectors used for article body extraction
# ---------------------------------------------------------------------------

_ARTICLE_SELECTORS: list[str] = [
    "article",
    "[role='main']",
    ".article-content",
    ".article-body",
    ".post-content",
    ".post-body",
    ".entry-content",
    ".content-body",
    ".rich_media_content",  # WeChat articles
    "#js_content",          # WeChat articles
    "div.content",
    "div.main-content",
    "div.text",
    "div.body",
]

# Tags that usually carry non-content boilerplate
_STRIP_TAGS: set[str] = {
    "script", "style", "nav", "header", "footer",
    "aside", "iframe", "noscript", "form",
}


# ===================================================================
# Public API
# ===================================================================


def clean_html(html_str: str) -> str:
    """Strip all HTML tags and decode HTML entities.

    Args:
        html_str: Raw HTML string.

    Returns:
        Plain text with tags removed and entities decoded.
        Returns an empty string for ``None`` or empty input.
    """
    if not html_str:
        return ""

    soup = BeautifulSoup(html_str, "html.parser")
    text = soup.get_text(separator="\n")
    # Decode any remaining HTML entities (e.g. &amp; &lt;)
    text = html.unescape(text)
    return text


def remove_ads(text: str) -> str:
    """Remove common advertisement and promotion patterns in Chinese web content.

    Handles call-to-action phrases, public-account promotions, course/product
    ads, app download prompts, ad markers, URLs, and social media handles.

    Args:
        text: Plain text (ideally already stripped of HTML).

    Returns:
        Text with ad content removed.
    """
    if not text:
        return ""

    for pattern in _CTA_PATTERNS:
        text = pattern.sub("", text)

    return text


def remove_boilerplate(text: str) -> str:
    """Remove boilerplate content commonly found in Chinese web pages.

    Strips copyright notices, source/repost attributions, disclaimers,
    and navigation elements.

    Args:
        text: Plain text.

    Returns:
        Text with boilerplate removed.
    """
    if not text:
        return ""

    for pattern in _BOILERPLATE_PATTERNS:
        text = pattern.sub("", text)

    return text


def normalize_whitespace(text: str) -> str:
    """Collapse multiple spaces and newlines into single instances and trim.

    - Consecutive blank lines are collapsed to a single blank line.
    - Leading/trailing whitespace on each line is removed.
    - Overall leading/trailing whitespace is trimmed.

    Args:
        text: Input text.

    Returns:
        Whitespace-normalized text.
    """
    if not text:
        return ""

    # Replace runs of horizontal whitespace (excluding newlines) with a single space
    text = re.sub(r"[^\S\n]+", " ", text)
    # Strip each line
    lines = [line.strip() for line in text.splitlines()]
    # Collapse multiple consecutive blank lines into one
    cleaned: list[str] = []
    prev_blank = False
    for line in lines:
        if line == "":
            if not prev_blank:
                cleaned.append("")
            prev_blank = True
        else:
            cleaned.append(line)
            prev_blank = False

    return "\n".join(cleaned).strip()


def clean_text(text: str) -> str:
    """Full cleaning pipeline for Chinese web content.

    Applies, in order:
    1. :func:`clean_html` — strip tags and decode entities
    2. :func:`remove_ads` — remove ad / promotion text
    3. :func:`remove_boilerplate` — remove copyright, disclaimers, etc.
    4. :func:`normalize_whitespace` — collapse whitespace

    Args:
        text: Raw text or HTML string.

    Returns:
        Fully cleaned plain text.
    """
    if not text:
        return ""

    text = clean_html(text)
    text = remove_ads(text)
    text = remove_boilerplate(text)
    text = normalize_whitespace(text)
    return text


def extract_text_from_html(html_str: str) -> str:
    """Extract article body text from an HTML page using BeautifulSoup.

    Attempts to locate the main content area via common selectors
    (``<article>``, ``div.content``, WeChat rich-media containers, etc.).
    Falls back to the ``<body>`` tag if no known content container is found.

    Non-content elements (``<script>``, ``<style>``, ``<nav>``, ``<footer>``,
    etc.) and HTML comments are removed before extraction.

    Args:
        html_str: Full HTML page source.

    Returns:
        Extracted and whitespace-normalized plain text.
        Returns an empty string for ``None`` or empty input.
    """
    if not html_str:
        return ""

    soup = BeautifulSoup(html_str, "html.parser")

    # Remove non-content tags and comments
    for tag in soup.find_all(list(_STRIP_TAGS)):
        tag.decompose()
    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()

    # Try known article-body selectors
    content_node = None
    for selector in _ARTICLE_SELECTORS:
        content_node = soup.select_one(selector)
        if content_node is not None:
            break

    # Fallback to <body> or entire document
    if content_node is None:
        content_node = soup.body or soup

    # Prefer <p> tags within the content node for cleaner output
    paragraphs = content_node.find_all("p")
    if paragraphs:
        text = "\n".join(p.get_text(separator=" ", strip=True) for p in paragraphs)
    else:
        text = content_node.get_text(separator="\n", strip=True)

    text = html.unescape(text)
    text = normalize_whitespace(text)
    return text
