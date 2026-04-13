import os
import random
import string
import threading
import time
import urllib.parse
from dataclasses import dataclass
from typing import Dict, List, Optional



def _load_dotenv(path: str = ".env") -> None:
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for raw in handle:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                if not key or key in os.environ:
                    continue
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                    value = value[1:-1]
                os.environ[key] = value
    except Exception:
        pass


_load_dotenv()

MAIL_DOMAIN = os.getenv("MAIL_DOMAIN", "")
MAIL_WORKER_BASE = os.getenv("MAIL_WORKER_BASE", "").rstrip("/")
MAIL_ADMIN_PASSWORD = os.getenv("MAIL_ADMIN_PASSWORD", "")
TOKEN_OUTPUT_DIR = (os.getenv("TOKEN_OUTPUT_DIR") or "./tokens").strip()
CLI_PROXY_AUTHS_DIR = os.getenv("CLI_PROXY_AUTHS_DIR", "").strip()
CODEX2API_BASE_URL = os.getenv("CODEX2API_BASE_URL", "").strip().rstrip("/")
CODEX2API_ADMIN_SECRET = os.getenv("CODEX2API_ADMIN_SECRET", "").strip()

RESIN_URL = os.getenv("RESIN_URL", "").strip()
RESIN_PLATFORM_NAME = os.getenv("RESIN_PLATFORM_NAME", "").strip()

PROXY_FILE = os.getenv("PROXY_FILE", "").strip()
SINGLE_PROXY = os.getenv("PROXY", "").strip()
BATCH_COUNT = os.getenv("BATCH_COUNT", "").strip()
BATCH_THREADS = os.getenv("BATCH_THREADS", "").strip()

EMAIL_MODE = os.getenv("EMAIL_MODE", "cf").strip().lower()
HOTMAIL007_API_URL = os.getenv("HOTMAIL007_API_URL", "https://gapi.hotmail007.com").rstrip("/")
HOTMAIL007_API_KEY = os.getenv("HOTMAIL007_API_KEY", "").strip()
HOTMAIL007_MAIL_TYPE = os.getenv("HOTMAIL007_MAIL_TYPE", "outlook").strip()
HOTMAIL007_MAIL_MODE = os.getenv("HOTMAIL007_MAIL_MODE", "graph").strip().lower()
HOTMAIL007_ALIAS_SPLIT_ENABLED = os.getenv("HOTMAIL007_ALIAS_SPLIT_ENABLED", "false").strip().lower() == "true"
try:
    HOTMAIL007_MAX_RETRY = max(1, int(os.getenv("HOTMAIL007_MAX_RETRY", "3").strip()))
except ValueError:
    HOTMAIL007_MAX_RETRY = 3
LOCAL_OUTLOOK_MAIL_MODE = os.getenv("LOCAL_OUTLOOK_MAIL_MODE", "graph").strip().lower()
LOCAL_OUTLOOK_BAD_FILE = os.getenv("LOCAL_OUTLOOK_BAD_FILE", "bad_local_outlook.txt").strip()

LUCKMAIL_API_KEY = os.getenv("LUCKMAIL_API_KEY", "").strip()
LUCKMAIL_API_URL = os.getenv("LUCKMAIL_API_URL", "https://mails.luckyous.com/api/v1/openapi").rstrip("/")
LUCKMAIL_AUTO_BUY = os.getenv("LUCKMAIL_AUTO_BUY", "true").strip().lower() == "true"
LUCKMAIL_PURCHASED_ONLY = os.getenv("LUCKMAIL_PURCHASED_ONLY", "false").strip().lower() == "true"
LUCKMAIL_SKIP_PURCHASED = os.getenv("LUCKMAIL_SKIP_PURCHASED", "false").strip().lower() == "true"
LUCKMAIL_OWN_ONLY = os.getenv("LUCKMAIL_OWN_ONLY", "false").strip().lower() == "true"
LUCKMAIL_MAIL_DEBUG = os.getenv("LUCKMAIL_MAIL_DEBUG", "false").strip().lower() == "true"
LUCKMAIL_EMAIL_TYPE = os.getenv("LUCKMAIL_EMAIL_TYPE", "ms_imap").strip().lower()
try:
    LUCKMAIL_MAX_RETRY = int(os.getenv("LUCKMAIL_MAX_RETRY", "3").strip())
