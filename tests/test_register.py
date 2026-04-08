import unittest
from unittest import mock

from gpt_register import context as ctx
from gpt_register import register


class RegisterFlowTests(unittest.TestCase):
    def setUp(self):
        self._original_resin_url = ctx.RESIN_URL
        self._original_resin_platform_name = ctx.RESIN_PLATFORM_NAME

    def tearDown(self):
        ctx.RESIN_URL = self._original_resin_url
        ctx.RESIN_PLATFORM_NAME = self._original_resin_platform_name

    def test_is_phone_challenge_response_detects_add_phone_page(self):
        payload = {
            "continue_url": "https://auth.openai.com/add-phone",
            "page": {"type": "add_phone"},
        }

        self.assertTrue(register._is_phone_challenge_response(payload))

    def test_is_phone_challenge_response_ignores_normal_continue(self):
        payload = {
            "continue_url": "https://auth.openai.com/about-you",
            "page": {"type": "about_you"},
        }

        self.assertFalse(register._is_phone_challenge_response(payload))

    def test_call_with_timeout_retry_retries_three_times_before_success(self):
        timeout_error = Exception(
            "Failed to perform, curl: (28) Operation timed out after 15002 milliseconds with 0 bytes received."
        )
        action = mock.Mock(side_effect=[timeout_error, timeout_error, timeout_error, "ok"])

        with mock.patch.object(register.time, "sleep") as sleep_mock:
            result = register._call_with_timeout_retry(action, label="测试请求")

        self.assertEqual(result, "ok")
        self.assertEqual(action.call_count, 4)
        self.assertEqual(sleep_mock.call_count, 3)

    def test_bootstrap_authorize_continue_retries_sentinel_403_three_times(self):
        class FakeSession:
            def __init__(self):
                self.cookies = {}
                self.get_calls = 0

            def get(self, *args, **kwargs):
                self.get_calls += 1
                self.cookies["oai-did"] = f"did-{self.get_calls}"
                return mock.Mock(status_code=200)

        session = FakeSession()
        resp_403 = mock.Mock(status_code=403)
        resp_200 = mock.Mock(status_code=200)
        resp_200.json.return_value = {"token": "sentinel-token"}

        with mock.patch.object(register.requests, "post", side_effect=[resp_403, resp_403, resp_403, resp_200]) as post_mock, \
             mock.patch.object(register.time, "sleep") as sleep_mock:
            did, sentinel = register._bootstrap_authorize_continue(
                session,
                "https://auth.openai.com/oauth/authorize",
                proxies=None,
            )

        self.assertEqual(did, "did-4")
        self.assertIn("sentinel-token", sentinel)
        self.assertEqual(session.get_calls, 4)
        self.assertEqual(post_mock.call_count, 4)
        self.assertEqual(sleep_mock.call_count, 3)

    def test_initial_device_id_failure_switches_proxy_and_returns_new_proxy(self):
        class FakeCookies(dict):
            pass

        class FakeSession:
            def __init__(self, proxies=None, impersonate=None):
                del impersonate
                self.proxies = proxies
                self.cookies = FakeCookies()

            def get(self, url, **kwargs):
                del kwargs
                proxy = (self.proxies or {}).get("http")
                resp = mock.Mock()
                if "cloudflare.com/cdn-cgi/trace" in str(url):
                    resp.text = "loc=US\n"
                elif proxy and "proxy-b" in proxy:
                    resp.text = "loc=US\n"
                    self.cookies["oai-did"] = "did-proxy-b"
                else:
                    self.cookies["oai-did"] = None
                    resp.text = ""
                return resp

        with mock.patch.object(register.requests, "Session", side_effect=lambda proxies=None, impersonate=None: FakeSession(proxies=proxies, impersonate=impersonate)), \
             mock.patch.object(register.requests, "post") as post_mock, \
             mock.patch.object(register.time, "sleep") as sleep_mock:
            post_mock.return_value = mock.Mock(status_code=200)
            post_mock.return_value.json.return_value = {"token": "sentinel-token"}
            session, proxy, proxies, did, sentinel = register._bootstrap_initial_device_with_proxy_refresh(
                "https://auth.openai.com/oauth/authorize",
                "http://proxy-a:8080",
                get_next_proxy=mock.Mock(return_value="http://proxy-b:8080"),
            )

        self.assertIsNotNone(session)
        self.assertEqual(proxy, "http://proxy-b:8080")
        self.assertEqual(proxies, {"http": "http://proxy-b:8080", "https": "http://proxy-b:8080"})
        self.assertEqual(did, "did-proxy-b")
        self.assertIn("sentinel-token", sentinel)
        self.assertEqual(sleep_mock.call_count, 1)

    def test_initial_device_id_failure_stops_after_three_proxy_refreshes(self):
        class FakeCookies(dict):
            pass

        class FakeSession:
            def __init__(self, proxies=None, impersonate=None):
                del proxies, impersonate
                self.cookies = FakeCookies()

            def get(self, url, **kwargs):
                del kwargs
                resp = mock.Mock()
                if "cloudflare.com/cdn-cgi/trace" in url:
                    resp.text = "loc=US\n"
                else:
                    self.cookies["oai-did"] = None
                    resp.text = ""
                return resp

        get_next_proxy = mock.Mock(side_effect=[
            "http://proxy-b:8080",
            "http://proxy-c:8080",
            "http://proxy-d:8080",
        ])

        with mock.patch.object(register.requests, "Session", side_effect=lambda proxies=None, impersonate=None: FakeSession(proxies=proxies, impersonate=impersonate)), \
             mock.patch.object(register.time, "sleep") as sleep_mock:
            session, proxy, proxies, did, sentinel = register._bootstrap_initial_device_with_proxy_refresh(
                "https://auth.openai.com/oauth/authorize",
                "http://proxy-a:8080",
                get_next_proxy=get_next_proxy,
            )

        self.assertIsNotNone(session)
        self.assertEqual(proxy, "http://proxy-d:8080")
        self.assertEqual(proxies, {"http": "http://proxy-d:8080", "https": "http://proxy-d:8080"})
        self.assertEqual(did, "")
        self.assertEqual(sentinel, "")
        self.assertEqual(get_next_proxy.call_count, 3)
        self.assertGreaterEqual(sleep_mock.call_count, 4)

    def test_initial_device_id_failure_refreshes_resin_startup_account(self):
        ctx.RESIN_URL = "http://127.0.0.1:2260/my-token"
        ctx.RESIN_PLATFORM_NAME = "reg"

        class FakeCookies(dict):
            pass

        class FakeSession:
            def __init__(self, proxies=None, impersonate=None):
                del impersonate
                self.proxies = proxies
                self.cookies = FakeCookies()

            def get(self, url, **kwargs):
                del kwargs
                proxy = (self.proxies or {}).get("http", "")
                resp = mock.Mock()
                if "cloudflare.com/cdn-cgi/trace" in str(url):
                    resp.text = "loc=US\n"
                elif "reset99" in proxy:
                    resp.text = "loc=US\n"
                    self.cookies["oai-did"] = "did-reset"
                else:
                    self.cookies["oai-did"] = None
                    resp.text = ""
                return resp

        resin_state = ctx.ResinRunState(startup_account="start01", current_account="user@example.com")

        def fake_refresh(force_new=False, resin_state=None):
            self.assertTrue(force_new)
            self.assertIs(resin_state, resin_state_obj)
            resin_state.startup_account = "reset99"
            resin_state.current_account = "reset99"
            return "reset99"

        resin_state_obj = resin_state

        with mock.patch.object(register.requests, "Session", side_effect=lambda proxies=None, impersonate=None: FakeSession(proxies=proxies, impersonate=impersonate)), \
             mock.patch.object(register.requests, "post") as post_mock, \
             mock.patch.object(register.ctx, "get_resin_startup_account", side_effect=fake_refresh), \
             mock.patch.object(register.time, "sleep") as sleep_mock:
            post_mock.return_value = mock.Mock(status_code=200)
            post_mock.return_value.json.return_value = {"token": "sentinel-token"}
            session, proxy, proxies, did, sentinel = register._bootstrap_initial_device_with_proxy_refresh(
                "https://auth.openai.com/oauth/authorize",
                None,
                resin_state=resin_state,
            )

        self.assertIsNotNone(session)
        self.assertIsNone(proxy)
        self.assertEqual(
            proxies,
            {
                "http": "http://reg.reset99:my-token@127.0.0.1:2260",
                "https": "http://reg.reset99:my-token@127.0.0.1:2260",
            },
        )
        self.assertEqual(did, "did-reset")
        self.assertIn("sentinel-token", sentinel)
        self.assertEqual(resin_state.current_account, "reset99")
        self.assertEqual(sleep_mock.call_count, 1)

    def test_run_switches_from_startup_account_to_email_account_before_network_check(self):
        ctx.RESIN_URL = "http://127.0.0.1:2260/my-token"
        ctx.RESIN_PLATFORM_NAME = "reg"
        observed = {}

        def fake_get_email_and_token(proxies):
            observed["provider_proxy"] = proxies["http"]
            return "user@example.com", "dev-token"

        def fake_check_network_ready(session, proxies=None):
            del session
            observed["network_proxy"] = (proxies or {}).get("http")
            return False

        with mock.patch.object(register.ctx, "_generate_resin_account", return_value="start01"), \
             mock.patch.object(register.mail, "get_email_and_token", side_effect=fake_get_email_and_token), \
             mock.patch.object(register, "_check_network_ready", side_effect=fake_check_network_ready):
            result = register.run(None)

        self.assertEqual(
            observed["provider_proxy"],
            "http://reg.start01:my-token@127.0.0.1:2260",
        )
        self.assertEqual(
            observed["network_proxy"],
            "http://reg.user%40example.com:my-token@127.0.0.1:2260",
        )
        self.assertEqual(result[3], "network_error")
        self.assertEqual(
            result[4],
            "http://reg.user%40example.com:my-token@127.0.0.1:2260",
        )


if __name__ == "__main__":
    unittest.main()
