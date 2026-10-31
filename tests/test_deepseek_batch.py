"""Offline behavior tests for the batch research pipeline."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "deepseek-web-search/scripts/deepseek_batch.py"
spec = importlib.util.spec_from_file_location("deepseek_batch", SCRIPT)
batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch)


def result(url, title="Title", content="full text"):
    return {"title": title, "url": url, "snippet": "snippet", "summary": "summary",
            "date": "2026-01-01", "content": content}


def response(results):
    return subprocess.CompletedProcess(args=[], returncode=0,
                                       stdout=json.dumps({"results": results}), stderr="")


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "output"
        # Never read a user's real credential, even when a test fails.
        self.env = mock.patch.dict(os.environ, {"HOME": self.temp.name, "DEEPSEEK_API_KEY": "test-only-key"}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.run = mock.patch.object(batch.subprocess, "run")
        self.call = self.run.start()
        self.addCleanup(self.run.stop)

    def invoke(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "argv", ["deepseek_batch.py", *args, "--output-dir", str(self.output)]), \
             contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                status = batch.main()
            except SystemExit as error:
                status = error.code
        return status, stdout.getvalue(), stderr.getvalue()

    def test_multi_query_deduplicates_preserves_provenance_and_raw(self):
        self.call.side_effect = [
            response([result("https://EXAMPLE.org:443/a#first"), result("https://example.org/other", "Other")]),
            response([result("https://example.org/a#second"), result("https://example.org/a?version=2", "Different version")]),
        ]
        status, stdout, stderr = self.invoke("--query", "first", "--query", "second", "--need-content", "--count", "50", "--batch-size", "2")
        self.assertEqual(status, 0, stderr)
        report = json.loads(stdout)
        self.assertEqual(report["search_requests"], 2)
        self.assertEqual(report["candidate_count"], 3)
        run = Path(report["run_dir"])
        candidates = json.loads((run / "candidates.json").read_text())
        self.assertEqual(len(candidates), 3)
        self.assertEqual(set(candidates[0]["source_queries"]), {"first", "second"})
        self.assertNotIn("content", candidates[0])
        self.assertEqual(candidates[0]["summary"], "summary")
        raw = sorted((run / "raw").glob("*.json"))
        self.assertEqual(len(raw), 2)
        self.assertEqual(json.loads(raw[0].read_text())["results"][0]["content"], "full text")
        slices = sorted((run / "batches").glob("*.json"))
        self.assertEqual([len(json.loads(p.read_text())) for p in slices], [2, 1])
        self.assertEqual(self.call.call_count, 2)
        self.assertTrue(all("--need-content" in call.args[0] for call in self.call.call_args_list))
        self.assertTrue(all("50" in call.args[0] for call in self.call.call_args_list))

    def test_cache_hit_creates_new_run_with_raw_snapshot_without_network(self):
        self.call.return_value = response([result("https://example.org/one")])
        first = self.invoke("--query", "same")
        self.assertEqual(first[0], 0, first[2])
        self.call.reset_mock()
        second = self.invoke("--query", "same")
        self.assertEqual(second[0], 0, second[2])
        report = json.loads(second[1])
        self.assertEqual(report["cache_hits"], 1)
        self.assertEqual(report["search_requests"], 0)
        self.assertEqual(len(list((Path(report["run_dir"]) / "raw").glob("*.json"))), 1)
        self.call.assert_not_called()

    def test_refresh_and_parameter_change_make_new_requests(self):
        self.call.return_value = response([])
        self.assertEqual(self.invoke("--query", "same")[0], 0)
        self.call.reset_mock()
        self.assertEqual(self.invoke("--query", "same", "--refresh")[0], 0)
        self.assertEqual(self.invoke("--query", "same", "--count", "10")[0], 0)
        self.assertEqual(self.invoke("--query", "same", "--need-content")[0], 0)
        self.assertEqual(self.call.call_count, 3)

    def test_user_selected_context_fields_are_forwarded_and_cache_separated(self):
        self.call.return_value = response([])
        self.assertEqual(self.invoke("--query", "same")[0], 0)
        self.call.reset_mock()
        status, _, stderr = self.invoke("--query", "same", "--original-question", "question", "--localization", "192.0.2.1")
        self.assertEqual(status, 0, stderr)
        self.call.assert_called_once()
        command = self.call.call_args.args[0]
        self.assertIn("--original-question=question", command)
        self.assertIn("--localization=192.0.2.1", command)
        self.assertNotIn("--count", command)

    def test_expired_cache_is_refetched(self):
        self.call.return_value = response([result("https://example.org/a")])
        self.assertEqual(self.invoke("--query", "old")[0], 0)
        cached = list((self.output / "cache").glob("*.json"))
        self.assertEqual(len(cached), 1)
        old = time.time() - 2 * 3600
        os.utime(cached[0], (old, old))
        self.call.reset_mock()
        status, stdout, stderr = self.invoke("--query", "old", "--max-age-hours", "1")
        self.assertEqual(status, 0, stderr)
        self.assertEqual(json.loads(stdout)["search_requests"], 1)
        self.call.assert_called_once()

    def test_partial_failure_preserves_successes_and_returns_nonzero(self):
        self.call.side_effect = [response([result("https://example.org/a")]),
                                 subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="search failed")]
        status, stdout, stderr = self.invoke("--query", "good", "--query", "bad")
        self.assertNotEqual(status, 0)
        report = json.loads(stdout)
        self.assertEqual(report["candidate_count"], 1)
        self.assertTrue(report["errors"])
        self.assertNotIn("test-only-key", stdout + stderr)
        self.assertEqual(len(list((Path(report["run_dir"]) / "raw").glob("*.json"))), 1)

    def test_invalid_query_count_is_rejected_without_search(self):
        for args in ((), ("--query", "valid", "--count", "51")):
            with self.subTest(args=args):
                self.assertNotEqual(self.invoke(*args)[0], 0)
        self.call.assert_not_called()

    def test_callers_choose_how_many_searches_to_make(self):
        self.call.return_value = response([])
        args = tuple(value for number in range(6) for value in ("--query", str(number)))
        status, stdout, stderr = self.invoke(*args)
        self.assertEqual(status, 0, stderr)
        self.assertEqual(self.call.call_count, 6)
        self.assertEqual(json.loads(stdout)["search_requests"], 6)

    def test_duplicate_query_is_not_charged_twice(self):
        self.call.return_value = response([])
        status, stdout, stderr = self.invoke("--query", "same", "--query", "same")
        self.assertEqual(status, 0, stderr)
        self.assertEqual(self.call.call_count, 1)
        self.assertEqual(json.loads(stdout)["search_requests"], 1)


if __name__ == "__main__":
    unittest.main()
