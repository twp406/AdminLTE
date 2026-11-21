"""命令行入口。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .engine import PipelineError, run_pipeline
from .report import render


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="price-lens",
        description="电商商品价格采集与横向对比工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python cli.py search \"无线蓝牙耳机\"\n"
            "  python cli.py search \"机械键盘\" --source demo --sort value --format md --out report.md\n"
            "  python cli.py search \"保温杯\" --format csv --out data/result.csv\n"
            "  python cli.py serve --port 8000\n"
        ),
    )
    parser.add_argument("--version", action="version", version=f"price-lens {__version__}")
    sub = parser.add_subparsers(dest="command")

    search = sub.add_parser("search", help="采集并分析指定关键词")
    search.add_argument("keyword", help="搜索关键词，例如：无线蓝牙耳机")
    search.add_argument("--source", choices=["demo", "live"], default="demo", help="数据源，默认 demo（离线可运行）")
    search.add_argument("--platforms", default="jd,tb,pdd", help="平台，逗号分隔：jd,tb,pdd")
    search.add_argument("--sort", choices=["price", "value", "sales", "rating"], default="price", help="排序方式")
    search.add_argument("--limit", type=int, default=30, help="展示条数，默认 30")
    search.add_argument("--format", choices=["table", "json", "csv", "md"], default="table", help="输出格式")
    search.add_argument("--out", help="将结果写入文件")
    search.add_argument("--no-color", action="store_true", help="关闭终端颜色")

    serve = sub.add_parser("serve", help="启动演示网页与本地 API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--source", choices=["demo", "live"], default="demo", help="网页默认数据源")

    return parser


def _platforms(value: str) -> list[str]:
    allowed = {"jd", "tb", "pdd"}
    result = [part.strip() for part in value.split(",") if part.strip()]
    invalid = [part for part in result if part not in allowed]
    if invalid:
        raise SystemExit(f"未知平台: {', '.join(invalid)}（可选 jd,tb,pdd）")
    return result or ["jd", "tb", "pdd"]


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        args.command = "search"
        parser.error("请提供子命令 search 或 serve（python cli.py search \"关键词\"）")

    if args.command == "serve":
        from .server import run_server

        run_server(host=args.host, port=args.port, source=args.source)
        return 0

    try:
        result = run_pipeline(
            args.keyword,
            platforms=_platforms(args.platforms),
            source=args.source,
            sort=args.sort,
            limit=args.limit,
        )
    except PipelineError as exc:
        print(f"采集失败：{exc}", file=sys.stderr)
        for warning in exc.warnings:
            print(f"  - {warning}", file=sys.stderr)
        return 1

    content = render(result, args.format, color=not args.no_color)
    print(content)

    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        encoding = "utf-8-sig" if args.format == "csv" else "utf-8"
        path.write_text(content + ("\n" if not content.endswith("\n") else ""), encoding=encoding)
        print(f"\n已写入 {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
