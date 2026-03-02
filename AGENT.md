# AGENT.md — 职场热文抓取 & 需求库系统

## 项目概述

构建一个 **全自动化职场内容采集与分析系统**，从多个中文内容平台抓取职场相关热门文章，利用 AI 提炼职场问题、痛点和需求，建立结构化的「需求库」，并提供可视化的 Web 管理界面。

**技术栈**：Python 3.11+ / FastAPI / SQLite / Vue 3（或 React）/ Claude API

---

## 一、项目结构

```
workplace-demand-library/
├── AGENT.md                    # 本文件
├── README.md                   # 项目说明文档
├── requirements.txt            # Python 依赖
├── config/
│   ├── settings.yaml           # 全局配置（API Key、抓取频率、平台开关等）
│   └── platforms.yaml          # 各平台的抓取规则配置
├── src/
│   ├── __init__.py
│   ├── main.py                 # 主入口，CLI 命令行工具
│   ├── scrapers/               # 各平台爬虫模块
│   │   ├── __init__.py
│   │   ├── base.py             # 爬虫基类（抽象类）
│   │   ├── zhihu.py            # 知乎
│   │   ├── kr36.py             # 36氪
│   │   ├── huxiu.py            # 虎嗅
│   │   ├── juejin.py           # 掘金（职场/成长频道）
│   │   ├── toutiao.py          # 今日头条
│   │   ├── douban.py           # 豆瓣小组
│   │   ├── xiaohongshu.py      # 小红书
│   │   ├── bilibili.py         # B站专栏
│   │   ├── weixin_sogou.py     # 微信公众号（通过搜狗搜索）
│   │   ├── maimai.py           # 脉脉
│   │   ├── baidu_baijiahao.py  # 百度百家号
│   │   └── rss_generic.py      # 通用 RSS 源抓取器
│   ├── analyzer/               # AI 分析模块
│   │   ├── __init__.py
│   │   ├── extractor.py        # 问题/需求提炼器
│   │   ├── classifier.py       # 需求分类器
│   │   ├── deduplicator.py     # 语义去重
│   │   ├── trend_detector.py   # 趋势检测
│   │   └── prompts.py          # 所有 AI Prompt 模板
│   ├── storage/                # 数据存储层
│   │   ├── __init__.py
│   │   ├── database.py         # SQLite 数据库操作
│   │   ├── models.py           # 数据模型定义（SQLAlchemy/Pydantic）
│   │   └── migrations.py       # 数据库迁移
│   ├── scheduler/              # 定时任务
│   │   ├── __init__.py
│   │   └── cron.py             # 定时抓取调度器
│   ├── exporter/               # 数据导出
│   │   ├── __init__.py
│   │   ├── excel.py            # 导出为 Excel
│   │   ├── csv_export.py       # 导出为 CSV
│   │   ├── markdown.py         # 导出为 Markdown 报告
│   │   └── notion.py           # 导出到 Notion（可选）
│   ├── api/                    # Web API
│   │   ├── __init__.py
│   │   ├── server.py           # FastAPI 主服务
│   │   └── routes.py           # API 路由定义
│   └── utils/                  # 工具函数
│       ├── __init__.py
│       ├── http_client.py      # 统一 HTTP 请求封装（含重试、代理、UA轮换）
│       ├── anti_crawl.py       # 反反爬策略
│       ├── text_cleaner.py     # 文本清洗（去HTML标签、去广告）
│       ├── logger.py           # 日志模块
│       └── rate_limiter.py     # 请求频率控制
├── web/                        # 前端 Web 界面
│   ├── index.html              # 单页面应用（可用 CDN 引入 Vue/React）
│   ├── app.js
│   └── style.css
├── data/                       # 数据目录
│   ├── workplace.db            # SQLite 数据库文件
│   └── exports/                # 导出文件存放目录
├── logs/                       # 日志目录
│   └── scraper.log
└── tests/                      # 测试
    ├── test_scrapers.py
    ├── test_analyzer.py
    └── test_api.py
```

---

## 二、数据库设计

使用 SQLite，通过 SQLAlchemy ORM 操作。

