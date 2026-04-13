from __future__ import annotations

import argparse
import copy
import json
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


class UserDeclinedError(Exception):
    """用户拒绝在库存不足时继续处理。"""


@dataclass(frozen=True)
class AccountLine:
    line_index: int
    raw_line: str
    email: str


@dataclass(frozen=True)
class SubSource:
    path: Path
    account: dict[str, Any]


@dataclass
class RunInventory:
    path: Path
    accounts_path: Path
    account_lines: list[AccountLine]
    cpa_index: dict[str, Path]
    sub_index: dict[str, SubSource]


@dataclass(frozen=True)
class SelectedRecord:
    run_dir: Path
    accounts_path: Path
    line_index: int
    raw_line: str
    email: str
    cpa_path: Path
    sub_path: Path
    sub_account: dict[str, Any]


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("数量必须是正整数") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("数量必须是正整数")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="整理 run_* 目录中的账号记录")
    parser.add_argument("count", type=_positive_int, help="要处理的账号数量")
    parser.add_argument("input_dir", nargs="?", default="tokens", help="输入目录，默认 tokens")
    return parser


def _extract_account_email_from_line(raw_line: str) -> str:
    return raw_line.split("----", 1)[0].strip()


def _load_json_object(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} 顶层不是 JSON 对象")
    return data


def _extract_cpa_email(path: Path) -> str:
    email = str(_load_json_object(path).get("email") or "").strip()
    if not email:
        raise ValueError(f"{path} 缺少 email 字段")
    return email


def _extract_sub_account(path: Path) -> dict[str, Any]:
    data = _load_json_object(path)
    accounts = data.get("accounts")
    if not isinstance(accounts, list) or not accounts:
        raise ValueError(f"{path} 的 accounts[0] 不存在")
    account = accounts[0]
    if not isinstance(account, dict):
        raise ValueError(f"{path} 的 accounts[0] 不是对象")
    return account


def _extract_sub_email_from_account(account: dict[str, Any], source: Path) -> str:
    extra = account.get("extra", {})
    extra_email = ""
    if isinstance(extra, dict):
        extra_email = str(extra.get("email") or "").strip()
    email = extra_email or str(account.get("name") or "").strip()
    if not email:
        raise ValueError(f"{source} 的 accounts[0] 缺少邮箱信息")
    return email


def _build_cpa_index(cpa_dir: Path) -> dict[str, Path]:
    index: dict[str, Path] = {}
    if not cpa_dir.is_dir():
        return index
    for path in sorted(cpa_dir.glob("*.json")):
        email = _extract_cpa_email(path)
        if email in index:
            raise ValueError(f"{cpa_dir} 中邮箱 {email} 存在重复 cpa JSON")
        index[email] = path
    return index


def _build_sub_index(sub_dir: Path) -> dict[str, SubSource]:
    index: dict[str, SubSource] = {}
    if not sub_dir.is_dir():
        return index
    for path in sorted(sub_dir.glob("*.json")):
        account = _extract_sub_account(path)
        email = _extract_sub_email_from_account(account, path)
        if email in index:
            raise ValueError(f"{sub_dir} 中邮箱 {email} 存在重复 sub JSON")
        index[email] = SubSource(path=path, account=account)
    return index


def _load_account_lines(accounts_path: Path) -> list[AccountLine]:
    if not accounts_path.exists():
        return []
    lines: list[AccountLine] = []
    for index, raw_line in enumerate(accounts_path.read_text(encoding="utf-8").splitlines()):
        if not raw_line.strip():
            continue
        email = _extract_account_email_from_line(raw_line)
        if not email:
            continue
        lines.append(AccountLine(line_index=index, raw_line=raw_line, email=email))
    return lines


def scan_run_directories(input_dir: Path) -> list[RunInventory]:
    if not input_dir.exists():
        raise FileNotFoundError(f"目录不存在: {input_dir}")
    if not input_dir.is_dir():
        raise NotADirectoryError(f"不是目录: {input_dir}")

    inventories: list[RunInventory] = []
    run_dirs = sorted(path for path in input_dir.iterdir() if path.is_dir() and path.name.startswith("run_"))
    for run_dir in run_dirs:
        accounts_path = run_dir / "accounts.txt"
        inventories.append(
            RunInventory(
                path=run_dir,
                accounts_path=accounts_path,
                account_lines=_load_account_lines(accounts_path),
                cpa_index=_build_cpa_index(run_dir / "cpa"),
                sub_index=_build_sub_index(run_dir / "sub"),
            )
        )
    return inventories


