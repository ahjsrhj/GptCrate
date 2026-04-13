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

    def test_collect_email_otp_retries_mailbox_access_before_resending(self):
        session = mock.Mock()

        with mock.patch.object(register.mail, "get_oai_code", side_effect=["", "", "", "", "123456"]) as get_code_mock, \
             mock.patch.object(
                 register.mail,
                 "get_last_mail_error",
                 side_effect=["mail_access_retryable:inbox:HTTP 503"] * 4,
             ), \
             mock.patch.object(register.mail, "should_retry_mail_fetch_without_resend", return_value=True), \
             mock.patch.object(register.oauth, "_post_with_retry", return_value=mock.Mock(status_code=200)) as resend_mock, \
             mock.patch.object(register.time, "sleep") as sleep_mock:
            code = register._collect_email_otp(
                session,
                sentinel="sentinel-token",
                dev_token="dev-token",
                email="user@example.com",
            )

        self.assertEqual(code, "123456")
        self.assertEqual(get_code_mock.call_count, 5)
        resend_mock.assert_called_once()
        self.assertEqual(
            resend_mock.call_args.args[1],
            "https://auth.openai.com/api/accounts/email-otp/resend",
        )
        self.assertEqual(sleep_mock.call_count, 4)

    def test_collect_email_otp_plain_timeout_resends_immediately(self):
        session = mock.Mock()

        with mock.patch.object(register.mail, "get_oai_code", side_effect=["", "654321"]) as get_code_mock, \
             mock.patch.object(register.mail, "get_last_mail_error", return_value="otp_timeout"), \
             mock.patch.object(register.mail, "should_retry_mail_fetch_without_resend", return_value=False), \
             mock.patch.object(register.oauth, "_post_with_retry", return_value=mock.Mock(status_code=200)) as resend_mock, \
             mock.patch.object(register.time, "sleep") as sleep_mock:
            code = register._collect_email_otp(
                session,
                sentinel="sentinel-token",
                dev_token="dev-token",
                email="user@example.com",
            )

        self.assertEqual(code, "654321")
        self.assertEqual(get_code_mock.call_count, 2)
        resend_mock.assert_called_once()
        self.assertEqual(sleep_mock.call_count, 1)

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

    def test_relogin_device_id_failure_switches_proxy_and_reuses_existing_session(self):
        class FakeCookies(dict):
            pass

        class FakeSession:
            def __init__(self, proxies=None, impersonate=None):
                del impersonate
                self.proxies = proxies
                self.cookies = FakeCookies()
                self.get_calls = []

            def get(self, url, **kwargs):
                del kwargs
                self.get_calls.append(str(url))
                proxy = (self.proxies or {}).get("http")
                resp = mock.Mock()
                if "cloudflare.com/cdn-cgi/trace" in str(url):
                    resp.text = "loc=US\n"
                elif proxy and "proxy-b" in proxy:
                    resp.text = ""
                    self.cookies["oai-did"] = "did-proxy-b"
                else:
                    resp.text = ""
                    self.cookies["oai-did"] = None
                return resp

        existing_session = FakeSession(
            proxies={"http": "http://proxy-a:8080", "https": "http://proxy-a:8080"}
        )

        with mock.patch.object(
            register.requests,
            "Session",
            side_effect=lambda proxies=None, impersonate=None: FakeSession(
                proxies=proxies,
                impersonate=impersonate,
            ),
        ) as session_mock, mock.patch.object(register.requests, "post") as post_mock, mock.patch.object(
            register.time, "sleep"
        ) as sleep_mock:
            post_mock.return_value = mock.Mock(status_code=200)
            post_mock.return_value.json.return_value = {"token": "sentinel-token"}
            session, proxy, proxies, did, sentinel = register._bootstrap_relogin_device_with_proxy_refresh(
                existing_session,
                "https://auth.openai.com/oauth/authorize",
                "http://proxy-a:8080",
                get_next_proxy=mock.Mock(return_value="http://proxy-b:8080"),
                network_checked=True,
            )

        self.assertIsNot(session, existing_session)
        self.assertEqual(proxy, "http://proxy-b:8080")
        self.assertEqual(
            proxies,
            {"http": "http://proxy-b:8080", "https": "http://proxy-b:8080"},
        )
        self.assertEqual(did, "did-proxy-b")
        self.assertIn("sentinel-token", sentinel)
        self.assertEqual(existing_session.get_calls, ["https://auth.openai.com/oauth/authorize"] * 2)
        self.assertEqual(
            session.get_calls,
            [
                "https://cloudflare.com/cdn-cgi/trace",
                "https://auth.openai.com/oauth/authorize",
            ],
        )
        self.assertEqual(session_mock.call_count, 1)
        self.assertEqual(sleep_mock.call_count, 1)

    def test_run_falls_back_to_startup_account_after_email_proxy_network_failure(self):
        ctx.RESIN_URL = "http://127.0.0.1:2260/my-token"
        ctx.RESIN_PLATFORM_NAME = "reg"
        observed = {"network_proxies": []}

        def fake_get_email_and_token(proxies):
            observed["provider_proxy"] = proxies["http"]
            return "user@example.com", "dev-token"

        def fake_check_network_ready(session, proxies=None):
            del session
            observed["network_proxies"].append((proxies or {}).get("http"))
            return len(observed["network_proxies"]) > 1

        def fake_bootstrap(auth_url, proxy, get_next_proxy=None, resin_state=None, network_checked=False):
            del auth_url, get_next_proxy, network_checked
            observed["bootstrap_proxy"] = ctx.build_proxy_url(proxy, resin_state=resin_state)
            return mock.Mock(), proxy, ctx.build_proxies(proxy, resin_state=resin_state), "did-ok", "sentinel-ok"

        failed_signup_resp = mock.Mock(status_code=500, text="bad request")

        with mock.patch.object(register.ctx, "_generate_resin_account", side_effect=["start01", "reset99"]), \
             mock.patch.object(register.mail, "get_email_and_token", side_effect=fake_get_email_and_token), \
             mock.patch.object(register, "_check_network_ready", side_effect=fake_check_network_ready), \
             mock.patch.object(register, "_bootstrap_initial_device_with_proxy_refresh", side_effect=fake_bootstrap), \
             mock.patch.object(register, "_call_with_timeout_retry", return_value=failed_signup_resp):
            result = register.run(None)

        self.assertEqual(
            observed["provider_proxy"],
            "http://reg.start01:my-token@127.0.0.1:2260",
        )
        self.assertEqual(
            observed["network_proxies"][0],
            "http://reg.user:my-token@127.0.0.1:2260",
        )
        self.assertEqual(
            observed["network_proxies"][1],
            "http://reg.reset99:my-token@127.0.0.1:2260",
        )
        self.assertEqual(
            observed["bootstrap_proxy"],
            "http://reg.reset99:my-token@127.0.0.1:2260",
        )
        self.assertEqual(result[3], "signup_form_error")
        self.assertEqual(result[4], "http://reg.reset99:my-token@127.0.0.1:2260")

    def test_run_prints_email_resin_proxy_before_network_check(self):
        ctx.RESIN_URL = "http://127.0.0.1:2260/my-token"
        ctx.RESIN_PLATFORM_NAME = "reg"
        observed = {"printed": []}

        def fake_get_email_and_token(proxies):
            observed["provider_proxy"] = proxies["http"]
            return "user@example.com", "dev-token"

        def fake_print(message):
            observed["printed"].append(str(message))

        def fake_check_network_ready(session, proxies=None):
            del session
            observed["printed_before_check"] = list(observed["printed"])
            observed["network_proxy"] = (proxies or {}).get("http")
            return False

        with mock.patch.object(register.ctx, "_generate_resin_account", return_value="start01"), \
             mock.patch.object(register.mail, "get_email_and_token", side_effect=fake_get_email_and_token), \
             mock.patch.object(register, "print", side_effect=fake_print), \
             mock.patch.object(register, "_new_session", return_value=mock.Mock()), \
             mock.patch.object(register, "_check_network_ready", side_effect=fake_check_network_ready), \
             mock.patch.object(register, "_refresh_resin_startup_proxy_for_retry", return_value=False):
            result = register.run(None)

        self.assertEqual(
            observed["provider_proxy"],
            "http://reg.start01:my-token@127.0.0.1:2260",
        )
        self.assertEqual(
            observed["network_proxy"],
            "http://reg.user:my-token@127.0.0.1:2260",
        )
        self.assertIn(
            "[*] 当前使用的粘性代理: http://reg.user:my-token@127.0.0.1:2260",
            observed["printed_before_check"],
        )
        self.assertEqual(result[3], "network_error")
        self.assertEqual(
            result[4],
            "http://reg.user:my-token@127.0.0.1:2260",
        )

    def test_run_stops_after_five_resin_proxy_retries_on_network_failure(self):
        ctx.RESIN_URL = "http://127.0.0.1:2260/my-token"
        ctx.RESIN_PLATFORM_NAME = "reg"
        observed = {"network_proxies": []}

        def fake_get_email_and_token(proxies):
            observed["provider_proxy"] = proxies["http"]
            return "user@example.com", "dev-token"

        def fake_check_network_ready(session, proxies=None):
            del session
            observed["network_proxies"].append((proxies or {}).get("http"))
            return False

        with mock.patch.object(
            register.ctx,
            "_generate_resin_account",
            side_effect=["start01", "retry01", "retry02", "retry03", "retry04", "retry05"],
        ), \
             mock.patch.object(register.mail, "get_email_and_token", side_effect=fake_get_email_and_token), \
             mock.patch.object(register, "_check_network_ready", side_effect=fake_check_network_ready):
            result = register.run(None)

        self.assertEqual(
            observed["provider_proxy"],
            "http://reg.start01:my-token@127.0.0.1:2260",
        )
        self.assertEqual(
            observed["network_proxies"],
            [
                "http://reg.user:my-token@127.0.0.1:2260",
                "http://reg.retry01:my-token@127.0.0.1:2260",
                "http://reg.retry02:my-token@127.0.0.1:2260",
                "http://reg.retry03:my-token@127.0.0.1:2260",
                "http://reg.retry04:my-token@127.0.0.1:2260",
                "http://reg.retry05:my-token@127.0.0.1:2260",
            ],
        )
        self.assertEqual(result[3], "network_error")
        self.assertEqual(
            result[4],
            "http://reg.retry05:my-token@127.0.0.1:2260",
        )


if __name__ == "__main__":
    unittest.main()