### 表结构

```sql
-- 1. 文章表：存储原始抓取的文章
CREATE TABLE articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform VARCHAR(50) NOT NULL,          -- 来源平台：zhihu/kr36/huxiu/...
    platform_id VARCHAR(200),               -- 文章在原平台的唯一ID
    title TEXT NOT NULL,                    -- 文章标题
    author VARCHAR(200),                    -- 作者
    url TEXT NOT NULL,                      -- 原文链接
    content TEXT,                           -- 正文内容（纯文本）
    summary TEXT,                           -- AI 生成的摘要
    publish_time DATETIME,                  -- 发布时间
    crawl_time DATETIME DEFAULT CURRENT_TIMESTAMP,  -- 抓取时间
    heat_score REAL DEFAULT 0,              -- 热度分数（综合阅读/点赞/评论）
    view_count INTEGER DEFAULT 0,           -- 阅读数
    like_count INTEGER DEFAULT 0,           -- 点赞数
    comment_count INTEGER DEFAULT 0,        -- 评论数
    share_count INTEGER DEFAULT 0,          -- 转发/分享数
    is_analyzed BOOLEAN DEFAULT FALSE,      -- 是否已进行 AI 分析
    raw_html TEXT,                          -- 原始 HTML（可选保留）
    UNIQUE(platform, platform_id)
);

-- 2. 需求/问题表：AI 提炼出的核心问题
CREATE TABLE demands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,                    -- 需求/问题标题（一句话描述）
    description TEXT,                       -- 详细描述
    category VARCHAR(100),                  -- 分类：沟通/晋升/跳槽/管理/情绪/效率/...
    subcategory VARCHAR(100),               -- 子分类
    tags TEXT,                              -- 标签，JSON 数组格式 ["标签1","标签2"]
    frequency INTEGER DEFAULT 1,            -- 出现频次（多少篇文章涉及）
    importance_score REAL DEFAULT 0,        -- 重要性评分（0-10）
    trend VARCHAR(20) DEFAULT 'stable',     -- 趋势：rising/stable/declining
    first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(20) DEFAULT 'new',       -- 状态：new/confirmed/archived/rejected
    notes TEXT,                             -- 用户备注
    semantic_vector TEXT                    -- 语义向量（用于去重，JSON格式存储）
);

-- 3. 文章-需求关联表
CREATE TABLE article_demand_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id INTEGER NOT NULL,
    demand_id INTEGER NOT NULL,
    relevance_score REAL DEFAULT 0,         -- 相关度评分（0-1）
    context_snippet TEXT,                   -- 原文中涉及该需求的片段
    FOREIGN KEY (article_id) REFERENCES articles(id),
    FOREIGN KEY (demand_id) REFERENCES demands(id),
    UNIQUE(article_id, demand_id)
);

-- 4. 热门评论表（高赞评论往往直接反映需求）
CREATE TABLE hot_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id INTEGER NOT NULL,
    platform VARCHAR(50) NOT NULL,
    commenter VARCHAR(200),
    content TEXT NOT NULL,
    like_count INTEGER DEFAULT 0,
    crawl_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_analyzed BOOLEAN DEFAULT FALSE,
    FOREIGN KEY (article_id) REFERENCES articles(id)
);

-- 5. 抓取日志表
CREATE TABLE crawl_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform VARCHAR(50) NOT NULL,
    start_time DATETIME NOT NULL,
    end_time DATETIME,
    status VARCHAR(20),                     -- success/failed/partial
    articles_found INTEGER DEFAULT 0,
    articles_new INTEGER DEFAULT 0,
    error_message TEXT
);

-- 6. 趋势快照表（每周记录一次需求热度变化）
CREATE TABLE trend_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    demand_id INTEGER NOT NULL,
    snapshot_date DATE NOT NULL,
    frequency INTEGER DEFAULT 0,
    heat_score REAL DEFAULT 0,
    FOREIGN KEY (demand_id) REFERENCES demands(id)
);

-- 索引
CREATE INDEX idx_articles_platform ON articles(platform);
CREATE INDEX idx_articles_crawl_time ON articles(crawl_time);
CREATE INDEX idx_articles_heat ON articles(heat_score DESC);
CREATE INDEX idx_demands_category ON demands(category);
CREATE INDEX idx_demands_frequency ON demands(frequency DESC);
CREATE INDEX idx_demands_trend ON demands(trend);
```

