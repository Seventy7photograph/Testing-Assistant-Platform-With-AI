# 测试工程师助手平台

[![CI](https://github.com/Seventy7photograph/Testing-Assistant-Platform-With-AI/actions/workflows/ci.yml/badge.svg)](https://github.com/Seventy7photograph/Testing-Assistant-Platform-With-AI/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688.svg)](https://fastapi.tiangolo.com/)
[![Vue](https://img.shields.io/badge/Vue-3-42b883.svg)](https://vuejs.org/)
[![Version](https://img.shields.io/badge/version-v1.1.0-blue.svg)](CHANGELOG.md)

> 面向测试工程师的**一体化本地 / 内网工作台**：把「需求文档 → 测试用例」与「测试执行数据 → 测试报告」
> 两条日常高频链路，收进同一个控制台、同一套配置、同一份存储。
>
> 后端 **Python + FastAPI**，前端 **Vue 3 + TypeScript + Vite + Element Plus**，
> 默认主题**冰川蓝 + 白**，可一键切换**深色护眼模式**；可折叠侧边栏 + 顶部导航，
> 全站带操作提示与动效。
> **未配置大模型 API Key 时自动降级为纯规则引擎，链路依然端到端可用。**

**导航**：[能力范围](#一能力范围) · [目录结构](#二目录结构) · [快速开始](#三快速开始) ·
[接口清单](#四接口清单) · [架构与扩展点](#五架构与扩展点) · [设计系统](#六设计系统与提示系统) ·
[常见问题](#七常见问题faq) · [许可与致谢](#八许可与致谢) ·
[更新日志](CHANGELOG.md) · [贡献指南](CONTRIBUTING.md) · [安全策略](SECURITY.md)

---

## 一、能力范围

平台由两条**互相独立、共用基座**的链路组成。它们可以分别使用，也可以串在同一次工作流里。

### 1.1 用例生成链路（需求 → 用例）

| 能力 | 说明 |
| --- | --- |
| 文档上传与解析 | `.docx` / `.pdf` / `.txt` / `.md` / `.csv` / `.json`，兼容 GBK 等中文编码，Word 表格结构化平铺 |
| 需求结构化 | LLM 结构化抽取 + 规则引擎解析双路，LLM 缺失 / 失败自动降级并显式告警 |
| 测试设计 | 等价类划分、边界值分析（min-1/min/min+1/max-1/max/max+1）、场景法（主流程 / 备选流 / 异常流 / 业务规则） |
| 用例优化 | 两层去重（精确指纹 + 跨方法语义重叠，合并关联需求并记录覆盖方法）、优先级排序、按方法自动编号（TC-EQ / BV / SC） |
| 用例导出 | Excel（4 个 Sheet：用例明细 / 用例统计 / 需求追溯 / 生成信息）+ JSON |
| 需求追溯 | 需求条目 ↔ 用例双向追溯；覆盖率与缺口（未被覆盖的需求）直接可见 |

### 1.2 测试报告链路（执行数据 → 报告）

| 能力 | 说明 |
| --- | --- |
| 多来源执行数据摄入 | 手工粘贴 / 上传 JSON / 内置示例数据集；字段容错、缺失值显式标注 |
| 确定性指标 | 通过率、失败率、阻塞率、用例总数、缺陷分布、模块维度拆解——先算指标，再谈结论 |
| AI 归纳报告 | 结论先行 → 风险与阻塞 → 缺陷分析 → 改进建议；支持 **SSE 流式输出**，边生成边阅读 |
| 发版判定 | 可配置阈值（失败率 / 阻塞率 / 执行率 / 通过线），自动给出「可发布 / 有条件发布 / 不建议发布」判定 |
| 存档与趋势 | SQLite 存档，历史报告检索、趋势对比、多份报告横向比对 |
| 报告导出 | Markdown / HTML / DOCX / JSON 四种格式 |

### 1.3 平台能力

| 能力 | 说明 |
| --- | --- |
| 统一总览 | 首页仪表盘汇总两条链路的状态、最近文档 / 用例集 / 报告与关键指标 |
| 统一配置 | 两条链路**共用同一份大模型配置**（`.env` 基线 + 界面运行时覆盖），保存即生效、可一键恢复 |
| 双主题与密度 | 默认「冰川蓝 + 白」，顶部一键切换**深色护眼模式**；标准 / 紧凑 / 宽松三档显示密度 |
| 批量操作 | 文档库、用例集、报告存档均支持多选与**批量删除**（服务端一次最多 200 条，自动去重） |
| 产出可追溯 | 用例集列表直出「来源需求 + 生成引擎（模型名）」，点来源需求直达结构化需求；需求页反向列出已生成的用例集；文档库标出解析引擎 |
| 全站提示系统 | 五种提示形态统一落地（见 [六、设计系统](#六设计系统与提示系统)） |
| 统一异常出口 | 所有错误返回 `{success, code, message, detail}`，前端统一渲染为可读错误卡片 |

### 1.4 架构预留（只定义接口，不实现逻辑）

未实现的能力**一律显式标注**，调用返回 **501 + 说明**，不做静默降级：

- 设计策略：判定表、因果图、正交实验（`app/design/planned_strategies.py`，占位已就绪）
- 导出器：XMind / CSV / TestLink XML（`Exporter` 抽象 + 注册表已就绪）
- LLM Provider：Qwen / GLM / 本地 Ollama（注册表已就绪）
- 外部集成：禅道 / Jira（`ExternalSyncAdapter` 抽象已定义，含占位实现）

---

## 二、目录结构

```
Testing-Assistant-Platform With AI/
├── .github/                          # CI / Issue 与 PR 模板 / Dependabot
├── app/                              # 后端（FastAPI）
│   ├── main.py                       # 装配入口：中间件 / 异常处理 / 路由 / 静态页
│   ├── repository.py                 # 持久化门面 + JSON 文件存储实现
│   ├── api/
│   │   ├── deps.py                   # 依赖注入
│   │   ├── responses.py              # 下载响应（中文文件名 RFC 5987，导出与原文下载共用）
│   │   └── routes/                   # 路由层（一个业务面一个文件）
│   │       ├── health.py             #   /health /integrations
│   │       ├── overview.py           #   /overview
│   │       ├── documents.py          #   文档上传 / 列表 / 详情 / 原文下载 / 删除 / 批量删除
│   │       ├── requirements.py       #   需求解析 / 查询 / 基于需求生成用例
│   │       ├── testcases.py          #   设计方法清单 / 用例集列表 / 生成 / 详情 / 删除 / 批量删除
│   │       ├── pipeline.py           #   一键流水线
│   │       ├── export.py             #   导出格式 / 导出文件流
│   │       ├── llm.py                #   大模型配置读写 / 连通性测试 / 模型候选
│   │       └── report.py             #   测试报告：状态/指标/样例/生成/流式/存档/趋势/阈值/导出
│   ├── core/                         # 配置 / 异常 / 日志 / 注册表 / 工具
│   ├── schemas/                      # 领域枚举与请求响应契约（pydantic）
│   ├── services/                     # 应用服务：文档 / 需求 / 流水线 / 导出 / 规则解析
│   ├── parsers/                      # 文档解析器（docx / pdf / text + 注册表）
│   ├── design/                       # 测试设计引擎（等价类 / 边界值 / 场景法 / 优化器 / 未实现方法占位）
│   ├── exporters/                    # 用例导出器（excel / json + 注册表）
│   ├── llm/                          # LLM Provider（deepseek / openai 兼容 / fake / null + 工厂 + 目录）
│   ├── report/                       # 测试报告模块（config/metrics/prompts/llm/store/exporters/samples/schemas）
│   ├── integrations/                 # 外部集成抽象（禅道 / Jira 占位，未实现）
│   └── static/                       # 前端构建产物（由 frontend 构建生成，勿手改）
├── frontend/                         # 前端源码（Vue 3 + TS + Vite + Element Plus）
│   ├── src/
│   │   ├── api/                      # 类型化 API 客户端（client / index / types）
│   │   ├── components/               # 通用组件（AppShell / SideRail / TopBar / Tip / NoticeHost ...）
│   │   ├── composables/              # useAsync / useFeedback（含 confirmAction）
│   │   ├── router/                   # 路由表（11 条路由）
│   │   ├── stores/                   # Pinia：health / notice / ui（密度与主题偏好）
│   │   ├── styles/                   # tokens.css / base.css / element.css（设计令牌 / 双主题 / 动效）
│   │   ├── utils/                    # labels / markdown
│   │   └── views/                    # 页面视图（总览 / 用例生成 / 文档 / 用例集 / 报告 ...）
│   └── tools/                        # 本地 QA 辅助脚本（截图 / 布局测量，需本机 Chrome）
├── examples/                         # 离线演示与验收脚本
├── tests/                            # pytest 测试
├── scripts/                          # 辅助脚本（本地假模型服务等）
├── docs/review/                      # UI 走查截图（本地证据，不入库）
├── storage/                          # 运行时数据（上传原文 / 解析结果 / 用例集 / 报告库 / 运行时配置，不入库）
├── output/                           # 离线脚本产物（不入库）
├── DESIGN.md / PRODUCT.md            # 设计世界与产品定义（前端改动的依据）
├── CHANGELOG.md                      # 更新日志
├── OPTIMIZATION.md                   # 资深测试工程师视角的体验与缺陷修复记录
└── run.py                            # 本地启动入口
```

> **文件分类原则**：后端按「层次 + 业务面」分目录，前端按「api / components / views / stores / styles / utils」分目录；
> 运行时产物一律落在 `storage/`、`output/`，与源码严格分离，便于查找、编辑与删除。

---

## 三、快速开始

### 3.1 环境准备

```powershell
# 后端（Windows PowerShell 7）
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

> 若 `pip install` 报 `UnicodeDecodeError: 'gbk' codec...`，是旧版 pip 按本地编码读取 UTF-8 需求文件，
> 先执行 `python -m pip install -U pip` 升级即可。

### 3.2 启动

```powershell
python run.py                    # 默认 http://127.0.0.1:8000
python run.py --port 8123        # 换端口
python run.py --host 127.0.0.1   # 只允许本机访问（更安全）
python run.py --no-reload        # 关闭热重载
```

浏览器请用 **`http://127.0.0.1:<port>/`** 访问，不要用 `0.0.0.0`（那是监听地址，不是访问地址，
经系统代理时会被当成非法目标返回 502）。

### 3.3 前端开发（仅在改动 `frontend/**` 时需要）

```powershell
cd frontend
npm install
npm run dev        # 开发服务器 :5173，/api 已代理到 127.0.0.1:8000
npm run typecheck  # vue-tsc 类型检查
npm run build      # 类型检查 + 构建，产物自动写入 ../app/static
```

> `app/static` 是**前端构建产物目录**，由 `npm run build` 生成（CI 也会校验 `app/static/index.html` 存在）。
> 仓库中已保留一份最新产物，克隆后 `python run.py` 即可直接使用；**改了 `frontend/**` 必须重新
> 执行 `npm run build` 并一并提交产物**，否则界面不会更新。

### 3.4 无 Key 也能验证：离线演示与验收

```powershell
python examples/demo_offline.py         # 用例生成链路：需求 -> 用例 -> Excel（纯规则引擎）
python examples/demo_report_offline.py  # 报告链路：状态->指标->生成->流式->存档->导出->删除
python examples/acceptance_check.py     # 黑盒验收：起真实服务跑端到端 HTTP 链路
python -m pytest -q                     # 单元 + 接口测试
```

三个脚本都会把 `STORAGE_DIR` 指向各自的临时目录，并显式指定模型形态，
因此**不看本机 `.env` 与界面覆盖配置的脸色**，跑到哪儿结果都一样；
演示产物也不会落进你的真实文档 / 用例集库。

---

## 四、接口清单

统一前缀 `api_prefix = /api/v1`，统一响应包 `{success, code, message, detail, data}`。
交互式文档：服务启动后访问 `/docs`（Swagger）或 `/redoc`。

### 平台 / 配置

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 健康检查与能力清单（含 LLM 启用状态） |
| GET | `/integrations` | 外部集成清单（禅道 / Jira 占位，未实现） |
| GET | `/overview` | 平台总览（首页仪表盘数据） |
| GET / PUT / DELETE | `/llm/config` | 读取 / 保存 / 恢复大模型配置（基线为 `.env`） |
| POST | `/llm/config/test` | 大模型连通性测试 |
| GET | `/llm/models` | 候选模型列表 |

### 用例生成链路

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/documents/upload` | 上传文档并解析为文本（multipart，字段名 `file`） |
| GET | `/documents` | 最近上传的文档 |
| GET | `/documents/{doc_id}` | 文档详情 |
| GET | `/documents/{doc_id}/download` | 下载文档原文（原文件名，附件形式） |
| DELETE | `/documents/{doc_id}` | 删除文档及其解析结果与原文 |
| POST | `/documents/batch-delete` | 批量删除文档（body `{ids: [...]}`，≤ 200，自动去重） |
| POST | `/requirements/parse` | 解析需求为结构化模型 |
| POST | `/requirements/{doc_id}/testcases` | 基于已解析需求生成用例（`methods` / `use_llm_in_design` 为查询参数） |
| GET | `/requirements/{doc_id}` | 获取已解析的需求模型 |
| DELETE | `/requirements/{doc_id}` | 删除已解析的需求模型 |
| POST | `/pipeline/generate` | 一键：需求文档 → 结构化需求 → 测试用例 |
| GET | `/testcases/methods` | 可用设计方法清单 |
| POST | `/testcases/generate` | 生成测试用例 |
| GET | `/testcases/suites` | 最近生成的用例集（`limit` ≤ 50；`doc_id` 只列该需求生成的，供需求页反向追溯） |
| GET | `/testcases/{suite_id}` | 用例集详情 |
| DELETE | `/testcases/{suite_id}` | 删除用例集 |
| POST | `/testcases/batch-delete` | 批量删除用例集（body `{ids: [...]}`，≤ 200，自动去重） |
| GET | `/export/formats` | 可用导出格式 |
| POST | `/export` | 导出用例集（返回文件流） |
| GET | `/export/{suite_id}/{fmt}` | 按路径导出（便于浏览器直接下载） |

### 测试报告链路（前缀 `/report`）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/report/status` | 报告模块运行状态 |
| POST | `/report/metrics` | 只算指标，不调模型 |
| GET | `/report/samples` | 内置示例数据集 |
| POST | `/report/analyze` | 指标 + AI 报告（一次性返回） |
| POST | `/report/analyze/stream` | 指标 + AI 报告（SSE 流式） |
| POST | `/report/probe` | 报告链路模型探活 |
| GET | `/report/reports` | 历史报告列表 |
| GET | `/report/reports/{report_id}` | 报告详情 |
| DELETE | `/report/reports/{report_id}` | 删除报告 |
| POST | `/report/reports/batch-delete` | 批量删除报告存档（body `{ids: [...]}`，≤ 200，自动去重） |
| GET | `/report/reports/{report_id}/export` | 导出报告（md / html / docx / json） |
| GET | `/report/trends` | 趋势数据点 |
| GET / PUT / DELETE | `/report/thresholds` | 读取 / 保存 / 恢复发版判定阈值 |

---

## 五、架构与扩展点

### 5.1 分层

```
HTTP 路由 (app/api/routes)
        │  只做参数校验、编排与响应包装
        ▼
应用服务 (app/services, app/report)
        │  编排领域能力，不关心 HTTP
        ▼
领域能力 (parsers / design / exporters / llm / metrics)
        │  全部通过注册表可插拔
        ▼
持久化 (app/repository.py, app/report/store.py)
```

### 5.2 五类扩展点

| 扩展点 | 抽象 | 注册表 | 新增一个的实现方式 |
| --- | --- | --- | --- |
| 文档解析 | `DocumentParser` | `app/parsers/registry.py` | 新增子类并注册，前后端支持列表自动出现 |
| 测试设计 | `DesignStrategy` | `app/design/registry.py` | 同上；判定表 / 因果图 / 正交已留占位（未实现） |
| 用例导出 | `Exporter` | `app/exporters/registry.py` | 同上；`/export/formats` 与前端下拉框自动出现 |
| LLM 提供方 | `LLMProvider` | `app/llm/factory.py` | 实现接口 + 在 `catalog.py` 登记能力 |
| 外部集成 | `ExternalSyncAdapter` | `app/integrations/base.py` | 抽象已定义，占位调用返回 501 |

### 5.3 配置优先级（两条链路共用）

```
界面运行时覆盖 (storage/data/llm_config.json)
        >
.env 基线 (LLM_PROVIDER / LLM_API_KEY / LLM_BASE_URL / LLM_MODEL ...)
        >
代码默认值 (app/core/config.py)
```

- 报告链路额外维护「发版判定阈值」，存于 `storage/data/report_config.json`，同样支持界面改、界面恢复。
- 版本号以代码 `app/__init__.py` 为唯一来源，`.env` 中的 `APP_VERSION` 不会覆盖它。

---

## 六、设计系统与提示系统

完整定义见 [DESIGN.md](DESIGN.md)（设计世界「冰川刻度」）与 [PRODUCT.md](PRODUCT.md)（产品定位与提示规范）。

**主题**：默认**冰川蓝 + 白**，顶部导航可一键切换**深色护眼模式**（极夜冰层）。
两套主题共用同一组令牌，集中在 `frontend/src/styles/tokens.css`——冰层、墨色、语义色、
密度变量、字体尺度都在那里，改主题只改这一处；切换时给 `<html>` 挂 260ms 全局过渡，
做一次「冰面重结晶」而不是硬跳。主题选择写入 `localStorage`，下次打开保持。

**布局**：左侧可展开菜单栏（窄屏自动收起为浮层 + 遮罩，点击任意处关闭）+ 顶部导航
（面包屑、命令面板入口、显示密度、主题开关、帮助抽屉、健康状态）。11 条路由：总览 / 用例生成 /
文档与需求 / 结构化需求 / 用例集 / 用例集详情 / 报告工作台 / 报告存档 / 报告详情 / 大模型与阈值 / 404。

**五种提示形态**（覆盖「不打断」到「必须确认」的全部强度）：

| 形态 | 组件 | 使用场景 |
| --- | --- | --- |
| 行内字段提示 | `FieldHint.vue` | 表单字段下方的常驻说明，解释输入格式与影响 |
| 悬停解释 | `Tip.vue` | 术语、指标口径、算法细节；虚线下划线或 `?` 圆标，悬停/聚焦展开 |
| 空状态引导 | `EmptyState.vue` | 列表为空时说明「为什么空」并给出主操作入口 |
| 二次确认 | `confirmAction`（`useFeedback.ts`） | 删除等不可逆操作，必须显式确认 |
| 浮层通知 | `NoticeHost.vue` | 成功 / 失败 / 警告 / 信息四态，操作结果即时反馈 |

**动效**：结冰式入场（`freeze-sweep` / `settle` / `rule-draw` / `rise-in`）与路由过渡（`route-fade`），
统一在 `frontend/src/styles/base.css`。全部动画（含主题切换过渡与明暗图标旋转）尊重
`prefers-reduced-motion`。

**拒绝清单**（前端改动不得引入）：渐变文字、装饰性玻璃拟态、卡片彩色左描边、硬偏移阴影、
emoji 图标、纯灰中性色、眉题（kicker）、01/02/03 序号、hero 大数字模板、每节相同入场动画。

---

## 七、常见问题（FAQ）

**Q1：没有大模型 API Key 能用吗？**
能。用例生成链路自动降级为纯规则引擎，功能完整可跑通；报告链路会显式提示「未启用 AI 归纳」，
但仍可输出确定性指标与模板化报告。想验证 LLM 链路又不想花钱，可用 `LLM_PROVIDER=fake`。

**Q2：两条链路的模型配置是分开的吗？**
不是。**共用同一份配置**：`.env` 是基线，界面「大模型与阈值」页可临时覆盖，保存即生效，
并可一键「恢复 `.env` 配置」。

**Q3：为什么某些能力点了没反应？**
那些是**架构预留**（判定表 / 因果图 / 正交 / XMind / CSV / TestLink / 禅道 / Jira /
Qwen / GLM / Ollama），当前版本尚未实现。平台**不会静默失败**：接口返回 501，
界面在这些入口上显式标注「未实现」，不会让你以为点了就会出结果。

**Q4：数据存放在哪里？会不会丢？**
统一在 `storage/`：`uploads/`（上传原文）、`data/`（解析结果、用例集、报告库 `reports.db`、运行时配置）、
`exports/`（导出归档）。这是纯本地文件 / SQLite，备份 `storage/` 即完成备份。

**Q5：浏览器打开是 502 Bad Gateway？**
多半是本地代理（Clash / V2Ray / 公司代理）拦截了 `127.0.0.1`。把 `127.0.0.1`、`localhost`
加入代理绕过列表，或在 Windows「设置 → 网络和 Internet → 代理」勾选「请勿对本地地址使用代理服务器」。

**Q6：端口被占用？**
`python run.py --port <其他端口>`。后端与前端开发服务器（5173）都已参数化。

**Q7：怎么切换深色护眼模式？**
顶部导航右侧的月亮 / 太阳图标一键切换，选择会记住。深色模式只换配色，不改布局与信息层级；
所有数字、判定色与对比度都按 WCAG 重新核算过，长时间读屏不刺眼。

**Q8：默认该用 `deepseek-flash` 还是 `deepseek-chat`？**
用 `deepseek-flash`。它是当前端点 `/models` 实际返回的官方现行名（DeepSeek-V4.1-Flash，1M 上下文、
默认开启思考模式、单价更低）；`deepseek-v4-pro` 是深度推理档，质量更高但更贵；
`deepseek-chat` 是**旧版兼容别名**，已不在端点返回的模型列表中，虽然仍能调用（非思考模式），
但不建议作为新配置的默认值。三个名字都保留在下拉里，迁移旧配置时不会失效。

**Q9：为什么「最大输出」要留很大？思考模式下温度好像没用？**
因为 `deepseek-flash` / `deepseek-v4-pro` **默认开启思考模式**：模型会先输出一段思维链、
再输出正文，`max_tokens` 是「思维链 + 正文」的总预算，给太小会导致正文被截断
（表现为结构化解析失败、或探针误报「返回内容为空」）。同时官方文档明确：**思考模式下
`temperature` 不生效**，只有 `top_p`（0.95–1.0）有效。界面在选中这两个模型时会在温度字段下方
如实提示这一点。

**Q10：模型下拉里的选项是在哪里配置的？**
统一来自后端目录 `app/llm/catalog.py`，前端不硬编码。打开配置页时会调用
`GET /api/v1/llm/models?provider=...&base_url=...`：优先读端点实时返回的 `/models`（`source=remote`），
失败则回退内置目录（`source=builtin`），并用内置目录的中文说明补全 label。
所以新增厂商 / 模型只需在 `catalog.py` 里加一条，前后端同时生效。

下拉列表以**表单里当前的厂商 + 端点地址**为准：端点一改（停顿约 0.6 秒）会自动重拉，
保存配置后也会重拉，也可以随时点「拉取」手动刷新。切换厂商时会回到该厂商已保存的端点与模型；
若切过去的厂商与当前已保存的配置不是同一个，平台**不会**把 A 家的端点或 Key 借给 B 家，
而是先给出该厂商的内置候选并提示「先保存配置再拉取」——避免出现「填了千问的地址、
下拉里却是别的厂商模型」这种串台。

**Q11：接阿里云百炼（通义千问）怎么填？**
服务商选「OpenAI 兼容端点」，端点地址填百炼的 OpenAI 兼容地址
（形如 `https://<业务空间>.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`，保留到 `/v1`），
Key 填百炼的 `sk-...`，然后「保存配置」→ 点「拉取」。百炼的 `/models` 会返回几百个模型，
下拉支持输入关键字过滤，也可以直接手输模型名（如 `qwen-plus`、`glm-5`）。

**Q12：解析过的需求还能回看吗？原文能下载吗？**
都能。文档库列表里「结构化需求」一列会显示已解析的条目数（未解析则显示「未解析」），
点它直接打开上次的解析结果，不必重新解析——重新解析会覆盖原结果、也可能重复消耗大模型额度，
所以只在真的需要重跑时才点「重新解析」。原文在上传时就按 `doc_id` 留了一份
（`storage/uploads/`），列表和预览抽屉里的下载按钮可以按**原文件名**取回，方便评审、归档与跨版本比对。
删除文档会同时清掉原文与解析结果，三者不会各留一份对不上。

**Q13：用例集能追溯到「哪份需求、哪个模型」吗？**
能，而且是在**列表级**能看清，不用点进详情：用例集列表的「来源需求」列直接显示生成它的需求编号
（点击跳到该需求的结构化需求页），「生成引擎」列显示实际用到的模型名（如 `deepseek-flash`；
纯规则引擎显示「规则引擎」，降级显示「规则引擎（降级）」并在悬停里说明原因）。
同一份需求换个模型重跑，结果本来就会不一样，列表里对不上就没法复盘。
反向也通：结构化需求页的「已生成的用例集」会列出这条需求生成过的每一份用例集
（接口 `GET /testcases/suites?doc_id=...`），不必再回列表里翻。文档库同口径，
解析过的文档会在「结构化需求」条数下方标出解析引擎。

---

## 八、许可与致谢

本项目基于 [MIT 许可](LICENSE) 开源。

整合自两个既有项目：**AI-TestCase-Platform-Pro**（用例生成，后端基座）与
**ai_test_report_assistant**（测试报告）；两者的能力、抽象接口与 LLM SDK 调用方式在整合中保持不变。

历史变更见 [CHANGELOG.md](CHANGELOG.md)；本地体验走查与修复记录见 [OPTIMIZATION.md](OPTIMIZATION.md)。
