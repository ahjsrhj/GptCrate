import unittest
from unittest import mock

from gpt_register import context as ctx


class ResinContextTests(unittest.TestCase):
    def setUp(self):
        self._original_resin_url = ctx.RESIN_URL
        self._original_resin_platform_name = ctx.RESIN_PLATFORM_NAME
        self._original_log_thread_id = ctx.get_log_thread_id()

    def tearDown(self):
        ctx.RESIN_URL = self._original_resin_url
        ctx.RESIN_PLATFORM_NAME = self._original_resin_platform_name
        if self._original_log_thread_id is None:
            ctx.clear_log_thread_id()
        else:
            ctx.set_log_thread_id(self._original_log_thread_id)

    def test_build_proxies_assembles_resin_proxy_url_with_explicit_account(self):
        ctx.RESIN_URL = "http://127.0.0.1:2260/my-token"
        ctx.RESIN_PLATFORM_NAME = "reg"
        resin_state = ctx.ResinRunState(startup_account="start01")

        proxies = ctx.build_proxies(None, account="user_1", resin_state=resin_state)

        self.assertEqual(
            proxies,
            {
                "http": "http://reg.user_1:my-token@127.0.0.1:2260",
                "https": "http://reg.user_1:my-token@127.0.0.1:2260",
            },
        )
        self.assertEqual(resin_state.current_account, "user_1")

    def test_get_resin_startup_account_force_new_updates_state(self):
        resin_state = ctx.ResinRunState(startup_account="abc123")

        with mock.patch.object(ctx.random, "choices", return_value=list("xyz789")):
            refreshed = ctx.get_resin_startup_account(force_new=True, resin_state=resin_state)

        self.assertEqual(refreshed, "xyz789")
        self.assertEqual(resin_state.startup_account, "xyz789")
        self.assertEqual(resin_state.current_account, "xyz789")

    def test_build_proxies_uses_current_account_when_no_explicit_account_given(self):
        ctx.RESIN_URL = "http://127.0.0.1:2260/my-token"
        ctx.RESIN_PLATFORM_NAME = "reg"
        resin_state = ctx.ResinRunState(startup_account="start01", current_account="user@example.com")

        proxies = ctx.build_proxies(None, resin_state=resin_state)

        self.assertEqual(
            proxies["http"],
            "http://reg.user:my-token@127.0.0.1:2260",
        )

    def test_set_current_account_strips_email_domain_for_resin(self):
        resin_state = ctx.ResinRunState(startup_account="start01")

        current_account = resin_state.set_current_account("tvufekb8677@hotmail.com")

        self.assertEqual(current_account, "tvufekb8677")
        self.assertEqual(resin_state.current_account, "tvufekb8677")

    def test_extract_resin_account_reads_account_from_proxy_url(self):
        ctx.RESIN_URL = "http://127.0.0.1:2260/my-token"
        ctx.RESIN_PLATFORM_NAME = "reg"

        account = ctx.extract_resin_account("http://reg.user123:my-token@127.0.0.1:2260")

        self.assertEqual(account, "user123")

    def test_extract_resin_account_ignores_non_resin_proxy(self):
        ctx.RESIN_URL = "http://127.0.0.1:2260/my-token"
        ctx.RESIN_PLATFORM_NAME = "reg"

        account = ctx.extract_resin_account("http://user:pass@10.0.0.1:8080")

        self.assertEqual(account, "")

    def test_log_thread_color_uses_fixed_mapping(self):
        self.assertEqual(ctx.get_log_thread_color(1), "cyan")
        self.assertEqual(ctx.get_log_thread_color(2), "green")
        self.assertEqual(ctx.get_log_thread_color(8), "cyan")

    def test_set_log_thread_id_stores_positive_integer_only(self):
        ctx.set_log_thread_id("3")
        self.assertEqual(ctx.get_log_thread_id(), 3)

        ctx.set_log_thread_id(0)
        self.assertIsNone(ctx.get_log_thread_id())

    def test_multiple_resin_states_do_not_share_startup_accounts(self):
        state_one = ctx.ResinRunState(startup_account="aaa111")
        state_two = ctx.ResinRunState(startup_account="bbb222")

        self.assertEqual(ctx.get_resin_startup_account(resin_state=state_one), "aaa111")
        self.assertEqual(ctx.get_resin_startup_account(resin_state=state_two), "bbb222")
        self.assertNotEqual(state_one.startup_account, state_two.startup_account)


if __name__ == "__main__":
    unittest.main()
