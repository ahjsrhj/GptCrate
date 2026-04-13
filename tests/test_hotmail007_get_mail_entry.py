import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest import mock
import sys

import hotmail007_get_mail


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload


class Hotmail007GetMailEntryTests(unittest.TestCase):
    def test_request_get_mail_raises_keyboard_interrupt_on_user_cancel(self):
        error = (
            "Failed to perform, curl: (23) Failure writing output to destination, "
            "passed 13 returned 0. See https://curl.se/libcurl/c/libcurl-errors.html first for more details."
        )

        with mock.patch.object(hotmail007_get_mail.requests, "get", side_effect=Exception(error)):
            with self.assertRaises(KeyboardInterrupt):
                hotmail007_get_mail.request_get_mail(
                    "https://gapi.hotmail007.com",
                    client_key="key",
                    mail_type="outlook",
                    quantity=1,
                )

    def test_format_mail_lines_outputs_expected_order(self):
        lines = hotmail007_get_mail._format_mail_lines(
            {
                "code": 0,
                "success": True,
                "data": [
                    "user@hotmail.com:password123:refresh-token-value:client-id-value",
                ],
            }
        )

        self.assertEqual(
            lines,
            ["user@hotmail.com----password123----client-id-value----refresh-token-value"],
        )

    def test_build_get_mail_url_matches_project_call_style(self):
        url = hotmail007_get_mail.build_get_mail_url(
            "https://gapi.hotmail007.com/",
            client_key="key 123",
            mail_type="outlook premium",
            quantity=2,
        )

        self.assertEqual(
            url,
            "https://gapi.hotmail007.com/api/mail/getMail"
            "?clientKey=key%20123&mailType=outlook%20premium&quantity=2",
        )

    def test_request_get_mail_prefers_outlook_proxy(self):
        with mock.patch.object(
            hotmail007_get_mail.ctx,
            "OUTLOOK_PROXY",
            "http://mail-proxy:7890",
        ), mock.patch.object(
            hotmail007_get_mail.requests,
            "get",
            return_value=_FakeResponse({"success": True, "code": 0, "data": []}),
        ) as get_mock:
            hotmail007_get_mail.request_get_mail(
                "https://gapi.hotmail007.com",
                client_key="key",
                mail_type="outlook",
                quantity=1,
                proxies={"http": "http://general-proxy:8080", "https": "http://general-proxy:8080"},
            )

        self.assertEqual(
            get_mock.call_args.kwargs["proxies"],
            {
                "http": "http://mail-proxy:7890",
                "https": "http://mail-proxy:7890",
            },
        )

    def test_fetch_get_mail_with_retry_retries_until_success(self):
        responses = [
            _FakeResponse({"success": False, "code": 500, "message": "temporary error"}),
            _FakeResponse({"success": True, "code": 0, "data": ["a:b:c:d"]}),
        ]

        with mock.patch.object(hotmail007_get_mail.requests, "get", side_effect=responses) as get_mock, \
            redirect_stdout(StringIO()) as output:
            result, attempts = hotmail007_get_mail.fetch_get_mail_with_retry(
                "https://gapi.hotmail007.com",
                client_key="key",
                mail_type="outlook",
                quantity=1,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(attempts, 2)
        self.assertEqual(get_mock.call_count, 2)
        self.assertIn("temporary error", output.getvalue())
        self.assertIn("立即继续", output.getvalue())

    def test_fetch_get_mail_with_retry_retries_after_exception_until_success(self):
        with mock.patch.object(
            hotmail007_get_mail.requests,
            "get",
            side_effect=[
                Exception("network down"),
                Exception("network down"),
                _FakeResponse({"success": True, "code": 0, "data": ["a:b:c:d"]}),
            ],
        ) as get_mock, \
            redirect_stdout(StringIO()) as output:
            result, attempts = hotmail007_get_mail.fetch_get_mail_with_retry(
                "https://gapi.hotmail007.com",
                client_key="key",
                mail_type="outlook",
                quantity=1,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(attempts, 3)
        self.assertEqual(get_mock.call_count, 3)
        self.assertIn("network down", output.getvalue())
        self.assertIn("立即继续", output.getvalue())

    def test_fetch_get_mail_with_retry_retries_buy_error_until_success(self):
        responses = [
            _FakeResponse({"success": False, "code": 1, "message": "buy error"}),
            _FakeResponse({"success": False, "code": 1, "message": "buy error"}),
            _FakeResponse({"success": True, "code": 0, "data": ["a:b:c:d"]}),
        ]

        with mock.patch.object(hotmail007_get_mail.requests, "get", side_effect=responses) as get_mock, \
            redirect_stdout(StringIO()) as output:
            result, attempts = hotmail007_get_mail.fetch_get_mail_with_retry(
                "https://gapi.hotmail007.com",
                client_key="key",
                mail_type="outlook",
                quantity=1,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(attempts, 3)
        self.assertEqual(get_mock.call_count, 3)
        self.assertIn("buy error", output.getvalue())
        self.assertIn("立即继续", output.getvalue())

    def test_fetch_get_mail_with_retry_rotates_resin_account_on_timeout(self):
        timeout_error = "Failed to perform, curl: (28) Connection timed out after 15001 milliseconds."
        resin_state = object()

        with mock.patch.object(
            hotmail007_get_mail.requests,
            "get",
            side_effect=[
                Exception(timeout_error),
                _FakeResponse({"success": True, "code": 0, "data": ["a:b:c:d"]}),
            ],
        ) as get_mock, \
            mock.patch.object(hotmail007_get_mail.ctx, "is_resin_enabled", return_value=True), \
            mock.patch.object(
                hotmail007_get_mail.ctx,
                "get_resin_startup_account",
                return_value="new-resin-account",
            ) as get_resin_account_mock, \
            mock.patch.object(
                hotmail007_get_mail.ctx,
                "build_proxy_url",
                return_value="http://new-resin-proxy",
            ) as build_proxy_url_mock, \
            mock.patch.object(
                hotmail007_get_mail.ctx,
                "build_proxies",
                side_effect=[
                    {"http": "http://old-resin-proxy", "https": "http://old-resin-proxy"},
                    {"http": "http://new-resin-proxy", "https": "http://new-resin-proxy"},
                ],
            ) as build_proxies_mock, \
            redirect_stdout(StringIO()) as output:
            result, attempts = hotmail007_get_mail.fetch_get_mail_with_retry(
                "https://gapi.hotmail007.com",
                client_key="key",
                mail_type="outlook",
                quantity=1,
                resin_state=resin_state,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(attempts, 2)
        self.assertEqual(get_mock.call_count, 2)
        get_resin_account_mock.assert_called_once_with(force_new=True, resin_state=resin_state)
        build_proxy_url_mock.assert_called_once_with(None, resin_state=resin_state)
        self.assertEqual(build_proxies_mock.call_count, 2)
        self.assertIn("请求超时，已切换 Resin 启动账号: new-resin-account", output.getvalue())
        self.assertIn("已切换新代理: http://new-resin-proxy", output.getvalue())

    def test_main_returns_130_when_keyboard_interrupt_occurs(self):
        with mock.patch.object(
            hotmail007_get_mail,
            "fetch_get_mail_with_retry",
            side_effect=KeyboardInterrupt,
        ), mock.patch.object(
            sys,
            "argv",
            ["hotmail007_get_mail.py", "--api-key", "key"],
        ), redirect_stdout(StringIO()), redirect_stdout(StringIO()):
            stderr_buffer = StringIO()
            with mock.patch("sys.stderr", stderr_buffer):
                exit_code = hotmail007_get_mail.main()

        self.assertEqual(exit_code, 130)
        self.assertIn("已停止。", stderr_buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
