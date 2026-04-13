import os
import inspect
import tempfile
import unittest
from unittest import mock

from gpt_register import cli
from gpt_register import context as ctx
from gpt_register import hotmail
from gpt_register import mail
from gpt_register import luckmail

_MISSING = object()


class MailProviderTests(unittest.TestCase):
    def setUp(self):
        self._original = {
            "EMAIL_MODE": ctx.EMAIL_MODE,
            "MAIL_DOMAIN": ctx.MAIL_DOMAIN,
            "ACCOUNTS_FILE": ctx.ACCOUNTS_FILE,
            "LUCKMAIL_AUTO_BUY": ctx.LUCKMAIL_AUTO_BUY,
            "LUCKMAIL_OWN_ONLY": ctx.LUCKMAIL_OWN_ONLY,
            "LOCAL_OUTLOOK_MAIL_MODE": ctx.LOCAL_OUTLOOK_MAIL_MODE,
            "LOCAL_OUTLOOK_BAD_FILE": ctx.LOCAL_OUTLOOK_BAD_FILE,
            "LUCKMAIL_API_KEY": ctx.LUCKMAIL_API_KEY,
            "HOTMAIL007_API_KEY": ctx.HOTMAIL007_API_KEY,
            "OUTLOOK_PROXY": ctx.OUTLOOK_PROXY,
            "HOTMAIL007_ALIAS_SPLIT_ENABLED": ctx.HOTMAIL007_ALIAS_SPLIT_ENABLED,
            "HOTMAIL007_MAX_RETRY": ctx.HOTMAIL007_MAX_RETRY,
            "BATCH_COUNT": ctx.BATCH_COUNT,
            "HOTMAIL007_QUEUE_FILE": getattr(ctx, "HOTMAIL007_QUEUE_FILE", _MISSING),
            "_email_queue": ctx._email_queue,
            "_active_email_queue": ctx._active_email_queue,
            "_hotmail007_queue": ctx._hotmail007_queue,
            "_luckmail_purchased_only": ctx._luckmail_purchased_only,
            "_luckmail_own_only": ctx._luckmail_own_only,
            "_hotmail007_credentials": dict(ctx._hotmail007_credentials),
            "_luckmail_credentials": dict(ctx._luckmail_credentials),
        }
        ctx._hotmail007_credentials.clear()
        ctx._luckmail_credentials.clear()
        ctx.HOTMAIL007_ALIAS_SPLIT_ENABLED = False
        ctx._hotmail007_queue = None
        ctx.BATCH_COUNT = ""
        self._isolated_hotmail007_queue_file = os.path.join(
            tempfile.gettempdir(),
            f"hotmail007-test-{id(self)}.txt",
        )
        if os.path.exists(self._isolated_hotmail007_queue_file):
            os.remove(self._isolated_hotmail007_queue_file)
        setattr(ctx, "HOTMAIL007_QUEUE_FILE", self._isolated_hotmail007_queue_file)
        self._isolated_accounts_file = os.path.join(
            tempfile.gettempdir(),
            f"accounts-test-{id(self)}.txt",
        )
        if os.path.exists(self._isolated_accounts_file):
            os.remove(self._isolated_accounts_file)
        ctx.ACCOUNTS_FILE = self._isolated_accounts_file

    def tearDown(self):
        ctx.EMAIL_MODE = self._original["EMAIL_MODE"]
        ctx.MAIL_DOMAIN = self._original["MAIL_DOMAIN"]
        ctx.ACCOUNTS_FILE = self._original["ACCOUNTS_FILE"]
        ctx.LUCKMAIL_AUTO_BUY = self._original["LUCKMAIL_AUTO_BUY"]
        ctx.LUCKMAIL_OWN_ONLY = self._original["LUCKMAIL_OWN_ONLY"]
        ctx.LOCAL_OUTLOOK_MAIL_MODE = self._original["LOCAL_OUTLOOK_MAIL_MODE"]
        ctx.LOCAL_OUTLOOK_BAD_FILE = self._original["LOCAL_OUTLOOK_BAD_FILE"]
        ctx.LUCKMAIL_API_KEY = self._original["LUCKMAIL_API_KEY"]
        ctx.HOTMAIL007_API_KEY = self._original["HOTMAIL007_API_KEY"]
        ctx.OUTLOOK_PROXY = self._original["OUTLOOK_PROXY"]
        ctx.HOTMAIL007_ALIAS_SPLIT_ENABLED = self._original["HOTMAIL007_ALIAS_SPLIT_ENABLED"]
        ctx.HOTMAIL007_MAX_RETRY = self._original["HOTMAIL007_MAX_RETRY"]
        ctx.BATCH_COUNT = self._original["BATCH_COUNT"]
        if self._original["HOTMAIL007_QUEUE_FILE"] is _MISSING:
            if hasattr(ctx, "HOTMAIL007_QUEUE_FILE"):
                delattr(ctx, "HOTMAIL007_QUEUE_FILE")
        else:
            setattr(ctx, "HOTMAIL007_QUEUE_FILE", self._original["HOTMAIL007_QUEUE_FILE"])
        if os.path.exists(self._isolated_hotmail007_queue_file):
            os.remove(self._isolated_hotmail007_queue_file)
        if os.path.exists(self._isolated_accounts_file):
            os.remove(self._isolated_accounts_file)
        ctx._email_queue = self._original["_email_queue"]
        ctx._active_email_queue = self._original["_active_email_queue"]
        ctx._hotmail007_queue = self._original["_hotmail007_queue"]
        ctx._luckmail_purchased_only = self._original["_luckmail_purchased_only"]
        ctx._luckmail_own_only = self._original["_luckmail_own_only"]
        ctx._hotmail007_credentials.clear()
        ctx._hotmail007_credentials.update(self._original["_hotmail007_credentials"])
        ctx._luckmail_credentials.clear()
        ctx._luckmail_credentials.update(self._original["_luckmail_credentials"])

    def _build_hotmail007_queue_line(
        self,
        alias_email: str,
        primary_email: str = "primary@example.com",
        password: str = "secret",
        client_id: str = "client",
        mail_mode: str = "graph",
        refresh_token: str = "refresh",
    ) -> str:
        return "----".join(
            [
                alias_email,
                primary_email,
                password,
                client_id,
                mail_mode,
                refresh_token,
            ]
        )

    def _read_queue_lines(self, path: str) -> list[str]:
        if not os.path.exists(path):
            return []
        with open(path, "r", encoding="utf-8") as handle:
            return [line.strip() for line in handle if line.strip()]

    def _hotmail007_async_pipeline_ready(self) -> bool:
        prepare_source = inspect.getsource(cli._prepare_hotmail007_queue_stock)
        pop_source = inspect.getsource(hotmail._pop_hotmail007_queue_account)
        return (
            "ensure_hotmail007_queue_capacity(batch_count" not in prepare_source
            and "ensure_hotmail007_queue_capacity(1" not in pop_source
        )

    def test_get_email_and_token_dispatches_to_cloudflare_mode(self):
        ctx.EMAIL_MODE = "cf"
        ctx.MAIL_DOMAIN = "example.com"

        email, token = mail.get_email_and_token()

        self.assertEqual(email, token)
        self.assertTrue(email.endswith("@example.com"))

    def test_get_email_and_token_dispatches_to_hotmail007_mode(self):
        ctx.EMAIL_MODE = "hotmail007"
        ctx.HOTMAIL007_API_KEY = "key"
        ctx.HOTMAIL007_MAX_RETRY = 3
        fake_mail = {
            "email": "user@example.com",
            "password": "secret",
            "refresh_token": "refresh",
            "client_id": "client",
        }

        with mock.patch.object(hotmail, "hotmail007_get_mail", return_value=([fake_mail], "")), \
             mock.patch.object(hotmail, "_outlook_get_known_ids", return_value={"known-id"}):
            email, token = mail.get_email_and_token()

        self.assertEqual((email, token), ("user@example.com", "user@example.com"))
        self.assertEqual(ctx._hotmail007_credentials["user@example.com"]["known_ids"], {"known-id"})

    def test_hotmail007_non_alias_purchase_appends_accounts_file(self):
        ctx.EMAIL_MODE = "hotmail007"
        ctx.HOTMAIL007_API_KEY = "key"
        ctx.HOTMAIL007_MAX_RETRY = 3
        ctx.HOTMAIL007_ALIAS_SPLIT_ENABLED = False
        fake_mail = {
            "email": "user@example.com",
            "password": "secret",
            "refresh_token": "refresh",
            "client_id": "client",
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            ctx.ACCOUNTS_FILE = os.path.join(temp_dir, "accounts.txt")

            with mock.patch.object(hotmail, "hotmail007_get_mail", return_value=([fake_mail], "")), \
                 mock.patch.object(hotmail, "_outlook_get_known_ids", return_value={"known-id"}):
                email, token = mail.get_email_and_token()

            self.assertEqual((email, token), ("user@example.com", "user@example.com"))
            with open(ctx.ACCOUNTS_FILE, "r", encoding="utf-8") as handle:
                self.assertEqual(
                    handle.read(),
                    "user@example.com----secret----client----refresh\n",
                )

    def test_hotmail007_alias_split_purchase_does_not_append_accounts_file(self):
        ctx.EMAIL_MODE = "hotmail007"
        ctx.HOTMAIL007_API_KEY = "key"
        ctx.HOTMAIL007_MAX_RETRY = 3
        ctx.HOTMAIL007_ALIAS_SPLIT_ENABLED = True
        fake_mail = {
            "email": "user@example.com",
            "password": "secret",
            "refresh_token": "refresh",
            "client_id": "client",
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            ctx.ACCOUNTS_FILE = os.path.join(temp_dir, "accounts.txt")

            with mock.patch.object(hotmail, "hotmail007_get_mail", return_value=([fake_mail], "")), \
                 mock.patch.object(
                     hotmail,
                     "expand_microsoft_alias_emails",
                     return_value=["user+alias@example.com"],
                 ), \
                 mock.patch.object(hotmail, "_outlook_get_known_ids", return_value={"known-id"}):
                email, token = mail.get_email_and_token()

            self.assertEqual((email, token), ("user+alias@example.com", "user+alias@example.com"))
            self.assertFalse(os.path.exists(ctx.ACCOUNTS_FILE))

    def test_hotmail007_alias_split_reuses_queue_before_buying_next_account(self):
        ctx.EMAIL_MODE = "hotmail007"
        ctx.HOTMAIL007_API_KEY = "key"
        ctx.HOTMAIL007_MAX_RETRY = 3
        ctx.HOTMAIL007_ALIAS_SPLIT_ENABLED = True
        first_mail = {
            "email": "first@example.com",
            "password": "secret-1",
            "refresh_token": "refresh-1",
            "client_id": "client-1",
        }
        second_mail = {
            "email": "second@example.com",
            "password": "secret-2",
            "refresh_token": "refresh-2",
            "client_id": "client-2",
        }
        first_aliases = [
            "first+aaaaaa@example.com",
            "first+bbbbbb@example.com",
            "first+cccccc@example.com",
            "first+dddddd@example.com",
            "first+eeeeee@example.com",
        ]
        second_aliases = [
            "second+fffffg@example.com",
            "second+gggggh@example.com",
            "second+hhhhhi@example.com",
            "second+iiiiij@example.com",
            "second+jjjjjk@example.com",
        ]

        with mock.patch.object(
            hotmail,
            "hotmail007_get_mail",
            side_effect=[([first_mail], ""), ([second_mail], "")],
        ) as get_mail_mock, \
            mock.patch.object(
                hotmail,
                "expand_microsoft_alias_emails",
                side_effect=[first_aliases, second_aliases],
            ), \
            mock.patch.object(
                hotmail,
                "_outlook_get_known_ids",
                side_effect=[set() for _ in range(6)],
            ):
            emails = [mail.get_email_and_token()[0] for _ in range(6)]

        self.assertEqual(set(emails[:5]), set(first_aliases))
        self.assertIn(emails[5], second_aliases)
        self.assertEqual(get_mail_mock.call_count, 2)
        self.assertEqual(len(ctx._hotmail007_queue), 4)

    def test_hotmail007_alias_split_refreshes_known_ids_for_each_dequeued_alias(self):
        ctx.EMAIL_MODE = "hotmail007"
        ctx.HOTMAIL007_API_KEY = "key"
        ctx.HOTMAIL007_MAX_RETRY = 3
        ctx.HOTMAIL007_ALIAS_SPLIT_ENABLED = True
        fake_mail = {
            "email": "primary@example.com",
            "password": "secret",
            "refresh_token": "refresh",
            "client_id": "client",
        }
        aliases = [
            "primary+aaaaaa@example.com",
            "primary+bbbbbb@example.com",
            "primary+cccccc@example.com",
            "primary+dddddd@example.com",
            "primary+eeeeee@example.com",
        ]

        with mock.patch.object(hotmail, "hotmail007_get_mail", return_value=([fake_mail], "")) as get_mail_mock, \
             mock.patch.object(hotmail, "expand_microsoft_alias_emails", return_value=aliases), \
             mock.patch.object(
                 hotmail,
                 "_outlook_get_known_ids",
                 side_effect=[{"old-1"}, {"old-2"}],
             ) as known_ids_mock:
            first_email, _ = mail.get_email_and_token()
            second_email, _ = mail.get_email_and_token()

        self.assertIn(first_email, aliases)
        self.assertIn(second_email, aliases)
        self.assertNotEqual(first_email, second_email)
        self.assertEqual(get_mail_mock.call_count, 1)
        self.assertEqual(known_ids_mock.call_count, 2)
        self.assertEqual(known_ids_mock.call_args_list[0].args[0], "primary@example.com")
        self.assertEqual(known_ids_mock.call_args_list[1].args[0], "primary@example.com")
        self.assertEqual(ctx._hotmail007_credentials[first_email]["known_ids"], {"old-1"})
        self.assertEqual(ctx._hotmail007_credentials[second_email]["known_ids"], {"old-2"})

    def test_hotmail007_alias_split_queue_consumes_persistent_file_in_order(self):
        ctx.EMAIL_MODE = "hotmail007"
        ctx.HOTMAIL007_API_KEY = "key"
        ctx.HOTMAIL007_ALIAS_SPLIT_ENABLED = True

        with tempfile.TemporaryDirectory() as temp_dir:
            queue_file = os.path.join(temp_dir, "hotmail007.txt")
            with open(queue_file, "w", encoding="utf-8") as handle:
                handle.write(
                    "\n".join(
                        [
                            self._build_hotmail007_queue_line("alias-1@example.com"),
                            self._build_hotmail007_queue_line("alias-2@example.com"),
                            self._build_hotmail007_queue_line("alias-3@example.com"),
                        ]
                    )
                    + "\n"
                )
            setattr(ctx, "HOTMAIL007_QUEUE_FILE", queue_file)

            with mock.patch.object(hotmail, "hotmail007_get_mail", side_effect=AssertionError("不应购买新邮箱")), \
                 mock.patch.object(
                     hotmail,
                     "_outlook_get_known_ids",
                     side_effect=[{"id-1"}, {"id-2"}],
                 ):
                first_email, _ = mail.get_email_and_token()
                second_email, _ = mail.get_email_and_token()

            self.assertEqual(first_email, "alias-1@example.com")
            self.assertEqual(second_email, "alias-2@example.com")
            self.assertEqual(self._read_queue_lines(queue_file), [self._build_hotmail007_queue_line("alias-3@example.com")])

    def test_hotmail007_alias_split_queue_recovers_from_file_after_memory_reset(self):
        ctx.EMAIL_MODE = "hotmail007"
        ctx.HOTMAIL007_API_KEY = "key"
        ctx.HOTMAIL007_ALIAS_SPLIT_ENABLED = True

        with tempfile.TemporaryDirectory() as temp_dir:
            queue_file = os.path.join(temp_dir, "hotmail007.txt")
            with open(queue_file, "w", encoding="utf-8") as handle:
                handle.write(
                    "\n".join(
                        [
                            self._build_hotmail007_queue_line("recover-1@example.com"),
                            self._build_hotmail007_queue_line("recover-2@example.com"),
                        ]
                    )
                    + "\n"
                )
            setattr(ctx, "HOTMAIL007_QUEUE_FILE", queue_file)

            with mock.patch.object(hotmail, "hotmail007_get_mail", side_effect=AssertionError("不应购买新邮箱")), \
                 mock.patch.object(
                     hotmail,
                     "_outlook_get_known_ids",
                     side_effect=[{"id-1"}, {"id-2"}],
                 ):
                first_email, _ = mail.get_email_and_token()
                ctx._hotmail007_queue = None
                second_email, _ = mail.get_email_and_token()

            self.assertEqual(first_email, "recover-1@example.com")
            self.assertEqual(second_email, "recover-2@example.com")
            self.assertEqual(self._read_queue_lines(queue_file), [])

    def test_hotmail007_batch_mode_uses_existing_queue_stock_without_buying_when_warm_pool_ready(self):
        ctx.EMAIL_MODE = "hotmail007"
        ctx.HOTMAIL007_API_KEY = "key"
        ctx.HOTMAIL007_ALIAS_SPLIT_ENABLED = True

        with tempfile.TemporaryDirectory() as temp_dir:
            queue_file = os.path.join(temp_dir, "hotmail007.txt")
            with open(queue_file, "w", encoding="utf-8") as handle:
                handle.write(
                    "\n".join(
                        [
                            self._build_hotmail007_queue_line(f"stock-{index}@example.com")
                            for index in range(21)
                        ]
                    )
                    + "\n"
                )
            setattr(ctx, "HOTMAIL007_QUEUE_FILE", queue_file)

            fake_args = mock.Mock(
                proxy=None,
                proxy_file=None,
                once=False,
                count=3,
                threads=1,
                check=False,
                sleep_min=1,
                sleep_max=1,
                email_mode="hotmail007",
                accounts_file=None,
                hotmail007_key="key",
                hotmail007_type=None,
                hotmail007_mail_mode=None,
                local_outlook_mail_mode=None,
                luckmail_key=None,
                luckmail_auto_buy=False,
                luckmail_max_retry=None,
            )
            stats_thread = mock.Mock()
            observed = {}

            def capture_batch_mode(**kwargs):
                observed["batch_count"] = kwargs["batch_count"]
                observed["queue_lines"] = self._read_queue_lines(queue_file)

            with mock.patch.object(hotmail, "hotmail007_get_mail", side_effect=AssertionError("库存足够时不应购买")), \
                 mock.patch.object(cli.argparse.ArgumentParser, "parse_args", return_value=fake_args), \
                 mock.patch.object(cli, "_print_runtime_summary"), \
                 mock.patch.object(cli, "_prepare_output_session"), \
                 mock.patch.object(cli, "_print_status_snapshot"), \
                 mock.patch.object(cli, "_start_luckmail_prefetch", return_value=None), \
                 mock.patch.object(cli, "_start_stats_thread", return_value=stats_thread), \
                 mock.patch.object(cli, "_run_batch_mode", side_effect=capture_batch_mode), \
                 mock.patch.object(cli, "_run_loop_mode"):
                cli.main()

            self.assertEqual(observed["batch_count"], 3)
            self.assertEqual(len(observed["queue_lines"]), 21)
            stats_thread.join.assert_called_once()

    def test_hotmail007_batch_mode_warms_queue_to_twenty_one_before_start(self):
        if not self._hotmail007_async_pipeline_ready():
            self.skipTest("等待核心切换到 Hotmail007 后台购买 + 前台注册模型")
        ctx.EMAIL_MODE = "hotmail007"
        ctx.HOTMAIL007_API_KEY = "key"
        ctx.HOTMAIL007_ALIAS_SPLIT_ENABLED = True

        with tempfile.TemporaryDirectory() as temp_dir:
            queue_file = os.path.join(temp_dir, "hotmail007.txt")
            with open(queue_file, "w", encoding="utf-8") as handle:
                handle.write(
                    "\n".join(
                        [
                            self._build_hotmail007_queue_line("existing-1@example.com"),
                            self._build_hotmail007_queue_line("existing-2@example.com"),
                        ]
                    )
                    + "\n"
                )
            setattr(ctx, "HOTMAIL007_QUEUE_FILE", queue_file)

            fake_args = mock.Mock(
                proxy=None,
                proxy_file=None,
                once=False,
                count=6,
                threads=1,
                check=False,
                sleep_min=1,
                sleep_max=1,
                email_mode="hotmail007",
                accounts_file=None,
                hotmail007_key="key",
                hotmail007_type=None,
                hotmail007_mail_mode=None,
                local_outlook_mail_mode=None,
                luckmail_key=None,
                luckmail_auto_buy=False,
                luckmail_max_retry=None,
            )
            stats_thread = mock.Mock()
            purchased_mail = {
                "email": "primary@example.com",
                "password": "secret",
                "refresh_token": "refresh",
                "client_id": "client",
            }
            aliases = [
                "primary+a@example.com",
                "primary+b@example.com",
                "primary+c@example.com",
                "primary+d@example.com",
                "primary+e@example.com",
            ]
            observed = {}

            def capture_batch_mode(**kwargs):
                observed["batch_count"] = kwargs["batch_count"]
                observed["queue_lines"] = self._read_queue_lines(queue_file)

            with mock.patch.object(hotmail, "hotmail007_get_mail", return_value=([purchased_mail], "")) as get_mail_mock, \
                 mock.patch.object(hotmail, "expand_microsoft_alias_emails", return_value=aliases), \
                 mock.patch.object(cli.argparse.ArgumentParser, "parse_args", return_value=fake_args), \
                 mock.patch.object(cli, "_print_runtime_summary"), \
                 mock.patch.object(cli, "_prepare_output_session"), \
                 mock.patch.object(cli, "_print_status_snapshot"), \
                 mock.patch.object(cli, "_start_luckmail_prefetch", return_value=None), \
                 mock.patch.object(cli, "_start_stats_thread", return_value=stats_thread), \
                 mock.patch.object(cli, "_run_batch_mode", side_effect=capture_batch_mode), \
                 mock.patch.object(cli, "_run_loop_mode"):
                cli.main()

            self.assertEqual(observed["batch_count"], 6)
            self.assertGreaterEqual(len(observed["queue_lines"]), 21)
            self.assertLess(len(observed["queue_lines"]), 26)
            self.assertEqual(get_mail_mock.call_count, 4)
            stats_thread.join.assert_called_once()

    def test_hotmail007_batch_mode_does_not_prefill_all_remaining_registrations_before_start(self):
        if not self._hotmail007_async_pipeline_ready():
            self.skipTest("等待核心切换到 Hotmail007 后台购买 + 前台注册模型")
        ctx.EMAIL_MODE = "hotmail007"
        ctx.HOTMAIL007_API_KEY = "key"
        ctx.HOTMAIL007_ALIAS_SPLIT_ENABLED = True

        with tempfile.TemporaryDirectory() as temp_dir:
            queue_file = os.path.join(temp_dir, "hotmail007.txt")
            setattr(ctx, "HOTMAIL007_QUEUE_FILE", queue_file)

            fake_args = mock.Mock(
                proxy=None,
                proxy_file=None,
                once=False,
                count=50,
                threads=1,
                check=False,
                sleep_min=1,
                sleep_max=1,
                email_mode="hotmail007",
                accounts_file=None,
                hotmail007_key="key",
                hotmail007_type=None,
                hotmail007_mail_mode=None,
                local_outlook_mail_mode=None,
                luckmail_key=None,
                luckmail_auto_buy=False,
                luckmail_max_retry=None,
            )
            stats_thread = mock.Mock()
            purchased_mail = {
                "email": "primary@example.com",
                "password": "secret",
                "refresh_token": "refresh",
                "client_id": "client",
            }
            aliases = [
                "primary+a@example.com",
                "primary+b@example.com",
                "primary+c@example.com",
                "primary+d@example.com",
                "primary+e@example.com",
            ]
            observed = {}

            def capture_batch_mode(**kwargs):
                observed["batch_count"] = kwargs["batch_count"]
                observed["queue_lines"] = self._read_queue_lines(queue_file)

            with mock.patch.object(hotmail, "hotmail007_get_mail", return_value=([purchased_mail], "")) as get_mail_mock, \
                 mock.patch.object(hotmail, "expand_microsoft_alias_emails", return_value=aliases), \
                 mock.patch.object(cli.argparse.ArgumentParser, "parse_args", return_value=fake_args), \
                 mock.patch.object(cli, "_print_runtime_summary"), \
                 mock.patch.object(cli, "_prepare_output_session"), \
                 mock.patch.object(cli, "_print_status_snapshot"), \
                 mock.patch.object(cli, "_start_luckmail_prefetch", return_value=None), \
                 mock.patch.object(cli, "_start_stats_thread", return_value=stats_thread), \
                 mock.patch.object(cli, "_run_batch_mode", side_effect=capture_batch_mode), \
                 mock.patch.object(cli, "_run_loop_mode"):
                cli.main()

            self.assertEqual(observed["batch_count"], 50)
            self.assertGreaterEqual(len(observed["queue_lines"]), 21)
            self.assertLess(len(observed["queue_lines"]), 50)
            self.assertGreaterEqual(get_mail_mock.call_count, 5)
            self.assertLessEqual(get_mail_mock.call_count, 6)
            stats_thread.join.assert_called_once()

    def test_hotmail007_loop_mode_prefills_queue_above_twenty(self):
        ctx.EMAIL_MODE = "hotmail007"
        ctx.HOTMAIL007_API_KEY = "key"
        ctx.HOTMAIL007_ALIAS_SPLIT_ENABLED = True

        with tempfile.TemporaryDirectory() as temp_dir:
            queue_file = os.path.join(temp_dir, "hotmail007.txt")
            with open(queue_file, "w", encoding="utf-8") as handle:
                handle.write(
                    "\n".join(
                        [
                            self._build_hotmail007_queue_line(f"loop-{index}@example.com")
                            for index in range(20)
                        ]
                    )
                    + "\n"
                )
            setattr(ctx, "HOTMAIL007_QUEUE_FILE", queue_file)

            fake_args = mock.Mock(
                proxy=None,
                proxy_file=None,
                once=False,
                count=None,
                threads=1,
                check=False,
                sleep_min=1,
                sleep_max=1,
                email_mode="hotmail007",
                accounts_file=None,
                hotmail007_key="key",
                hotmail007_type=None,
                hotmail007_mail_mode=None,
                local_outlook_mail_mode=None,
                luckmail_key=None,
                luckmail_auto_buy=False,
                luckmail_max_retry=None,
            )
            stats_thread = mock.Mock()
            purchased_mail = {
                "email": "loop-primary@example.com",
                "password": "secret",
                "refresh_token": "refresh",
                "client_id": "client",
            }
            aliases = [
                "loop-primary+a@example.com",
                "loop-primary+b@example.com",
                "loop-primary+c@example.com",
                "loop-primary+d@example.com",
                "loop-primary+e@example.com",
            ]
            observed = {}

            def capture_loop_mode(**kwargs):
                observed["queue_lines"] = self._read_queue_lines(queue_file)

            with mock.patch.object(hotmail, "hotmail007_get_mail", return_value=([purchased_mail], "")) as get_mail_mock, \
                 mock.patch.object(hotmail, "expand_microsoft_alias_emails", return_value=aliases), \
                 mock.patch.object(cli.argparse.ArgumentParser, "parse_args", return_value=fake_args), \
                 mock.patch.object(cli, "_print_runtime_summary"), \
                 mock.patch.object(cli, "_prepare_output_session"), \
                 mock.patch.object(cli, "_print_status_snapshot"), \
                 mock.patch.object(cli, "_start_luckmail_prefetch", return_value=None), \
                 mock.patch.object(cli, "_start_stats_thread", return_value=stats_thread), \
                 mock.patch.object(cli, "_run_batch_mode"), \
                 mock.patch.object(cli, "_run_loop_mode", side_effect=capture_loop_mode):
                cli.main()

            self.assertGreater(len(observed["queue_lines"]), 20)
            self.assertEqual(get_mail_mock.call_count, 1)
            stats_thread.join.assert_called_once()

    def test_hotmail007_without_alias_split_does_not_require_queue_file(self):
        ctx.EMAIL_MODE = "hotmail007"
        ctx.HOTMAIL007_API_KEY = "key"
        ctx.HOTMAIL007_ALIAS_SPLIT_ENABLED = False
        setattr(ctx, "HOTMAIL007_QUEUE_FILE", os.path.join(tempfile.gettempdir(), "missing-hotmail007-queue.txt"))
        fake_mail = {
            "email": "legacy@example.com",
            "password": "secret",
            "refresh_token": "refresh",
            "client_id": "client",
        }

        with mock.patch.object(hotmail, "hotmail007_get_mail", return_value=([fake_mail], "")) as get_mail_mock, \
             mock.patch.object(hotmail, "_outlook_get_known_ids", return_value={"known-id"}):
            email, token = mail.get_email_and_token()

        self.assertEqual((email, token), ("legacy@example.com", "legacy@example.com"))
        self.assertEqual(get_mail_mock.call_count, 1)

    def test_hotmail007_api_get_raises_keyboard_interrupt_on_user_cancel(self):
        error = (
            "Failed to perform, curl: (23) Failure writing output to destination, "
            "passed 13 returned 0. See https://curl.se/libcurl/c/libcurl-errors.html first for more details."
        )

        with mock.patch.object(hotmail.requests, "get", side_effect=Exception(error)):
            with self.assertRaises(KeyboardInterrupt):
                hotmail._hotmail007_api_get("api/mail/getMail")

    def test_hotmail007_user_cancel_error_does_not_retry(self):
        ctx.EMAIL_MODE = "hotmail007"
        ctx.HOTMAIL007_API_KEY = "key"
        ctx.HOTMAIL007_MAX_RETRY = 3
        cancel_error = (
            "Failed to perform, curl: (23) Failure writing output to destination, "
            "passed 13 returned 0. See https://curl.se/libcurl/c/libcurl-errors.html first for more details."
        )

        with mock.patch.object(hotmail, "hotmail007_get_mail", return_value=([], cancel_error)) as get_mail_mock, \
            mock.patch("gpt_register.hotmail.time.sleep") as sleep_mock:
            with self.assertRaises(KeyboardInterrupt):
                mail.get_email_and_token()

        self.assertEqual(get_mail_mock.call_count, 1)
        sleep_mock.assert_not_called()

    def test_hotmail007_retries_three_times_before_success(self):
        ctx.EMAIL_MODE = "hotmail007"
        ctx.HOTMAIL007_API_KEY = "key"
        ctx.HOTMAIL007_MAX_RETRY = 3
        fake_mail = {
            "email": "retry@example.com",
            "password": "secret",
            "refresh_token": "refresh",
            "client_id": "client",
        }

        with mock.patch.object(
            hotmail,
            "hotmail007_get_mail",
            side_effect=[
                ([], "tls error"),
                ([], "tls error"),
                ([fake_mail], ""),
            ],
        ) as get_mail_mock, \
            mock.patch.object(hotmail, "_outlook_get_known_ids", return_value=set()), \
            mock.patch("gpt_register.hotmail.time.sleep") as sleep_mock:
            email, token = mail.get_email_and_token()

        self.assertEqual((email, token), ("retry@example.com", "retry@example.com"))
        self.assertEqual(get_mail_mock.call_count, 3)
        sleep_mock.assert_not_called()

    def test_hotmail007_api_get_prefers_outlook_proxy(self):
        ctx.OUTLOOK_PROXY = "http://mail-proxy:7890"
        response = mock.Mock()
        response.json.return_value = {"success": True, "code": 0, "data": 10}

        with mock.patch.object(hotmail.requests, "get", return_value=response) as get_mock:
            hotmail.hotmail007_get_balance(
                proxies={"http": "http://general-proxy:8080", "https": "http://general-proxy:8080"}
            )

        self.assertEqual(
            get_mock.call_args.kwargs["proxies"],
            {
                "http": "http://mail-proxy:7890",
                "https": "http://mail-proxy:7890",
            },
        )

    def test_outlook_graph_token_prefers_outlook_proxy(self):
        ctx.OUTLOOK_PROXY = "http://mail-proxy:7890"
        response = mock.Mock()
        response.json.return_value = {"access_token": "graph-token"}

        with mock.patch.object(hotmail.requests, "post", return_value=response) as post_mock:
            token = hotmail._outlook_get_graph_token(
                "client-id",
                "refresh-token",
                proxies={"http": "http://general-proxy:8080", "https": "http://general-proxy:8080"},
            )

        self.assertEqual(token, "graph-token")
        self.assertEqual(
            post_mock.call_args.kwargs["proxies"],
            {
                "http": "http://mail-proxy:7890",
                "https": "http://mail-proxy:7890",
            },
        )

    def test_hotmail007_buy_error_retries_until_success(self):
        ctx.EMAIL_MODE = "hotmail007"
        ctx.HOTMAIL007_API_KEY = "key"
        ctx.HOTMAIL007_MAX_RETRY = 3
        fake_mail = {
            "email": "buy-retry@example.com",
            "password": "secret",
            "refresh_token": "refresh",
            "client_id": "client",
        }

        with mock.patch.object(
            hotmail,
            "hotmail007_get_mail",
            side_effect=[
                ([], "buy error"),
                ([], "buy error"),
                ([], "buy error"),
                ([fake_mail], ""),
            ],
        ) as get_mail_mock, \
            mock.patch.object(hotmail, "_outlook_get_known_ids", return_value=set()), \
            mock.patch("gpt_register.hotmail.time.sleep") as sleep_mock:
            email, token = mail.get_email_and_token()

        self.assertEqual((email, token), ("buy-retry@example.com", "buy-retry@example.com"))
        self.assertEqual(get_mail_mock.call_count, 4)
        sleep_mock.assert_not_called()

    def test_hotmail007_timeout_retries_three_times_before_success(self):
        ctx.EMAIL_MODE = "hotmail007"
        ctx.HOTMAIL007_API_KEY = "key"
        ctx.HOTMAIL007_MAX_RETRY = 3
        fake_mail = {
            "email": "timeout-retry@example.com",
            "password": "secret",
            "refresh_token": "refresh",
            "client_id": "client",
        }
        timeout_error = "Failed to perform, curl: (28) Connection timed out after 15001 milliseconds."

        with mock.patch.object(
            hotmail,
            "hotmail007_get_mail",
            side_effect=[
                ([], timeout_error),
                ([], timeout_error),
                ([], timeout_error),
                ([fake_mail], ""),
            ],
        ) as get_mail_mock, \
            mock.patch.object(hotmail, "_outlook_get_known_ids", return_value=set()), \
            mock.patch("gpt_register.hotmail.time.sleep") as sleep_mock:
            email, token = mail.get_email_and_token()

        self.assertEqual((email, token), ("timeout-retry@example.com", "timeout-retry@example.com"))
        self.assertEqual(get_mail_mock.call_count, 4)
        sleep_mock.assert_not_called()

    def test_hotmail007_timeout_fails_after_three_retries(self):
        ctx.EMAIL_MODE = "hotmail007"
        ctx.HOTMAIL007_API_KEY = "key"
        ctx.HOTMAIL007_MAX_RETRY = 3
        timeout_error = "Failed to perform, curl: (28) Operation timed out after 15002 milliseconds with 0 bytes received."

        with mock.patch.object(
            hotmail,
            "hotmail007_get_mail",
            side_effect=[
                ([], timeout_error),
                ([], timeout_error),
                ([], timeout_error),
                ([], timeout_error),
            ],
        ) as get_mail_mock, \
            mock.patch("gpt_register.hotmail.time.sleep") as sleep_mock:
            email, token = mail.get_email_and_token()

        self.assertEqual((email, token), ("", ""))
        self.assertEqual(get_mail_mock.call_count, 4)
        sleep_mock.assert_not_called()

    def test_hotmail007_tls_error_uses_max_retry_after_multiple_buy_errors(self):
        ctx.EMAIL_MODE = "hotmail007"
        ctx.HOTMAIL007_API_KEY = "key"
        ctx.HOTMAIL007_MAX_RETRY = 3
        fake_mail = {
            "email": "tls-retry@example.com",
            "password": "secret",
            "refresh_token": "refresh",
            "client_id": "client",
        }
        tls_error = (
            "Failed to perform, curl: (35) TLS connect error: "
            "error:00000000:invalid library (0):OPENSSL_internal:invalid library (0)."
        )

        with mock.patch.object(
            hotmail,
            "hotmail007_get_mail",
            side_effect=[
                ([], "buy error"),
                ([], "buy error"),
                ([], "buy error"),
                ([], "buy error"),
                ([], "buy error"),
                ([], tls_error),
                ([], tls_error),
                ([fake_mail], ""),
            ],
        ) as get_mail_mock, \
            mock.patch.object(hotmail, "_outlook_get_known_ids", return_value=set()), \
            mock.patch("gpt_register.hotmail.time.sleep") as sleep_mock:
            email, token = mail.get_email_and_token()

        self.assertEqual((email, token), ("tls-retry@example.com", "tls-retry@example.com"))
        self.assertEqual(get_mail_mock.call_count, 8)
        sleep_mock.assert_not_called()

    def test_hotmail007_tls_error_fails_after_hotmail007_max_retry(self):
        ctx.EMAIL_MODE = "hotmail007"
        ctx.HOTMAIL007_API_KEY = "key"
        ctx.HOTMAIL007_MAX_RETRY = 3
        tls_error = (
            "Failed to perform, curl: (35) TLS connect error: "
            "error:00000000:invalid library (0):OPENSSL_internal:invalid library (0)."
        )

        with mock.patch.object(
            hotmail,
            "hotmail007_get_mail",
            side_effect=[
                ([], tls_error),
                ([], tls_error),
                ([], tls_error),
                ([], tls_error),
            ],
        ) as get_mail_mock, \
            mock.patch("gpt_register.hotmail.time.sleep") as sleep_mock:
            email, token = mail.get_email_and_token()

        self.assertEqual((email, token), ("", ""))
        self.assertEqual(get_mail_mock.call_count, 4)
        sleep_mock.assert_not_called()

    def test_get_email_and_token_dispatches_to_local_outlook_mode(self):
        ctx.EMAIL_MODE = "local_outlook"
        ctx.LOCAL_OUTLOOK_MAIL_MODE = "graph"

        class FakeQueue:
            def __init__(self):
                self.used = False

            def __len__(self):
                return 0 if self.used else 1

            def pop(self):
                if self.used:
                    return None
                self.used = True
                return {
                    "email": "local@example.com",
                    "password": "ms-pass",
                    "client_id": "client-id",
                    "refresh_token": "refresh-token",
                }

        ctx._email_queue = FakeQueue()

        with mock.patch.object(hotmail, "_outlook_get_graph_token", return_value="access-token"), \
             mock.patch.object(hotmail, "_outlook_get_known_ids", return_value={"known-id"}):
            email, token = mail.get_email_and_token()

        self.assertEqual((email, token), ("local@example.com", "local@example.com"))
        self.assertEqual(ctx._hotmail007_credentials["local@example.com"]["client_id"], "client-id")
        self.assertEqual(ctx._hotmail007_credentials["local@example.com"]["known_ids"], {"known-id"})

    def test_local_outlook_invalid_account_is_recorded_and_skipped(self):
        import os
        import tempfile

        ctx.EMAIL_MODE = "local_outlook"
        ctx.LOCAL_OUTLOOK_MAIL_MODE = "graph"

        with tempfile.TemporaryDirectory() as temp_dir:
            bad_file = os.path.join(temp_dir, "bad.txt")
            ctx.LOCAL_OUTLOOK_BAD_FILE = bad_file

            class FakeQueue:
                def __init__(self):
                    self.items = [
                        {
                            "email": "bad@example.com",
                            "password": "bad-pass",
                            "client_id": "bad-client",
                            "refresh_token": "bad-refresh",
                        },
                        {
                            "email": "good@example.com",
                            "password": "good-pass",
                            "client_id": "good-client",
                            "refresh_token": "good-refresh",
                        },
                    ]

                def __len__(self):
                    return len(self.items)

                def pop(self):
                    return self.items.pop(0) if self.items else None

            ctx._email_queue = FakeQueue()

            def fake_graph_token(client_id, refresh_token, proxies=None):
                if client_id == "bad-client":
                    raise Exception("invalid_grant")
                return "access-token"

            with mock.patch.object(hotmail, "_outlook_get_graph_token", side_effect=fake_graph_token), \
                 mock.patch.object(hotmail, "_outlook_get_known_ids", return_value=set()):
                email, token = mail.get_email_and_token()

            self.assertEqual((email, token), ("good@example.com", "good@example.com"))
            self.assertTrue(os.path.exists(bad_file))
            with open(bad_file, "r", encoding="utf-8") as handle:
                bad_content = handle.read()
            self.assertIn("bad@example.com----bad-pass----bad-client----bad-refresh", bad_content)

    def test_local_outlook_transient_precheck_error_is_not_recorded_and_requeued(self):
        import os
        import tempfile

        ctx.EMAIL_MODE = "local_outlook"
        ctx.LOCAL_OUTLOOK_MAIL_MODE = "graph"

        with tempfile.TemporaryDirectory() as temp_dir:
            bad_file = os.path.join(temp_dir, "bad.txt")
            ctx.LOCAL_OUTLOOK_BAD_FILE = bad_file

            class FakeQueue:
                def __init__(self):
                    self.items = [
                        {
                            "email": "temp@example.com",
                            "password": "temp-pass",
                            "client_id": "temp-client",
                            "refresh_token": "temp-refresh",
                        }
                    ]

                def __len__(self):
                    return len(self.items)

                def pop(self):
                    return self.items.pop(0) if self.items else None

                def push_front(self, account):
                    self.items.insert(0, account)

            queue = FakeQueue()
            ctx._email_queue = queue

            with mock.patch.object(hotmail, "_outlook_get_graph_token", side_effect=Exception("Could not resolve host: login.microsoftonline.com")):
                email, token = mail.get_email_and_token()

            self.assertEqual((email, token), ("", ""))
            self.assertEqual(len(queue.items), 1)
            self.assertEqual(queue.items[0]["email"], "temp@example.com")
            self.assertFalse(os.path.exists(bad_file))

    def test_local_outlook_uses_imap_mode_when_configured(self):
        ctx.EMAIL_MODE = "local_outlook"
        ctx.LOCAL_OUTLOOK_MAIL_MODE = "imap"

        class FakeQueue:
            def __len__(self):
                return 0

            def pop(self):
                return {
                    "email": "imap@example.com",
                    "password": "imap-pass",
                    "client_id": "imap-client",
                    "refresh_token": "imap-refresh",
                }

        ctx._email_queue = FakeQueue()

        with mock.patch.object(hotmail, "_outlook_get_imap_token", return_value=("token", "outlook.office365.com")) as imap_mock, \
             mock.patch.object(hotmail, "_outlook_get_known_ids", return_value=set()):
            email, token = mail.get_email_and_token()

        self.assertEqual((email, token), ("imap@example.com", "imap@example.com"))
        self.assertEqual(ctx._hotmail007_credentials["imap@example.com"]["mail_mode"], "imap")
        imap_mock.assert_called()

    def test_local_outlook_mail_error_records_bad_account(self):
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            bad_file = os.path.join(temp_dir, "bad.txt")
            ctx.LOCAL_OUTLOOK_BAD_FILE = bad_file
            ctx._hotmail007_credentials["broken@example.com"] = {
                "client_id": "client",
                "refresh_token": "refresh",
                "mail_mode": "graph",
                "source": "local_outlook",
                "account_line": "broken@example.com----pass----client----refresh",
                "known_ids": set(),
            }

            with mock.patch.object(hotmail, "_outlook_fetch_otp", return_value="") as fetch_mock:
                def inject_error(*args, **kwargs):
                    ctx._hotmail007_credentials["broken@example.com"]["last_mail_error"] = "token_error:invalid_grant"
                    return ""

                fetch_mock.side_effect = inject_error
                code = hotmail.get_oai_code("broken@example.com")

            self.assertEqual(code, "")
            self.assertTrue(os.path.exists(bad_file))
            with open(bad_file, "r", encoding="utf-8") as handle:
                self.assertIn("broken@example.com----pass----client----refresh", handle.read())

    def test_get_oai_code_uses_primary_email_for_alias_mailbox(self):
        ctx._hotmail007_credentials["alias+abcdef@example.com"] = {
            "client_id": "client",
            "refresh_token": "refresh",
            "primary_email": "primary@example.com",
            "mail_mode": "imap",
            "known_ids": set(),
        }

        with mock.patch.object(hotmail, "_outlook_fetch_otp", return_value="654321") as fetch_mock:
            code = hotmail.get_oai_code("alias+abcdef@example.com")

        self.assertEqual(code, "654321")
        self.assertEqual(fetch_mock.call_args.args[0], "primary@example.com")
        self.assertEqual(fetch_mock.call_args.kwargs["error_email"], "alias+abcdef@example.com")

    def test_outlook_fetch_otp_graph_marks_retryable_mail_access_error_on_http_503(self):
        ctx._hotmail007_credentials["graph503@example.com"] = {
            "client_id": "client",
            "refresh_token": "refresh",
            "known_ids": set(),
        }
        debug_response = mock.Mock(status_code=503)

        with mock.patch.object(hotmail, "_outlook_get_graph_token", return_value="graph-token"), \
             mock.patch.object(
                 hotmail,
                 "_outlook_graph_get_openai_messages_detailed",
                 return_value=([], "inbox:HTTP 503; junkemail:HTTP 503; all:HTTP 503", False),
             ), \
             mock.patch.object(hotmail.requests, "get", return_value=debug_response), \
             mock.patch("gpt_register.hotmail.time.sleep"):
            code = hotmail._outlook_fetch_otp_graph(
                "graph503@example.com",
                "client",
                "refresh",
                set(),
                timeout=30,
            )

        self.assertEqual(code, "")
        last_error = hotmail.get_last_mail_error("graph503@example.com")
        self.assertTrue(last_error.startswith("mail_access_retryable:"))
        self.assertTrue(hotmail.is_retryable_mail_error(last_error))

    def test_get_email_and_token_dispatches_to_luckmail_order_mode(self):
        ctx.EMAIL_MODE = "luckmail"
        ctx.LUCKMAIL_API_KEY = "key"
        ctx.LUCKMAIL_AUTO_BUY = False

        with mock.patch.object(
            luckmail,
            "luckmail_create_order",
            return_value=("order-1", {"email_address": "luck@example.com"}),
        ):
            email, token = mail.get_email_and_token()

        self.assertEqual((email, token), ("luck@example.com", "luck@example.com"))
        self.assertEqual(ctx._luckmail_credentials["luck@example.com"]["order_no"], "order-1")

    def test_select_latest_unseen_code_prefers_fresh_mail(self):
        mails = [
            {
                "message_id": "old-1",
                "received_at": "2026-04-06 04:57:38",
                "subject": "Your ChatGPT code is 879511",
            },
            {
                "message_id": "new-1",
                "received_at": "2026-04-06 08:17:22",
                "subject": "Your ChatGPT code is 721049",
            },
        ]

        code, message_id = luckmail._select_latest_unseen_code(mails, {"old-1"})

        self.assertEqual(code, "721049")
        self.assertEqual(message_id, "new-1")

    def test_get_oai_code_prefers_mail_list_before_token_endpoint(self):
        ctx._luckmail_credentials["gmail@example.com"] = {
            "token": "tok_test",
            "known_message_ids": {"old-1"},
        }
        seen_ids = set()
        mails = [
            {
                "message_id": "old-1",
                "received_at": "2026-04-06 04:57:38",
                "subject": "Your ChatGPT code is 879511",
            },
            {
                "message_id": "new-1",
                "received_at": "2026-04-06 08:17:22",
                "subject": "Your ChatGPT code is 721049",
            },
        ]

        with mock.patch.object(luckmail, "luckmail_get_token_mails", return_value=(mails, None)), \
             mock.patch.object(luckmail, "luckmail_get_code_by_token", return_value="879511") as fallback_mock:
            code = luckmail.get_oai_code("gmail@example.com", seen_ids=seen_ids)

        self.assertEqual(code, "721049")
        self.assertEqual(seen_ids, {"new-1"})
        fallback_mock.assert_not_called()

    def test_get_oai_code_uses_existing_order_before_creating_new_one(self):
        ctx._luckmail_credentials["order@example.com"] = {"order_no": "order-1"}

        with mock.patch.object(luckmail, "luckmail_get_code", return_value="654321") as code_mock, \
             mock.patch.object(luckmail, "luckmail_create_order") as create_order_mock:
            code = luckmail.get_oai_code("order@example.com")

        self.assertEqual(code, "654321")
        code_mock.assert_called_once_with("order-1", proxies=None)
        create_order_mock.assert_not_called()

    def test_collect_private_emails_pushes_normal_emails_into_queue(self):
        private_emails = [
            {"id": 1, "address": "user1@outlook.com", "status": 1, "type": "ms_graph"},
            {"id": 2, "address": "user2@hotmail.com", "status": 1, "type": "ms_imap"},
        ]
        active_queue = ctx.ActiveEmailQueue()

        with mock.patch.object(luckmail, "luckmail_get_all_private_emails", return_value=(private_emails, None)):
            active = luckmail.luckmail_collect_private_emails(active_queue=active_queue)

        self.assertEqual(
            active,
            [
                {"email": "user1@outlook.com", "id": 1, "source": "private", "type": "ms_graph"},
                {"email": "user2@hotmail.com", "id": 2, "source": "private", "type": "ms_imap"},
            ],
        )
        self.assertEqual(len(active_queue), 2)

    def test_get_email_and_token_uses_private_email_queue_in_own_mode(self):
        ctx.EMAIL_MODE = "luckmail"
        ctx.LUCKMAIL_API_KEY = "key"
        ctx.LUCKMAIL_AUTO_BUY = True
        ctx.LUCKMAIL_OWN_ONLY = True
        ctx._luckmail_own_only = True
        ctx._active_email_queue = ctx.ActiveEmailQueue()
        ctx._active_email_queue.add_batch([{"email": "user@outlook.com", "id": 9, "source": "private"}])

        with mock.patch.object(luckmail, "luckmail_get_private_email_mails", return_value=([], None, 0)):
            email, token = mail.get_email_and_token()

        self.assertEqual((email, token), ("user@outlook.com", "user@outlook.com"))
        self.assertEqual(ctx._luckmail_credentials["user@outlook.com"]["email_id"], 9)
        self.assertEqual(ctx._luckmail_credentials["user@outlook.com"]["source"], "private")

    def test_get_oai_code_reads_private_email_mails(self):
        ctx._luckmail_credentials["own@example.com"] = {
            "email_id": 12,
            "known_message_ids": {"old-1"},
        }
        seen_ids = set()
        mails = [
            {
                "message_id": "new-1",
                "received_at": "2026-04-06 08:17:22",
                "subject": "Your ChatGPT code is 721049",
            },
        ]

        with mock.patch.object(luckmail, "luckmail_get_private_email_mails", return_value=(mails, None, 1)), \
             mock.patch.object(luckmail, "luckmail_get_private_email_mail_detail") as detail_mock:
            code = luckmail.get_oai_code("own@example.com", seen_ids=seen_ids)

        self.assertEqual(code, "721049")
        self.assertEqual(seen_ids, {"new-1"})
        detail_mock.assert_not_called()

    def test_check_purchased_emails_filters_non_hotmail_and_streams_active_results(self):
        purchased = [
            {"email_address": "user1@hotmail.com", "token": "tok-1", "id": 1},
            {"email_address": "user2@outlook.com", "token": "tok-2", "id": 2},
            {"email_address": "user3@hotmail.com", "token": "tok-3", "id": 3},
        ]
        active_queue = ctx.ActiveEmailQueue()

        def fake_alive(token: str, proxies=None):
            return (token == "tok-3", "ok")

        with mock.patch.object(luckmail, "luckmail_get_all_purchased_emails", return_value=(purchased, None)), \
             mock.patch.object(luckmail, "luckmail_check_email_alive", side_effect=fake_alive) as alive_mock:
            active = luckmail.luckmail_check_purchased_emails(max_workers=2, active_queue=active_queue)

        self.assertEqual(active, [{"email": "user3@hotmail.com", "token": "tok-3", "id": 3}])
        self.assertEqual(len(active_queue), 1)
        self.assertEqual(active_queue.pop(), {"email": "user3@hotmail.com", "token": "tok-3", "id": 3})
        self.assertEqual(alive_mock.call_count, 2)


if __name__ == "__main__":
    unittest.main()
