"""本地 Web 服务：静态演示页 + 现场调用采集流水线的 JSON API。"""

from __future__ import annotations

import json
import sys
import urllib.parse
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .engine import PipelineError, run_pipeline
from .report import render_csv, render_json, render_markdown

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def _split_platforms(value: str | None) -> list[str] | None:
    if not value:
        return None
    platforms = [part.strip() for part in value.split(",") if part.strip()]
    return platforms or None


class Handler(SimpleHTTPRequestHandler):
    server_version = "PriceLens/1.0"

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 接口
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self._handle_api(parsed)
            return
        super().do_GET()

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt: str, *args: Any) -> None:
        if args and str(args[0]).startswith("4"):
            super().log_message(fmt, *args)

    def _handle_api(self, parsed: urllib.parse.ParseResult) -> None:
        params = urllib.parse.parse_qs(parsed.query)
        keyword = (params.get("keyword") or ["无线蓝牙耳机"])[0].strip()

        if parsed.path == "/api/health":
            self._send_json({"ok": True, "service": "price-lens"})
            return

        try:
            if parsed.path == "/api/search":
                result = self._run(params, keyword)
                self._send_json(result)
            elif parsed.path == "/api/export":
                fmt = (params.get("format") or ["csv"])[0]
                result = self._run(params, keyword)
                if fmt == "json":
                    body, mime, ext = render_json(result), "application/json", "json"
                elif fmt == "md":
                    body, mime, ext = render_markdown(result), "text/markdown", "md"
                else:
                    body, mime, ext = "\ufeff" + render_csv(result), "text/csv", "csv"
                self._send_bytes(
                    body.encode("utf-8"),
                    mime + "; charset=utf-8",
                    extra={"Content-Disposition": f'attachment; filename="price-report.{ext}"'},
                )
            else:
                self._send_json({"error": "未知接口"}, HTTPStatus.NOT_FOUND)
        except PipelineError as exc:
            self._send_json({"error": str(exc), "warnings": exc.warnings}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:  # noqa: BLE001 - API 边界统一兜底
            self._send_json({"error": f"服务端异常：{exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _run(self, params: dict[str, list[str]], keyword: str) -> dict[str, Any]:
        source = (params.get("source") or [getattr(self.server, "default_source", "demo")])[0]
        sort = (params.get("sort") or ["price"])[0]
        try:
            limit = int((params.get("limit") or ["24"])[0])
        except ValueError:
            limit = 24
        return run_pipeline(
            keyword,
            platforms=_split_platforms((params.get("platforms") or [None])[0]),
            source=source,
            sort=sort,
            limit=limit,
        )

    def _send_json(self, payload: dict[str, Any], status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_bytes(body, "application/json; charset=utf-8", status=status)

    def _send_bytes(
        self,
        body: bytes,
        content_type: str,
        status: int = HTTPStatus.OK,
        extra: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)


def create_server(host: str = "127.0.0.1", port: int = 8000, source: str = "demo") -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    server.default_source = source  # type: ignore[attr-defined]
    return server


def run_server(host: str = "127.0.0.1", port: int = 8000, source: str = "demo") -> None:
    server = create_server(host, port, source)
    url = f"http://{host}:{port}"
    print(f"价探 PriceLens 已启动: {url}")
    print(f"默认数据源: {'离线演示数据' if source == 'demo' else '实时采集'}  ｜  Ctrl+C 退出")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止服务")
    finally:
        server.server_close()


if __name__ == "__main__":
    run_server(port=int(sys.argv[1]) if len(sys.argv) > 1 else 8000)
