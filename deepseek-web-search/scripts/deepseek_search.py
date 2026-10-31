#!/usr/bin/env python3
"""Minimal client for DeepSeek's Search and Fetch APIs."""
import argparse
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_URL = "https://api.deepseek.com/v1/tools/"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    search = commands.add_parser("search", help="Search the web")
    search.add_argument("query")
    search.add_argument("--count", type=int, default=10)
    search.add_argument("--need-content", action="store_true")
    search.add_argument("--original-question")
    search.add_argument("--localization")
    fetch = commands.add_parser("fetch", help="Fetch one web page")
    fetch.add_argument("url")
    args = parser.parse_args()

    if args.command == "search":
        if not args.query.strip() or len(args.query) > 128:
            parser.error("query must contain 1–128 characters and cannot be all blank")
        if not 1 <= args.count <= 50:
            parser.error("count must be between 1 and 50")
        payload = {"query": args.query, "count": args.count, "need_content": args.need_content}
        if args.original_question is not None:
            payload["ori_question"] = args.original_question
        if args.localization is not None:
            payload["localization"] = args.localization
    else:
        payload = {"url": args.url}

    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        path = Path.home() / ".config/deepseek/api_key"
        try:
            key = path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            pass
        except OSError as exc:
            print(f"Cannot read DeepSeek API key file: {exc.strerror}", file=sys.stderr)
            return 1
    if not key:
        print("Set DEEPSEEK_API_KEY or save the key in ~/.config/deepseek/api_key (mode 600).", file=sys.stderr)
        return 1

    request = Request(BASE_URL + args.command, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                      headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=60) as response:
            result = json.load(response)
    except HTTPError as exc:
        print(f"DeepSeek {args.command} failed with HTTP {exc.code}.", file=sys.stderr)
        return 1
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        print(f"DeepSeek {args.command} failed: {type(exc).__name__}.", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