---

## 三、各模块详细实现要求

### 3.1 爬虫基类 `base.py`

```python
# 所有平台爬虫继承此抽象基类
class BaseScraper(ABC):
    """
    必须实现的方法：
    - get_hot_articles_list() -> List[ArticleMeta]
      获取热门/最新文章列表（标题、链接、基础热度数据）

    - get_article_detail(url: str) -> ArticleDetail
      获取单篇文章的完整内容

    - get_hot_comments(url: str) -> List[Comment]  (可选)
      获取文章的高赞评论

    基类提供的通用能力：
    - self.http: 统一 HTTP 客户端（含UA轮换、重试、代理）
    - self.rate_limiter: 频率控制
    - self.logger: 日志记录
    - self.save_article(): 保存到数据库（含去重检查）
    - self.clean_text(): 文本清洗
    """
```

### 3.2 各平台爬虫实现要点

#### 知乎 `zhihu.py`
- **目标页面**：
  - 知乎热榜 `https://www.zhihu.com/hot`（筛选职场相关）
  - 话题页面：职场、求职、人际关系、职业发展、跳槽、面试
  - 热门回答（高赞回答 > 1000赞）
- **抓取策略**：
  - 知乎有较严格的反爬，优先使用 API 接口（如果可用）
  - 使用 `playwright` 或 `selenium` 处理动态渲染
  - 需要模拟登录或使用 Cookie（在 config 中配置）
- **数据提取**：标题、问题描述、最高赞回答、回答数、关注数、浏览量
- **特殊处理**：知乎回答是问答形式，将"问题"本身也作为一个需求来源

#### 36氪 `kr36.py`
- **目标页面**：
  - 首页热门 `https://36kr.com/`
  - 职场频道文章
  - 搜索：关键词"职场""管理""团队""领导力""跳槽""面试"
- **抓取策略**：
  - 36氪页面结构相对规整，用 `requests` + `BeautifulSoup` 即可
  - 文章列表可通过 API 接口获取 JSON
- **数据提取**：标题、摘要、正文、阅读数、点赞数、发布时间

#### 虎嗅 `huxiu.py`
- **目标页面**：
  - 首页 `https://www.huxiu.com/`
  - 搜索职场关键词
- **抓取策略**：`requests` + `BeautifulSoup`，注意分页
- **数据提取**：标题、摘要、正文、评论数

#### 掘金 `juejin.py`
- **目标页面**：
  - 「职业成长」频道
  - 「前端/后端」中与职场成长相关的文章
- **抓取策略**：掘金用 API 返回数据，直接请求 JSON 接口
- **数据提取**：标题、正文、点赞数、评论数、阅读量

#### 今日头条 `toutiao.py`
- **目标页面**：搜索"职场"相关关键词
- **抓取策略**：使用 `playwright`，头条反爬较严
- **数据提取**：标题、正文、评论数、转发数

#### 豆瓣 `douban.py`
- **目标小组**：
  - "上班这件事"
  - "985废物引进计划"
  - "找工作互助"
  - 其他职场相关小组
- **抓取策略**：`requests` + 模拟登录 Cookie
- **数据提取**：帖子标题、正文、回复数、喜欢数

#### 小红书 `xiaohongshu.py`
- **目标**：搜索"职场""面试""辞职""升职"等关键词
- **抓取策略**：反爬很严，使用 `playwright` 模拟浏览
- **数据提取**：笔记标题、正文、点赞数、收藏数、评论数
- **注意**：小红书内容偏短，多篇聚合后再提炼

#### B站专栏 `bilibili.py`
- **目标**：专栏文章中搜索职场关键词
- **抓取策略**：B站有较完善的 API
- **数据提取**：标题、正文、播放量（视频则取标题和简介）

