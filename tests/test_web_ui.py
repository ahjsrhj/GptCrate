import tempfile
import unittest
from pathlib import Path

from gpt_register import web_ui


class WebUiTests(unittest.TestCase):
    def test_normalize_base_url_adds_scheme(self):
        self.assertEqual(web_ui._normalize_base_url("127.0.0.1:8080/api"), "http://127.0.0.1:8080/api/v0/management")
        self.assertEqual(web_ui._normalize_base_url("https://example.com/"), "https://example.com/v0/management")
        self.assertEqual(
            web_ui._normalize_base_url("http://localhost:8317/management.html"),
            "http://localhost:8317/v0/management",
        )
        self.assertEqual(
            web_ui._normalize_base_url("http://localhost:8317/management"),
            "http://localhost:8317/v0/management",
        )
        self.assertEqual(
            web_ui._normalize_base_url("http://localhost:8317/v0/management"),
            "http://localhost:8317/v0/management",
        )

    def test_extract_auth_files_supports_multiple_shapes(self):
        payload = {"data": [{"name": "acc-1", "email": "a@example.com"}]}
        items = web_ui._extract_auth_files(payload)
        self.assertEqual(items[0]["name"], "acc-1")
        self.assertEqual(items[0]["email"], "a@example.com")

        payload2 = {"results": ["acc-2"]}
        items2 = web_ui._extract_auth_files(payload2)
        self.assertEqual(items2[0]["name"], "acc-2")

    def test_accounts_helpers_read_from_project_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_accounts = web_ui.ACCOUNTS_PATH
            try:
                web_ui.ACCOUNTS_PATH = Path(temp_dir) / "accounts.txt"
                web_ui.ACCOUNTS_PATH.write_text("a\nb\nc\n", encoding="utf-8")
                self.assertEqual(web_ui._accounts_count(), 3)
                self.assertEqual(web_ui._accounts_preview(), ["a", "b", "c"])
            finally:
                web_ui.ACCOUNTS_PATH = original_accounts

    def test_ui_state_defaults_and_can_switch(self):
        original = dict(web_ui.UI_STATE)
        try:
            web_ui.UI_STATE["selected_mode"] = "luckmail"
            self.assertEqual(web_ui.UI_STATE["selected_mode"], "luckmail")
            web_ui.UI_STATE["selected_mode"] = "cf"
            self.assertEqual(web_ui.UI_STATE["selected_mode"], "cf")
        finally:
            web_ui.UI_STATE.clear()
            web_ui.UI_STATE.update(original)


if __name__ == "__main__":
    unittest.main()
