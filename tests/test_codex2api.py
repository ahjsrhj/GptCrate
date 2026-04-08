import importlib
import os
import tempfile
import unittest
from contextlib import contextmanager
from unittest import mock

from gpt_register import codex2api
from gpt_register import context as ctx


@contextmanager
def chdir(path: str):
    previous = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


class Codex2ApiTests(unittest.TestCase):
    def setUp(self):
        self._orig_base_url = ctx.CODEX2API_BASE_URL
        self._orig_admin_secret = ctx.CODEX2API_ADMIN_SECRET

    def tearDown(self):
        ctx.CODEX2API_BASE_URL = self._orig_base_url
        ctx.CODEX2API_ADMIN_SECRET = self._orig_admin_secret

    def test_upload_account_posts_refresh_token(self):
        ctx.CODEX2API_BASE_URL = "https://codex2api.example.com/"
        ctx.CODEX2API_ADMIN_SECRET = "secret"

        response = mock.Mock(status_code=200, text='{"message":"成功添加 1 个账号"}')
        response.json.return_value = {"message": "成功添加 1 个账号"}

        with mock.patch.object(codex2api.requests, "post", return_value=response) as post_mock:
            result = codex2api.upload_account(
                {"email": "user@example.com", "refresh_token": "rt-123"},
                "http://proxy.example.com:8080",
            )

        self.assertEqual(
            post_mock.call_args.args[0],
            "https://codex2api.example.com/api/admin/accounts",
        )
        self.assertEqual(post_mock.call_args.kwargs["headers"]["X-Admin-Key"], "secret")
        self.assertEqual(
            post_mock.call_args.kwargs["json"],
            {
                "name": "user@example.com",
                "refresh_token": "rt-123",
                "proxy_url": "http://proxy.example.com:8080",
            },
        )
        self.assertNotIn("proxies", post_mock.call_args.kwargs)
        self.assertTrue(result["attempted"])
        self.assertTrue(result["ok"])

    def test_upload_account_skips_when_missing_config(self):
        ctx.CODEX2API_BASE_URL = ""
        ctx.CODEX2API_ADMIN_SECRET = ""

        with mock.patch.object(codex2api.requests, "post") as post_mock:
            result = codex2api.upload_account(
                {"email": "user@example.com", "refresh_token": "rt-123"},
                None,
            )

        post_mock.assert_not_called()
        self.assertFalse(result["attempted"])
        self.assertEqual(result["reason"], "disabled")

    def test_upload_account_skips_when_missing_refresh_token(self):
        ctx.CODEX2API_BASE_URL = "https://codex2api.example.com"
        ctx.CODEX2API_ADMIN_SECRET = "secret"

        with mock.patch.object(codex2api.requests, "post") as post_mock:
            result = codex2api.upload_account({"email": "user@example.com"}, None)

        post_mock.assert_not_called()
        self.assertFalse(result["attempted"])
        self.assertEqual(result["reason"], "missing_refresh_token")


class ContextEnvTests(unittest.TestCase):
    def test_context_loads_codex2api_settings_from_env_file(self):
        with tempfile.TemporaryDirectory() as temp_dir, chdir(temp_dir):
            with open(".env", "w", encoding="utf-8") as handle:
                handle.write("CODEX2API_BASE_URL=https://codex2api.example.com/\n")
                handle.write("CODEX2API_ADMIN_SECRET=secret-admin-key\n")

            with mock.patch.dict(os.environ, {}, clear=True):
                reloaded_ctx = importlib.reload(ctx)
                self.assertEqual(reloaded_ctx.CODEX2API_BASE_URL, "https://codex2api.example.com")
                self.assertEqual(reloaded_ctx.CODEX2API_ADMIN_SECRET, "secret-admin-key")

        importlib.reload(ctx)
