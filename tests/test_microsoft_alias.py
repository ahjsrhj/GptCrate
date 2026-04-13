import unittest
from unittest import mock

from gpt_register import microsoft_alias


class MicrosoftAliasTests(unittest.TestCase):
    def test_normalize_base_email_removes_existing_plus_suffix(self):
        normalized = microsoft_alias.normalize_microsoft_alias_base_email("demo+legacy@outlook.com")

        self.assertEqual(normalized, "demo@outlook.com")

    def test_expand_alias_emails_generates_five_aliases_without_original(self):
        with mock.patch.object(microsoft_alias.random, "choices") as choices_mock:
            choices_mock.side_effect = [
                list("abcdef"),
                list("ghijkl"),
                list("mnopqr"),
                list("stuvwx"),
                list("yzabcd"),
            ]
            aliases = microsoft_alias.expand_microsoft_alias_emails(
                "demo+legacy@outlook.com",
                count=5,
                include_original=False,
            )

        self.assertEqual(
            aliases,
            [
                "demo+abcdef@outlook.com",
                "demo+ghijkl@outlook.com",
                "demo+mnopqr@outlook.com",
                "demo+stuvwx@outlook.com",
                "demo+yzabcd@outlook.com",
            ],
        )
