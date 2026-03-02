# 职场热文抓取 & 需求库系统

## 📖 项目简介

职场需求库是一套自动化的职场内容采集与分析系统。它从 12 个主流中文内容平台定时抓取职场相关热文，利用 AI（Claude / OpenAI / Ollama）自动提取和分类职场需求，将结构化数据存入需求库，并通过 Web 仪表盘实现可视化浏览、趋势追踪与数据导出。

**核心功能：**

- 🕷️ **多平台抓取** — 支持知乎、36氪、虎嗅、掘金等 12 个平台，自动限速与反爬
- 🤖 **AI 需求提取** — 基于大语言模型从文章中提取结构化职场需求，自动分类为 9 大类
- 📊 **Web 仪表盘** — Vue 3 + Tailwind CSS 单页面应用，含仪表盘、需求库、文章库、趋势分析等 6 个页面
- 📈 **趋势检测** — 按周快照，自动识别上升/下降/新增需求趋势
- 🔄 **定时调度** — APScheduler 驱动，可配置抓取和分析周期
- 📦 **多格式导出** — 支持 Excel、CSV、Markdown、Notion
- 🔍 **全文搜索** — 跨文章和需求的关键词搜索
- 💾 **自动备份** — SQLite 数据库定期备份与清理

---

## 🚀 快速开始

### 环境要求

- Python 3.11+
- Node.js（可选，仅 Playwright 渲染 JS 页面时需要）

### 安装

```bash
git clone https://github.com/charlesbo/workplace-demand-library.git
cd workplace-demand-library
pip install -r requirements.txt
playwright install  # 可选，抓取 JS 渲染页面时需要
```

### 配置

1. **设置 API 密钥** — 复制 `.env.example` 为 `.env`，填入 `ANTHROPIC_API_KEY`（或 OpenAI 密钥）
2. **AI 配置** — 编辑 `config/settings.yaml`，调整 `ai.provider`、`ai.model` 等参数
3. **平台开关** — 编辑 `config/platforms.yaml`，启用或禁用各平台，填入需要的 Cookie

### 初始化数据库

```bash
python -m src.main init-db
```

### 启动

```bash
# 完整服务（定时调度 + Web API）
python -m src.main serve

# 手动触发一次抓取
python -m src.main crawl

# 手动触发一次 AI 分析
python -m src.main analyze
```

服务启动后，访问 `http://localhost:8000` 打开 Web 界面。

---

## 📋 CLI 命令参考

| 命令 | 说明 | 示例 |
|------|------|------|
| `serve` | 启动完整服务（调度器 + Web API） | `python -m src.main serve` |
| `crawl` | 手动抓取文章 | `python -m src.main crawl --platform zhihu --limit 50` |
| `analyze` | 手动运行 AI 需求提取 | `python -m src.main analyze --batch-size 10` |
| `export excel` | 导出需求到 Excel | `python -m src.main export excel` |
| `export csv` | 导出需求到 CSV | `python -m src.main export csv` |
| `export markdown` | 导出需求到 Markdown | `python -m src.main export markdown` |
| `export notion` | 导出需求到 Notion | `python -m src.main export notion` |
| `stats` | 查看数据库统计信息 | `python -m src.main stats` |
| `cleanup` | 清理过期的原始 HTML 数据 | `python -m src.main cleanup` |
| `trends` | 查看趋势报告 | `python -m src.main trends --snapshot` |
| `backup` | 手动备份数据库 | `python -m src.main backup` |
| `init-db` | 初始化或迁移数据库 | `python -m src.main init-db` |

---

## 🌐 Web 界面

> Web 界面基于 Vue 3 + Tailwind CSS + Chart.js，以单页面应用形式提供。

<!-- 截图占位 -->
<!-- ![Dashboard](docs/screenshots/dashboard.png) -->

| 页面 | 说明 |
|------|------|
| 📊 **仪表盘** | 总览统计、平台分布、最近抓取日志、需求类别分布图 |
| 📋 **需求库** | 需求列表，支持分类筛选、状态管理、标签过滤与搜索 |
| 📰 **文章库** | 已抓取文章列表，支持按平台和日期筛选，查看关联需求 |
| 📈 **趋势分析** | 需求趋势折线图、上升/下降趋势识别、周报生成 |
| 🏷️ **标签云** | 需求标签可视化，快速定位高频话题 |
| ⚙️ **设置** | 平台开关配置、AI 参数调整、触发手动抓取/分析 |

---

## 📡 API 文档

服务启动后可访问 Swagger 文档：`http://localhost:8000/docs`

