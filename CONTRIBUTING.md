# 贡献指南

感谢你考虑为本项目做贡献。本文说明**开发环境、分支模型、提交规范与发版流程**，
请先读一遍再动手，能让你的 PR 顺利合入。

---

## 一、开发环境

```bash
git clone https://github.com/Seventy7photograph/Testing-Assistant-Platform-With-AI.git
cd Testing-Assistant-Platform-With-AI

python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
# macOS / Linux
# source .venv/bin/activate

python -m pip install -U pip
pip install -r requirements-dev.txt

Copy-Item .env.example .env   # macOS / Linux: cp .env.example .env
```

> Windows 上若 `pip install -r requirements-dev.txt` 报 `UnicodeDecodeError: 'gbk' codec...`，
> 是旧版 pip 按本地编码读取 UTF-8 需求文件所致，`python -m pip install -U pip` 升级后即可。

前端（仅改动 `frontend/**` 时需要）：

```bash
cd frontend
npm install
npm run build     # vue-tsc 类型检查 + vite 构建，产物写入 app/static/
```

### 提交前自检

```bash
python -m pytest                              # 单元 / 接口测试
python examples/demo_offline.py               # 用例生成链路离线冒烟（无需 API Key）
python examples/demo_report_offline.py        # 测试报告链路离线冒烟（无需 API Key）
cd frontend && npm run build                  # 改了前端才需要
```

---

## 二、分支模型

采用「主干稳定 + 迭代分支」的轻量 Git Flow，保证每个版本可独立演进、可回溯、互不阻塞。

| 分支 | 用途 | 生命周期 |
| --- | --- | --- |
| `main` | **仅存放已发布版本**，任何提交都对应一个可用版本，随时可打包 | 永久 |
| `develop` | **下一版本集成分支**，日常功能合并到这里 | 永久 |
| `release/x.y` | 发版冻结分支，只修 Bug、改版本号与 CHANGELOG | 发版后保留 |
| `feature/<scope>` | 单个特性开发，从 `develop` 切出 | 合并即删 |
| `hotfix/x.y.z` | 线上紧急修复，从 `main` 切出，修完同时回合 `main` 与 `develop` | 合并即删 |
| `docs/<scope>` | 纯文档改动 | 合并即删 |

### 分支流转（示例）

```
main ──●───────────────●────────────────●──▶
       v1.0.0          v1.1.0           v2.0.0
         │                 ▲                ▲
         │  release/1.1    │  release/2.0   │
         └── develop ──────┴────────────────┘
               ↑ feature/*  ↑ feature/*
```

### 从开发到发版（示例：1.1.0 → 2.0.0）

```bash
git checkout main && git pull
git checkout -b develop          # 下一版本集成分支
git checkout -b feature/decision-table
# ... 开发、自测、提交 ...
git checkout develop && git merge --no-ff feature/decision-table

# 功能冻结后发版
git checkout -b release/2.0 develop
# 改 app/__init__.py 的 __version__、更新 CHANGELOG.md
git checkout main && git merge --no-ff release/2.0
git tag -a v2.0.0 -m "Release v2.0.0"
git push origin main --tags
git checkout develop && git merge --no-ff release/2.0   # 回合修复
```

> **并行开发**：若两条线需要同时推进，从 `develop` 再切一条集成分支（如 `develop-2.x`），
> 各自合并回 `main` 时保持 tag 唯一即可，无需引入更重的分支结构。

---

## 三、提交信息规范

采用 [Conventional Commits](https://www.conventionalcommits.org/)：

```
<type>(<scope>): <简短描述>

[可选正文：为什么改、改动要点]
[可选脚注：BREAKING CHANGE / Closes #123]
```

常用 `type`：

| type | 含义 |
| --- | --- |
| `feat` | 新功能 |
| `fix` | 缺陷修复 |
| `docs` | 文档 |
| `refactor` | 重构（不改变外部行为） |
| `perf` | 性能优化 |
| `test` | 测试 |
| `build` / `chore` | 构建、依赖、脚本、杂项 |
| `ci` | CI/CD 配置 |

示例：`feat(design): 新增判定表策略并接入注册表`

---

## 四、代码约定

- **Python**：类型标注 + `from __future__ import annotations`；新增能力走「抽象 + 注册表」，
  不改主干（见 README「五、架构与扩展点」）。
- **前端**：Vue 3 `<script setup>` + TypeScript；颜色只改 `frontend/src/styles/tokens.css` 令牌。
- **设计约束**：改动前端前先读 `DESIGN.md` 与 `PRODUCT.md`，遵守其中的「拒绝清单」与提示规范。
- **密钥**：任何密钥都不得硬编码或提交，一律走环境变量；`.env` 已被 `.gitignore` 排除。
- **数据**：`storage/`、`output/`、`docs/review/` 为本地数据与走查产物，禁止提交。

## 五、Pull Request 要求

1. 目标分支：日常改动 → `develop`；紧急修复 → `main`（并回合 `develop`）。
2. 描述清楚**动机、改动点、验证方式**；关联相关 Issue。
3. 通过 CI（`pytest` + 前端构建）；界面改动建议附截图。
4. 不夹带无关改动；一次 PR 只做一件事。

## 六、发布 Checklist

- [ ] `app/__init__.py` 中 `__version__` 已更新（版本号唯一来源）
- [ ] `CHANGELOG.md` 已补充对应版本条目
- [ ] `python -m pytest` 全绿，且离线冒烟脚本通过
- [ ] `frontend` 已 `npm run build`，且 `app/static/` 产物已一并提交（平台按「后端托管前端」交付，产物随仓库提供）
- [ ] 打 tag：`git tag -a vX.Y.Z -m "Release vX.Y.Z"` 并推送
- [ ] GitHub Release 已出现在仓库 Release 列表（`.github/workflows/release.yml` 会按 tag
      与 `CHANGELOG.md` 自动创建；发布后必须人工确认，不得只推 tag）
