"""生成资产的静态安全门禁。"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass

from app.schemas.execution import GeneratedFile, ValidationIssue

FORBIDDEN_IMPORTS = {
    "ctypes",
    "multiprocessing",
    "shutil",
    "socket",
    "subprocess",
    "sys",
}
FORBIDDEN_CALLS = {
    "__import__",
    "eval",
    "exec",
    "input",
    "open",
}
FORBIDDEN_METHODS = {
    "chmod",
    "remove",
    "rename",
    "replace",
    "rmdir",
    "unlink",
    "write_bytes",
    "write_text",
}

SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"(?i)\bBearer\s+(?!\{\{)[A-Za-z0-9._~+/=-]{20,}"),
)


@dataclass(frozen=True)
class ValidationResult:
    errors: list[ValidationIssue]
    warnings: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors


def _python_targets(files: list[GeneratedFile]) -> list[GeneratedFile]:
    return [item for item in files if item.path.endswith(".py")]


def validate_generated_files(files: list[GeneratedFile]) -> ValidationResult:
    """检查语法、导入、危险调用和明文密钥。"""
    errors: list[ValidationIssue] = []
    warnings: list[str] = []

    for item in files:
        if not item.path or item.path.startswith(("/", "\\")) or ".." in item.path.split("/"):
            errors.append(
                ValidationIssue(code="UNSAFE_PATH", path=item.path, message="生成文件路径不合法。")
            )
        for pattern in SECRET_PATTERNS:
            if pattern.search(item.content):
                errors.append(
                    ValidationIssue(
                        code="POSSIBLE_SECRET",
                        path=item.path,
                        message="检测到疑似明文密钥或 Token，已阻止下载。",
                    )
                )
                break

    for item in _python_targets(files):
        try:
            tree = ast.parse(item.content, filename=item.path)
            compile(item.content, item.path, "exec")
        except (SyntaxError, ValueError) as exc:
            errors.append(
                ValidationIssue(
                    code="PYTHON_SYNTAX",
                    path=item.path,
                    message=f"Python 语法校验失败：{exc}",
                )
            )
            continue

        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = (
                    [alias.name for alias in node.names]
                    if isinstance(node, ast.Import)
                    else [node.module or ""]
                )
                for name in names:
                    root = name.split(".", 1)[0]
                    if root in FORBIDDEN_IMPORTS:
                        errors.append(
                            ValidationIssue(
                                code="FORBIDDEN_IMPORT",
                                path=item.path,
                                message=f"禁止导入模块：{root}",
                            )
                        )
            elif isinstance(node, ast.Call):
                target = ""
                is_name = isinstance(node.func, ast.Name)
                if isinstance(node.func, ast.Name):
                    target = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    target = node.func.attr
                if target in FORBIDDEN_CALLS or (is_name and target == "compile"):
                    errors.append(
                        ValidationIssue(
                            code="FORBIDDEN_CALL",
                            path=item.path,
                            message=f"禁止调用：{target}",
                        )
                    )
                if target in FORBIDDEN_METHODS:
                    errors.append(
                        ValidationIssue(
                            code="FORBIDDEN_FILESYSTEM",
                            path=item.path,
                            message=f"禁止文件写入或破坏性操作：{target}",
                        )
                    )

    if not any(item.path == ".env.example" for item in files):
        warnings.append("资产缺少 .env.example，环境变量说明不完整。")
    if not any(item.path.startswith("tests/") and item.path.endswith(".py") for item in files):
        errors.append(
            ValidationIssue(code="MISSING_TESTS", path="", message="资产未包含 pytest 测试文件。")
        )
    return ValidationResult(errors=errors, warnings=warnings)


__all__ = ["ValidationResult", "validate_generated_files"]