### 文章相关

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/articles` | 分页查询文章列表 |
| GET | `/api/articles/stats` | 文章统计信息（按平台、日期等） |
| GET | `/api/articles/{article_id}` | 获取文章详情及关联需求 |

### 需求相关

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/demands` | 分页查询需求列表 |
| GET | `/api/demands/categories` | 获取需求分类及计数 |
| GET | `/api/demands/tags` | 获取需求标签及计数 |
| GET | `/api/demands/trending` | 获取热门/趋势需求 |
| GET | `/api/demands/{demand_id}` | 获取需求详情、关联文章和相关需求 |
| PUT | `/api/demands/{demand_id}` | 更新需求信息（分类、标签等） |
| PUT | `/api/demands/{demand_id}/status` | 更新需求状态 |
| PUT | `/api/demands/{demand_id}/annotate` | 需求标注（确认、拒绝、合并） |

### 分析与统计

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/analytics/overview` | 总览数据 |
| GET | `/api/analytics/trends` | 趋势图表数据 |
| GET | `/api/analytics/category-dist` | 需求分类分布 |
| GET | `/api/analytics/weekly-report` | 周报数据 |
| GET | `/api/analytics/demand-graph` | 需求关系图谱 |

### 操作

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/crawl/trigger` | 触发手动抓取 |
| POST | `/api/analyze/trigger` | 触发手动 AI 分析 |
| GET | `/api/crawl/logs` | 查询抓取日志 |
| POST | `/api/export/{fmt}` | 导出数据（excel/csv/markdown/notion） |

### 配置与搜索

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/config` | 获取当前运行时配置 |
| PUT | `/api/config` | 更新运行时配置 |
| GET | `/api/search` | 全文搜索文章与需求 |
| GET | `/health` | 健康检查 |

---

## 🔧 配置说明

### settings.yaml

```yaml
app:                          # 应用基础配置
  name: "职场需求库"
  data_dir: "./data"
  log_level: "INFO"

ai:                           # AI 分析配置
  provider: "anthropic"       # 可选: anthropic / openai / ollama
  model: "claude-sonnet-4-20250514"
  batch_size: 5               # 每批分析文章数
  daily_budget: 100           # 每日 API 调用预算

scraping:                     # 抓取全局配置
  default_interval: 5         # 默认请求间隔（秒）
  max_retries: 3
  timeout: 30

keywords:                     # 搜索关键词（所有平台通用）
  primary: ["职场", "工作", "跳槽", ...]
  secondary: ["职业规划", "内卷", "35岁", ...]

scheduler:                    # 定时任务配置
  crawl_interval_hours: 6
  analyze_interval_hours: 12
  cleanup_days: 90

server:                       # Web 服务配置
  host: "0.0.0.0"
  port: 8000

export:                       # 导出配置
  default_format: "excel"
  output_dir: "./data/exports"

backup:                       # 备份配置
  max_backups: 4
  backup_dir: "./data/backups"
```

### platforms.yaml

```yaml
zhihu:                        # 每个平台独立配置
  enabled: true
  interval: 8                 # 请求间隔（秒）
  topics: ["职场", "求职"]
  min_upvotes: 100
  cookie: ""                  # 手动填入 Cookie
  use_playwright: true

kr36:
  enabled: true
  interval: 3
  use_playwright: false