def _confirm_shortage(requested: int, available: int, input_func: Callable[[str], str]) -> int:
    if available <= 0:
        raise ValueError("没有可处理的记录")
    prompt = (
        f"请求 {requested} 条，但当前仅有 {available} 条可处理记录。"
        "是否继续把剩余的都处理掉？[y/N]: "
    )
    answer = input_func(prompt).strip().lower()
    if answer not in {"y", "yes"}:
        raise UserDeclinedError("用户取消处理")
    return available


def select_records(
    inventories: list[RunInventory],
    requested_count: int,
    input_func: Callable[[str], str],
) -> list[SelectedRecord]:
    available = sum(len(inventory.account_lines) for inventory in inventories)
    actual_count = requested_count
    if requested_count > available:
        actual_count = _confirm_shortage(requested_count, available, input_func)

    selected: list[SelectedRecord] = []
    used_cpa_paths: set[Path] = set()
    used_sub_paths: set[Path] = set()
    for inventory in inventories:
        for account_line in inventory.account_lines:
            if len(selected) >= actual_count:
                return selected

            cpa_path = inventory.cpa_index.get(account_line.email)
            if cpa_path is None:
                raise ValueError(f"{inventory.path} 中邮箱 {account_line.email} 缺少对应 cpa JSON")

            sub_source = inventory.sub_index.get(account_line.email)
            if sub_source is None:
                raise ValueError(f"{inventory.path} 中邮箱 {account_line.email} 缺少对应 sub JSON")

            if cpa_path in used_cpa_paths:
                raise ValueError(f"{inventory.path} 中邮箱 {account_line.email} 复用了同一个 cpa JSON")
            if sub_source.path in used_sub_paths:
                raise ValueError(f"{inventory.path} 中邮箱 {account_line.email} 复用了同一个 sub JSON")

            used_cpa_paths.add(cpa_path)
            used_sub_paths.add(sub_source.path)
            selected.append(
                SelectedRecord(
                    run_dir=inventory.path,
                    accounts_path=inventory.accounts_path,
                    line_index=account_line.line_index,
                    raw_line=account_line.raw_line,
                    email=account_line.email,
                    cpa_path=cpa_path,
                    sub_path=sub_source.path,
                    sub_account=copy.deepcopy(sub_source.account),
                )
            )
    return selected


