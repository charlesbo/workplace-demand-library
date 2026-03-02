"""Internationalization support module.

Centralizes all user-visible strings with Chinese (zh) and English (en) translations.
Uses a simple dict-based translation system.
"""

from __future__ import annotations

from typing import Dict

# ---------------------------------------------------------------------------
# Master translation table
# ---------------------------------------------------------------------------

MESSAGES: Dict[str, Dict[str, str] | Dict[str, Dict[str, str]]] = {
    # ---- application metadata ----
    "app_name": {
        "zh": "职场需求库",
        "en": "Workplace Demand Library",
    },

    # ---- 9 demand categories ----
    "categories": {
        "沟通协作": {"zh": "沟通协作", "en": "Communication & Collaboration"},
        "职业发展": {"zh": "职业发展", "en": "Career Development"},
        "求职面试": {"zh": "求职面试", "en": "Job Seeking & Interviews"},
        "团队管理": {"zh": "团队管理", "en": "Team Management"},
        "职场情绪": {"zh": "职场情绪", "en": "Workplace Emotions"},
        "职场关系": {"zh": "职场关系", "en": "Workplace Relationships"},
        "工作效率": {"zh": "工作效率", "en": "Work Efficiency"},
        "薪酬福利": {"zh": "薪酬福利", "en": "Compensation & Benefits"},
        "行业洞察": {"zh": "行业洞察", "en": "Industry Insights"},
    },

    # ---- demand statuses ----
    "statuses": {
        "new":       {"zh": "新发现", "en": "New"},
        "confirmed": {"zh": "已确认", "en": "Confirmed"},
        "archived":  {"zh": "已归档", "en": "Archived"},
        "rejected":  {"zh": "已拒绝", "en": "Rejected"},
        "merged":    {"zh": "已合并", "en": "Merged"},
    },

    # ---- trend directions ----
    "trends": {
        "rising":    {"zh": "上升", "en": "Rising"},
        "stable":    {"zh": "平稳", "en": "Stable"},
        "declining": {"zh": "下降", "en": "Declining"},
    },

    # ---- common UI labels ----
    "ui": {
        "starting_scheduler":  {"zh": "正在启动调度器…", "en": "Starting scheduler…"},
        "starting_server":     {"zh": "正在启动 Web 服务器…", "en": "Starting web server…"},
        "no_platforms":        {"zh": "未找到已启用的平台。", "en": "No enabled platforms found."},
        "crawling":            {"zh": "正在爬取 {n} 个平台…", "en": "Crawling {n} platform(s)…"},
        "processed_articles":  {"zh": "已处理 {n} 篇文章。", "en": "Processed {n} article(s)."},
        "exporting":           {"zh": "正在导出为 {fmt}…", "en": "Exporting to {fmt}…"},
        "saved_to":            {"zh": "已保存至 {path}", "en": "Saved to {path}"},
        "database_ready":      {"zh": "数据库就绪。", "en": "Database ready."},
        "detecting_trends":    {"zh": "正在检测趋势…", "en": "Detecting trends…"},
        "cleaned_articles":    {"zh": "已清理 {n} 篇文章。", "en": "Cleaned {n} article(s)."},
        "category":            {"zh": "分类", "en": "Category"},
        "count":               {"zh": "数量", "en": "Count"},
        "value":               {"zh": "值", "en": "Value"},
        "metric":              {"zh": "指标", "en": "Metric"},
        "platform":            {"zh": "平台", "en": "Platform"},
        "new_demands":         {"zh": "新需求", "en": "New demands"},
    },

    # ---- error messages ----
    "errors": {
        "unknown_category":  {"zh": "未知分类: {key}", "en": "Unknown category: {key}"},
        "unknown_status":    {"zh": "未知状态: {key}", "en": "Unknown status: {key}"},
        "unknown_trend":     {"zh": "未知趋势: {key}", "en": "Unknown trend: {key}"},
        "config_missing":    {"zh": "缺少配置文件: {path}", "en": "Missing config file: {path}"},
        "crawl_failed":      {"zh": "爬取失败: {reason}", "en": "Crawl failed: {reason}"},
        "analysis_failed":   {"zh": "分析失败: {reason}", "en": "Analysis failed: {reason}"},
        "export_failed":     {"zh": "导出失败: {reason}", "en": "Export failed: {reason}"},
        "db_connection_error": {"zh": "数据库连接错误: {reason}", "en": "Database connection error: {reason}"},
    },
}


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def get_text(key: str, lang: str = "zh") -> str:
    """Return a translated string for a top-level *key*.

    Parameters
    ----------
    key:
        A top-level key in :data:`MESSAGES` whose value is
        ``{"zh": ..., "en": ...}``.
    lang:
        Language code – ``"zh"`` (default) or ``"en"``.

    Returns
    -------
    str
        The translated string, or *key* itself when not found.
    """
    entry = MESSAGES.get(key)
    if isinstance(entry, dict) and lang in entry:
        value = entry[lang]
        if isinstance(value, str):
            return value
    return key


def get_category_name(category: str, lang: str = "zh") -> str:
    """Translate a category name.

    Parameters
    ----------
    category:
        One of the nine category keys (e.g. ``"沟通协作"``).
    lang:
        Language code – ``"zh"`` (default) or ``"en"``.

    Returns
    -------
    str
        The translated category name, or *category* itself when not found.
    """
    categories = MESSAGES.get("categories", {})
    if isinstance(categories, dict):
        entry = categories.get(category)
        if isinstance(entry, dict):
            return entry.get(lang, category)
    return category


def get_status_name(status: str, lang: str = "zh") -> str:
    """Translate a demand status.

    Parameters
    ----------
    status:
        One of ``"new"``, ``"confirmed"``, ``"archived"``,
        ``"rejected"``, or ``"merged"``.
    lang:
        Language code – ``"zh"`` (default) or ``"en"``.

    Returns
    -------
    str
        The translated status name, or *status* itself when not found.
    """
    statuses = MESSAGES.get("statuses", {})
    if isinstance(statuses, dict):
        entry = statuses.get(status)
        if isinstance(entry, dict):
            return entry.get(lang, status)
    return status
