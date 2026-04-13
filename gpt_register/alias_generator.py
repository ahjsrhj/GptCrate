from __future__ import annotations

import argparse
import random
import string
from dataclasses import dataclass
from pathlib import Path


SUPPORTED_PREFIXES = ("hotmail.", "outlook.")


@dataclass
class AliasGenerationResult:
    aliases: list[str]
    valid_count: int
    skipped_count: int
    removed_count: int
    skipped_lines: list[str]
    remaining_lines: list[str]


def backup_file(path: Path) -> Path:
    backup_path = path.with_suffix(path.suffix + ".bak") if path.suffix else Path(str(path) + ".bak")
    backup_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return backup_path


def is_supported_outlook_email(email: str) -> bool:
    email = (email or "").strip().lower()
    if "@" not in email:
        return False
    domain = email.split("@", 1)[1]
    return domain.startswith(SUPPORTED_PREFIXES)


def split_account_line(line: str) -> tuple[str, list[str]]:
    parts = [part.strip() for part in str(line).rstrip().split("----")]
    if not parts:
        return "", []
    return parts[0], parts[1:]


def random_suffix(length: int = 6) -> str:
    return "".join(random.choices(string.ascii_lowercase, k=length))


def build_alias_email(email: str, suffix: str) -> str:
    local, domain = email.split("@", 1)
    return f"{local}+{suffix}@{domain}"


def generate_aliases_from_lines(
    raw_lines: list[str],
    *,
    per_email: int = 5,
    preserve_fields: bool = True,
    remove_processed: bool = False,
    shuffle_output: bool = True,
    suffix_length: int = 6,
) -> AliasGenerationResult:
    aliases: list[str] = []
    skipped_lines: list[str] = []
    remaining_lines: list[str] = []
    valid_count = 0
    removed_count = 0

    for raw in raw_lines:
        line = str(raw).strip()
        if not line:
            continue
        email, rest = split_account_line(line)
        if not is_supported_outlook_email(email):
            skipped_lines.append(line)
            remaining_lines.append(line)
            continue

        valid_count += 1
        count = max(1, int(per_email))
        for _ in range(count):
            alias = build_alias_email(email, random_suffix(suffix_length))
            aliases.append("----".join([alias, *rest]) if preserve_fields and rest else alias)

        if remove_processed:
            removed_count += 1
        else:
            remaining_lines.append(line)

    if shuffle_output:
        random.shuffle(aliases)

    return AliasGenerationResult(
        aliases=aliases,
        valid_count=valid_count,
        skipped_count=len(skipped_lines),
        removed_count=removed_count,
        skipped_lines=skipped_lines,
        remaining_lines=remaining_lines,
    )


def _read_multiline_input() -> list[str]:
    print("请直接粘贴账号文本，输入单独一行 END 结束：")
    lines: list[str] = []
    while True:
        line = input().rstrip("\n")
        if line.strip().upper() == "END":
            break
        lines.append(line)
    return lines


def _prompt_bool(prompt: str, default: bool = True) -> bool:
    suffix = "Y/n" if default else "y/N"
    raw = input(f"{prompt} [{suffix}]: ").strip().lower()
    if not raw:
        return default
    return raw in {"y", "yes", "1", "true"}


