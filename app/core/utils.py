"""通用工具函数：ID 生成、文本清洗、JSON 容错解析等。"""
from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any

# --------------------------------------------------------------------------- #
# ID / 时间
# --------------------------------------------------------------------------- #

_ID_SAFE_RE = re.compile(r"[^0-9a-zA-Z_\-\u4e00-\u9fff]+")


def new_id(prefix: str = "") -> str:
    """生成短且唯一的 ID，例如 DOC-3f9a2c7b。"""
    token = uuid.uuid4().hex[:8]
    return f"{prefix}{token}" if prefix else token


def now_iso() -> str:
    """当前时间的 ISO8601 字符串（本地时区，便于人读）。"""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def slugify_filename(name: str, fallback: str = "file") -> str:
    """把中文/特殊字符文件名转换为安全的文件名片段。"""
    stem = re.sub(r"\.[A-Za-z0-9]{1,8}$", "", name or "")
    stem = _ID_SAFE_RE.sub("_", stem).strip("_")
    return stem or fallback


def short_hash(*parts: object, length: int = 16) -> str:
    """对入参做稳定哈希，用于用例去重指纹。"""
    raw = "||".join(str(p) for p in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:length]


# --------------------------------------------------------------------------- #
# 文本处理
# --------------------------------------------------------------------------- #

_MULTI_BLANK_RE = re.compile(r"\n{3,}")
_TRAILING_SPACE_RE = re.compile(r"[ \t]+\n")


def normalize_whitespace(text: str) -> str:
    """统一换行符、压缩连续空行、去掉行尾空格。"""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u3000", " ").replace("\xa0", " ")
    text = _TRAILING_SPACE_RE.sub("\n", text)
    text = _MULTI_BLANK_RE.sub("\n\n", text)
    return text.strip()


def truncate(text: str, limit: int = 300, suffix: str = "...") -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: max(limit - len(suffix), 0)] + suffix


def decode_bytes(data: bytes, encodings: tuple[str, ...] = ("utf-8", "gb18030", "utf-16")) -> tuple[str, str]:
    """按候选编码依次尝试解码，返回 (文本, 实际编码)。

    中文需求文档常见 GBK/GB18030 编码，这里做显式兼容，
    全部失败时用 utf-8 + errors='replace' 兜底，保证不因编码崩溃。
    """
    for encoding in encodings:
        try:
            return data.decode(encoding), encoding
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace"), "utf-8(replace)"


# --------------------------------------------------------------------------- #
# JSON 容错解析（抵抗大模型输出格式抖动）
# --------------------------------------------------------------------------- #

_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.DOTALL)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")
_LINE_COMMENT_RE = re.compile(r"(?m)^\s*//.*$")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


class JsonExtractionError(ValueError):
    """无法从文本中抽取合法 JSON。"""


def _try_loads(candidate: str) -> Any:
    return json.loads(candidate)


def _repair(candidate: str) -> str:
    """常见 LLM JSON 瑕疵修复：代码块残留、注释、尾逗号、中文引号。"""
    fixed = candidate.strip()
    fixed = _LINE_COMMENT_RE.sub("", fixed)
    fixed = _BLOCK_COMMENT_RE.sub("", fixed)
    fixed = _TRAILING_COMMA_RE.sub(r"\1", fixed)
    fixed = fixed.replace("“", '"').replace("”", '"')
    fixed = fixed.replace("‘", "'").replace("’", "'")
    return fixed.strip()


def extract_json(text: str) -> Any:
    """从任意 LLM 输出文本中抽取 JSON 对象/数组。

    处理顺序：
    1. 剥离 ```json 代码块；
    2. 直接 json.loads；
    3. 截取首个 { / [ 到最后一个 } / ] 的子串再解析；
    4. 常规修复（注释、尾逗号、中文引号）后重试。

    :raises JsonExtractionError: 全部策略失败时抛出。
    """
    if not text or not text.strip():
        raise JsonExtractionError("模型输出为空")

    candidates: list[str] = []
    fenced = _FENCE_RE.findall(text)
    if fenced:
        candidates.extend(block for block in fenced if block.strip())
    candidates.append(text)

    for raw in candidates:
        for candidate in (raw.strip(), _repair(raw)):
            if not candidate:
                continue
            try:
                return _try_loads(candidate)
            except json.JSONDecodeError:
                pass

            start_positions = [p for p in (candidate.find("{"), candidate.find("[")) if p != -1]
            if not start_positions:
                continue
            start = min(start_positions)
            end = max(candidate.rfind("}"), candidate.rfind("]"))
            if end <= start:
                continue
            snippet = _repair(candidate[start : end + 1])
            try:
                return _try_loads(snippet)
            except json.JSONDecodeError:
                continue

    raise JsonExtractionError(f"无法解析为 JSON，原文片段：{truncate(text, 200)}")


def dump_json(data: Any, *, indent: int | None = 2) -> str:
    """统一的中文友好 JSON 序列化。"""
    return json.dumps(data, ensure_ascii=False, indent=indent, default=str)


# --------------------------------------------------------------------------- #
# 计时
# --------------------------------------------------------------------------- #


class Timer:
    """极简计时上下文，用于记录 LLM/解析耗时（毫秒）。"""

    def __init__(self) -> None:
        self._start = time.perf_counter()
        self.elapsed_ms: int = 0

    def __enter__(self) -> "Timer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.elapsed_ms = int((time.perf_counter() - self._start) * 1000)