#### 微信公众号 `weixin_sogou.py`
- **入口**：搜狗微信搜索 `https://weixin.sogou.com/`
- **搜索关键词**：职场、管理、领导力、求职、面试技巧
- **注意**：搜狗有反爬验证码，需要控制频率

#### 脉脉 `maimai.py`
- **目标**：职言板块、热门话题
- **抓取策略**：需要登录，用 Cookie 维持会话
- **数据提取**：话题标题、讨论内容、评论

#### 百家号 `baidu_baijiahao.py`
- **入口**：百度搜索，筛选百家号来源
- **搜索关键词**：同上
- **抓取策略**：`requests` 即可

#### 通用 RSS `rss_generic.py`
- 支持用户自定义 RSS 源
- 解析 RSS/Atom feed，提取文章内容
- 配置文件中可添加任意 RSS 地址

### 3.3 反反爬策略 `anti_crawl.py`

```python
"""
实现以下反反爬能力：
1. User-Agent 轮换：维护 50+ 个真实浏览器 UA 字符串池
2. 请求间隔随机化：基础间隔 + 随机抖动（2-8秒）
3. Cookie 管理：支持手动导入浏览器 Cookie
4. 代理池（可选）：支持配置 HTTP/SOCKS 代理列表
5. 请求头完善：补全 Referer、Accept-Language 等必要头
6. 重试机制：遇到 429/503 自动退避重试（指数退避）
7. 验证码检测：检测到验证码页面时暂停并通知用户
8. IP 被封检测：连续失败超过阈值时暂停该平台抓取
"""
```

### 3.4 AI 分析模块

#### `prompts.py` — Prompt 模板集合

```python
# 定义所有用到的 Prompt 模板，支持变量替换

EXTRACT_DEMANDS_PROMPT = """
你是一个职场需求分析专家。请从以下职场文章中，提炼出文章涉及的核心职场问题和需求。

要求：
1. 每个问题用一句话概括（不超过30字）
2. 为每个问题给出详细描述（2-3句话）
3. 为每个问题分配分类，只能从以下分类中选择：
   - 沟通协作：同事沟通、跨部门协作、向上管理、会议效率
   - 职业发展：晋升、转行、跳槽、职业规划、技能提升
   - 求职面试：简历、面试技巧、薪资谈判、offer 选择
   - 团队管理：领导力、团队建设、绩效管理、人才培养
   - 职场情绪：焦虑、倦怠、内卷、压力管理、工作生活平衡
   - 职场关系：同事关系、上下级关系、办公室政治、职场霸凌
   - 工作效率：时间管理、项目管理、工具方法、远程办公
   - 薪酬福利：薪资结构、股权期权、福利待遇、劳动权益
   - 行业洞察：行业趋势、公司文化、创业、自由职业
4. 为每个问题添加 1-3 个标签
5. 评估重要性（0-10 分），依据：影响范围、普遍性、紧迫性

输出严格使用 JSON 格式：
{
  "demands": [
    {
      "title": "问题标题",
      "description": "详细描述",
      "category": "分类",
      "subcategory": "子分类",
      "tags": ["标签1", "标签2"],
      "importance_score": 8.5
    }
  ],
  "article_summary": "文章整体摘要（100字以内）"
}

文章标题：{title}
文章来源：{platform}
文章正文：
{content}
"""

CLASSIFY_DEMAND_PROMPT = """
判断以下两个职场需求是否描述的是同一个问题（语义相同或高度相似）。

需求A：{demand_a}
需求B：{demand_b}

请回答：
1. 是否相同（是/否）
2. 相似度评分（0-1）
3. 如果相同，给出合并后的更好描述

严格使用 JSON 格式输出：
{
  "is_same": true/false,
  "similarity_score": 0.85,
  "merged_title": "合并后的标题",
  "merged_description": "合并后的描述"
}
"""

TREND_ANALYSIS_PROMPT = """
分析以下职场需求在过去 {period} 内的变化趋势。

需求列表（含各时期出现频次）：
{demand_data}

请分析：
1. 哪些需求在上升（rising）
2. 哪些需求保持稳定（stable）
3. 哪些需求在下降（declining）
4. 是否有新出现的需求主题
5. 给出整体趋势洞察

以 JSON 格式输出。
"""

COMMENT_ANALYSIS_PROMPT = """
以下是一篇职场文章下的高赞评论。请从评论中提炼出读者真正关心的职场问题和需求。
评论比文章更直接反映真实痛点。

评论列表：
{comments}

请提炼出问题列表，JSON 格式，结构同文章分析。
"""
```