def _build_sub_export(accounts: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    return {
        "exported_at": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "proxies": [],
        "accounts": accounts,
    }


def _stage_output(
    selected: list[SelectedRecord],
    output_dir: Path,
    now: datetime,
) -> Path:
    staging_root = Path(tempfile.mkdtemp(prefix=".organize_tokens_", dir=output_dir.parent))
    staging_cpa_dir = staging_root / "cpa"
    staging_cpa_dir.mkdir(parents=True, exist_ok=True)

    accounts_content = "\n".join(record.raw_line for record in selected)
    if accounts_content:
        accounts_content += "\n"
    (staging_root / "accounts.txt").write_text(accounts_content, encoding="utf-8")

    for record in selected:
        shutil.copy2(record.cpa_path, staging_cpa_dir / record.cpa_path.name)

    sub_payload = _build_sub_export([copy.deepcopy(record.sub_account) for record in selected], now)
    with (staging_root / "sub.json").open("w", encoding="utf-8") as handle:
        json.dump(sub_payload, handle, ensure_ascii=False, indent=2)
    return staging_root


def _validate_staged_output(selected: list[SelectedRecord], staging_root: Path) -> None:
    expected_emails = [record.email for record in selected]
    staged_account_lines = [
        raw_line
        for raw_line in (staging_root / "accounts.txt").read_text(encoding="utf-8").splitlines()
        if raw_line.strip()
    ]
    staged_account_emails = [_extract_account_email_from_line(raw_line) for raw_line in staged_account_lines]
    staged_cpa_emails = [
        _extract_cpa_email(staging_root / "cpa" / record.cpa_path.name)
        for record in selected
    ]

    sub_data = _load_json_object(staging_root / "sub.json")
    sub_accounts = sub_data.get("accounts")
    if not isinstance(sub_accounts, list):
        raise ValueError("输出的 sub.json 中 accounts 不是数组")
    staged_sub_emails = [
        _extract_sub_email_from_account(account, staging_root / "sub.json")
        for account in sub_accounts
        if isinstance(account, dict)
    ]
    if len(staged_sub_emails) != len(sub_accounts):
        raise ValueError("输出的 sub.json 中存在非对象账号")

    if expected_emails != staged_account_emails:
        raise ValueError("输出的 accounts.txt 账号顺序与已选账号不一致")
    if expected_emails != staged_cpa_emails:
        raise ValueError("输出的 cpa 账号顺序与已选账号不一致")
    if expected_emails != staged_sub_emails:
        raise ValueError("输出的 sub 账号顺序与已选账号不一致")


def _apply_staged_output(staging_root: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    target_cpa_dir = output_dir / "cpa"
    if target_cpa_dir.exists():
        shutil.rmtree(target_cpa_dir)
    shutil.move(str(staging_root / "cpa"), str(target_cpa_dir))

    staged_sub_path = staging_root / "sub.json"
    temp_sub_path = output_dir / ".sub.json.tmp"
    shutil.copy2(staged_sub_path, temp_sub_path)
    temp_sub_path.replace(output_dir / "sub.json")

    staged_accounts_path = staging_root / "accounts.txt"
    temp_accounts_path = output_dir / ".accounts.txt.tmp"
    shutil.copy2(staged_accounts_path, temp_accounts_path)
    temp_accounts_path.replace(output_dir / "accounts.txt")


def _write_remaining_lines(accounts_path: Path, removed_indexes: set[int]) -> None:
    if not accounts_path.exists():
        return
    raw_lines = accounts_path.read_text(encoding="utf-8").splitlines()
    remaining = [line for index, line in enumerate(raw_lines) if index not in removed_indexes]
    content = "\n".join(remaining)
    if remaining:
        content += "\n"
    accounts_path.write_text(content, encoding="utf-8")


def _run_dir_has_json(json_dir: Path) -> bool:
    return json_dir.is_dir() and any(json_dir.glob("*.json"))


def _run_dir_has_records(run_dir: Path) -> bool:
    accounts_path = run_dir / "accounts.txt"
    if accounts_path.exists():
        for raw_line in accounts_path.read_text(encoding="utf-8").splitlines():
            if _extract_account_email_from_line(raw_line):
                return True
    return _run_dir_has_json(run_dir / "cpa") or _run_dir_has_json(run_dir / "sub")


def _run_dir_has_unexpected_entries(run_dir: Path) -> bool:
    expected_names = {"accounts.txt", "cpa", "sub"}
    for path in run_dir.iterdir():
        if path.name not in expected_names:
            return True
    return False


def _delete_run_dir_if_empty(run_dir: Path) -> None:
    if not run_dir.exists():
        return
    if _run_dir_has_records(run_dir) or _run_dir_has_unexpected_entries(run_dir):
        return
    shutil.rmtree(run_dir)


def _cleanup_sources(inventories: list[RunInventory], selected: list[SelectedRecord]) -> None:
    removed_line_indexes: dict[Path, set[int]] = {}
    cpa_paths: set[Path] = set()
    sub_paths: set[Path] = set()

    for record in selected:
        removed_line_indexes.setdefault(record.accounts_path, set()).add(record.line_index)
        cpa_paths.add(record.cpa_path)
        sub_paths.add(record.sub_path)

    for accounts_path, indexes in removed_line_indexes.items():
        _write_remaining_lines(accounts_path, indexes)

    for path in sorted(cpa_paths):
        if path.exists():
            path.unlink()

    for path in sorted(sub_paths):
        if path.exists():
            path.unlink()

    for inventory in inventories:
        _delete_run_dir_if_empty(inventory.path)


def organize_tokens(
    count: int,
    input_dir: str | Path = "tokens",
    *,
    cwd: Path | None = None,
    input_func: Callable[[str], str] | None = None,
    now: datetime | None = None,
) -> list[SelectedRecord]:
    base_dir = Path(cwd or Path.cwd())
    source_dir = Path(input_dir)
    if not source_dir.is_absolute():
        source_dir = base_dir / source_dir

    inventories = scan_run_directories(source_dir)
    if not inventories:
        raise ValueError(f"{source_dir} 下没有 run_* 子目录")

    resolved_input = input_func or input
    selected = select_records(inventories, count, resolved_input)
    if not selected:
        raise ValueError("没有选中任何记录")

    output_dir = base_dir / "out"
    current_time = now or datetime.now(timezone.utc)
    staging_root = _stage_output(selected, output_dir, current_time)

    try:
        _validate_staged_output(selected, staging_root)
        _apply_staged_output(staging_root, output_dir)
        _cleanup_sources(inventories, selected)
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)

    return selected


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        selected = organize_tokens(args.count, args.input_dir)
    except UserDeclinedError:
        print("已取消，未做任何修改。")
        return 1
    except Exception as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    print(f"处理完成，共整理 {len(selected)} 条记录，输出目录: {Path.cwd() / 'out'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