# ... 更多平台配置见 config/platforms.yaml
```

### 环境变量

| 变量 | 说明 | 必填 |
|------|------|------|
| `ANTHROPIC_API_KEY` | Anthropic Claude API 密钥 | 使用 Claude 时必填 |
| `OPENAI_API_KEY` | OpenAI API 密钥 | 使用 OpenAI 时必填 |
| `NOTION_TOKEN` | Notion Integration Token | 导出到 Notion 时必填 |

---

## 📊 支持的平台

| 平台名 | 模块 | 抓取策略 | 默认状态 |
|--------|------|----------|----------|
| 知乎 | `zhihu.py` | Playwright + Cookie | ✅ 启用 |
| 36氪 | `kr36.py` | HTTP 请求 | ✅ 启用 |
| 虎嗅 | `huxiu.py` | HTTP 请求 | ✅ 启用 |
| 掘金 | `juejin.py` | HTTP 请求 | ✅ 启用 |
| 今日头条 | `toutiao.py` | Playwright | ❌ 禁用 |
| 豆瓣小组 | `douban.py` | HTTP + Cookie | ✅ 启用 |
| 小红书 | `xiaohongshu.py` | Playwright | ❌ 禁用 |
| B站 | `bilibili.py` | HTTP 请求 | ✅ 启用 |
| 微信（搜狗） | `weixin_sogou.py` | Playwright | ✅ 启用 |
| 脉脉 | `maimai.py` | Cookie 登录 | ❌ 禁用 |
| 百度百家号 | `baidu_baijiahao.py` | HTTP 请求 | ✅ 启用 |
| RSS 通用 | `rss_generic.py` | feedparser | ✅ 启用 |

---

## 🤖 AI 分析

### 支持的模型提供商

- **Anthropic Claude**（默认） — 推荐使用 Claude Sonnet 系列
- **OpenAI** — 支持 GPT-4 等模型
- **Ollama** — 本地部署，无需 API 密钥

### 需求分类体系（9 大类）

| 类别 | 说明 |
|------|------|
| 沟通协作 | 跨部门沟通、远程协作、会议效率等 |
| 职业发展 | 晋升路径、技能提升、职业转型等 |
| 求职面试 | 简历优化、面试技巧、求职渠道等 |
| 团队管理 | 团队建设、绩效管理、领导力等 |
| 职场情绪 | 压力管理、倦怠应对、心理健康等 |
| 职场关系 | 同事相处、上下级关系、办公室政治等 |
| 工作效率 | 时间管理、工具推荐、流程优化等 |
| 薪酬福利 | 薪资谈判、福利对比、行业薪资水平等 |
| 行业洞察 | 行业趋势、政策解读、市场分析等 |

### 去重策略

系统通过 `DemandDeduplicator` 模块对提取的需求进行去重，综合使用 Levenshtein 编辑距离和 jieba 分词相似度，避免重复需求入库。

---

## 📁 项目结构

```
workplace-demand-library/
├── config/
│   ├── settings.yaml          # 全局配置
│   └── platforms.yaml         # 平台配置
├── data/                      # 数据目录（SQLite 数据库、导出文件、备份）
├── logs/                      # 日志文件
├── src/
│   ├── main.py                # CLI 入口（Click）
│   ├── analyzer/
│   │   ├── extractor.py       # AI 需求提取器
│   │   ├── classifier.py      # 需求分类器
│   │   ├── deduplicator.py    # 需求去重
│   │   ├── trend_detector.py  # 趋势检测
│   │   └── prompts.py         # AI Prompt 模板
│   ├── api/
│   │   ├── server.py          # FastAPI 服务启动
│   │   └── routes.py          # API 路由定义（24 个端点）
│   ├── scrapers/
│   │   ├── base.py            # 爬虫基类
│   │   ├── zhihu.py           # 知乎爬虫
│   │   ├── kr36.py            # 36氪爬虫
│   │   ├── huxiu.py           # 虎嗅爬虫
│   │   ├── juejin.py          # 掘金爬虫
│   │   ├── toutiao.py         # 今日头条爬虫
│   │   ├── douban.py          # 豆瓣爬虫
│   │   ├── xiaohongshu.py     # 小红书爬虫
│   │   ├── bilibili.py        # B站爬虫
│   │   ├── weixin_sogou.py    # 微信搜狗爬虫
│   │   ├── maimai.py          # 脉脉爬虫
│   │   ├── baidu_baijiahao.py # 百度百家号爬虫
│   │   └── rss_generic.py     # RSS 通用爬虫
│   ├── storage/
│   │   ├── database.py        # 数据库连接与会话管理
│   │   ├── models.py          # SQLAlchemy 模型定义
│   │   └── migrations.py      # 数据库迁移
│   ├── exporter/
│   │   ├── excel.py           # Excel 导出
│   │   ├── csv_export.py      # CSV 导出
│   │   ├── markdown.py        # Markdown 导出
│   │   └── notion.py          # Notion 导出
│   ├── scheduler/
│   │   └── cron.py            # APScheduler 定时任务
│   └── utils/
│       ├── config.py          # 配置加载
│       ├── logger.py          # 日志工具（Loguru + Rich）
│       ├── http_client.py     # HTTP 客户端封装
│       ├── anti_crawl.py      # 反爬对策
│       ├── rate_limiter.py    # 速率限制
│       └── text_cleaner.py    # 文本清洗
├── web/
│   ├── index.html             # 前端入口
│   ├── app.js                 # Vue 3 应用
│   └── style.css              # 样式
├── tests/                     # 测试目录
├── requirements.txt           # Python 依赖
└── README.md
```

---

## 🧪 测试

```bash
# 运行全部测试
pytest tests/

# 运行指定测试文件
pytest tests/test_extractor.py -v

# 异步测试
pytest tests/ -v --asyncio-mode=auto
```

---

## 📦 导出格式

| 格式 | 命令 | 说明 |
|------|------|------|
| Excel (.xlsx) | `python -m src.main export excel` | 含分类 Sheet、自动列宽 |
| CSV (.csv) | `python -m src.main export csv` | 纯文本，适合二次处理 |
| Markdown (.md) | `python -m src.main export markdown` | 按分类分组的报告格式 |
| Notion | `python -m src.main export notion` | 同步到 Notion 数据库 |

导出文件默认保存在 `data/exports/` 目录。

---

## 🔒 安全说明

- **API 密钥** — 通过环境变量（`.env` 文件）配置，不要提交到版本控制
- **Cookie 配置** — 在 `config/platforms.yaml` 中手动填入，注意保护隐私
- **Web 界面** — 默认绑定 `0.0.0.0:8000`，建议仅在本地或内网使用，生产环境请配合反向代理和认证

---

## 📄 License

[MIT](LICENSE)