#### `extractor.py` — 需求提炼器

```python
"""
核心分析引擎：
1. 接收文章内容，调用 Claude API 提炼需求
2. 支持批量处理：每次发送多篇文章（注意 token 限制）
3. 错误重试：API 调用失败自动重试 3 次
4. 结果解析：将 AI 返回的 JSON 解析为 Demand 对象
5. 成本控制：记录每次 API 调用的 token 消耗
6. 支持本地模型：可配置使用 Ollama 等本地模型替代
"""
```

#### `deduplicator.py` — 语义去重

```python
"""
需求去重策略（按优先级）：
1. 精确匹配：标题完全相同 → 直接合并，frequency +1
2. 模糊匹配：用编辑距离（Levenshtein）检测高度相似标题
3. 语义匹配：用 AI 或文本嵌入（如 sentence-transformers）判断语义相似度
4. 合并逻辑：相似需求合并时，保留更好的描述，累加 frequency

实现方式：
- 新需求入库前，与已有需求逐一比对
- 当需求量大时（>500），先用 TF-IDF 或嵌入向量做初筛，再用 AI 精判
- 可选：使用 sentence-transformers 的 all-MiniLM-L6-v2 模型做本地嵌入
"""
```

#### `trend_detector.py` — 趋势检测

```python
"""
功能：
1. 每周生成趋势快照，记录每个需求的 frequency 和 heat_score
2. 对比相邻两个快照，计算变化率
3. 标记 trend 字段：
   - rising：frequency 周环比增长 > 20%
   - declining：frequency 周环比下降 > 20%
   - stable：其余
4. 生成趋势报告（调用 AI 总结）
5. 检测「新兴需求」：首次出现且热度高的需求
"""
```

### 3.5 定时调度器 `cron.py`

```python
"""
使用 APScheduler 或 schedule 库实现：

定时任务配置：
- 每 6 小时：抓取所有已启用平台的热门文章列表
- 每 12 小时：对未分析的文章执行 AI 分析
- 每周一凌晨：生成趋势快照 + 周报
- 每天凌晨：清理超过 90 天的原始 HTML 数据（保留纯文本）

支持功能：
- 在 settings.yaml 中配置各任务的 cron 表达式
- 支持手动触发某个任务
- 任务执行状态记录到 crawl_logs 表
- 任务失败自动告警（写日志 + 可选邮件通知）
"""
```

### 3.6 数据导出 `exporter/`

```python
"""
支持以下导出格式：

1. Excel 导出 (excel.py)：
   - 需求库总表：所有需求 + 分类 + 频次 + 趋势
   - 按分类分 Sheet
   - 包含数据透视图（按分类统计需求数量）
   - 用 openpyxl 实现

2. CSV 导出 (csv_export.py)：
   - 简单的表格导出，方便导入其他工具

3. Markdown 周报 (markdown.py)：
   - 本周新发现的需求
   - 趋势上升 TOP 10
   - 热门文章 TOP 10
   - 各分类需求数量统计
   - 洞察与分析（AI 生成）

4. Notion 导出 (notion.py)（可选）：
   - 通过 Notion API 同步需求库到 Notion 数据库
   - 需用户提供 Notion Integration Token
"""
```

### 3.7 Web API `api/`

