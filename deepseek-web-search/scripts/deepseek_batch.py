#!/usr/bin/env python3
"""Run DeepSeek searches and prepare review batches."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

CLIENT = Path(__file__).resolve().with_name("deepseek_search.py")


def private_directory(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not path.is_dir():
        raise ValueError("output path is not a directory")
    if path.stat().st_mode & 0o077:
        raise ValueError("output directory must be private (mode 700)")


def write_json(path, data):
    # Atomic replacement keeps cache files valid if a process is interrupted.
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as output:
        temp_path = Path(output.name)
        try:
            json.dump(data, output, ensure_ascii=False, indent=2)
            output.write("\n")
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
    try:
        os.replace(temp_path, path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def cache_key(query, count, need_content, original_question=None, localization=None):
    params = {"query": query, "count": count, "need_content": need_content,
              "ori_question": original_question, "localization": localization}
    return hashlib.sha256(json.dumps(params, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def valid_response(result):
    return (isinstance(result, dict) and isinstance(result.get("results"), list)
            and all(isinstance(item, dict) for item in result["results"]))


def read_cache(path, max_age_hours):
    if max_age_hours <= 0:
        return None
    try:
        age = time.time() - path.stat().st_mtime
        if age < 0 or age > max_age_hours * 3600:
            return None
        result = json.loads(path.read_text(encoding="utf-8"))
        if valid_response(result):
            return result
    except (OSError, ValueError):
        pass
    return None


def run_search(query, count, need_content, original_question=None, localization=None):
    command = [sys.executable, str(CLIENT), "search"]
    if count is not None:
        command.extend(["--count", str(count)])
    if need_content:
        command.append("--need-content")
    if original_question is not None:
        command.append("--original-question=" + original_question)
    if localization is not None:
        command.append("--localization=" + localization)
    command.extend(["--", query])
    try:
        response = subprocess.run(command, capture_output=True, text=True, timeout=75, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None, "Search client could not run or timed out."
    if response.returncode:
        # Do not forward arbitrary subprocess stderr, which could contain sensitive data.
        match = re.search(r"failed with HTTP (\d{3})\b", response.stderr)
        if match:
            code = int(match.group(1))
            hints = {401: "check the API key", 402: "check the account balance",
                     429: "wait before retrying"}
            return None, f"Search failed with HTTP {code}; {hints.get(code, 'check the API status and request')}."
        return None, "Search request failed; check the key, balance, connection and API status."
    try:
        data = json.loads(response.stdout)
        if not valid_response(data):
            raise ValueError("invalid response")
    except (ValueError, TypeError):
        return None, "Search returned an invalid response."
    return data, None


def normalized_url(url):
    """Normalize only safe URL components; preserve the path and query string."""
    if not isinstance(url, str) or not url:
        return None
    try:
        parsed = urlsplit(url)
        if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            return url
        scheme = parsed.scheme.lower()
        host = parsed.hostname.lower()
        if ":" in host:
            host = "[" + host + "]"
        port = parsed.port
        authority = host + (f":{port}" if port is not None and (scheme, port) not in (("http", 80), ("https", 443)) else "")
        return urlunsplit((scheme, authority, parsed.path or "/", parsed.query, ""))
    except ValueError:
        return url


def parse_arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", action="append", required=True, help="Search query; repeat for each search")
    parser.add_argument("--output-dir", type=Path, required=True, help="Private directory for raw results, cache and review batches")
    parser.add_argument("--count", type=int, help="Results per query (1–50; otherwise use the client default)")
    parser.add_argument("--need-content", action="store_true")
    parser.add_argument("--original-question", help="Original question passed to each search")
    parser.add_argument("--localization", help="IP address for localized results")
    parser.add_argument("--max-age-hours", type=float, default=24)
    parser.add_argument("--refresh", action="store_true", help="Skip the cache")
    parser.add_argument("--batch-size", type=int, default=20)
    args = parser.parse_args(argv)
    if any(not q.strip() or len(q) > 128 for q in args.query):
        parser.error("each query must have 1–128 characters and cannot be blank")
    if args.count is not None and not 1 <= args.count <= 50:
        parser.error("count must be between 1 and 50")
    if args.original_question is not None and not 1 <= len(args.original_question) <= 128:
        parser.error("original-question must have 1–128 characters")
    if args.batch_size < 1:
        parser.error("batch-size must be positive")
    if not 0 <= args.max_age_hours < float("inf"):
        parser.error("max-age-hours must be a nonnegative finite number")
    return args


def main(argv=None):
    args = parse_arguments(argv)
    try:
        private_directory(args.output_dir)
        cache_dir = args.output_dir / "cache"
        runs_dir = args.output_dir / "runs"
        private_directory(cache_dir)
        private_directory(runs_dir)
        run_name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid4().hex[:12]
        run_dir = runs_dir / run_name
        run_dir.mkdir(mode=0o700)
        raw_dir = run_dir / "raw"
        batch_dir = run_dir / "batches"
        raw_dir.mkdir(mode=0o700)
        batch_dir.mkdir(mode=0o700)

        queries = list(dict.fromkeys(args.query))
        candidates = []
        seen = {}
        errors = []
        query_results = []
        cache_hits = 0
        search_requests = 0
        for index, query in enumerate(queries, 1):
            key = cache_key(query, args.count, args.need_content, args.original_question, args.localization)
            cache_path = cache_dir / (key + ".json")
            result = None if args.refresh else read_cache(cache_path, args.max_age_hours)
            from_cache = result is not None
            if from_cache:
                cache_hits += 1
            else:
                search_requests += 1
                result, error = run_search(query, args.count, args.need_content, args.original_question, args.localization)
                if error:
                    errors.append({"query": query, "message": error})
                    query_results.append({"query": query, "status": "failed"})
                    continue
                write_json(cache_path, result)
            raw_name = f"{index:03d}-{key[:12]}.json"
            write_json(raw_dir / raw_name, result)
            query_results.append({"query": query, "status": "cached" if from_cache else "searched", "result_count": len(result["results"]), "raw_file": "raw/" + raw_name})
            for item in result["results"]:
                if not isinstance(item, dict):
                    continue
                url = item.get("url")
                normalized = normalized_url(url)
                if normalized is not None and normalized in seen:
                    prior = candidates[seen[normalized]]
                    if query not in prior["source_queries"]:
                        prior["source_queries"].append(query)
                    continue
                candidate = {field: item.get(field) for field in ("title", "url", "snippet", "summary", "date")}
                candidate["source_queries"] = [query]
                if normalized is not None:
                    seen[normalized] = len(candidates)
                candidates.append(candidate)
        write_json(run_dir / "candidates.json", candidates)
        batch_files = []
        for offset in range(0, len(candidates), args.batch_size):
            name = f"batches/batch-{len(batch_files) + 1:03d}.json"
            write_json(run_dir / name, candidates[offset:offset + args.batch_size])
            batch_files.append(name)
        manifest = {"run_dir": str(run_dir), "query_count": len(queries), "search_requests": search_requests,
                    "cache_hits": cache_hits, "candidate_count": len(candidates), "batch_files": batch_files,
                    "query_results": query_results, "errors": errors}
        write_json(run_dir / "manifest.json", manifest)
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 1 if errors else 0
    except (OSError, ValueError) as exc:
        print(f"Batch search failed: {type(exc).__name__}. Check that the output directory is writable and private (mode 700).", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
