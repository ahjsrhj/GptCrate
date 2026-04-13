import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gpt_register import alias_generator


class AliasGeneratorTests(unittest.TestCase):
    def test_generate_aliases_preserves_fields_and_skips_unsupported(self):
        with mock.patch.object(alias_generator, "random_suffix", side_effect=["abc123", "def456"]):
            result = alias_generator.generate_aliases_from_lines(
                [
                    "user@hotmail.com----pass----client----refresh",
                    "user@gmail.com----pass",
                ],
                per_email=2,
                preserve_fields=True,
                remove_processed=False,
                shuffle_output=False,
            )

        self.assertEqual(
            result.aliases,
            [
                "user+abc123@hotmail.com----pass----client----refresh",
                "user+def456@hotmail.com----pass----client----refresh",
            ],
        )
        self.assertEqual(result.valid_count, 1)
        self.assertEqual(result.skipped_count, 1)
        self.assertIn("user@gmail.com----pass", result.remaining_lines)

    def test_generate_aliases_can_remove_processed_from_input(self):
        with mock.patch.object(alias_generator, "random_suffix", return_value="abc123"):
            result = alias_generator.generate_aliases_from_lines(
                [
                    "user@hotmail.com----pass",
                    "user2@outlook.com----pass2",
                ],
                per_email=1,
                remove_processed=True,
                shuffle_output=False,
            )

        self.assertEqual(result.removed_count, 2)
        self.assertEqual(result.remaining_lines, [])

    def test_cli_main_writes_output_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "accounts.txt"
            output_path = Path(temp_dir) / "result.txt"
            input_path.write_text("user@hotmail.com----pass\n", encoding="utf-8")

            with mock.patch.object(alias_generator, "random_suffix", return_value="abc123"):
                exit_code = alias_generator.main(
                    [
                        "--input",
                        str(input_path),
                        "--output",
                        str(output_path),
                        "--per-email",
                        "1",
                        "--no-shuffle",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(output_path.read_text(encoding="utf-8").strip(), "user+abc123@hotmail.com----pass")

    def test_cli_main_can_overwrite_input_with_backup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "accounts.txt"
            input_path.write_text("user@hotmail.com----pass\n", encoding="utf-8")

            with mock.patch.object(alias_generator, "random_suffix", return_value="abc123"):
                exit_code = alias_generator.main(
                    [
                        "--input",
                        str(input_path),
                        "--per-email",
                        "1",
                        "--no-shuffle",
                        "--overwrite-accounts",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(input_path.read_text(encoding="utf-8").strip(), "user+abc123@hotmail.com----pass")
            backup_path = Path(str(input_path) + ".bak")
            self.assertTrue(backup_path.exists())
            self.assertEqual(backup_path.read_text(encoding="utf-8").strip(), "user@hotmail.com----pass")


if __name__ == "__main__":
    unittest.main()