```python
"""
使用 FastAPI 构建 RESTful API，提供以下端点：

文章相关：
- GET    /api/articles                  # 文章列表（支持分页、筛选、排序）
- GET    /api/articles/{id}             # 文章详情
- GET    /api/articles/stats            # 文章统计（各平台数量、时间分布）

需求相关：
- GET    /api/demands                   # 需求列表（支持分页、分类筛选、趋势筛选）
- GET    /api/demands/{id}              # 需求详情（含关联文章列表）
- PUT    /api/demands/{id}              # 更新需求（修改分类、状态、备注）
- PUT    /api/demands/{id}/status       # 更改需求状态（确认/归档/拒绝）
- GET    /api/demands/categories        # 获取所有分类及各分类数量
- GET    /api/demands/tags              # 获取所有标签（词云数据）
- GET    /api/demands/trending          # 趋势上升的需求

分析相关：
- GET    /api/analytics/overview        # 总览仪表盘数据
- GET    /api/analytics/trends          # 趋势图数据
- GET    /api/analytics/category-dist   # 分类分布饼图数据
- GET    /api/analytics/weekly-report   # 获取最新周报

操作相关：
- POST   /api/crawl/trigger             # 手动触发抓取（可选平台）
- POST   /api/analyze/trigger           # 手动触发 AI 分析
- GET    /api/crawl/logs                # 抓取日志
- POST   /api/export/{format}           # 导出数据（excel/csv/markdown）
- GET    /api/config                    # 获取当前配置
- PUT    /api/config                    # 更新配置

搜索：
- GET    /api/search?q=关键词           # 全文搜索（搜文章和需求）

所有列表接口支持：
- page / page_size 分页
- sort_by / sort_order 排序
- platform / category / status / date_range 筛选
"""
```

### 3.8 Web 前端界面

```
构建一个单页面 Web 管理界面，功能区域：

1. 仪表盘（Dashboard）首页：
   - 需求总数、本周新增数、文章总数、已分析比例
   - 需求分类分布饼图
   - 最近7天需求趋势折线图
   - 最新发现的需求列表（TOP 10）
   - 趋势上升的需求列表（TOP 10）

2. 需求库页面：
   - 表格展示所有需求
   - 支持按分类、状态、趋势筛选
   - 支持按频次、重要性、时间排序
   - 点击某个需求可查看详情和关联文章
   - 可修改需求状态和添加备注
   - 搜索框支持全文搜索

3. 文章库页面：
   - 表格展示所有文章
   - 支持按平台、时间筛选
   - 点击可查看文章摘要和提炼出的需求

4. 标签云/分类视图页面：
   - 可视化展示标签的热度分布
   - 按分类浏览需求

5. 趋势分析页面：
   - 需求热度变化趋势图（可选时间段）
   - 新兴需求提示
   - AI 生成的趋势洞察报告

6. 设置页面：
   - 各平台爬虫开关
   - 抓取频率配置
   - AI API Key 配置
   - 导出操作按钮

技术选择：
- 方案A（推荐）：单个 HTML 文件 + Vue 3 CDN + Chart.js CDN
- 方案B：React + Vite（如果需要更复杂的交互）
- 样式：Tailwind CSS CDN
- 图表：Chart.js 或 ECharts
```

---

## 四、配置文件设计

### `settings.yaml`

```yaml
# 全局设置
app:
  name: "职场需求库"
  version: "1.0.0"
  data_dir: "./data"
  log_dir: "./logs"
  log_level: "INFO"

# AI 分析配置
ai:
  provider: "anthropic"           # anthropic / openai / ollama
  api_key: "${ANTHROPIC_API_KEY}" # 从环境变量读取
  model: "claude-sonnet-4-20250514"
  max_tokens: 4096
  temperature: 0.3
  batch_size: 5                   # 每次分析的文章数
  daily_budget: 100               # 每日 API 调用预算（次数）

# 抓取全局配置
scraping:
  default_interval: 5             # 默认请求间隔（秒）
  max_retries: 3
  timeout: 30
  use_proxy: false
  proxy_list: []

# 搜索关键词（所有平台通用）
keywords:
  primary:
    - "职场"
    - "工作"
    - "跳槽"
    - "面试"
    - "升职"
    - "加薪"
    - "辞职"
    - "管理"
    - "领导力"
    - "团队"
  secondary:
    - "职业规划"
    - "职业发展"
    - "工作压力"
    - "职场沟通"
    - "办公室政治"
    - "远程办公"
    - "内卷"
    - "35岁"
    - "裁员"
    - "绩效"

# 定时任务
scheduler:
  crawl_interval_hours: 6
  analyze_interval_hours: 12
  trend_snapshot: "0 0 * * 1"     # 每周一凌晨
  cleanup_days: 90                # 清理超过N天的原始HTML

# Web 服务
server:
  host: "0.0.0.0"
  port: 8000
  cors_origins: ["*"]

# 导出
export:
  default_format: "excel"
  output_dir: "./data/exports"
```