except ValueError:
    LUCKMAIL_MAX_RETRY = 3
try:
    LUCKMAIL_CHECK_WORKERS = max(1, int(os.getenv("LUCKMAIL_CHECK_WORKERS", "20").strip()))
except ValueError:
    LUCKMAIL_CHECK_WORKERS = 20

ACCOUNTS_FILE = os.getenv("ACCOUNTS_FILE", "accounts.txt").strip()
AUTO_REGISTER_THRESHOLD = 10
_LOG_THREAD_COLORS = (
    "cyan",
    "green",
    "yellow",
    "blue",
    "magenta",
    "red",
    "white",
)
_log_thread_local = threading.local()


def is_resin_enabled() -> bool:
    return bool(RESIN_URL and RESIN_PLATFORM_NAME)


def parse_resin_url(resin_url: Optional[str] = None) -> dict:
    raw = (resin_url if resin_url is not None else RESIN_URL).strip()
    if not raw:
        raise ValueError("RESIN_URL 未配置")

    parsed = urllib.parse.urlsplit(raw)
    token = parsed.path.lstrip("/")
    if not parsed.scheme:
        raise ValueError("RESIN_URL 缺少协议头")
    if not parsed.hostname:
        raise ValueError("RESIN_URL 缺少主机地址")
    if not token:
        raise ValueError("RESIN_URL 缺少 Token 路径")
    if "/" in token:
        raise ValueError("RESIN_URL Token 路径格式不正确")

    return {
        "scheme": parsed.scheme,
        "host": parsed.hostname,
        "port": parsed.port,
        "token": token,
    }


def compose_resin_proxy_url(
    platform: str,
    account: str,
    token: str,
    host: str,
    port: Optional[int] = None,
    scheme: str = "http",
) -> str:
    platform_name = str(platform or "").strip()
    account_name = str(account or "").strip()
    token_value = str(token or "").strip()
    host_name = str(host or "").strip()
    scheme_name = str(scheme or "").strip()

    if not platform_name:
        raise ValueError("RESIN_PLATFORM_NAME 未配置")
    if not account_name:
        raise ValueError("Resin Account 不能为空")
    if not token_value:
        raise ValueError("RESIN_URL 中未包含有效 Token")
    if not host_name:
        raise ValueError("RESIN_URL 中未包含有效主机地址")
    if not scheme_name:
        raise ValueError("RESIN_URL 中未包含有效协议")

    username = urllib.parse.quote(f"{platform_name}.{account_name}", safe=".")
    password = urllib.parse.quote(token_value, safe="")
    host_display = host_name
    if ":" in host_name and not host_name.startswith("["):
        host_display = f"[{host_name}]"
    port_part = f":{port}" if port is not None else ""
    return f"{scheme_name}://{username}:{password}@{host_display}{port_part}"


def _generate_resin_account(length: int = 6) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(random.choices(alphabet, k=length))


@dataclass
class ResinRunState:
    startup_account: str = ""
    current_account: str = ""

    def __post_init__(self) -> None:
        if not self.startup_account:
            self.get_resin_startup_account(force_new=True)
        elif not self.current_account:
            self.current_account = self.startup_account

    def get_resin_startup_account(self, force_new: bool = False) -> str:
        if force_new or not self.startup_account:
            self.startup_account = _generate_resin_account()
            self.current_account = self.startup_account
        elif not self.current_account:
            self.current_account = self.startup_account
        return self.startup_account

    def set_current_account(self, account: Optional[str]) -> str:
        account_value = normalize_resin_account(account)
        if not account_value:
            return self.get_resin_startup_account()
        self.current_account = account_value
        return self.current_account


