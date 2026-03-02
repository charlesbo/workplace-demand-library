"""AI prompt templates for workplace demand extraction and analysis.

Defines prompt constants used by LLM-based analyzers to extract, classify,
and analyze workplace demands from social media content.
"""

from string import Formatter
from typing import Any


# ---------------------------------------------------------------------------
# Valid categories & descriptions
# ---------------------------------------------------------------------------

VALID_CATEGORIES: list[str] = [
    "沟通协作",
    "职业发展",
    "求职面试",
    "团队管理",
    "职场情绪",
    "职场关系",
    "工作效率",
    "薪酬福利",
    "行业洞察",
]
"""The 9 predefined workplace-demand categories."""

CATEGORY_DESCRIPTIONS: dict[str, dict[str, Any]] = {
    "沟通协作": {
        "subcategories": ["跨部门沟通", "远程协作", "会议效率", "信息同步", "文档协作"],
        "examples": ["跨部门项目沟通困难", "远程团队协作工具选择", "会议过多影响工作"],
    },
    "职业发展": {
        "subcategories": ["晋升路径", "技能提升", "转行转岗", "职业规划", "学习成长"],
        "examples": ["技术转管理的困惑", "35岁职业危机", "如何制定职业规划"],
    },
    "求职面试": {
        "subcategories": ["简历优化", "面试技巧", "offer选择", "背景调查", "薪资谈判"],
        "examples": ["如何准备技术面试", "多个offer如何选择", "简历石沉大海"],
    },
    "团队管理": {
        "subcategories": ["领导力", "团队建设", "绩效管理", "冲突处理", "人才培养"],
        "examples": ["新晋管理者如何带团队", "如何处理团队冲突", "绩效考核不公平"],
    },
    "职场情绪": {
        "subcategories": ["压力管理", "职业倦怠", "焦虑抑郁", "工作生活平衡", "心理调适"],
        "examples": ["加班导致身心俱疲", "对工作失去热情", "职场PUA导致焦虑"],
    },
    "职场关系": {
        "subcategories": ["上下级关系", "同事相处", "办公室政治", "职场社交", "边界感"],
        "examples": ["如何与难相处的上司沟通", "同事抢功劳", "职场中被孤立"],
    },
    "工作效率": {
        "subcategories": ["时间管理", "工具方法", "流程优化", "专注力", "自动化"],
        "examples": ["总是无法按时完成任务", "如何提高专注力", "重复工作太多"],
    },
    "薪酬福利": {
        "subcategories": ["薪资水平", "福利待遇", "股权期权", "加班补偿", "社保公积金"],
        "examples": ["同岗不同酬", "年终奖缩水", "加班没有加班费"],
    },
    "行业洞察": {
        "subcategories": ["行业趋势", "技术变革", "政策影响", "市场分析", "AI影响"],
        "examples": ["AI会取代哪些岗位", "互联网行业还值得进入吗", "新能源行业前景"],
    },
}
"""Maps each category to its subcategories and representative examples."""


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

EXTRACT_DEMANDS_PROMPT: str = """\
你是一位资深的职场需求分析师。请从以下文章中提取核心职场问题和需求。

文章标题: {title}
来源平台: {platform}
文章内容:
{content}

请按以下要求提取需求：
1. 识别文章中反映的核心职场问题或需求
2. 每个需求包含以下字段：
   - title: 需求标题（不超过30个字符）
   - description: 需求描述（2-3句话概括该需求的具体表现和影响）
   - category: 从以下9个类别中选择一个：沟通协作、职业发展、求职面试、团队管理、职场情绪、职场关系、工作效率、薪酬福利、行业洞察
   - subcategory: 所属子类别
   - tags: 1-3个标签，用于进一步描述该需求的关键特征
   - importance_score: 重要性评分（0-10），根据需求的普遍性和紧迫性评估
3. 同时提供文章的简要摘要

输出语言: {language}

请严格按照以下JSON格式输出：
{{
  "demands": [
    {{
      "title": "需求标题",
      "description": "需求描述",
      "category": "类别",
      "subcategory": "子类别",
      "tags": ["标签1", "标签2"],
      "importance_score": 8
    }}
  ],
  "article_summary": "文章摘要"
}}
"""
"""Extract workplace demands from an article.

Template variables:
    title: Article title.
    platform: Source platform name.
    content: Full article text.
    language: Output language code (default ``"zh"``).
"""