### `platforms.yaml`

```yaml
# 各平台独立配置
zhihu:
  enabled: true
  interval: 8                     # 请求间隔（秒），知乎要更保守
  topics:
    - "职场"
    - "求职"
    - "职业发展"
    - "人际交往"
  min_upvotes: 100                # 只抓点赞数超过此值的回答
  cookie: ""                      # 知乎 Cookie（手动填入）
  use_playwright: true

kr36:
  enabled: true
  interval: 3
  channels:
    - "workplace"
  use_playwright: false

huxiu:
  enabled: true
  interval: 4
  use_playwright: false

juejin:
  enabled: true
  interval: 3
  categories:
    - "career"
  use_playwright: false

toutiao:
  enabled: false                  # 默认关闭，反爬较难
  interval: 10
  use_playwright: true

douban:
  enabled: true
  interval: 5
  groups:
    - "shangban"                  # "上班这件事"
    - "985waste"                  # 按实际小组 ID 填写
  cookie: ""

xiaohongshu:
  enabled: false                  # 默认关闭，反爬很严
  interval: 10
  use_playwright: true

bilibili:
  enabled: true
  interval: 3
  use_playwright: false

weixin_sogou:
  enabled: true
  interval: 15                    # 搜狗限制严格
  use_playwright: true

maimai:
  enabled: false                  # 需登录，默认关闭
  interval: 8
  cookie: ""

baidu_baijiahao:
  enabled: true
  interval: 5
  use_playwright: false

rss_feeds:
  enabled: true
  feeds: []                       # 用户自行添加 RSS 地址
```

---

## 五、CLI 命令行接口

```bash
# 主入口 main.py，使用 click 或 argparse

# 启动完整服务（包含定时任务 + Web 服务）
python -m src.main serve

# 手动抓取
python -m src.main crawl                     # 抓取所有已启用平台
python -m src.main crawl --platform zhihu    # 只抓取知乎
python -m src.main crawl --platform kr36 --limit 20  # 只抓36氪，限制20篇

# 手动分析
python -m src.main analyze                   # 分析所有未分析的文章
python -m src.main analyze --batch-size 10   # 每批处理10篇

# 导出
python -m src.main export excel              # 导出 Excel
python -m src.main export csv                # 导出 CSV
python -m src.main export markdown           # 导出 Markdown 周报
python -m src.main export notion             # 同步到 Notion

# 数据管理
python -m src.main stats                     # 查看统计信息
python -m src.main cleanup                   # 清理旧数据
python -m src.main init-db                   # 初始化数据库

# 趋势
python -m src.main trends                    # 输出当前趋势报告
python -m src.main trends --snapshot         # 生成趋势快照
```

---

## 六、核心实现约束

### 代码质量要求
1. 所有函数必须有 docstring
2. 使用 type hints
3. 异常处理：所有网络请求必须 try-except，不能因为单个页面失败导致整个任务终止
4. 日志：关键操作必须有 INFO 级别日志，错误必须有 ERROR 级别日志含堆栈
5. 配置驱动：所有可变参数通过 yaml 配置，不硬编码

### 爬虫规范
1. 每个爬虫必须检查 robots.txt
2. 请求间隔不小于 2 秒
3. 遵循平台 ToS，不抓取付费内容
4. 存储原文仅供分析，不做公开展示
5. 每个平台单独的错误计数，连续失败 5 次暂停该平台

### AI 调用规范
1. 所有 Prompt 集中管理在 `prompts.py`
2. API 调用必须有重试机制和超时控制
3. 记录每次调用的 token 消耗
4. 支持配置 daily_budget 防止费用失控
5. AI 返回结果必须做 JSON 校验，格式异常则重试

