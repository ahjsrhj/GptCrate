import json
import unittest
from unittest import mock

from gpt_register import mail
from gpt_register import oauth as oauth_helpers


class OAuthHelperTests(unittest.TestCase):
    def test_extract_otp_code_matches_expected_patterns(self):
        content = "Subject: Verify\nYour ChatGPT code is 123456"
        self.assertEqual(mail._extract_otp_code(content), "123456")

    def test_submit_callback_url_builds_token_payload(self):
        fake_token_response = {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "id_token": "header.payload.signature",
            "expires_in": 3600,
        }
        fake_claims = {
            "email": "user@example.com",
            "https://api.openai.com/auth": {"chatgpt_account_id": "acct_123"},
        }

        with mock.patch.object(oauth_helpers, "_post_form", return_value=fake_token_response), \
             mock.patch.object(oauth_helpers, "_jwt_claims_no_verify", return_value=fake_claims), \
             mock.patch.object(oauth_helpers.time, "time", return_value=1_700_000_000):
            result = oauth_helpers.submit_callback_url(
                callback_url="http://localhost:1455/auth/callback?code=abc&state=xyz",
                expected_state="xyz",
                code_verifier="verifier",
            )

        payload = json.loads(result)
        self.assertEqual(payload["access_token"], "access-token")
        self.assertEqual(payload["refresh_token"], "refresh-token")
        self.assertEqual(payload["account_id"], "acct_123")
        self.assertEqual(payload["email"], "user@example.com")

    def test_post_with_retry_retries_three_times_on_timeout_before_success(self):
        session = mock.Mock()
        timeout_error = Exception(
            "Failed to perform, curl: (28) Connection timed out after 15001 milliseconds."
        )
        response = mock.Mock(status_code=200)
        session.post.side_effect = [timeout_error, timeout_error, timeout_error, response]

        with mock.patch.object(oauth_helpers.time, "sleep") as sleep_mock:
            result = oauth_helpers._post_with_retry(
                session,
                "https://example.com/api",
                headers={"content-type": "application/json"},
                json_body={},
                retries=1,
            )

        self.assertIs(result, response)
        self.assertEqual(session.post.call_count, 4)
        self.assertEqual(sleep_mock.call_count, 3)


if __name__ == "__main__":
    unittest.main()
