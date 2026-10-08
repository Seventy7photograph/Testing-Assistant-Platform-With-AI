"""启动器（run.py）回归测试。

覆盖一个真实踩坑点：用户用 http://0.0.0.0:8000/ 访问，请求被本地代理拦截后
返回 502 Bad Gateway。启动横幅必须给出 127.0.0.1 访问地址与代理绕过提示。
"""
from __future__ import annotations

import run


def test_parser_defaults(settings) -> None:
    args = run.build_parser(settings).parse_args([])
    assert args.host == "0.0.0.0"
    assert args.port == 8000
    assert args.reload is settings.debug


def test_parser_accepts_overrides(settings) -> None:
    args = run.build_parser(settings).parse_args(["--host", "127.0.0.1", "--port", "8080", "--no-reload"])
    assert (args.host, args.port, args.reload) == ("127.0.0.1", 8080, False)
    assert run.build_parser(settings).parse_args(["--reload"]).reload is True


def test_banner_shows_loopback_url_and_proxy_hint(capsys) -> None:
    run.print_banner("0.0.0.0", 8000, reload=False)
    output = capsys.readouterr().out

    assert "http://127.0.0.1:8000/" in output, "横幅必须给出可访问的回环地址"
    assert "http://127.0.0.1:8000/docs" in output
    assert "/api/v1/health" in output
    assert "0.0.0.0" in output, "必须显式提醒不要用 0.0.0.0 访问"
    assert "502" in output, "必须包含 502 排障提示"
    assert "绕过代理" in output


def test_banner_for_explicit_host(capsys) -> None:
    run.print_banner("127.0.0.1", 9001, reload=True)
    output = capsys.readouterr().out
    assert "http://127.0.0.1:9001/" in output
    assert "局域网访问" not in output, "仅监听回环时不应展示局域网地址"