def normalize_resin_account(account: Optional[str]) -> str:
    account_value = str(account or "").strip()
    if not account_value:
        return ""
    local_part, sep, _domain = account_value.partition("@")
    if sep and local_part:
        return local_part
    return account_value


def get_resin_startup_account(
    force_new: bool = False,
    *,
    resin_state: Optional[ResinRunState] = None,
) -> str:
    state = resin_state or ResinRunState()
    return state.get_resin_startup_account(force_new=force_new)


def set_log_thread_id(thread_id: Optional[int]) -> None:
    try:
        value = int(thread_id) if thread_id is not None else None
    except (TypeError, ValueError):
        value = None
    if value is not None and value <= 0:
        value = None
    _log_thread_local.thread_id = value


def clear_log_thread_id() -> None:
    _log_thread_local.thread_id = None


def get_log_thread_id() -> Optional[int]:
    value = getattr(_log_thread_local, "thread_id", None)
    if isinstance(value, int) and value > 0:
        return value
    return None


def get_log_thread_color(thread_id: Optional[int] = None) -> str:
    value = thread_id if thread_id is not None else get_log_thread_id()
    if not value:
        return "bright_black"
    return _LOG_THREAD_COLORS[(value - 1) % len(_LOG_THREAD_COLORS)]


def build_proxy_url(
    proxy: Optional[str],
    *,
    account: Optional[str] = None,
    resin_state: Optional[ResinRunState] = None,
) -> Optional[str]:
    if proxy:
        return proxy
    if not is_resin_enabled():
        return None

    state = resin_state or ResinRunState()
    if account is not None and str(account).strip():
        account_value = state.set_current_account(account)
    else:
        account_value = normalize_resin_account(state.current_account) or state.get_resin_startup_account()

    resin_config = parse_resin_url()
    return compose_resin_proxy_url(
        RESIN_PLATFORM_NAME,
        account_value,
        resin_config["token"],
        resin_config["host"],
        resin_config["port"],
        resin_config["scheme"],
    )


def extract_resin_account(proxy_url: Optional[str]) -> str:
    raw_proxy = str(proxy_url or "").strip()
    if not raw_proxy or not is_resin_enabled():
        return ""

    try:
        parsed_proxy = urllib.parse.urlsplit(raw_proxy)
        resin_config = parse_resin_url()
    except Exception:
        return ""

    if parsed_proxy.scheme != resin_config["scheme"]:
        return ""
    if parsed_proxy.hostname != resin_config["host"]:
        return ""
    if parsed_proxy.port != resin_config["port"]:
        return ""

    username = urllib.parse.unquote(parsed_proxy.username or "").strip()
    if not username:
        return ""

    platform_prefix = f"{RESIN_PLATFORM_NAME}."
    if not username.startswith(platform_prefix):
        return ""

    return normalize_resin_account(username[len(platform_prefix):])


def _load_proxies(filepath: str) -> List[str]:
    proxies_list: List[str] = []
    if not filepath or not os.path.exists(filepath):
        return proxies_list
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                proxies_list.append(line)
    except Exception as e:
        print(f"[Error] 加载代理文件失败 ({filepath}): {e}")
    return proxies_list


class ProxyRotator:
    """线程安全的代理轮换器 (round-robin)"""

    def __init__(self, proxy_list: List[str]):
        self._proxies = list(proxy_list) if proxy_list else []
        self._index = 0
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self._proxies)

    def next(self) -> Optional[str]:
        if not self._proxies:
            return None
        with self._lock:
            proxy = self._proxies[self._index % len(self._proxies)]
            self._index += 1
            return proxy


class EmailQueue:
    """线程安全的邮箱队列，从文件逐行读取并消费"""

    def __init__(self, filepath: str):
        self._filepath = filepath
        self._emails: List[str] = []
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self._filepath):
            return
        with open(self._filepath, "r", encoding="utf-8") as f:
            for line in f:
                addr = line.strip()
                if not addr or addr.startswith("#"):
                    continue
                if "----" in addr:
                    addr = addr.split("----")[0].strip()
                if addr and "@" in addr:
                    self._emails.append(addr)

    def pop(self) -> Optional[str]:
        with self._lock:
            if not self._emails:
                return None
            email = self._emails.pop(0)
            self._save_unlocked()
            return email

    def _save_unlocked(self) -> None:
        try:
            with open(self._filepath, "w", encoding="utf-8") as f:
                for email in self._emails:
                    f.write(email + "\n")
        except Exception:
            pass

    def __len__(self) -> int:
        with self._lock:
            return len(self._emails)


