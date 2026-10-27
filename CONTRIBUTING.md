<p align="center">
  <img src="docs/assets/doc-banner.svg" alt="测试工程师助手平台贡献指南" width="100%">
</p>

# 贡献指南

## 开发环境

```powershell
git clone https://github.com/Seventy7photograph/Testing-Assistant-Platform-With-AI.git
cd Testing-Assistant-Platform-With-AI

python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

前端：

```powershell
cd frontend
npm install
```

## 代码约定

### Python

- 使用类型标注和 `from __future__ import annotations`。
- 新解析器、设计方法、导出器、模型 Provider 和外部集成通过注册表接入。
- 路由只做参数校验、身份上下文和响应包装。
- 业务规则放在服务或领域模块，不写进路由。

### 前端

- 使用 Vue 3 `<script setup>` 与 TypeScript。
- API 类型集中维护在 `frontend/src/api/types.ts`。
- 颜色只使用 `frontend/src/styles/tokens.css` 中的语义令牌。
- 修改界面前阅读 [设计系统](DESIGN.md)。
- 禁止卡片嵌套卡片、渐变装饰、玻璃拟态、Emoji 图标和真实业务截图。

### 数据与安全

- 不提交 `.env`、Token、上传原文、运行数据或导出文件。
- 模型输出按不可信数据校验。
- 新外部调用必须有超时、限制、错误映射和降级行为。
- 新写操作必须考虑项目边界、配额和审计。

## 提交前自检

```powershell
python -m pytest -q
python examples/demo_offline.py
python examples/demo_report_offline.py
```

修改前端后：

```powershell
cd frontend
npm run typecheck
npm run build
```

后端托管前端构建产物，因此 `frontend/**` 修改必须同时提交更新后的 `app/static/`。

## 分支与提交

建议分支：

- `feature/<scope>`：功能。
- `fix/<scope>`：缺陷修复。
- `docs/<scope>`：文档和视觉资产。
- `release/<version>`：发版准备。

提交信息使用 Conventional Commits：

```text
feat(assistant): add controlled web research
fix(report): keep deterministic verdict when model fails
docs(repository): reorganize current documentation
```

## Pull Request

PR 描述应包含：

1. 动机；
2. 改动范围；
3. 行为变化；
4. 验证命令与结果；
5. 界面改动截图；
6. 数据、安全和兼容性影响。

一次 PR 只处理一个主题，不夹带无关重构和生成文件。

## 发布

发布前检查：

- [ ] `app/__init__.py` 版本号正确。
- [ ] `CHANGELOG.md` 有对应条目。
- [ ] 全量 `pytest` 通过。
- [ ] 前端 `npm run typecheck` 与 `npm run build` 通过。
- [ ] `app/static/` 已更新。
- [ ] 文档、API、FAQ、配置和安全说明与实现一致。
- [ ] 已用独立临时存储验证，不包含真实数据或密钥。
- [ ] 创建并推送版本 tag。
- [ ] GitHub Release workflow 成功。

发布命令：

```powershell
git tag -a v3.0.0 -m "Release v3.0.0"
git push origin main --tags
```

tag 推送后，GitHub Actions 会读取 `app/__init__.py` 和 `CHANGELOG.md` 创建 Release。
