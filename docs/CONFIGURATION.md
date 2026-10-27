<p align="center">
  <img src="assets/doc-banner.svg" alt="测试工程师助手平台配置文档" width="100%">
</p>

# 配置说明

配置文件优先级：

```text
界面运行时覆盖
    >
.env / 环境变量
    >
app/core/config.py 代码默认值
```

完整基线模板见 [`.env.example`](../.env.example)。

## 应用

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_NAME` | `测试工程师助手平台` | 应用名称 |
| `API_PREFIX` | `/api/v1` | REST 路由前缀 |
| `PUBLIC_BASE_URL` | `http://127.0.0.1:8000` | OpenAPI/Postman 默认服务地址 |
| `DEBUG` | `false` | 调试与默认热重载 |
| `LOG_LEVEL` | `INFO` | 日志等级 |

## 存储

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `STORAGE_DIR` | `./storage` | 运行时数据根目录 |
| `STORAGE_BACKEND` | `json` | `json` 或 `sqlite` |
| `MAX_UPLOAD_SIZE_MB` | `20` | 单文件上传上限 |

切换到 SQLite：

```powershell
python scripts/migrate_json_to_sqlite.py
$env:STORAGE_BACKEND = "sqlite"
python run.py
```

迁移后先保留 JSON 文件作为回滚备份。

## 项目与鉴权

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `PROJECT_ISOLATION_ENABLED` | `false` | 是否强制项目身份 |
| `AUTH_ENABLED` | `false` | 是否校验 API Key |
| `PROJECT_HEADER` | `X-Project-ID` | 项目请求头 |
| `AUTH_HEADER` | `X-API-Key` | 鉴权请求头 |
| `AUTH_TOKENS` | `{}` | Token 到项目、角色和操作者的 JSON 映射 |
| `PROJECT_QUOTA_DOCUMENTS` | `10000` | 项目文档配额 |
| `PROJECT_QUOTA_SUITES` | `5000` | 项目用例集配额 |
| `PROJECT_QUOTA_JOBS` | `50000` | 项目任务配额 |

`AUTH_TOKENS` 示例：

```json
{
  "replace-with-token": {
    "project_id": "PRJ-demo",
    "actor": "tester",
    "role": "member"
  }
}
```

真实 Token 只放在环境变量或部署平台密钥中。

## 大模型

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `LLM_PROVIDER` | `deepseek` | `deepseek`、`openai_compatible`、`fake`、`none` |
| `LLM_API_KEY` | 空 | Bearer Key |
| `LLM_BASE_URL` | `https://api.deepseek.com` | OpenAI 兼容端点 |
| `LLM_MODEL` | `deepseek-flash` | 默认模型 |
| `LLM_TIMEOUT` | `60` | 请求超时秒数 |
| `LLM_MAX_RETRIES` | `2` | JSON 修复/截断重试次数 |
| `LLM_TEMPERATURE` | `0.2` | 通用温度 |
| `LLM_MAX_TOKENS` | `8192` | 单次输出预算 |
| `LLM_ROUTING_STRATEGY` | `balanced` | `quality`、`balanced` 或 `cost` |

思考型模型会先消耗推理 token。输出预算过小时可能出现正文为空或 JSON 截断，不应盲目调低。

## 文档与图片识别

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `VISION_PROVIDER` | `auto` | `auto`、`vlm`、`local-ocr`、`cloud-ocr`、`none` |
| `VISION_MODE` | `text` | `text`、`describe`、`both` |
| `VISION_API_KEY` | 空 | 留空时复用 `LLM_API_KEY` |
| `VISION_BASE_URL` | 空 | 留空时复用 `LLM_BASE_URL` |
| `VISION_MODEL` | 空 | 多模态模型名 |
| `VISION_OCR_BACKEND` | 空 | 留空自动探测本地 OCR |
| `VISION_LANGUAGES` | `chi_sim+eng` | OCR 语言 |
| `VISION_CLOUD_URL` | 空 | 云端 OCR 地址 |
| `VISION_CLOUD_KEY` | 空 | 云端 OCR Key |
| `VISION_MAX_IMAGES` | `20` | 单文档最多识别图片数 |
| `VISION_MAX_SIDE` | `1600` | 提交视觉模型前的最长边 |
| `VISION_MIN_PIXELS` | `4096` | 小于该面积直接跳过 |

