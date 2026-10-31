#!/usr/bin/env python3
"""Minimal client for DeepSeek's Search and Fetch APIs."""
import argparse
import json
import os
import socket
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

BASE_URL = "https://api.deepseek.com/v1/tools/"
CONTENT_LIMIT = 2000


class NoRedirectHandler(HTTPRedirectHandler):
    """Never forward the API key in an HTTP redirect."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def compact_search(result):
    """Return a smaller search response while flagging truncated content."""
    items = []
    for item in result["results"]:
        entry = {key: item.get(key) for key in ("title", "url", "snippet", "date")}
        content = item.get("content")
        if content:
            entry["content"] = content[:CONTENT_LIMIT]
            entry["content_truncated"] = len(content) > CONTENT_LIMIT
        items.append(entry)
    return {"results": items}


def http_error_message(code):
    if 300 <= code < 400:
        return "API redirect refused; check the official endpoint and try again."
    messages = {
        400: "Invalid request; check the query, URL, and parameters.",
        401: "Invalid or missing API key; check the configured key.",
        402: "Insufficient account balance; check the DeepSeek account.",
        403: "Request rejected by the API security policy.",
        404: "Page unavailable or no extractable content; check the target URL.",
        408: "Request timed out; retry later.",
        413: "Request body too large; reduce the input.",
        429: "Rate limit exceeded; wait before retrying.",
    }
    if code >= 500:
        return "DeepSeek service error; retry later."
    return messages.get(code, "Request failed; check the API documentation.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    search = commands.add_parser("search", help="Search the web")
    search.add_argument("query")
    search.add_argument("--count", type=int, default=10)
    search.add_argument("--need-content", action="store_true")
    search.add_argument("--compact", action="store_true", help="Return fewer fields and limit each page's content to 2000 characters")
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
        with build_opener(NoRedirectHandler()).open(request, timeout=60) as response:
            result = json.load(response)
    except HTTPError as exc:
        print(f"DeepSeek {args.command} failed with HTTP {exc.code}: {http_error_message(exc.code)}", file=sys.stderr)
        exc.close()
        return 1
    except (TimeoutError, socket.timeout):
        print(f"DeepSeek {args.command} timed out; retry later.", file=sys.stderr)
        return 1
    except URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            print(f"DeepSeek {args.command} timed out; retry later.", file=sys.stderr)
        else:
            print(f"DeepSeek {args.command} network error; check connectivity and retry later.", file=sys.stderr)
        return 1
    except (OSError, ValueError):
        print(f"DeepSeek {args.command} failed: unreadable response or connection error.", file=sys.stderr)
        return 1
    if args.command == "search" and args.compact:
        try:
            result = compact_search(result)
        except (KeyError, TypeError):
            print("DeepSeek search failed: unexpected response format.", file=sys.stderr)
            return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