### 安全规范
1. API Key 通过环境变量注入，不写入代码或配置文件
2. Cookie 等敏感信息在 yaml 中留空占位，用户手动填入
3. Web 界面仅限本地访问（localhost），如需远程访问需手动配置

---

## 七、开发顺序建议

请按以下顺序实现，每完成一步确保可以运行测试：

```
Phase 1 — 基础设施
├── 1.1 项目结构初始化 + requirements.txt
├── 1.2 配置加载模块（读取 yaml）
├── 1.3 日志模块
├── 1.4 数据库初始化 + ORM 模型
└── 1.5 HTTP 客户端封装（含反爬策略）

Phase 2 — 爬虫开发
├── 2.1 爬虫基类
├── 2.2 36氪爬虫（最简单，先跑通流程）
├── 2.3 虎嗅爬虫
├── 2.4 知乎爬虫（需要 playwright）
├── 2.5 掘金爬虫
├── 2.6 其余平台爬虫
└── 2.7 通用 RSS 爬虫

Phase 3 — AI 分析
├── 3.1 Prompt 模板
├── 3.2 需求提炼器
├── 3.3 语义去重
├── 3.4 分类器
└── 3.5 趋势检测

Phase 4 — 数据流打通
├── 4.1 CLI 命令行工具（crawl + analyze）
├── 4.2 定时调度器
└── 4.3 导出模块

Phase 5 — Web 界面
├── 5.1 FastAPI 后端 API
├── 5.2 前端仪表盘
├── 5.3 需求库页面
├── 5.4 文章库页面
├── 5.5 趋势分析页面
└── 5.6 设置页面

Phase 6 — 完善
├── 6.1 单元测试
├── 6.2 README 文档
└── 6.3 Docker 部署文件（可选）
```

---

## 八、依赖清单 `requirements.txt`

```
# 网络请求
requests>=2.31.0
httpx>=0.25.0
playwright>=1.40.0
beautifulsoup4>=4.12.0
lxml>=5.0.0
feedparser>=6.0.0           # RSS 解析

# 数据库
sqlalchemy>=2.0.0
alembic>=1.13.0             # 数据库迁移

# Web 框架
fastapi>=0.109.0
uvicorn>=0.27.0
pydantic>=2.5.0

# AI
anthropic>=0.18.0           # Claude API
# openai>=1.10.0            # 可选 OpenAI

# 数据处理
openpyxl>=3.1.0             # Excel 导出
pandas>=2.1.0               # 数据分析辅助

# 定时任务
apscheduler>=3.10.0

# CLI
click>=8.1.0

# 工具
pyyaml>=6.0.0
python-dotenv>=1.0.0
fake-useragent>=1.4.0       # UA 生成
python-Levenshtein>=0.23.0  # 文本相似度
jieba>=0.42.0               # 中文分词

# 日志
rich>=13.0.0                # 美化终端输出
loguru>=0.7.0               # 更好的日志

# 测试
pytest>=7.4.0
pytest-asyncio>=0.23.0
```

---

## 九、额外功能（请一并实现）

1. **数据备份**：每周自动备份 SQLite 数据库文件，保留最近 4 个备份
2. **健康检查**：API 提供 `/health` 端点，返回各平台爬虫状态和最后成功时间
3. **通知机制**：发现热门新需求时（importance > 8），在终端高亮提示
4. **数据清洗管道**：去除文章中的广告文案、推广内容、无关段落
5. **多语言适配**：虽然以中文为主，但代码结构预留英文内容支持
6. **热度标准化**：不同平台的热度指标（阅读数、点赞数）量级不同，需做归一化处理（公式记录在代码注释中）
7. **去重缓存**：用布隆过滤器或 set 缓存已抓取的 URL，避免重复请求
8. **断点续爬**：记录每个平台上次抓取的位置（页码/时间戳），下次从断点继续
9. **需求关联图谱**：相似需求之间建立关联关系，在前端可视化为网络图
10. **用户标注系统**：前端支持用户对需求进行「确认」「拒绝」「合并」操作，这些操作反馈到 AI 后续分析中（主动学习）