def run_interactive() -> int:
    print("=" * 56)
    print(" 微软邮箱多别名生成器")
    print("=" * 56)
    print("支持 @hotmail.* 和 @outlook.* 邮箱，默认保留原有字段。")
    print("格式示例: email----password----client_id----refresh_token")
    print()

    source_path_raw = input("输入源文件路径（留空则手动粘贴，默认 accounts.txt）: ").strip()
    use_manual_input = source_path_raw.lower() == "paste"
    source_path = Path(source_path_raw or "accounts.txt")

    if use_manual_input:
        raw_lines = _read_multiline_input()
    else:
        if not source_path.exists():
            print(f"[Error] 文件不存在: {source_path}")
            return 1
        raw_lines = source_path.read_text(encoding="utf-8").splitlines()

    try:
        per_email = int(input("每个邮箱生成数量（默认 5）: ").strip() or "5")
    except ValueError:
        per_email = 5
    per_email = max(1, per_email)

    preserve_fields = _prompt_bool("保留原字段", True)
    shuffle_output = _prompt_bool("打乱输出顺序", True)
    remove_processed = False if use_manual_input else _prompt_bool("生成后从源文件移除已处理原邮箱", False)
    overwrite_accounts = False if use_manual_input else _prompt_bool("直接覆盖 accounts.txt（会先自动备份）", source_path.name == "accounts.txt")
    default_output = str(source_path if overwrite_accounts else "alias_result.txt")
    output_path = Path(input(f"输出文件路径（默认 {default_output}）: ").strip() or default_output)
    result = generate_aliases_from_lines(
        raw_lines,
        per_email=per_email,
        preserve_fields=preserve_fields,
        remove_processed=remove_processed,
        shuffle_output=shuffle_output,
    )
    backup_path: Path | None = None
    if overwrite_accounts and not use_manual_input:
        backup_path = backup_file(source_path)
    output_path.write_text("\n".join(result.aliases) + ("\n" if result.aliases else ""), encoding="utf-8")
    if remove_processed and not use_manual_input and output_path != source_path:
        source_path.write_text("\n".join(result.remaining_lines) + ("\n" if result.remaining_lines else ""), encoding="utf-8")

    print()
    print("处理完成：")
    print(f"  已生成 {len(result.aliases)} 条别名")
    print(f"  有效邮箱 {result.valid_count} 行")
    print(f"  跳过 {result.skipped_count} 行")
    print(f"  已移除原邮箱 {result.removed_count} 行")
    print(f"  结果文件: {output_path}")
    if backup_path:
        print(f"  源文件备份: {backup_path}")
    if result.aliases:
        print()
        print("前 10 条结果：")
        for line in result.aliases[:10]:
            print(f"  {line}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="微软邮箱多别名生成器")
    parser.add_argument("--input", dest="input_path", default="accounts.txt", help="输入文件路径")
    parser.add_argument("--output", dest="output_path", default="alias_result.txt", help="输出文件路径")
    parser.add_argument("--per-email", type=int, default=5, help="每个邮箱生成数量")
    parser.add_argument("--no-preserve-fields", action="store_true", help="只输出别名邮箱，不保留其余字段")
    parser.add_argument("--no-shuffle", action="store_true", help="不打乱输出顺序")
    parser.add_argument("--remove-processed", action="store_true", help="生成后从源文件移除已处理原邮箱")
    parser.add_argument("--overwrite-accounts", action="store_true", help="直接覆盖输入文件（会先创建 .bak 备份）")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    input_path = Path(args.input_path)
    if not input_path.exists():
        print(f"[Error] 文件不存在: {input_path}")
        return 1

    raw_lines = input_path.read_text(encoding="utf-8").splitlines()
    result = generate_aliases_from_lines(
        raw_lines,
        per_email=max(1, args.per_email),
        preserve_fields=not args.no_preserve_fields,
        remove_processed=args.remove_processed,
        shuffle_output=not args.no_shuffle,
    )

    output_path = input_path if args.overwrite_accounts else Path(args.output_path)
    if args.overwrite_accounts:
        backup_path = backup_file(input_path)
    else:
        backup_path = None
    output_path.write_text("\n".join(result.aliases) + ("\n" if result.aliases else ""), encoding="utf-8")
    if args.remove_processed and not args.overwrite_accounts:
        input_path.write_text("\n".join(result.remaining_lines) + ("\n" if result.remaining_lines else ""), encoding="utf-8")

    summary = (
        f"已生成 {len(result.aliases)} 条别名 | 有效邮箱 {result.valid_count} 行 | "
        f"跳过 {result.skipped_count} 行 | 已移除 {result.removed_count} 行 | 输出: {output_path}"
    )
    if backup_path:
        summary += f" | 备份: {backup_path}"
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
