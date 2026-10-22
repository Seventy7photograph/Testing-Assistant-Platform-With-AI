# 测试工程师助手平台

[![CI](https://github.com/Seventy7photograph/Testing-Assistant-Platform-With-AI/actions/workflows/ci.yml/badge.svg)](https://github.com/Seventy7photograph/Testing-Assistant-Platform-With-AI/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688.svg)](https://fastapi.tiangolo.com/)
[![Vue](https://img.shields.io/badge/Vue-3-42b883.svg)](https://vuejs.org/)
[![Version](https://img.shields.io/badge/version-v2.2.0-blue.svg)](CHANGELOG.md)

> 面向测试工程师的**一体化本地 / 内网工作台**：把「需求文档 → 测试用例」与「测试执行数据 → 测试报告」
> 两条日常高频链路，收进同一个控制台、同一套配置、同一份存储。
>
> 后端 **Python + FastAPI**，前端 **Vue 3 + TypeScript + Vite + Element Plus**，
> 默认主题**冰川蓝 + 白**，可一键切换**深色护眼模式**；可折叠侧边栏 + 顶部导航，
> 全站带操作提示与动效。
> **未配置大模型 API Key 时自动降级为纯规则引擎，链路依然端到端可用。**
>
> V2.2：OpenAPI 3 JSON / YAML → operation / 契约断言 → Postman Collection 2.1，接口资产与需求用例共用追溯体系。
> V2.1：Prompt 具备版本、输入边界、证据校验与固定对抗回归；模型事实与推断在界面分开展示。
> V2.0：六种测试设计方法齐备（含判定表 / 因果图 / 正交实验），
> 需求文档里的**图片**（内嵌图 / 扫描件整页 / 截图）可经独立识别通道转成文字，
> 用例可导出 Excel / JSON / CSV / XMind / TestLink XML，并提供覆盖率、需求变更差异与持久化后端切换。

**导航**：[能力范围](#一能力范围) · [目录结构](#二目录结构) · [快速开始](#三快速开始) ·
[接口清单](#四接口清单) · [架构与扩展点](#五架构与扩展点) · [设计系统](#六设计系统与提示系统) ·
[常见问题](#七常见问题faq) · [许可与致谢](#八许可与致谢) ·
[更新日志](CHANGELOG.md) · [贡献指南](CONTRIBUTING.md) · [安全策略](SECURITY.md)

---

## 一、能力范围

平台由两条 AI 工作流和一条接口资产链路组成。它们共用存储与能力基座，可以分别使用，也可以串在同一次工作流里。

### 1.1 用例生成链路（需求 → 用例）

| 能力 | 说明 |
| --- | --- |
| 文档上传与解析 | `.docx` / `.pdf` / `.xlsx` / `.txt` / `.md` / `.csv` / `.json` / 图片（`.png` `.jpg` `.webp` `.bmp` `.tif`），兼容 GBK 等中文编码；粘贴文本同样作为 `.txt` 文档入库并可追溯 |
| 图片识别（多模态 OCR） | 文档内嵌图 / 扫描件整页 / 直接上传的截图 → 文字。**主模型不必支持图片**：识别走独立通道（多模态模型 → 本地 OCR → 云端 OCR 依次降级），识别结果回填到正文的图片位置，模型推断部分单独成段、不参与字段约束抽取 |
| 需求结构化 | LLM 结构化抽取 + 规则引擎解析双路，LLM 缺失 / 失败自动降级并显式告警 |
| Prompt 可信工程 | 五个任务独立 Prompt ID / 版本 / 输入边界；证据归一化校验、失败关闭、单次修复、注入告警与固定对抗样本 |
| 测试设计 | 六种方法：等价类划分、边界值分析（min-1/min/min+1/max-1/max/max+1）、场景法、**判定表**（条件桩 → 动作桩 → 无关项合并）、**因果图**（因/果/异或·包含·屏蔽约束 → 判定表）、**正交实验**（因子水平 → 两两覆盖表） |
| 生成阶段大模型参与 | 三档可调：**仅场景法补充**（默认）/ **复核规则产出**（六种方法都覆盖，只给意见、不改写用例）/ **复核 + 补充用例**（补充项标「[LLM补充] · 需复核」）。按需求条数计费，受调用次数上限约束 |
| 用例优化 | 两层去重（精确指纹 + 跨方法语义重叠，合并关联需求并记录覆盖方法）、优先级排序、按方法自动编号（TC-EQ / BV / DT / CE / OR / SC） |
| 用例导出 | Excel（4 个 Sheet）+ JSON + **CSV** + **XMind** + **TestLink XML**，后三种可被目标工具直接导入 |
| 需求追溯 | 需求条目 ↔ 用例双向追溯矩阵（正查 + 反查 + 孤儿用例）；**字段 / 边界 / 规则三维覆盖率与缺口清单**；**需求变更差异对比**（新增 / 删除 / 修改 + 字段级 diff） |
| 用例版本 | 同一需求的多次生成自动编号为「第 N 版」，可按需求查看历史版本 |

### 1.2 接口资产链路（OpenAPI → 契约用例）

| 能力 | 说明 |
| --- | --- |
| 接口资产（V2.2） | 导入 OpenAPI 3 JSON / YAML，展开本地 `$ref` 并检测循环；按 operation 生成正向、必填缺失、类型 / 枚举 / 长度 / 数值边界、Content-Type、鉴权与响应 schema 断言；缺口显式标为待补充 |
| AI 只读复核（可选） | 手动触发模型检查 operation 与确定性用例摘要，只提出缺口、风险与补充场景建议；不允许改写路径、参数、schema 或既有断言 |
| Postman 交付 | Collection 2.1 保留 `{{baseUrl}}` / `{{authToken}}` 等环境占位符、请求体样例和 schema tests；不写入明文 Token / API Key |
| 追溯与审查 | operation、来源 schema 路径、需求 ID 与待补充断言在同一个用例抽屉中查看；响应示例不作为固定返回值断言 |

### 1.3 测试报告链路（执行数据 → 报告）

| 能力 | 说明 |
| --- | --- |
| 多来源执行数据摄入 | 手工粘贴 / 上传 JSON / 内置示例数据集；字段容错、缺失值显式标注 |
| 确定性指标 | 通过率、失败率、阻塞率、用例总数、缺陷分布、模块维度拆解——先算指标，再谈结论 |
| AI 归纳报告 | 结论先行 → 风险与阻塞 → 缺陷分析 → 改进建议；支持 **SSE 流式输出**，边生成边阅读 |
| 发版判定 | 可配置阈值（失败率 / 阻塞率 / 执行率 / 通过线），自动给出「可发布 / 有条件发布 / 不建议发布」判定 |
| 存档与趋势 | SQLite 存档，历史报告检索、趋势对比、多份报告横向比对 |
| 报告导出 | Markdown / HTML / DOCX / JSON 四种格式 |

### 1.4 平台能力

| 能力 | 说明 |
| --- | --- |
| 统一总览 | 首页仪表盘汇总 AI 工作流状态、最近文档 / 用例集 / 报告与关键指标；接口资产从独立入口进入 |
| 统一配置 | 两条 AI 链路**共用同一份大模型配置**（`.env` 基线 + 界面运行时覆盖），保存即生效、可一键恢复；图片识别通道独立配置，且可复用大模型的 Key 与端点 |
| 持久化可选 | `STORAGE_BACKEND=json`（默认，一对象一文件、零依赖）或 `sqlite`（SQLAlchemy 单文件库）；两者接口一致，业务层零改动切换，并提供一次性迁移与回滚脚本 |
| 双主题与密度 | 默认「冰川蓝 + 白」，顶部一键切换**深色护眼模式**；标准 / 紧凑 / 宽松三档显示密度 |
| 批量操作 | 文档库、用例集、报告存档均支持多选与**批量删除**（服务端一次最多 200 条，自动去重） |
| 产出可追溯 | 用例集列表直出「来源需求 + 生成引擎（模型名）」，点来源需求直达结构化需求；需求页反向列出已生成的用例集；文档库标出解析引擎 |
| 全站提示系统 | 五种提示形态统一落地（见 [六、设计系统](#六设计系统与提示系统)） |
| 长期工作流 | 面包屑与返回上一级、返回顶部、生成状态缓存、吸底送检栏；菜单切换不中断生成与报告流式请求 |
| 过程提示不刷屏 | 生成过程提示按「需要复核 / 过程信息」分组，默认只露要动手的条目，其余折叠为一行计数摘要；长文本强制换行限高 |
| 统一异常出口 | 所有错误返回 `{success, code, message, detail}`，前端统一渲染为可读错误卡片 |

### 1.4 架构预留（只定义接口，不实现逻辑）

未实现的能力**一律显式标注**，调用返回 **501 + 说明**，不做静默降级：

- LLM Provider：Qwen / GLM / 本地 Ollama（注册表与目录已就绪，新增厂商只需实现一个类）
- 外部集成：禅道 / Jira（`ExternalSyncAdapter` 抽象已定义，含占位实现）

> V1.0 预留的三类能力已在 V2.0 全部落地：判定表 / 因果图 / 正交实验（`app/design/`）、
> XMind / CSV / TestLink XML（`app/exporters/`）、SQLAlchemy 持久化与用例版本（`app/sql_store.py`）。

---

## 二、目录结构

```
Testing-Assistant-Platform With AI/
├── .github/                          # CI / Issue 与 PR 模板 / Dependabot
├── app/                              # 后端（FastAPI）
│   ├── main.py                       # 装配入口：中间件 / 异常处理 / 路由 / 静态页
│   ├── repository.py                 # 持久化门面 + JSON 文件存储实现（+ 后端选择）
│   ├── sql_store.py                  # SQLAlchemy(SQLite) 存储实现（与 JSON 同接口）
│   ├── api/
│   │   ├── deps.py                   # 依赖注入
│   │   ├── responses.py              # 下载响应（中文文件名 RFC 5987，导出与原文下载共用）
│   │   └── routes/                   # 路由层（一个业务面一个文件）
│   │       ├── health.py             #   /health /integrations
│   │       ├── overview.py           #   /overview
│   │       ├── documents.py          #   文档上传 / 列表 / 详情 / 原文下载 / 图片查看与重识别 / 删除
│   │       ├── requirements.py       #   需求解析 / 查询 / 变更差异 / 追溯矩阵 / 基于需求生成用例
│   │       ├── testcases.py          #   设计方法清单 / 用例集列表 / 生成 / 详情 / 覆盖率 / 删除
│   │       ├── api_specs.py          #   OpenAPI 导入 / operation / 接口用例 / Postman 导出
│   │       ├── pipeline.py           #   一键流水线
│   │       ├── export.py             #   导出格式 / 导出文件流
│   │       ├── llm.py                #   大模型配置读写 / 连通性测试 / 模型候选
│   │       ├── vision.py             #   图片识别通道配置 / 真跑一次的识别探针
│   │       └── report.py             #   测试报告：状态/指标/样例/生成/流式/存档/趋势/阈值/导出
│   ├── core/                         # 配置 / 异常 / 日志 / 注册表 / 工具
│   ├── schemas/                      # 领域枚举与请求响应契约（pydantic）
│   ├── services/                     # 应用服务：文档 / 需求 / 证据闸门 / 流水线 / 导出 / 规则解析 / 图片识别 / 差异与追溯
│   ├── parsers/                      # 文档解析器（docx / pdf / excel / image / text + 注册表，含内嵌图提取）
│   ├── vision/                       # 图片识别通道（多模态模型 / 本地 OCR / 云端 OCR / 假实现 + 注册表）
│   ├── design/                       # 测试设计引擎（六种方法 / 接口契约用例 / 优化器 / 覆盖率分析）
│   ├── exporters/                    # 用例导出器（excel / json / csv / xmind / testlink / postman + 注册表）
│   ├── llm/                          # LLM Provider + Prompt 注册表（版本 / 边界 / 温度 / 变更记录）
│   ├── report/                       # 测试报告模块（config/metrics/prompts/llm/store/exporters/samples/schemas）
│   ├── integrations/                 # 外部集成抽象（禅道 / Jira 占位，未实现）
│   └── static/                       # 前端构建产物（由 frontend 构建生成，勿手改）
├── frontend/                         # 前端源码（Vue 3 + TS + Vite + Element Plus）
│   ├── src/
│   │   ├── api/                      # 类型化 API 客户端（client / index / types）
│   │   ├── components/               # 通用组件（AppShell / SideRail / TopBar / Tip / NoticeHost ...）
│   │   ├── composables/              # useAsync / useFeedback（含 confirmAction）
│   │   ├── router/                   # 路由表（13 条路由）
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

前端契约（后端能力清单 ↔ 界面展示）另有一个"真点一遍"的冒烟工具，在 `frontend/` 下运行：

```bash
node tools/smoke-ui.mjs   # 自动起后端 + Playwright：校验方法清单一致、导出按钮返回 200
```

它覆盖的是 pytest 看不到的一层：后端改了能力清单、界面还在按旧假设渲染（曾经因此把已实现的
判定表显示成「未实现」），或者按钮传的格式名与后端注册表对不上（曾经因此导出 404）。

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
| GET | `/llm/prompts` | Prompt 工程注册表：ID、版本、输入边界、温度与变更记录 |
| POST | `/llm/config/test` | 大模型连通性测试 |
| GET | `/llm/models` | 候选模型列表 |
| GET / PUT / DELETE | `/vision/config` | 读取 / 保存 / 恢复图片识别配置（清图片配置不影响大模型配置） |
| POST | `/vision/config/test` | 图片识别探针（用一张带文字的图片真跑一次） |

### 用例生成链路

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/documents/upload` | 上传文档并解析为文本（multipart，字段名 `file`） |
| GET | `/documents` | 最近上传的文档 |
| GET | `/documents/{doc_id}` | 文档详情 |
| GET | `/documents/{doc_id}/download` | 下载文档原文（原文件名，附件形式） |
| GET | `/documents/{doc_id}/images/{filename}` | 查看文档中的某张图片（缩略图 / 人工核对识别结果） |
| POST | `/documents/{doc_id}/images/recognize` | 重新识别文档中的图片（换通道后补识别；通道仍不可用返回 501） |
| GET | `/documents/vision/capabilities` | 当前图片识别通道与降级原因 |
| DELETE | `/documents/{doc_id}` | 删除文档及其解析结果与原文 |
| POST | `/documents/batch-delete` | 批量删除文档（body `{ids: [...]}`，≤ 200，自动去重） |
| POST | `/requirements/parse` | 解析需求为结构化模型 |
| POST | `/requirements/{doc_id}/testcases` | 基于已解析需求生成用例（`methods` / `use_llm_in_design` 为查询参数） |
| GET | `/requirements/{doc_id}` | 获取已解析的需求模型 |
| GET | `/requirements/{doc_id}/diff?against={old}` | 需求变更差异对比（`doc_id` 为新版，`against` 为旧版） |
| GET | `/requirements/{doc_id}/traceability` | 需求-用例双向追溯矩阵 |
| DELETE | `/requirements/{doc_id}` | 删除已解析的需求模型 |
| POST | `/pipeline/generate` | 一键：需求文档 → 结构化需求 → 测试用例 |
| GET | `/testcases/methods` | 可用设计方法清单 |
| POST | `/testcases/generate` | 生成测试用例 |
| GET | `/testcases/suites` | 最近生成的用例集（`limit` ≤ 50；`doc_id` 只列该需求生成的，供需求页反向追溯） |
| GET | `/testcases/{suite_id}` | 用例集详情 |
| GET | `/testcases/{suite_id}/coverage` | 覆盖率分析（字段 / 边界 / 规则三维 + 缺口清单） |
| DELETE | `/testcases/{suite_id}` | 删除用例集 |
| POST | `/testcases/batch-delete` | 批量删除用例集（body `{ids: [...]}`，≤ 200，自动去重） |
| GET | `/export/formats` | 可用导出格式 |
| POST | `/export` | 导出用例集（返回文件流） |
| GET | `/export/{suite_id}/{fmt}` | 按路径导出（便于浏览器直接下载） |

### 接口资产（V2.2）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api-specs/import` | 上传 OpenAPI 3 JSON / YAML（multipart，字段名 `file`），展开本地 `$ref` 并生成契约用例 |
| GET | `/api-specs` | 接口规范列表（来源文件、版本、operation / 用例 / 缺口统计） |
| GET | `/api-specs/{spec_id}` | 规范详情与全部 operation |
| GET | `/api-specs/{spec_id}/operations` | operation 列表 |
| GET | `/api-specs/{spec_id}/operations/{operation_id}` | 单个 operation 详情 |
| GET | `/api-specs/{spec_id}/cases` | 接口用例列表；`operation_id` 可过滤 |
| POST | `/api-specs/{spec_id}/review` | 可选的大模型只读复核；只保存建议，不改写确定性用例 |
| GET | `/api-specs/{spec_id}/export/postman` | 导出 Postman Collection 2.1 |
| DELETE | `/api-specs/{spec_id}` | 删除规范与全部派生接口用例 |

接口导入的边界：

- 只支持 OpenAPI 3.x 单文件 JSON / YAML；Swagger 2.0 与外部 `$ref` 会返回明确错误。
- 循环 `$ref` 保留占位节点并告警，不递归展开到无限深度。
- 响应示例只用于展示，不作为固定返回值断言。
- `requestBody` / 参数 / response schema 中缺失的约束不会补造；无法静态确定的断言标为 `manual`。
- Postman 导出只写环境变量占位符，目标账号、Cookie、Token 与 API Key 不进入平台存储。

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

### 5.2 六类扩展点

| 扩展点 | 抽象 | 注册表 | 新增一个的实现方式 |
| --- | --- | --- | --- |
| 文档解析 | `DocumentParser` | `app/parsers/registry.py` | 新增子类并注册，前后端支持列表自动出现 |
| 测试设计 | `DesignStrategy` | `app/design/registry.py` | 六种方法已全部实现；新增方法只需实现子类并注册 |
| 用例导出 | `Exporter` | `app/exporters/registry.py` | 同上；`/export/formats` 与前端下拉框自动出现 |
| LLM 提供方 | `LLMProvider` | `app/llm/factory.py` | 实现接口 + 在 `catalog.py` 登记能力 |
| 图片识别 | `ImageTextExtractor` | `app/vision/registry.py` | 新增视觉模型 / OCR 服务只需实现子类并注册，解析器与主干不动 |
| 外部集成 | `ExternalSyncAdapter` | `app/integrations/base.py` | 抽象已定义，占位调用返回 501 |

### 5.3 配置优先级（两条 AI 链路共用）

```
界面运行时覆盖 (storage/data/llm_config.json)
        >
.env 基线 (LLM_PROVIDER / LLM_API_KEY / LLM_BASE_URL / LLM_MODEL ...)
        >
代码默认值 (app/core/config.py)
```

- 报告链路额外维护「发版判定阈值」，存于 `storage/data/report_config.json`，同样支持界面改、界面恢复。
- OpenAPI / Postman 的默认服务地址由 `PUBLIC_BASE_URL` 控制，默认 `http://127.0.0.1:8000`。
- 版本号以代码 `app/__init__.py` 为唯一来源，`.env` 中的 `APP_VERSION` 不会覆盖它。

### 5.4 Prompt 可信工程（V2.2）

五个模型任务分别使用独立 Prompt，不允许抽取、复核、补缺、报告归纳、接口复核混用同一套指令：

| Prompt ID | 任务 | 输入边界 | 温度 |
| --- | --- | --- | --- |
| `requirement.extract` | 需求抽取 | 当前需求原文（截断 12000 字）与标题，原文只作为测试素材 | 0.1 |
| `design.scenario_enrichment` | 场景补缺 | 单条结构化需求与已有用例标题 | 0.2 |
| `design.generation_review` | 生成复核 | 单条需求与规则用例摘要（最多 4000 字） | 0.1 |
| `report.summarize` | 报告归纳 | 确定性指标与原始执行数据，原始数据视为不可信文本 | `REPORT_TEMPERATURE`（默认 0.3） |
| `api.case_review` | 接口用例复核 | 规范化 operation、确定性接口用例摘要与允许引用的 source_ref，不含密钥与完整请求体 | 0.1 |

证据闸门会先做 NFKC、空白、标点和 OCR 换行归一化，再判断 `evidence_quotes` 是否真实出现在原文；
字段名还必须能在证据或结构化需求中定位。校验结果按 `verified / inferred / rejected` 记录：

- `verified` 才允许进入确定性规则引擎；
- `inferred` 只作为待复核模型判断展示，不伪装成原文事实；
- `rejected` 不进入需求模型、用例或权威指标。

抽取与复核在语义校验失败时携带错误清单重试一次；仍失败则保留规则结果并写入 `validation_failures`。
预算不足时复核优先覆盖 P0/P1，未复核条目写入 `unreviewed_requirements`。

离线门禁：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_prompt_quality.py -q
.\.venv\Scripts\python.exe scripts\evaluate_prompts.py
```

---

## 六、设计系统与提示系统

完整定义见 [DESIGN.md](DESIGN.md)（设计世界「冰川刻度」）与 [PRODUCT.md](PRODUCT.md)（产品定位与提示规范）。

**主题**：默认**冰川蓝 + 白**，顶部导航可一键切换**深色护眼模式**（极夜冰层）。
两套主题共用同一组令牌，集中在 `frontend/src/styles/tokens.css`——冰层、墨色、语义色、
密度变量、字体尺度都在那里，改主题只改这一处；切换时给 `<html>` 挂 260ms 全局过渡，
做一次「冰面重结晶」而不是硬跳。主题选择写入 `localStorage`，下次打开保持。

**布局**：左侧可展开菜单栏（窄屏自动收起为浮层 + 遮罩，点击任意处关闭）+ 顶部导航
（面包屑、命令面板入口、显示密度、主题开关、帮助抽屉、健康状态）。13 条路由：总览 / 用例生成 /
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
剩下的**架构预留**是外部集成（禅道 / Jira）与部分模型厂商（Qwen / GLM / Ollama 需先按目录登记）。
平台**不会静默失败**：接口返回 501 并说明原因，不会让你以为点了就会出结果。
（V2.0 起判定表 / 因果图 / 正交实验 / XMind / CSV / TestLink XML / SQLAlchemy 持久化均已实现。）

**Q3.1：文档里的图片（原型图、截图、扫描件）会被解析吗？需要换多模态模型吗？**
会解析，而且**不必换模型**。「图片 → 文字」是一条独立通道：多模态模型 → 本地 OCR
（RapidOCR / pytesseract / tesseract 命令行，离线免费）→ 云端 OCR 依次降级。
因此在「设置 → 图片识别」里选 `auto` 时，`deepseek-flash` 这类纯文本模型照样能吃到图片信息。
识别出的文字会回填到正文的图片位置；模型对图片的**推断**单独成段，且不参与字段约束抽取
（避免把推测当成需求）。若通道都不可用，文档照常入库，只是每张图会标注「为什么没识别、该怎么办」。

**Q3.2：数据存在 JSON 文件还是数据库里？能切换吗？**
默认是 JSON 文件（`storage/data/*.json`，零依赖、开箱即跑）。要换成 SQLite：
先 `python scripts/migrate_json_to_sqlite.py` 迁移，再把 `STORAGE_BACKEND` 设为 `sqlite`。
两种后端接口完全一致，业务层不用改；迁移后**先别删**原 JSON 文件 —— 它们就是回滚备份
（`--rollback` 可反向导出）。

**Q3.3：提示说「超过单条需求上限已截断」，可为什么最终条数又不满那个上限？上限该设多大？**

因为这是两道关卡、三个数字：

1. **单方法上限**：每个设计方法自己最多产出 N 条（防止边界值在一个 40 字段表单上爆炸）；
2. **单条需求上限**：一条需求跨全部方法的合计上限 N 条（护栏）；
3. **去重**：跨方法语义重叠的用例会被合并 —— 等价类与边界值经常对「同一个测试点」各产一条、
   数据完全相同，合并后条数必然少于截断时保留的条数。

所以「截断到 60、界面显示 48」是对的：**截断发生在去重之前**。现在告警把三个数一起写清
（生成 N 条 → 按方法轮转保留 M 条 → 去重合并后本需求 K 条）。

超限时按**方法轮转**保留，而不是「取前 N 条」—— 后者会让排在前面的大方法吃光额度，
把判定表 / 因果图 / 正交实验整体挤掉（实测上限 60 时正交实验只剩 13 条，而它的自然产出是 47 条）。

**该设多大**：六种方法全开时，结构完整的需求自然产出 65~75 条是常态；默认值已从 60 调到 200，
到那个量级才可能触发，触发时结果里会写明被裁掉多少。上限可在「用例生成」页按次调整（10–2000），
基线在 `.env` 的 `MAX_CASES_PER_REQUIREMENT`。

**Q3.4：生成用例时，大模型到底参与了哪些环节？能让它参与更多吗？**

分两个阶段看，这是两条独立的开关：

1. **解析阶段（`解析用大模型`）**：模型把文档抽成结构化需求——字段约束、业务规则、流程、验收标准。
   这一步是**六种设计方法共同的输入**，抽取质量直接决定后面所有方法的产出。
2. **生成阶段（`生成用大模型` + 参与方式）**：规则引擎按设计方法确定性地产出用例，模型在此基础上按三档介入：
   - **仅场景法补充**（默认）：只有场景法会额外调一次模型补"易漏场景"，与 V1.0 行为一致；
   - **复核规则产出**：**六种方法都覆盖**。按需求条目调一次模型，让它检查"数据与字段约束是否矛盾、
     预期与业务规则是否冲突、同一需求内部是否自相矛盾、是否明显重复"，并指出规则方法覆盖不到的测试点；
   - **复核 + 补充用例**：在复核之外允许模型补充用例，补充项标为「[LLM补充] · 需复核」。

两个关键设计取舍：

- **模型不重写规则用例**。规则产出是确定、可复现、可离线核对的；一旦让模型直接改写，
  你就无法判断哪条是规则结论、哪条是模型判断，整份用例集的可信度都会打折。
  所以复核只产出"意见"（`generation_meta.review_findings`，在生成页与用例集详情页可见），改不改由你决定。
- **按需求条数计费，不是按方法数**。六个方法各调一次的话，一份 5 条需求的文档要发 30 次请求。
  现在是一条需求一次调用（同时产出意见与补充），并受 `LLM_MAX_CALLS_PER_GENERATION`（默认 20）约束；
  超出预算的需求沿用规则结果并给出告警。界面会显示"本次调用模型 N 次"。

离线与降级：没配 Key 时两档开关都不会生效（自动走规则引擎），选择不会让流程中断。

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