数据不出域时使用 `local-ocr` 或 `none`。

## 用例生成

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `LLM_DESIGN_MODE` | `scenario` | `scenario`、`review`、`enhance` |
| `LLM_MAX_CALLS_PER_GENERATION` | `20` | 单次生成最多模型调用 |
| `MAX_CASES_PER_REQUIREMENT` | `200` | 单条需求跨方法用例上限 |
| `KNOWLEDGE_CHUNK_SIZE` | `800` | 知识索引分块大小 |
| `KNOWLEDGE_CHUNK_OVERLAP` | `100` | 分块重叠字符数 |
| `KNOWLEDGE_SEARCH_LIMIT` | `8` | 知识检索基线数量 |

## 受控 HTTP 执行

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `EXECUTION_TIMEOUT_SECONDS` | `20` | 单请求超时 |
| `EXECUTION_MAX_CONCURRENCY` | `4` | 最大并发 |
| `EXECUTION_MAX_RESPONSE_BYTES` | `1000000` | 单响应体上限 |
| `EXECUTION_MAX_CASES` | `200` | 单次执行用例上限 |

## 外部连接

### Jira

```dotenv
JIRA_BASE_URL=
JIRA_EMAIL=
JIRA_TOKEN=
JIRA_PROJECT_KEY=
```

### 禅道

```dotenv
ZENTAO_BASE_URL=
ZENTAO_TOKEN=
ZENTAO_PROJECT_KEY=
```

缺少配置时接口返回明确错误，不用假数据替代真实连接。

## 知识助手与联网

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `ASSISTANT_MAX_KNOWLEDGE_RESULTS` | `5` | 每轮最多知识引用 |
| `ASSISTANT_CONTEXT_TURNS` | `12` | 上下文最近轮数 |
| `ASSISTANT_CONTEXT_CHARS` | `24000` | 上下文最大字符数 |
| `ASSISTANT_MAX_TURNS` | `30` | 单会话最多用户回合 |
| `ASSISTANT_MAX_OUTPUT_TOKENS` | `8192` | 助手输出预算 |
| `ASSISTANT_RATE_LIMIT_PER_MINUTE` | `8` | 项目级每分钟请求上限 |
| `ASSISTANT_WEB_SEARCH_ENABLED` | `true` | 是否允许网页工具 |
| `ASSISTANT_WEB_SEARCH_TIMEOUT` | `20` | Search/Fetch 超时 |
| `ASSISTANT_WEB_SEARCH_MAX_RESULTS` | `6` | 每次搜索最多结果 |
| `ASSISTANT_WEB_FETCH_LIMIT` | `2` | 每次最多抓取网页 |
| `ASSISTANT_WEB_FETCH_CHARS` | `12000` | 单网页正文上限 |
| `ASSISTANT_WEB_SEARCHES_PER_CONVERSATION` | `8` | 单会话联网次数 |
| `ASSISTANT_WEB_MIN_INTERVAL_SECONDS` | `2` | 联网最小间隔 |

DeepSeek 模式自动复用同一 Bearer Key：

```text
POST /v1/tools/search
POST /v1/tools/fetch
```

其他模型若提供兼容 JSON 契约，可配置：

```dotenv
ASSISTANT_WEB_SEARCH_BASE_URL=
ASSISTANT_WEB_SEARCH_API_KEY=
```

留空时不会猜测厂商私有接口，界面会显示联网不可用及原因。

## 报告阈值

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `VERDICT_FAIL_RATE` | `0.05` | 最大失败率 |
| `VERDICT_BLOCKED_RATE` | `0.05` | 最大阻塞率 |
| `VERDICT_EXECUTION_FLOOR` | `0.9` | 最低执行率 |
| `VERDICT_PASS_LINE` | `0.95` | 最低通过线 |

阈值可在界面运行时修改和恢复。

## 部署检查

- 对外暴露前开启鉴权并关闭不必要的 CORS 来源。
- 使用 HTTPS 和反向代理保护 API。
- 将 `storage/` 放在受控磁盘并配置备份。
- 不把 `.env`、真实 Token、上传文档或运行数据提交到 Git。
- 修改 `frontend/**` 后执行 `npm run build` 并提交 `app/static/` 产物。
