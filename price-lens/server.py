#!/usr/bin/env python3
"""网页服务启动文件：python server.py --port 8000。"""

import sys

from pricehunter.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["serve", *sys.argv[1:]]))
