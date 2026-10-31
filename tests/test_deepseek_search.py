"""Offline behavior tests for the DeepSeek Search/Fetch client."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
from urllib.error import HTTPError, URLError
from urllib.request import Request


SCRIPT = Path(__file__).resolve().parents[1] / "deepseek-web-search/scripts/deepseek_search.py"
spec = importlib.util.spec_from_file_location("deepseek_search", SCRIPT)
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        self.env = mock.patch.dict(os.environ, {"HOME": self.home.name, "DEEPSEEK_API_KEY": "test-only-key"}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.opener = mock.Mock()
        self.make_opener = mock.patch.object(client, "build_opener", return_value=self.opener)
        self.make_opener.start()
        self.addCleanup(self.make_opener.stop)

    def invoke(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "argv", ["deepseek_search.py", *args]), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                status = client.main()
            except SystemExit as error:
                status = error.code
        return status, stdout.getvalue(), stderr.getvalue()

    def respond(self, value):
        self.opener.open.return_value = io.BytesIO(json.dumps(value).encode())

    def test_search_sends_query_and_preserves_raw_response(self):
        result = {"results": [{"title": "A", "url": "https://example.org/a", "extra": 7}]}
        self.respond(result)
        status, stdout, stderr = self.invoke("search", "加密", "--count", "3", "--need-content", "--original-question", "用户问题")
        self.assertEqual(status, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(json.loads(stdout), result)
        request = self.opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.deepseek.com/v1/tools/search")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-only-key")
        self.assertEqual(json.loads(request.data), {"query": "加密", "count": 3, "need_content": True, "ori_question": "用户问题"})

    def test_fetch_sends_url_and_returns_page(self):
        page = {"title": "Example", "content": "# Hello"}
        self.respond(page)
        status, stdout, _ = self.invoke("fetch", "https://example.org/page")
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(stdout), page)
        request = self.opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.deepseek.com/v1/tools/fetch")
        self.assertEqual(json.loads(request.data), {"url": "https://example.org/page"})

    def test_empty_result_is_success(self):
        self.respond({"results": []})
        status, stdout, stderr = self.invoke("search", "unlikely term")
        self.assertEqual((status, json.loads(stdout), stderr), (0, {"results": []}, ""))

    def test_search_argument_validation_does_not_call_api(self):
        for args in (("search", "   "), ("search", "x" * 129), ("search", "x", "--count", "0"), ("search", "x", "--count", "51")):
            with self.subTest(args=args):
                self.assertNotEqual(self.invoke(*args)[0], 0)
        self.opener.open.assert_not_called()

    def test_compact_result_limits_content_and_omits_heavy_fields(self):
        self.respond({"results": [{"title": "A", "url": "https://example.org", "snippet": "s", "date": None,
                                    "summary": "lengthy", "content": "a" * 2100, "authority": 4}]})
        status, stdout, _ = self.invoke("search", "example", "--need-content", "--compact")
        self.assertEqual(status, 0)
        result = json.loads(stdout)["results"][0]
        self.assertEqual(result["title"], "A")
        self.assertEqual(result["content"], "a" * 2000)
        self.assertIs(result["content_truncated"], True)
        self.assertNotIn("summary", result)
        self.assertNotIn("authority", result)

    def test_compact_distinguishes_complete_or_missing_content(self):
        self.respond({"results": [{"title": "A", "content": "abc"}, {"title": "B", "content": ""}]})
        status, stdout, _ = self.invoke("search", "example", "--need-content", "--compact")
        self.assertEqual(status, 0)
        first, second = json.loads(stdout)["results"]
        self.assertEqual(first["content"], "abc")
        self.assertIs(first["content_truncated"], False)
        self.assertNotIn("content", second)
        self.assertNotIn("content_truncated", second)

    def test_http_errors_are_actionable_and_do_not_leak_key(self):
        hints = {401: ("key", "密钥", "鉴权"), 402: ("balance", "余额", "充值"),
                 429: ("rate", "limit", "限", "稍后"), 403: ("access", "policy", "拒绝", "策略"),
                 404: ("page", "content", "页面", "网页", "内容")}
        for code, words in hints.items():
            with self.subTest(code=code):
                error = HTTPError("https://api.deepseek.com", code, "error", {}, None)
                self.addCleanup(error.close)
                self.opener.open.side_effect = error
                status, stdout, stderr = self.invoke("fetch", "https://example.org")
                self.assertNotEqual(status, 0)
                self.assertEqual(stdout, "")
                self.assertIn(str(code), stderr)
                self.assertTrue(any(word in stderr.lower() for word in words), stderr)
                self.assertNotIn("test-only-key", stderr)

    def test_network_error_is_reported_without_sensitive_details(self):
        self.opener.open.side_effect = URLError("network failed")
        status, _, stderr = self.invoke("search", "example")
        self.assertNotEqual(status, 0)
        self.assertTrue(stderr)
        self.assertNotIn("test-only-key", stderr)

    def test_no_api_key_reports_configuration_without_calling_network(self):
        os.environ.pop("DEEPSEEK_API_KEY")
        status, stdout, stderr = self.invoke("search", "example")
        self.assertNotEqual(status, 0)
        self.assertFalse(stdout)
        self.assertIn("DEEPSEEK_API_KEY", stderr)
        self.opener.open.assert_not_called()


class RedirectTests(unittest.TestCase):
    def test_rejects_redirect_to_other_host_without_forwarding_authorization(self):
        handler = client.NoRedirectHandler()
        request = Request("https://api.deepseek.com/v1/tools/search", data=b"{}", headers={"Authorization": "Bearer test-only-key"})
        redirected = handler.redirect_request(request, None, 302, "Found", {}, "https://other.example/")
        self.assertIsNone(redirected)


if __name__ == "__main__":
    unittest.main()
