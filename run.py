"""本地启动入口。

用法：
    python run.py                    # 默认监听 0.0.0.0:8000
    python run.py --port 8080        # 更换端口
    python run.py --host 127.0.0.1   # 只允许本机访问（更安全）
    python run.py --no-reload        # 关闭热重载

浏览器访问请使用 http://127.0.0.1:<port>/ ，不要使用 http://0.0.0.0:<port>/ ：
0.0.0.0 是"监听全部网卡"的绑定地址，不是可访问的目的地址；经过系统代理时
会被代理当成非法目标而返回 502 Bad Gateway。
"""
from __future__ import annotations

import argparse
import os
import socket
import sys

import uvicorn

from app.core.config import get_settings

try:  # Windows 控制台默认 GBK，会把启动横幅的中文打成乱码
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:  # noqa: BLE001
    pass

PROXY_HINT = """\
注意：浏览器请用 127.0.0.1 或 localhost 访问，不要用 0.0.0.0（那是监听地址，不是访问地址）。
若浏览器返回 502 Bad Gateway，且网络面板里「远程地址」是 127.0.0.1:789x，
说明请求被本地代理（Clash / V2Ray / 公司代理）拦截了，而不是服务出错：
  1) 把 127.0.0.1、localhost、0.0.0.0 加入代理软件的「绕过代理 / Bypass」列表；
  2) 或临时关闭系统代理后再访问；
  3) Windows 也可在「设置 → 网络和 Internet → 代理」中勾选"请勿对本地地址使用代理服务器"。"""


def build_parser(settings) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="测试工程师助手平台 本地启动入口（用例生成 · 测试报告）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=PROXY_HINT,
    )
    parser.add_argument("--host", default="0.0.0.0", help="监听地址（默认 0.0.0.0；仅本机使用建议 127.0.0.1）")
    parser.add_argument("--port", type=int, default=8000, help="监听端口（默认 8000）")
    parser.add_argument(
        "--reload",
        dest="reload",
        action="store_true",
        default=settings.debug,
        help="开启代码热重载（默认跟随 DEBUG 配置）",
    )
    parser.add_argument("--no-reload", dest="reload", action="store_false", help="关闭代码热重载")
    return parser


def local_addresses() -> list[str]:
    """尽量列出本机可被局域网访问的 IPv4 地址，便于手机/同事联调。"""
    addresses: list[str] = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            address = info[4][0]
            if address not in addresses and not address.startswith("127."):
                addresses.append(address)
    except OSError:
        pass
    return addresses


def print_banner(host: str, port: int, reload: bool) -> None:
    settings = get_settings()

    from app.llm.factory import get_llm_provider  # 延迟导入，确保 .env 已加载

    provider = get_llm_provider()
    if provider.available:
        llm_line = f"{provider.name} / {provider.model}（已启用）"
    else:
        llm_line = f"未启用 → 纯规则引擎（{settings.llm_provider} 未配置 LLM_API_KEY）"

    display = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    base = f"http://{display}:{port}"
    width = 66

    print("=" * width)
    print(f" {settings.app_name} v{settings.app_version}")
    print("-" * width)
    print(f" 主页面  : {base}/")
    print(f" 接口文档  : {base}/docs")
    print(f" 健康检查  : {base}/api/v1/health")
    print(f" LLM       : {llm_line}")
    print(f" 存储目录  : {settings.storage_dir}")
    print(f" 热重载    : {'开启' if reload else '关闭'}")
    if host in ("0.0.0.0", "::", ""):
        others = local_addresses()
        if others:
            print(f" 局域网访问: http://{others[0]}:{port}")
    print("-" * width)

    if any(key.upper().endswith("_PROXY") and value for key, value in os.environ.items()):
        print(" 检测到代理环境变量，如遇 502 请把 localhost 加入 NO_PROXY。")
    print(PROXY_HINT)
    print("=" * width, flush=True)


def main() -> None:
    settings = get_settings()
    args = build_parser(settings).parse_args()
    print_banner(args.host, args.port, args.reload)
    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
