import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from gpt_register import token_organizer


@contextmanager
def chdir(path: str):
    previous = Path.cwd()
    try:
        import os

        os.chdir(path)
        yield
    finally:
        os.chdir(previous)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_bundle(run_dir: Path, email: str, timestamp: int) -> None:
    safe_email = email.replace("@", "_")
    write_json(
        run_dir / "cpa" / f"token_{safe_email}_{timestamp}.json",
        {
            "email": email,
            "type": "codex",
            "access_token": f"access-{email}",
        },
    )
    write_json(
        run_dir / "sub" / f"sub_{safe_email}_{timestamp}.json",
        {
            "exported_at": "2026-04-13T00:00:00Z",
            "proxies": [],
            "accounts": [
                {
                    "name": email,
                    "platform": "openai",
                    "type": "oauth",
                    "credentials": {
                        "access_token": f"access-{email}",
                        "refresh_token": f"refresh-{email}",
                    },
                    "extra": {
                        "email": email,
                    },
                }
            ],
        },
    )


def write_run(run_dir: Path, emails: list[str]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "cpa").mkdir(exist_ok=True)
    (run_dir / "sub").mkdir(exist_ok=True)
    accounts_text = "\n".join(f"{email}----pass-{index}" for index, email in enumerate(emails, start=1))
    if accounts_text:
        accounts_text += "\n"
    (run_dir / "accounts.txt").write_text(accounts_text, encoding="utf-8")
    for timestamp, email in enumerate(emails, start=1):
        write_bundle(run_dir, email, timestamp)


class TokenOrganizerTests(unittest.TestCase):
    def test_single_directory_success_rebuilds_out_and_preserves_other_files(self):
        with tempfile.TemporaryDirectory() as temp_dir, chdir(temp_dir):
            write_run(
                Path("tokens/run_20260413_171715"),
                ["alpha@hotmail.com", "beta@hotmail.com"],
            )
            Path("out/cpa").mkdir(parents=True, exist_ok=True)
            Path("out/cpa/old.json").write_text("{}", encoding="utf-8")
            Path("out/keep.txt").write_text("keep", encoding="utf-8")

            exit_code = token_organizer.main(["1"])

            self.assertEqual(exit_code, 0)
            self.assertTrue(Path("out/keep.txt").exists())
            self.assertFalse(Path("out/cpa/old.json").exists())
            self.assertTrue(Path("out/cpa/token_alpha_hotmail.com_1.json").exists())
            sub_data = json.loads(Path("out/sub.json").read_text(encoding="utf-8"))
            self.assertEqual([item["extra"]["email"] for item in sub_data["accounts"]], ["alpha@hotmail.com"])
            self.assertEqual(
                Path("tokens/run_20260413_171715/accounts.txt").read_text(encoding="utf-8"),
                "beta@hotmail.com----pass-2\n",
            )
            self.assertFalse(
                Path("tokens/run_20260413_171715/cpa/token_alpha_hotmail.com_1.json").exists()
            )
            self.assertFalse(
                Path("tokens/run_20260413_171715/sub/sub_alpha_hotmail.com_1.json").exists()
            )

    def test_cross_directory_success_uses_old_to_new_order(self):
        with tempfile.TemporaryDirectory() as temp_dir, chdir(temp_dir):
            write_run(Path("tokens_alt/run_20260413_171715"), ["first@hotmail.com"])
            write_run(Path("tokens_alt/run_20260413_171716"), ["second@hotmail.com"])

            exit_code = token_organizer.main(["2", "tokens_alt"])

            self.assertEqual(exit_code, 0)
            sub_data = json.loads(Path("out/sub.json").read_text(encoding="utf-8"))
            self.assertEqual(
                [item["extra"]["email"] for item in sub_data["accounts"]],
                ["first@hotmail.com", "second@hotmail.com"],
            )
            self.assertFalse(Path("tokens_alt/run_20260413_171715").exists())
            self.assertFalse(Path("tokens_alt/run_20260413_171716").exists())

    def test_shortage_rejected_keeps_source_unchanged(self):
        with tempfile.TemporaryDirectory() as temp_dir, chdir(temp_dir):
            write_run(Path("tokens/run_20260413_171715"), ["only@hotmail.com"])

            with mock.patch("builtins.input", return_value="n"):
                exit_code = token_organizer.main(["2"])

            self.assertEqual(exit_code, 1)
            self.assertFalse(Path("out").exists())
            self.assertEqual(
                Path("tokens/run_20260413_171715/accounts.txt").read_text(encoding="utf-8"),
                "only@hotmail.com----pass-1\n",
            )
            self.assertTrue(Path("tokens/run_20260413_171715/cpa/token_only_hotmail.com_1.json").exists())
            self.assertTrue(Path("tokens/run_20260413_171715/sub/sub_only_hotmail.com_1.json").exists())

    def test_shortage_accepted_processes_all_remaining_records(self):
        with tempfile.TemporaryDirectory() as temp_dir, chdir(temp_dir):
            write_run(Path("tokens/run_20260413_171715"), ["only@hotmail.com"])

            with mock.patch("builtins.input", return_value="y"):
                exit_code = token_organizer.main(["2"])

            self.assertEqual(exit_code, 0)
            sub_data = json.loads(Path("out/sub.json").read_text(encoding="utf-8"))
            self.assertEqual([item["extra"]["email"] for item in sub_data["accounts"]], ["only@hotmail.com"])
            self.assertFalse(Path("tokens/run_20260413_171715").exists())

    def test_missing_match_fails_without_mutating_source(self):
        with tempfile.TemporaryDirectory() as temp_dir, chdir(temp_dir):
            run_dir = Path("tokens/run_20260413_171715")
            write_run(run_dir, ["broken@hotmail.com"])
            (run_dir / "sub" / "sub_broken_hotmail.com_1.json").unlink()

            exit_code = token_organizer.main(["1"])

            self.assertEqual(exit_code, 1)
            self.assertFalse(Path("out").exists())
            self.assertTrue(Path("tokens/run_20260413_171715/accounts.txt").exists())
            self.assertTrue(Path("tokens/run_20260413_171715/cpa/token_broken_hotmail.com_1.json").exists())
            self.assertFalse(Path("tokens/run_20260413_171715/sub/sub_broken_hotmail.com_1.json").exists())
            self.assertEqual(
                Path("tokens/run_20260413_171715/accounts.txt").read_text(encoding="utf-8"),
                "broken@hotmail.com----pass-1\n",
            )

    def test_success_also_removes_historical_empty_run_directories(self):
        with tempfile.TemporaryDirectory() as temp_dir, chdir(temp_dir):
            write_run(Path("tokens/run_20260413_171715"), ["cleanup@hotmail.com"])
            empty_run = Path("tokens/run_20260413_171716")
            (empty_run / "cpa").mkdir(parents=True, exist_ok=True)
            (empty_run / "sub").mkdir(parents=True, exist_ok=True)

            exit_code = token_organizer.main(["1"])

            self.assertEqual(exit_code, 0)
            self.assertFalse(Path("tokens/run_20260413_171715").exists())
            self.assertFalse(empty_run.exists())


if __name__ == "__main__":
    unittest.main()
