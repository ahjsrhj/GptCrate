import json
import os
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from io import StringIO
from unittest import mock

from gpt_register import cli
from gpt_register import context as ctx


class FakeThread:
    instances = []

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self.target = target
        self.args = args
        self.kwargs = kwargs or {}
        self.daemon = daemon
        self.started = False
        FakeThread.instances.append(self)

    def start(self):
        self.started = True

    def join(self, timeout=None):
        return None

    def is_alive(self):
        return False


class GptMainTests(unittest.TestCase):
    def setUp(self):
        FakeThread.instances = []
        self._original_globals = {
            "EMAIL_MODE": ctx.EMAIL_MODE,
            "ACCOUNTS_FILE": ctx.ACCOUNTS_FILE,
            "BATCH_COUNT": ctx.BATCH_COUNT,
            "BATCH_THREADS": ctx.BATCH_THREADS,
            "LUCKMAIL_AUTO_BUY": ctx.LUCKMAIL_AUTO_BUY,
            "LUCKMAIL_PURCHASED_ONLY": ctx.LUCKMAIL_PURCHASED_ONLY,
            "LUCKMAIL_OWN_ONLY": ctx.LUCKMAIL_OWN_ONLY,
            "LOCAL_OUTLOOK_MAIL_MODE": ctx.LOCAL_OUTLOOK_MAIL_MODE,
            "LOCAL_OUTLOOK_BAD_FILE": ctx.LOCAL_OUTLOOK_BAD_FILE,
            "LUCKMAIL_CHECK_WORKERS": ctx.LUCKMAIL_CHECK_WORKERS,
            "LUCKMAIL_MAX_RETRY": ctx.LUCKMAIL_MAX_RETRY,
            "RESIN_URL": ctx.RESIN_URL,
            "RESIN_PLATFORM_NAME": ctx.RESIN_PLATFORM_NAME,
            "_email_queue": ctx._email_queue,
            "_active_email_queue": ctx._active_email_queue,
            "_luckmail_own_only": ctx._luckmail_own_only,
            "_success_counter": ctx._success_counter,
        }
        ctx.BATCH_COUNT = ""
        ctx.BATCH_THREADS = ""
        ctx.RESIN_URL = ""
        ctx.RESIN_PLATFORM_NAME = ""

    def tearDown(self):
        for key, value in self._original_globals.items():
            setattr(ctx, key, value)

    def test_main_applies_cli_overrides_and_starts_stats_thread_once(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            accounts_file = os.path.join(temp_dir, "accounts.txt")
            with open(accounts_file, "w", encoding="utf-8") as handle:
                handle.write("user@example.com\n")

            argv = [
                "gpt.py",
                "--email-mode",
                "file",
                "--accounts-file",
                accounts_file,
                "--count",
                "1",
                "--luckmail-max-retry",
                "7",
            ]

            with ExitStack() as stack:
                worker_mock = stack.enter_context(mock.patch.object(cli, "_worker"))
                stack.enter_context(mock.patch.object(ctx, "_load_proxies", return_value=[]))
                stack.enter_context(mock.patch.object(cli.threading, "Thread", FakeThread))
                stack.enter_context(mock.patch.object(sys, "argv", argv))
                with redirect_stdout(StringIO()):
                    cli.main()

            self.assertEqual(ctx.ACCOUNTS_FILE, accounts_file)
            self.assertEqual(ctx.LUCKMAIL_MAX_RETRY, 7)
            self.assertEqual(len(ctx._email_queue), 1)
            self.assertEqual(len(FakeThread.instances), 1)
            worker_mock.assert_called_once()

    def test_main_uses_once_flag_as_single_batch_run(self):
        ctx.EMAIL_MODE = "cf"
        ctx.LUCKMAIL_AUTO_BUY = False
        argv = ["gpt.py", "--once"]

        with ExitStack() as stack:
            worker_mock = stack.enter_context(mock.patch.object(cli, "_worker"))
            stack.enter_context(mock.patch.object(ctx, "_load_proxies", return_value=[]))
            stack.enter_context(mock.patch.object(cli.threading, "Thread", FakeThread))
            stack.enter_context(mock.patch.object(cli.time, "sleep", return_value=None))
            stack.enter_context(mock.patch.object(sys, "argv", argv))
            with redirect_stdout(StringIO()):
                cli.main()

        self.assertEqual(len(FakeThread.instances), 1)
        worker_mock.assert_called_once()
        self.assertEqual(worker_mock.call_args.kwargs["count_target"], 1)
        self.assertEqual(worker_mock.call_args.kwargs["remaining"], [1])

    def test_main_ignores_proxy_file_when_resin_enabled(self):
        ctx.EMAIL_MODE = "cf"
        ctx.LUCKMAIL_AUTO_BUY = False
        ctx.RESIN_URL = "http://127.0.0.1:2260/my-token"
        ctx.RESIN_PLATFORM_NAME = "reg"
        argv = ["gpt.py", "--once", "--proxy-file", "ignored.txt"]

        with ExitStack() as stack:
            worker_mock = stack.enter_context(mock.patch.object(cli, "_worker"))
            load_proxies_mock = stack.enter_context(mock.patch.object(ctx, "_load_proxies", return_value=["http://proxy.example:8080"]))
            stack.enter_context(mock.patch.object(cli.threading, "Thread", FakeThread))
            stack.enter_context(mock.patch.object(cli.time, "sleep", return_value=None))
            stack.enter_context(mock.patch.object(sys, "argv", argv))
            with redirect_stdout(StringIO()):
                cli.main()

        load_proxies_mock.assert_not_called()
        worker_mock.assert_called_once()

    def test_main_uses_env_batch_threads_when_cli_keeps_default_thread_count(self):
        ctx.EMAIL_MODE = "cf"
        ctx.LUCKMAIL_AUTO_BUY = False
        original_batch_threads = ctx.BATCH_THREADS
        ctx.BATCH_THREADS = "4"
        argv = ["gpt.py", "--count", "3"]

        try:
            with ExitStack() as stack:
                worker_mock = stack.enter_context(mock.patch.object(cli, "_worker"))
                stack.enter_context(mock.patch.object(ctx, "_load_proxies", return_value=[]))
                stack.enter_context(mock.patch.object(cli.threading, "Thread", FakeThread))
                stack.enter_context(mock.patch.object(cli.time, "sleep", return_value=None))
                stack.enter_context(mock.patch.object(sys, "argv", argv))
                with redirect_stdout(StringIO()):
                    cli.main()
        finally:
            ctx.BATCH_THREADS = original_batch_threads

        self.assertEqual(worker_mock.call_count, 0)
        self.assertEqual(len(FakeThread.instances), 4)
        worker_threads = [thread for thread in FakeThread.instances if thread.target is worker_mock]
        self.assertEqual(len(worker_threads), 3)
        self.assertTrue(all(thread.started for thread in worker_threads))

    def test_main_stops_early_when_purchased_only_finds_no_active_hotmail(self):
        ctx.EMAIL_MODE = "luckmail"
        ctx.LUCKMAIL_AUTO_BUY = True
        original_purchased_only = ctx.LUCKMAIL_PURCHASED_ONLY
        original_check_workers = ctx.LUCKMAIL_CHECK_WORKERS
        ctx.LUCKMAIL_PURCHASED_ONLY = True
        ctx.LUCKMAIL_CHECK_WORKERS = 8
        argv = ["gpt.py"]

        try:
            with ExitStack() as stack:
                worker_mock = stack.enter_context(mock.patch.object(cli, "_worker"))
                prefetch_mock = stack.enter_context(mock.patch.object(cli.mail, "_prefetch_active_emails"))
                stack.enter_context(mock.patch.object(ctx, "_load_proxies", return_value=[]))
                stack.enter_context(mock.patch.object(cli.threading, "Thread", FakeThread))
                stack.enter_context(mock.patch.object(sys, "argv", argv))
                with redirect_stdout(StringIO()):
                    cli.main()
        finally:
            ctx.LUCKMAIL_PURCHASED_ONLY = original_purchased_only
            ctx.LUCKMAIL_CHECK_WORKERS = original_check_workers

        worker_mock.assert_not_called()
        self.assertEqual(len(FakeThread.instances), 1)
        self.assertIs(FakeThread.instances[0].target, prefetch_mock)
        self.assertEqual(FakeThread.instances[0].args[1:], (10, 20))

    def test_main_local_outlook_auto_sets_batch_count_from_accounts_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            accounts_file = os.path.join(temp_dir, "accounts.txt")
            with open(accounts_file, "w", encoding="utf-8") as handle:
                handle.write("user1@example.com----pass----client1----refresh1\n")
                handle.write("user2@example.com----pass----client2----refresh2\n")

            argv = [
                "gpt.py",
                "--email-mode",
                "local_outlook",
                "--accounts-file",
                accounts_file,
            ]

            with ExitStack() as stack:
                worker_mock = stack.enter_context(mock.patch.object(cli, "_worker"))
                stack.enter_context(mock.patch.object(ctx, "_load_proxies", return_value=[]))
                stack.enter_context(mock.patch.object(cli.threading, "Thread", FakeThread))
                stack.enter_context(mock.patch.object(cli.time, "sleep", return_value=None))
                stack.enter_context(mock.patch.object(sys, "argv", argv))
                with redirect_stdout(StringIO()):
                    cli.main()

            self.assertEqual(len(FakeThread.instances), 1)
            worker_mock.assert_called_once()
            self.assertEqual(worker_mock.call_args.kwargs["count_target"], 2)

    def test_compact_stats_output_no_longer_contains_terminal_escape_sequences(self):
        stats = ctx.RegistrationStats()
        stats.add_attempt()
        stats.add_failure("other_error")

        compact = stats.format_compact()

        self.assertNotIn("\033", compact)
        self.assertIn("状态 |", compact)

    def test_save_result_writes_cpa_and_sub_formats(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            token_json = (
                '{"access_token":"access-token","refresh_token":"refresh-token",'
                '"account_id":"acc-001","email":"user@example.com","type":"codex",'
                '"expired":"2026-04-18T04:30:34Z"}'
            )
            original_output_dir = ctx.TOKEN_OUTPUT_DIR
            original_proxy_auths_dir = ctx.CLI_PROXY_AUTHS_DIR

            try:
                ctx.TOKEN_OUTPUT_DIR = temp_dir
                ctx.CLI_PROXY_AUTHS_DIR = ""
                with mock.patch.object(cli.time, "time", return_value=1775622635), \
                     mock.patch.object(cli.mail, "delete_temp_email") as delete_mock, \
                     mock.patch.object(
                         cli.codex2api,
                         "upload_account",
                         return_value={"attempted": True, "ok": True, "message": "成功添加 1 个账号"},
                     ) as upload_mock:
                    cli._save_result(token_json, "secret-pass", None)

                cpa_path = os.path.join(temp_dir, "token_user_example.com_1775622635.json")
                sub_path = os.path.join(temp_dir, "sub_user_example.com_1775622635.json")
                accounts_path = os.path.join(temp_dir, "accounts.txt")

                self.assertTrue(os.path.exists(cpa_path))
                self.assertTrue(os.path.exists(sub_path))
                self.assertTrue(os.path.exists(accounts_path))

                with open(sub_path, "r", encoding="utf-8") as handle:
                    sub_data = json.load(handle)

                self.assertEqual(len(sub_data["accounts"]), 1)
                self.assertEqual(sub_data["accounts"][0]["name"], "user@example.com")
                self.assertEqual(sub_data["accounts"][0]["extra"]["email"], "user@example.com")
                self.assertEqual(
                    sub_data["accounts"][0]["credentials"]["chatgpt_account_id"],
                    "acc-001",
                )
                upload_mock.assert_called_once_with(
                    {
                        "access_token": "access-token",
                        "refresh_token": "refresh-token",
                        "account_id": "acc-001",
                        "email": "user@example.com",
                        "type": "codex",
                        "expired": "2026-04-18T04:30:34Z",
                    },
                    None,
                )
                delete_mock.assert_called_once_with("user@example.com", proxies=None)
            finally:
                ctx.TOKEN_OUTPUT_DIR = original_output_dir
                ctx.CLI_PROXY_AUTHS_DIR = original_proxy_auths_dir

    def test_save_result_writes_hotmail007_emails_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            token_json = (
                '{"access_token":"access-token","refresh_token":"refresh-token",'
                '"account_id":"acc-001","email":"user@example.com","type":"codex",'
                '"expired":"2026-04-18T04:30:34Z"}'
            )
            original_output_dir = ctx.TOKEN_OUTPUT_DIR
            original_proxy_auths_dir = ctx.CLI_PROXY_AUTHS_DIR
            original_email_mode = ctx.EMAIL_MODE
            original_hotmail007_credentials = dict(ctx._hotmail007_credentials)

            try:
                ctx.TOKEN_OUTPUT_DIR = temp_dir
                ctx.CLI_PROXY_AUTHS_DIR = ""
                ctx.EMAIL_MODE = "hotmail007"
                ctx._hotmail007_credentials.clear()
                ctx._hotmail007_credentials["user@example.com"] = {
                    "ms_password": "mail-secret",
                    "client_id": "client-id",
                    "refresh_token": "refresh-token-2",
                }
                with mock.patch.object(cli.time, "time", return_value=1775622635), \
                     mock.patch.object(cli.mail, "delete_temp_email") as delete_mock, \
                     mock.patch.object(
                         cli.codex2api,
                         "upload_account",
                         return_value={"attempted": True, "ok": True, "message": "成功添加 1 个账号"},
                     ):
                    cli._save_result(token_json, "secret-pass", None)

                emails_path = os.path.join(temp_dir, "emails.txt")
                with open(emails_path, "r", encoding="utf-8") as handle:
                    self.assertEqual(
                        handle.read(),
                        "user@example.com----mail-secret----client-id----refresh-token-2\n",
                    )
                delete_mock.assert_called_once_with("user@example.com", proxies=None)
            finally:
                ctx.TOKEN_OUTPUT_DIR = original_output_dir
                ctx.CLI_PROXY_AUTHS_DIR = original_proxy_auths_dir
                ctx.EMAIL_MODE = original_email_mode
                ctx._hotmail007_credentials.clear()
                ctx._hotmail007_credentials.update(original_hotmail007_credentials)

    def test_save_result_does_not_write_emails_file_for_non_hotmail007(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            token_json = (
                '{"access_token":"access-token","refresh_token":"refresh-token",'
                '"account_id":"acc-001","email":"user@example.com","type":"codex",'
                '"expired":"2026-04-18T04:30:34Z"}'
            )
            original_output_dir = ctx.TOKEN_OUTPUT_DIR
            original_proxy_auths_dir = ctx.CLI_PROXY_AUTHS_DIR
            original_email_mode = ctx.EMAIL_MODE

            try:
                ctx.TOKEN_OUTPUT_DIR = temp_dir
                ctx.CLI_PROXY_AUTHS_DIR = ""
                ctx.EMAIL_MODE = "cf"
                with mock.patch.object(cli.time, "time", return_value=1775622635), \
                     mock.patch.object(cli.mail, "delete_temp_email"), \
                     mock.patch.object(
                         cli.codex2api,
                         "upload_account",
                         return_value={"attempted": True, "ok": True, "message": "成功添加 1 个账号"},
                     ):
                    cli._save_result(token_json, "secret-pass", None)

                self.assertFalse(os.path.exists(os.path.join(temp_dir, "emails.txt")))
            finally:
                ctx.TOKEN_OUTPUT_DIR = original_output_dir
                ctx.CLI_PROXY_AUTHS_DIR = original_proxy_auths_dir
                ctx.EMAIL_MODE = original_email_mode

    def test_save_result_skips_hotmail007_emails_file_when_credentials_incomplete(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            token_json = (
                '{"access_token":"access-token","refresh_token":"refresh-token",'
                '"account_id":"acc-001","email":"user@example.com","type":"codex",'
                '"expired":"2026-04-18T04:30:34Z"}'
            )
            original_output_dir = ctx.TOKEN_OUTPUT_DIR
            original_proxy_auths_dir = ctx.CLI_PROXY_AUTHS_DIR
            original_email_mode = ctx.EMAIL_MODE
            original_hotmail007_credentials = dict(ctx._hotmail007_credentials)

            try:
                ctx.TOKEN_OUTPUT_DIR = temp_dir
                ctx.CLI_PROXY_AUTHS_DIR = ""
                ctx.EMAIL_MODE = "hotmail007"
                ctx._hotmail007_credentials.clear()
                ctx._hotmail007_credentials["user@example.com"] = {
                    "ms_password": "mail-secret",
                    "client_id": "",
                    "refresh_token": "refresh-token-2",
                }
                with mock.patch.object(cli.time, "time", return_value=1775622635), \
                     mock.patch.object(cli.mail, "delete_temp_email"), \
                     mock.patch.object(
                         cli.codex2api,
                         "upload_account",
                         return_value={"attempted": True, "ok": True, "message": "成功添加 1 个账号"},
                     ), \
                     mock.patch.object(cli, "_safe_print") as print_mock:
                    cli._save_result(token_json, "secret-pass", None)

                self.assertFalse(os.path.exists(os.path.join(temp_dir, "emails.txt")))
                print_mock.assert_any_call("[Warning] Hotmail007 邮箱凭据不完整，跳过写入 emails.txt: user@example.com")
            finally:
                ctx.TOKEN_OUTPUT_DIR = original_output_dir
                ctx.CLI_PROXY_AUTHS_DIR = original_proxy_auths_dir
                ctx.EMAIL_MODE = original_email_mode
                ctx._hotmail007_credentials.clear()
                ctx._hotmail007_credentials.update(original_hotmail007_credentials)

    def test_save_result_keeps_local_files_when_codex2api_upload_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            token_json = (
                '{"access_token":"access-token","refresh_token":"refresh-token",'
                '"account_id":"acc-001","email":"user@example.com","type":"codex",'
                '"expired":"2026-04-18T04:30:34Z"}'
            )
            original_output_dir = ctx.TOKEN_OUTPUT_DIR
            original_proxy_auths_dir = ctx.CLI_PROXY_AUTHS_DIR

            try:
                ctx.TOKEN_OUTPUT_DIR = temp_dir
                ctx.CLI_PROXY_AUTHS_DIR = ""
                with mock.patch.object(cli.time, "time", return_value=1775622635), \
                     mock.patch.object(cli.mail, "delete_temp_email") as delete_mock, \
                     mock.patch.object(
                         cli.codex2api,
                         "upload_account",
                         return_value={"attempted": True, "ok": False, "reason": "HTTP 500"},
                     ) as upload_mock:
                    cli._save_result(token_json, "secret-pass", "http://127.0.0.1:8080")

                self.assertTrue(os.path.exists(os.path.join(temp_dir, "token_user_example.com_1775622635.json")))
                self.assertTrue(os.path.exists(os.path.join(temp_dir, "sub_user_example.com_1775622635.json")))
                self.assertTrue(os.path.exists(os.path.join(temp_dir, "accounts.txt")))
                upload_mock.assert_called_once()
                delete_mock.assert_called_once_with(
                    "user@example.com",
                    proxies={"http": "http://127.0.0.1:8080", "https": "http://127.0.0.1:8080"},
                )
            finally:
                ctx.TOKEN_OUTPUT_DIR = original_output_dir
                ctx.CLI_PROXY_AUTHS_DIR = original_proxy_auths_dir


if __name__ == "__main__":
    unittest.main()
