import unittest
from unittest import mock

from gpt_register import cf_mail
from gpt_register import context as ctx


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class CfMailTests(unittest.TestCase):
    def setUp(self):
        self._orig_worker_base = ctx.MAIL_WORKER_BASE
        self._orig_admin_password = ctx.MAIL_ADMIN_PASSWORD
        self._orig_mail_domain = ctx.MAIL_DOMAIN

    def tearDown(self):
        ctx.MAIL_WORKER_BASE = self._orig_worker_base
        ctx.MAIL_ADMIN_PASSWORD = self._orig_admin_password
        ctx.MAIL_DOMAIN = self._orig_mail_domain

    def test_get_oai_code_fallbacks_to_email_param_when_address_returns_api_error(self):
        ctx.MAIL_WORKER_BASE = "https://worker.example.com"
        ctx.MAIL_ADMIN_PASSWORD = "secret"

        get_mock = mock.Mock(
            side_effect=[
                _FakeResponse(status_code=400, payload={"error": "api 错误: address 参数不支持"}),
                _FakeResponse(status_code=200, payload={"results": [{"id": "m1", "subject": "Your ChatGPT code is 123456"}]}),
            ]
        )

        with mock.patch.object(cf_mail.requests, "get", get_mock), mock.patch.object(cf_mail.time, "sleep", return_value=None):
            code = cf_mail.get_oai_code("user@example.com")

        self.assertEqual(code, "123456")
        self.assertEqual(get_mock.call_count, 2)
        self.assertIn("address", get_mock.call_args_list[0].kwargs["params"])
        self.assertIn("email", get_mock.call_args_list[1].kwargs["params"])

    def test_get_oai_code_supports_data_items_shape(self):
        ctx.MAIL_WORKER_BASE = "https://worker.example.com"
        ctx.MAIL_ADMIN_PASSWORD = "secret"

        with mock.patch.object(
            cf_mail.requests,
            "get",
            return_value=_FakeResponse(
                status_code=200,
                payload={"data": {"items": [{"_id": "msg-1", "text": "verification code to continue: 654321"}]}},
            ),
        ), mock.patch.object(cf_mail.time, "sleep", return_value=None):
            code = cf_mail.get_oai_code("user@example.com")

        self.assertEqual(code, "654321")

    def test_get_oai_code_decodes_multipart_raw_email(self):
        ctx.MAIL_WORKER_BASE = "https://worker.example.com"
        ctx.MAIL_ADMIN_PASSWORD = "secret"

        raw_mail = (
            "Subject: =?UTF-8?Q?Your_ChatGPT_code?=\r\n"
            "MIME-Version: 1.0\r\n"
            "Content-Type: multipart/alternative; boundary=\"abc\"\r\n"
            "\r\n"
            "--abc\r\n"
            "Content-Type: text/plain; charset=UTF-8\r\n"
            "Content-Transfer-Encoding: quoted-printable\r\n"
            "\r\n"
            "Your ChatGPT code is 755838\r\n"
            "--abc--\r\n"
        )

        with mock.patch.object(
            cf_mail.requests,
            "get",
            return_value=_FakeResponse(
                status_code=200,
                payload={"results": [{"id": "m2", "raw": raw_mail}]},
            ),
        ), mock.patch.object(cf_mail.time, "sleep", return_value=None):
            code = cf_mail.get_oai_code("user@example.com")

        self.assertEqual(code, "755838")

    def test_generate_email_returns_empty_when_domain_missing(self):
        ctx.MAIL_DOMAIN = ""

        email, token = cf_mail.generate_email()

        self.assertEqual((email, token), ("", ""))


if __name__ == "__main__":
    unittest.main()