class LocalOutlookAccountQueue:
    """线程安全的本地 Outlook 账号队列，支持邮箱----密码----client_id----refresh_token"""

    def __init__(self, filepath: str):
        self._filepath = filepath
        self._accounts: List[dict] = []
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self._filepath):
            return
        with open(self._filepath, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                parts = [part.strip() for part in line.split("----", 3)]
                if len(parts) != 4:
                    continue
                email, password, client_id, refresh_token = parts
                if not email or "@" not in email or not client_id or not refresh_token:
                    continue
                self._accounts.append(
                    {
                        "email": email,
                        "password": password,
                        "client_id": client_id,
                        "refresh_token": refresh_token,
                    }
                )

    def pop(self) -> Optional[dict]:
        with self._lock:
            if not self._accounts:
                return None
            account = self._accounts.pop(0)
            self._save_unlocked()
            return account

    def push_front(self, account: dict) -> None:
        with self._lock:
            self._accounts.insert(0, account)
            self._save_unlocked()

    def _save_unlocked(self) -> None:
        try:
            with open(self._filepath, "w", encoding="utf-8") as f:
                for account in self._accounts:
                    f.write(
                        "----".join(
                            [
                                account.get("email", ""),
                                account.get("password", ""),
                                account.get("client_id", ""),
                                account.get("refresh_token", ""),
                            ]
                        )
                        + "\n"
                    )
        except Exception:
            pass

    def __len__(self) -> int:
        with self._lock:
            return len(self._accounts)


class RegistrationStats:
    """注册统计类，实时跟踪注册情况"""

    def __init__(self):
        self._lock = threading.Lock()
        self.start_time = time.time()
        self.total_attempts = 0
        self.success_count = 0
        self.fail_count = 0
        self.fail_reasons = {
            "403_forbidden": 0,
            "signup_form_error": 0,
            "password_error": 0,
            "otp_timeout": 0,
            "account_create_error": 0,
            "callback_error": 0,
            "network_error": 0,
            "other_error": 0,
        }
        self.last_10_results: List[bool] = []
        self.failed_resin_accounts: List[str] = []

    def add_attempt(self) -> None:
        with self._lock:
            self.total_attempts += 1

    def add_success(self) -> None:
        with self._lock:
            self.success_count += 1
            self.last_10_results.append(True)
            if len(self.last_10_results) > 10:
                self.last_10_results.pop(0)

    def add_failure(self, reason: str = "other_error") -> None:
        with self._lock:
            self.fail_count += 1
            if reason in self.fail_reasons:
                self.fail_reasons[reason] += 1
            else:
                self.fail_reasons["other_error"] += 1
            self.last_10_results.append(False)
            if len(self.last_10_results) > 10:
                self.last_10_results.pop(0)

    def add_failed_resin_account(self, account: str) -> None:
        account_value = normalize_resin_account(account)
        if not account_value:
            return
        with self._lock:
            self.failed_resin_accounts.append(account_value)

    def get_stats(self) -> dict:
        with self._lock:
            elapsed = time.time() - self.start_time
            total = self.success_count + self.fail_count
            overall_rate = (self.success_count / total * 100) if total > 0 else 0
            recent_rate = (sum(self.last_10_results) / len(self.last_10_results) * 100) if self.last_10_results else 0
            speed = self.success_count / (elapsed / 3600) if elapsed > 0 else 0
            return {
                "elapsed_time": elapsed,
                "total_attempts": self.total_attempts,
                "success_count": self.success_count,
                "fail_count": self.fail_count,
                "overall_success_rate": overall_rate,
                "recent_success_rate": recent_rate,
                "speed_per_hour": speed,
                "fail_reasons": self.fail_reasons.copy(),
                "failed_resin_accounts": list(self.failed_resin_accounts),
            }

    def format_display(self) -> str:
        stats = self.get_stats()
        elapsed = stats["elapsed_time"]
        hours = int(elapsed // 3600)
        minutes = int((elapsed % 3600) // 60)
        seconds = int(elapsed % 60)

        lines = [
            "",
            "=" * 60,
            " 📊 注册统计面板",
            "=" * 60,
            f" ⏱️  运行时间: {hours:02d}:{minutes:02d}:{seconds:02d}",
            f" 📈 总尝试数: {stats['total_attempts']}",
            f" ✅ 成功: {stats['success_count']} | ❌ 失败: {stats['fail_count']}",
            f" 📊 总体成功率: {stats['overall_success_rate']:.1f}%",
            f" 📊 最近10次成功率: {stats['recent_success_rate']:.1f}%",
            f" 🚀 速度: {stats['speed_per_hour']:.1f} 个/小时",
            "-" * 60,
            " 📉 失败原因分布:",
        ]

        for reason, count in stats["fail_reasons"].items():
            if count > 0:
                lines.append(f"    • {reason}: {count}")

        lines.append("=" * 60)
        return "\n".join(lines)

    def format_compact(self) -> str:
        stats = self.get_stats()
        elapsed = stats["elapsed_time"]
        hours = int(elapsed // 3600)
        minutes = int((elapsed % 3600) // 60)
        seconds = int(elapsed % 60)
        return (
            f"状态 | ⏱️ {hours:02d}:{minutes:02d}:{seconds:02d} | "
            f"尝试 {stats['total_attempts']} | "
            f"成功 {stats['success_count']} | "
            f"失败 {stats['fail_count']} | "
            f"总率 {stats['overall_success_rate']:.1f}% | "
            f"近10次 {stats['recent_success_rate']:.1f}% | "
            f"速度 {stats['speed_per_hour']:.1f}/h"
        )


class ActiveEmailQueue:
    """线程安全的活跃邮箱队列，存储预检测的活跃邮箱"""

    def __init__(self):
        self._emails: List[dict] = []
        self._lock = threading.Lock()

    def add_batch(self, emails: list) -> None:
        with self._lock:
            self._emails.extend(emails)

    def pop(self) -> Optional[dict]:
        with self._lock:
            if not self._emails:
                return None
            return self._emails.pop(0)

    def __len__(self) -> int:
        with self._lock:
            return len(self._emails)

    def is_empty(self) -> bool:
        with self._lock:
            return len(self._emails) == 0


_email_queue: Optional[EmailQueue] = None
_active_email_queue: Optional[ActiveEmailQueue] = None
_hotmail007_queue: Optional[ActiveEmailQueue] = None
_prefetch_no_stock = False
_prefetch_lock = threading.Lock()
_luckmail_purchased_only = False
_luckmail_skip_purchased = False
_luckmail_own_only = False
_reg_stats: Optional[RegistrationStats] = None
_stats_last_line = ""

_hotmail007_credentials: Dict[str, dict] = {}
_luckmail_credentials: Dict[str, dict] = {}

_file_write_lock = threading.Lock()
_success_counter_lock = threading.Lock()
_success_counter = 0
_session_output_dir = ""
_session_cpa_dir = ""
_session_sub_dir = ""
_session_accounts_file = ""

_INVALID_ERRORS = {
    "account_deactivated", "invalid_api_key", "user_deactivated",
    "account_banned", "invalid_grant",
}



def _ssl_verify() -> bool:
    return True



def _skip_net_check() -> bool:
    return False



def build_proxies(
    proxy: Optional[str],
    *,
    account: Optional[str] = None,
    resin_state: Optional[ResinRunState] = None,
):
    proxy_url = build_proxy_url(proxy, account=account, resin_state=resin_state)
    return {"http": proxy_url, "https": proxy_url} if proxy_url else None