CLASSIFY_DEMAND_PROMPT: str = """\
你是一位语义分析专家。请判断以下两个职场需求是否表达了相同的核心诉求。

需求A:
{demand_a}

需求B:
{demand_b}

请从语义层面分析两个需求：
1. 核心问题是否一致
2. 目标受众是否相同
3. 解决方向是否相似

请严格按照以下JSON格式输出：
{{
  "is_same": true,
  "similarity_score": 0.85,
  "merged_title": "合并后的需求标题",
  "merged_description": "合并后的需求描述，综合两个需求的关键信息"
}}

说明：
- is_same: 布尔值，当similarity_score >= 0.8时为true
- similarity_score: 0-1之间的浮点数，表示语义相似度
- merged_title: 如果判定为相同需求，给出合并后的标题
- merged_description: 如果判定为相同需求，给出合并后的描述
"""
"""Semantic deduplication — judge whether two demands are equivalent.

Template variables:
    demand_a: JSON or text representation of the first demand.
    demand_b: JSON or text representation of the second demand.
"""

TREND_ANALYSIS_PROMPT: str = """\
你是一位职场趋势分析师。请根据以下时间段内的职场需求数据进行趋势分析。

分析时段: {period}

需求数据:
{demand_data}

请完成以下分析：
1. 识别上升趋势的需求（热度或提及频率持续增加）
2. 识别稳定的需求（长期存在，热度相对稳定）
3. 识别下降趋势的需求（热度或提及频率持续减少）
4. 检测新兴需求（近期首次出现或突然爆发的需求）
5. 给出整体趋势总结和预测

请严格按照以下JSON格式输出：
{{
  "rising": [
    {{
      "title": "需求标题",
      "growth_rate": 0.35,
      "description": "上升原因分析"
    }}
  ],
  "stable": [
    {{
      "title": "需求标题",
      "avg_score": 7.5,
      "description": "稳定原因分析"
    }}
  ],
  "declining": [
    {{
      "title": "需求标题",
      "decline_rate": -0.2,
      "description": "下降原因分析"
    }}
  ],
  "emerging": [
    {{
      "title": "需求标题",
      "first_seen": "首次出现时间",
      "description": "新兴需求描述和潜力分析"
    }}
  ],
  "summary": "整体趋势总结",
  "predictions": "未来趋势预测"
}}
"""
"""Analyze demand trends over a given time period.

Template variables:
    period: Human-readable time range, e.g. ``"2024-01 ~ 2024-03"``.
    demand_data: JSON array of aggregated demand records with timestamps.
"""

COMMENT_ANALYSIS_PROMPT: str = """\
你是一位用户洞察分析师。请从以下评论中提取职场需求。

注意：评论往往比文章更直接地反映用户的真实痛点和需求，请特别关注：
- 用户抱怨或吐槽的问题
- 用户寻求帮助或建议的内容
- 用户分享的亲身经历中暴露的需求
- 引发大量共鸣（点赞/回复）的话题

评论内容:
{comments}

请按以下要求提取需求：
1. 每个需求包含以下字段：
   - title: 需求标题（不超过30个字符）
   - description: 需求描述（2-3句话概括该需求的具体表现和影响）
   - category: 从以下9个类别中选择一个：沟通协作、职业发展、求职面试、团队管理、职场情绪、职场关系、工作效率、薪酬福利、行业洞察
   - subcategory: 所属子类别
   - tags: 1-3个标签
   - importance_score: 重要性评分（0-10）
2. 同时提供评论的整体摘要

请严格按照以下JSON格式输出：
{{
  "demands": [
    {{
      "title": "需求标题",
      "description": "需求描述",
      "category": "类别",
      "subcategory": "子类别",
      "tags": ["标签1", "标签2"],
      "importance_score": 8
    }}
  ],
  "article_summary": "评论整体摘要"
}}
"""
"""Extract demands from user comments.

Comments are more direct indicators of real pain points than articles.

Template variables:
    comments: Newline-separated or JSON array of user comments.
"""


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def format_prompt(template: str, **kwargs: Any) -> str:
    """Safely format a prompt template, leaving missing placeholders intact.

    Unlike :py:meth:`str.format`, this function will **not** raise
    :class:`KeyError` for placeholders that are not provided in *kwargs*.
    Missing keys are left as literal ``{key}`` in the output.

    Args:
        template: A prompt template string containing ``{variable}``
            placeholders.
        **kwargs: Values to substitute into the template.

    Returns:
        The formatted string with provided keys substituted and missing
        keys preserved verbatim.

    Examples:
        >>> format_prompt("Hello {name}, welcome to {place}!", name="Alice")
        'Hello Alice, welcome to {place}!'
    """
    # Collect all field names referenced in the template
    field_names = {
        fname
        for _, fname, _, _ in Formatter().parse(template)
        if fname is not None
    }
    # Fill missing keys with the placeholder itself so str.format won't fail
    safe_kwargs = {k: kwargs.get(k, "{" + k + "}") for k in field_names}
    return template.format(**safe_kwargs)
