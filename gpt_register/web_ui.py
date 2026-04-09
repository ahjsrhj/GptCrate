from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from collections import deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import start


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ACCOUNTS_PATH = PROJECT_ROOT / "accounts.txt"
IMPORT_DIR = PROJECT_ROOT / "cliproxy_imports"


def _normalize_base_url(base_url: str) -> str:
    base_url = (base_url or "").strip()
    if not base_url:
        return ""
    if "://" not in base_url:
        base_url = "http://" + base_url
    parsed = urllib.parse.urlparse(base_url.rstrip("/"))
    path = parsed.path or ""
    if path.endswith(".html"):
        path = path[: path.rfind("/")] or ""
    for suffix in ("/v0/management/", "/v0/management", "/management"):
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    normalized_base = path.rstrip("/")
    if normalized_base.endswith("/api"):
        path = normalized_base + "/v0/management"
    else:
        path = normalized_base + "/v0/management"
    path = path.replace("//", "/")
    rebuilt = parsed._replace(path=path, params="", query="", fragment="")
    return urllib.parse.urlunparse(rebuilt).rstrip("/")


def _read_env(path: Path = PROJECT_ROOT / ".env") -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def _int_or_none(value: Any) -> int | None:
    if value in (None, "", 0, "0"):
        return None
    try:
        parsed = int(value)
    except Exception:
        return None
    return parsed if parsed > 0 else None


def _extract_auth_files(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = (
            payload.get("data")
            or payload.get("items")
            or payload.get("results")
            or payload.get("auth_files")
            or payload.get("files")
            or []
        )
    else:
        items = []

    result: list[dict[str, Any]] = []
    if not isinstance(items, list):
        return result

    for item in items:
        if isinstance(item, str):
            result.append({"name": item, "raw": item})
            continue
        if not isinstance(item, dict):
            continue
        name = (
            item.get("name")
            or item.get("filename")
            or item.get("file_name")
            or item.get("id")
            or item.get("email")
        )
        if not name:
            continue
        result.append(
            {
                "name": str(name),
                "email": str(item.get("email") or ""),
                "updated_at": str(item.get("updated_at") or item.get("created_at") or ""),
                "raw": item,
            }
        )
    return result


def _cliproxy_headers(api_key: str) -> dict[str, str]:
    api_key = (api_key or "").strip()
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        headers["X-API-Key"] = api_key
        headers["X-Management-Key"] = api_key
    return headers


def _cliproxy_get_json(base_url: str, api_key: str, endpoint: str) -> Any:
    url = _normalize_base_url(base_url) + endpoint
    request = urllib.request.Request(url, headers=_cliproxy_headers(api_key), method="GET")
    with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
        body = response.read().decode("utf-8", errors="ignore")
        return json.loads(body)


def _cliproxy_download_auth_file(base_url: str, api_key: str, name: str) -> str:
    encoded_name = urllib.parse.quote(name)
    candidates = [
        f"/auth-files/{encoded_name}/download",
        f"/auth-files/download?name={encoded_name}",
        f"/auth-files/{encoded_name}",
    ]
    last_error = ""
    for endpoint in candidates:
        try:
            url = _normalize_base_url(base_url) + endpoint
            request = urllib.request.Request(url, headers=_cliproxy_headers(api_key), method="GET")
            with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
                return response.read().decode("utf-8", errors="ignore")
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
    raise RuntimeError(last_error or "下载 auth-file 失败")


def _cliproxy_sync_auth_files(base_url: str, api_key: str, *, force: bool = False) -> dict[str, Any]:
    normalized = _normalize_base_url(base_url)
    data = _cliproxy_get_json(base_url, api_key, "/auth-files")
    files = _extract_auth_files(data)
    if not files:
        return {
            "ok": False,
            "normalized_base_url": normalized,
            "message": "未获取到 auth-files",
            "imported": [],
            "skipped": [],
        }

    IMPORT_DIR.mkdir(parents=True, exist_ok=True)
    imported: list[str] = []
    skipped: list[str] = []

    for item in files:
        name = item["name"]
        target = IMPORT_DIR / f"{name}.json"
        if target.exists() and not force:
            skipped.append(str(target.relative_to(PROJECT_ROOT)))
            continue
        content = _cliproxy_download_auth_file(base_url, api_key, name)
        target.write_text(content, encoding="utf-8")
        imported.append(str(target.relative_to(PROJECT_ROOT)))

    return {
        "ok": True,
        "normalized_base_url": normalized,
        "message": f"共发现 {len(files)} 个 auth-files，导入 {len(imported)} 个，跳过 {len(skipped)} 个",
        "count": len(files),
        "imported": imported,
        "skipped": skipped,
        "files": files[:200],
    }


def _save_env_from_payload(payload: dict[str, Any]) -> None:
    platform = str(payload.get("platform") or "luckmail").strip().lower()
    count = _int_or_none(payload.get("count"))
    threads = _int_or_none(payload.get("threads")) or 1
    start.generate_env(
        platform=platform,
        api_key=str(payload.get("api_key") or ""),
        count=count,
        threads=threads,
        luckmail_mode=str(payload.get("luckmail_mode") or "prefetch"),
        email_type=str(payload.get("luckmail_email_type") or "ms_imap"),
        local_outlook_mail_mode=str(payload.get("local_outlook_mail_mode") or "graph"),
        cf_domain=str(payload.get("cf_domain") or ""),
        cf_worker_base=str(payload.get("cf_worker_base") or ""),
        cf_admin_password=str(payload.get("cf_admin_password") or ""),
    )


class RuntimeState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.process: subprocess.Popen[str] | None = None
        self.logs: deque[str] = deque(maxlen=800)
        self.started_at: float | None = None

    def append_log(self, line: str) -> None:
        with self.lock:
            self.logs.append(line.rstrip())

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "running": self.process is not None and self.process.poll() is None,
                "pid": self.process.pid if self.process else None,
                "started_at": self.started_at,
                "logs": list(self.logs),
            }

    def start(self, count: int | None = None, threads: int | None = None) -> dict[str, Any]:
        with self.lock:
            if self.process and self.process.poll() is None:
                return {"ok": False, "message": "任务已在运行"}

            cmd = [sys.executable, "gpt.py"]
            if count:
                cmd.extend(["--count", str(count)])
            if threads:
                cmd.extend(["--threads", str(threads)])

            process = subprocess.Popen(
                cmd,
                cwd=PROJECT_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            self.process = process
            self.started_at = time.time()
            self.logs.clear()
            self.logs.append(f"$ {' '.join(cmd)}")

        threading.Thread(target=self._pump_logs, args=(process,), daemon=True).start()
        return {"ok": True, "message": "已启动"}

    def _pump_logs(self, process: subprocess.Popen[str]) -> None:
        assert process.stdout is not None
        for line in process.stdout:
            self.append_log(line)
        process.wait()
        self.append_log(f"[web-ui] 任务退出，退出码: {process.returncode}")

    def stop(self) -> dict[str, Any]:
        with self.lock:
            if not self.process or self.process.poll() is not None:
                return {"ok": False, "message": "当前没有运行中的任务"}
            process = self.process
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        self.append_log("[web-ui] 已停止任务")
        return {"ok": True, "message": "已停止"}


RUNTIME = RuntimeState()
UI_STATE = {"selected_mode": "luckmail"}


HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>GPT 注册机面板 · Web UI v3</title>
  <style>
    :root {
      --bg: #0b1020;
      --panel: #131a2b;
      --panel-2: #1b2438;
      --text: #eef3ff;
      --muted: #a6b0c3;
      --line: #2b3753;
      --accent: #6ea8fe;
      --green: #4ade80;
      --red: #fb7185;
      --yellow: #fbbf24;
      --cyan: #22d3ee;
    }
    * { box-sizing: border-box; }
    body { margin: 0; font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif; background: linear-gradient(180deg, #0b1020 0%, #0f172a 100%); color: var(--text); }
    .wrap { max-width: 1240px; margin: 0 auto; padding: 24px; }
    .hero { display:flex; justify-content:space-between; gap:16px; align-items:flex-start; margin-bottom:20px; }
    .hero h1 { margin:0 0 6px; font-size:28px; }
    .hero p { margin:0; color: var(--muted); }
    .pillbar { display:flex; flex-wrap:wrap; gap:10px; }
    .pill { padding:8px 12px; border-radius:999px; background: rgba(110,168,254,0.14); color:#dce8ff; border:1px solid rgba(110,168,254,0.22); font-size:13px; }
    .grid { display:grid; grid-template-columns: 1fr; gap:18px; }
    .stack { display:grid; gap:18px; }
    .card { background: rgba(19,26,43,0.92); border:1px solid var(--line); border-radius:18px; padding:18px; box-shadow: 0 10px 30px rgba(0,0,0,0.2); }
    .card h2 { margin:0 0 14px; font-size:18px; }
    .row { display:grid; grid-template-columns: 1fr 1fr; gap:12px; }
    .row-3 { display:grid; grid-template-columns: repeat(3, 1fr); gap:12px; }
    label { display:block; font-size:13px; color:var(--muted); margin-bottom:6px; }
    input, select, textarea { width:100%; background: var(--panel-2); color: var(--text); border:1px solid var(--line); border-radius:12px; padding:12px 13px; font-size:14px; outline:none; }
    textarea { min-height:120px; resize:vertical; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
    .actions { display:flex; flex-wrap:wrap; gap:10px; margin-top:14px; }
    button { border:none; border-radius:12px; padding:11px 14px; cursor:pointer; font-weight:600; }
    .primary { background: var(--accent); color:#081120; }
    .secondary { background: rgba(255,255,255,0.06); color: var(--text); border:1px solid var(--line); }
    .danger { background: rgba(251,113,133,0.18); color:#ffd9e0; border:1px solid rgba(251,113,133,0.32); }
    .status { display:grid; grid-template-columns: repeat(4, 1fr); gap:10px; }
    .stat { background: rgba(255,255,255,0.04); border:1px solid var(--line); border-radius:14px; padding:14px; }
    .stat .k { color: var(--muted); font-size:12px; margin-bottom:4px; }
    .stat .v { font-size:18px; font-weight:700; }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
    .logbox { min-height: 560px; max-height: 70vh; overflow:auto; background:#0a1220; border:1px solid var(--line); border-radius:14px; padding:14px; white-space:pre-wrap; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size:13px; line-height:1.5; }
    .hint { color: var(--muted); font-size:12px; margin-top:8px; }
    .ok { color: var(--green); }
    .warn { color: var(--yellow); }
    .bad { color: var(--red); }
    .section-tabs { display:flex; gap:8px; margin-bottom:14px; flex-wrap:wrap; }
    .tab { padding:9px 12px; border-radius:999px; background:rgba(255,255,255,0.04); border:1px solid var(--line); cursor:pointer; }
    .tab.active { background: rgba(34,211,238,0.15); border-color: rgba(34,211,238,0.4); color:#d8fbff; }
    .config-layout { display:grid; grid-template-columns: 220px 1fr 320px; gap:18px; align-items:start; }
    .mode-nav { display:grid; gap:10px; }
    .mode-btn { text-align:left; padding:14px 14px; border-radius:14px; background:rgba(255,255,255,0.04); border:1px solid var(--line); cursor:pointer; color:var(--text); }
    .mode-btn .title { font-size:15px; font-weight:700; margin-bottom:4px; }
    .mode-btn .desc { font-size:12px; color:var(--muted); line-height:1.35; }
    .mode-btn.active { background: rgba(110,168,254,0.14); border-color: rgba(110,168,254,0.36); box-shadow: inset 0 0 0 1px rgba(110,168,254,0.18); }
    .meta-line { display:flex; flex-wrap:wrap; gap:10px; margin-bottom:14px; }
    .meta-pill { padding:8px 12px; border-radius:999px; border:1px solid var(--line); background:rgba(255,255,255,0.04); font-size:13px; color:var(--muted); }
    .meta-pill strong { color:var(--text); }
    .subcard { border:1px solid var(--line); background:rgba(255,255,255,0.02); border-radius:16px; padding:14px; }
    .subcard h3 { margin:0 0 12px; font-size:15px; }
    .subcard.compact h3 { margin-bottom:8px; }
    .listbox { min-height:140px; max-height:220px; overflow:auto; background:#0a1220; border:1px solid var(--line); border-radius:14px; padding:12px; white-space:pre-wrap; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size:12px; line-height:1.45; }
    .hidden { display:none !important; }
    @media (max-width: 980px) {
      .grid { grid-template-columns: 1fr; }
      .row, .row-3, .status, .config-layout { grid-template-columns: 1fr; }
      .hero { flex-direction:column; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <div>
        <h1>GPT 注册机面板</h1>
        <p>清晰、简单、可用。统一管理模式配置、账号导入、运行控制和日志查看。</p>
      </div>
      <div class="pillbar">
        <div class="pill">Web UI v3</div>
        <div class="pill">LuckMail</div>
        <div class="pill">Cloudflare Worker</div>
        <div class="pill">本地 Outlook</div>
        <div class="pill">CLIProxyAPI 导入</div>
      </div>
    </div>

    <div class="status" style="margin-bottom:18px;">
      <div class="stat"><div class="k">当前模式</div><div class="v" id="stat-mode">-</div></div>
      <div class="stat"><div class="k">任务状态</div><div class="v" id="stat-running">空闲</div></div>
      <div class="stat"><div class="k">accounts.txt</div><div class="v" id="stat-accounts">0</div></div>
      <div class="stat"><div class="k">日志行数</div><div class="v" id="stat-logs">0</div></div>
    </div>

    <div class="grid">
      <div class="card">
        <h2>配置与运行</h2>
        <div class="meta-line">
          <div class="meta-pill">当前保存模式：<strong id="saved-platform-label">-</strong></div>
          <div class="meta-pill">当前编辑模式：<strong id="editing-platform-label">LuckMail</strong></div>
          <div class="meta-pill">界面版本：<strong>Web UI v3</strong></div>
        </div>
        <div class="config-layout">
          <div class="mode-nav">
            <button class="mode-btn active" type="button" data-mode="luckmail">
              <div class="title">LuckMail</div>
              <div class="desc">API 接码 / 已购邮箱 / 我的邮箱</div>
            </button>
            <button class="mode-btn" type="button" data-mode="cf">
              <div class="title">自建邮箱</div>
              <div class="desc">Cloudflare Worker / 自建邮件中转</div>
            </button>
            <button class="mode-btn" type="button" data-mode="local_outlook">
              <div class="title">本地 Outlook</div>
              <div class="desc">邮箱----密码----client_id----refresh_token</div>
            </button>
            <button class="mode-btn" type="button" data-mode="hotmail007">
              <div class="title">Hotmail007</div>
              <div class="desc">平台 API 拉取微软邮箱</div>
            </button>
          </div>
          <div class="stack">
            <div class="subcard compact">
              <h3>通用参数</h3>
              <div class="row-3">
                <div><label>数量</label><input id="count" placeholder="留空=循环" /></div>
                <div><label>线程数</label><input id="threads" value="1" /></div>
                <div><label>说明</label><input value="仅保存当前模式配置" readonly /></div>
              </div>
            </div>
            <div id="panel-luckmail" class="subcard stack">
              <h3>LuckMail</h3>
              <div class="row">
                <div><label>API Key</label><input id="luckmail_api_key" placeholder="ak_xxx" /></div>
                <div><label>邮箱类型</label><select id="luckmail_email_type"><option value="ms_imap">ms_imap</option><option value="ms_graph">ms_graph</option></select></div>
              </div>
              <div class="row">
                <div><label>工作模式</label><select id="luckmail_mode">
                  <option value="prefetch">预检测模式</option>
                  <option value="realtime">实时购买模式</option>
                  <option value="order">接码模式</option>
                  <option value="purchased">已购邮箱模式</option>
                  <option value="own">我的邮箱模式</option>
                </select></div>
                <div></div>
              </div>
            </div>
            <div id="panel-cf" class="subcard stack hidden">
              <h3>自建邮箱</h3>
              <div class="row">
                <div><label>MAIL_DOMAIN</label><input id="cf_domain" placeholder="your-domain.com" /></div>
                <div><label>MAIL_WORKER_BASE</label><input id="cf_worker_base" placeholder="https://worker.example.com" /></div>
              </div>
              <div><label>MAIL_ADMIN_PASSWORD</label><input id="cf_admin_password" placeholder="worker admin password" /></div>
            </div>
            <div id="panel-local" class="subcard stack hidden">
              <h3>本地 Outlook</h3>
              <div class="row">
                <div><label>收信模式</label><select id="local_outlook_mail_mode"><option value="graph">graph</option><option value="imap">imap</option></select></div>
                <div><label>坏号文件</label><input id="local_bad_file" value="bad_local_outlook.txt" disabled /></div>
              </div>
            </div>
            <div id="panel-hotmail007" class="subcard stack hidden">
              <h3>Hotmail007</h3>
              <div class="row">
                <div><label>API Key</label><input id="hotmail007_api_key" /></div>
                <div><label>收信模式</label><select id="hotmail007_mail_mode"><option value="imap">imap</option><option value="graph">graph</option></select></div>
              </div>
            </div>
            <div class="actions">
              <button class="primary" id="save-config">保存当前模式配置</button>
              <button class="secondary" id="reload-state">从 .env 重新载入</button>
            </div>
          </div>
          <div class="stack">
            <div class="subcard">
              <h3>运行控制</h3>
              <div class="row">
                <div><label>运行数量</label><input id="run_count" placeholder="留空=按 .env / 循环" /></div>
                <div><label>运行线程</label><input id="run_threads" placeholder="留空=按 .env" /></div>
              </div>
              <div class="actions">
                <button class="primary" id="run-start">启动任务</button>
                <button class="danger" id="run-stop">停止任务</button>
              </div>
            </div>
            <div class="subcard compact">
              <h3>实时状态</h3>
              <div class="hint">运行中只刷新只读状态，不会再覆盖你正在编辑的表单。</div>
            </div>
          </div>
        </div>
      </div>

      <div class="grid" style="grid-template-columns: 1fr 1fr;">
        <div class="card">
          <h2>账号导入</h2>
          <div class="row">
            <div>
              <label>导入到 accounts.txt</label>
              <textarea id="accounts_text" placeholder="local_outlook: 邮箱----密码----client_id----refresh_token&#10;file: 每行一个邮箱"></textarea>
              <div class="actions">
                <button class="primary" id="replace-accounts">覆盖导入</button>
                <button class="secondary" id="append-accounts">追加导入</button>
              </div>
            </div>
            <div>
              <label>当前 accounts.txt</label>
              <textarea id="accounts_preview" readonly></textarea>
            </div>
          </div>
        </div>

        <div class="card">
          <h2>CLIProxyAPI 导入</h2>
          <div class="row">
            <div><label>CLIProxyAPI Base URL</label><input id="cliproxy_base" placeholder="例如 http://127.0.0.1:8080/api 或完整 management 根地址" /></div>
            <div><label>API Key（可选，按你的服务要求）</label><input id="cliproxy_key" placeholder="Bearer token / X-API-Key" /></div>
          </div>
          <div class="actions">
            <button class="primary" id="cliproxy-test">测试连接并拉取 auth-files</button>
            <button class="secondary" id="cliproxy-import">同步 auth-files</button>
            <button class="secondary" id="cliproxy-auto-sync">开启自动同步</button>
          </div>
          <div class="row" style="margin-top:12px;">
            <div>
              <label>同步结果</label>
              <textarea id="cliproxy_result" readonly style="min-height:140px;"></textarea>
            </div>
            <div>
              <label>auth-files 列表 / 去重状态</label>
              <div id="cliproxy_files" class="listbox">尚未拉取</div>
            </div>
          </div>
          <div class="hint">支持填根地址、`management.html`、`/management`、`/v0/management` 等形式；同步会按文件名去重，已存在的文件默认跳过。</div>
        </div>
      </div>

      <div class="card">
        <h2>实时日志</h2>
        <div id="logbox" class="logbox">等待日志...</div>
      </div>
    </div>
  </div>

  <script>
    const byId = (id) => document.getElementById(id);
      const modePanels = {
        luckmail: byId('panel-luckmail'),
        cf: byId('panel-cf'),
        local_outlook: byId('panel-local'),
        hotmail007: byId('panel-hotmail007'),
      };
      const tabs = Array.from(document.querySelectorAll('.mode-btn'));
      let selectedMode = 'luckmail';
      let didInitialSync = false;
      let cliproxyAutoSyncTimer = null;

    function modeTitle(mode) {
      return {
        luckmail: 'LuckMail',
        cf: '自建邮箱 / Cloudflare Worker',
        local_outlook: '本地 Outlook',
        hotmail007: 'Hotmail007',
      }[mode] || mode;
    }

    function applyMode(mode) {
      selectedMode = mode;
      byId('editing-platform-label').textContent = modeTitle(mode);
      Object.entries(modePanels).forEach(([key, el]) => el.classList.toggle('hidden', key !== mode));
      tabs.forEach(tab => tab.classList.toggle('active', tab.dataset.mode === mode));
    }

    tabs.forEach(tab => tab.addEventListener('click', () => {
      applyMode(tab.dataset.mode);
      fetch('/api/ui-state', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ selected_mode: tab.dataset.mode }) });
    }));
    async function api(path, options = {}) {
      const response = await fetch(path, {
        headers: { 'Content-Type': 'application/json' },
        ...options,
      });
      const text = await response.text();
      try { return JSON.parse(text); } catch { return { ok: false, message: text }; }
    }

    function dump(obj) { return JSON.stringify(obj, null, 2); }

    function syncFormFromConfig(cfg, ui) {
      byId('count').value = cfg.BATCH_COUNT || '';
      byId('threads').value = cfg.BATCH_THREADS || '1';
      byId('luckmail_api_key').value = cfg.LUCKMAIL_API_KEY || '';
      byId('luckmail_email_type').value = cfg.LUCKMAIL_EMAIL_TYPE || 'ms_imap';
      byId('luckmail_mode').value = cfg.WEB_LUCKMAIL_MODE || 'prefetch';
      byId('cf_domain').value = cfg.MAIL_DOMAIN || '';
      byId('cf_worker_base').value = cfg.MAIL_WORKER_BASE || '';
      byId('cf_admin_password').value = cfg.MAIL_ADMIN_PASSWORD || '';
      byId('local_outlook_mail_mode').value = cfg.LOCAL_OUTLOOK_MAIL_MODE || 'graph';
      byId('hotmail007_api_key').value = cfg.HOTMAIL007_API_KEY || '';
      byId('hotmail007_mail_mode').value = cfg.HOTMAIL007_MAIL_MODE || 'imap';
      applyMode(ui.selected_mode || cfg.EMAIL_MODE || 'luckmail');
      didInitialSync = true;
    }

    function syncReadOnlyState(data) {
      const cfg = data.config;
      byId('saved-platform-label').textContent = modeTitle(cfg.EMAIL_MODE || '-');
      byId('accounts_preview').value = (data.accounts_preview || []).join('\\n');
      byId('stat-mode').textContent = cfg.EMAIL_MODE || '-';
      byId('stat-running').innerHTML = data.runtime.running ? '<span class=\"ok\">运行中</span>' : '<span class=\"warn\">空闲</span>';
      byId('stat-accounts').textContent = String(data.accounts_count || 0);
      byId('stat-logs').textContent = String((data.runtime.logs || []).length);
      const logbox = byId('logbox');
      logbox.textContent = (data.runtime.logs || []).join('\\n') || '暂无日志';
      logbox.scrollTop = logbox.scrollHeight;
    }

    function renderCliproxyFiles(data) {
      const filesEl = byId('cliproxy_files');
      const imported = new Set(data.imported || []);
      const skipped = new Set(data.skipped || []);
      const rows = [];
      if (data.normalized_base_url) rows.push(`标准化地址: ${data.normalized_base_url}`);
      if (Array.isArray(data.files) && data.files.length) {
        rows.push('');
        data.files.forEach((file) => {
          const target = `cliproxy_imports/${file.name}.json`;
          const flag = imported.has(target) ? '导入' : skipped.has(target) ? '跳过' : '待定';
          rows.push(`[${flag}] ${file.name}${file.email ? '  <' + file.email + '>' : ''}`);
        });
      } else if (data.count === 0) {
        rows.push('未发现 auth-files');
      }
      filesEl.textContent = rows.join('\\n') || '尚未拉取';
    }

    async function refreshState({ syncForm = false } = {}) {
      const data = await api('/api/state');
      if (!data.ok) return;
      syncReadOnlyState(data);
      if (syncForm || !didInitialSync) {
        syncFormFromConfig(data.config, data.ui || {});
      }
    }

    byId('save-config').addEventListener('click', async () => {
      const payload = {
        platform: selectedMode,
        count: byId('count').value,
        threads: byId('threads').value,
        api_key: selectedMode === 'luckmail' ? byId('luckmail_api_key').value : byId('hotmail007_api_key').value,
        luckmail_mode: byId('luckmail_mode').value,
        luckmail_email_type: byId('luckmail_email_type').value,
        local_outlook_mail_mode: byId('local_outlook_mail_mode').value,
        cf_domain: byId('cf_domain').value,
        cf_worker_base: byId('cf_worker_base').value,
        cf_admin_password: byId('cf_admin_password').value,
      };
      const data = await api('/api/config', { method: 'POST', body: JSON.stringify(payload) });
      alert(data.message || (data.ok ? '保存成功' : '保存失败'));
      await refreshState({ syncForm: true });
    });

    async function importAccounts(append) {
      const payload = { content: byId('accounts_text').value, append };
      const data = await api('/api/accounts/import', { method: 'POST', body: JSON.stringify(payload) });
      alert(data.message || (data.ok ? '导入成功' : '导入失败'));
      await refreshState({ syncForm: false });
    }
    byId('replace-accounts').addEventListener('click', () => importAccounts(false));
    byId('append-accounts').addEventListener('click', () => importAccounts(true));

    byId('run-start').addEventListener('click', async () => {
      const data = await api('/api/run/start', {
        method: 'POST',
        body: JSON.stringify({ count: byId('run_count').value, threads: byId('run_threads').value }),
      });
      alert(data.message || (data.ok ? '已启动' : '启动失败'));
      await refreshState({ syncForm: false });
    });

    byId('run-stop').addEventListener('click', async () => {
      const data = await api('/api/run/stop', { method: 'POST', body: '{}' });
      alert(data.message || (data.ok ? '已停止' : '停止失败'));
      await refreshState({ syncForm: false });
    });

    byId('cliproxy-test').addEventListener('click', async () => {
      const payload = { base_url: byId('cliproxy_base').value, api_key: byId('cliproxy_key').value };
      const data = await api('/api/cliproxy/list', { method: 'POST', body: JSON.stringify(payload) });
      byId('cliproxy_result').value = dump(data);
      renderCliproxyFiles(data);
    });

    byId('cliproxy-import').addEventListener('click', async () => {
      const payload = { base_url: byId('cliproxy_base').value, api_key: byId('cliproxy_key').value };
      const data = await api('/api/cliproxy/import', { method: 'POST', body: JSON.stringify(payload) });
      byId('cliproxy_result').value = dump(data);
      renderCliproxyFiles(data);
    });

    byId('cliproxy-auto-sync').addEventListener('click', async () => {
      const btn = byId('cliproxy-auto-sync');
      if (cliproxyAutoSyncTimer) {
        clearInterval(cliproxyAutoSyncTimer);
        cliproxyAutoSyncTimer = null;
        btn.textContent = '开启自动同步';
        return;
      }
      btn.textContent = '关闭自动同步';
      const runSync = async () => {
        const payload = { base_url: byId('cliproxy_base').value, api_key: byId('cliproxy_key').value };
        const data = await api('/api/cliproxy/import', { method: 'POST', body: JSON.stringify(payload) });
        byId('cliproxy_result').value = dump(data);
        renderCliproxyFiles(data);
      };
      await runSync();
      cliproxyAutoSyncTimer = setInterval(runSync, 30000);
    });

    byId('reload-state').addEventListener('click', () => refreshState({ syncForm: true }));
    setInterval(() => refreshState({ syncForm: false }), 2000);
    refreshState({ syncForm: true });
  </script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/":
            self._send_html(HTML)
            return
        if self.path.startswith("/api/state"):
            env = _read_env()
            self._send_json(
                {
                    "ok": True,
                    "config": {
                        **env,
                        "WEB_LUCKMAIL_MODE": _detect_luckmail_mode(env),
                    },
                    "runtime": RUNTIME.snapshot(),
                    "ui": dict(UI_STATE),
                    "accounts_count": _accounts_count(),
                    "accounts_preview": _accounts_preview(),
                }
            )
            return
        self._send_json({"ok": False, "message": "Not found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        payload = self._read_json()
        try:
            if self.path == "/api/config":
                _save_env_from_payload(payload)
                self._send_json({"ok": True, "message": "配置已保存"})
                return

            if self.path == "/api/ui-state":
                selected_mode = str(payload.get("selected_mode") or "").strip().lower()
                if selected_mode in {"luckmail", "cf", "local_outlook", "hotmail007"}:
                    UI_STATE["selected_mode"] = selected_mode
                self._send_json({"ok": True, "ui": dict(UI_STATE)})
                return

            if self.path == "/api/accounts/import":
                append = bool(payload.get("append"))
                content = str(payload.get("content") or "").strip()
                if not content:
                    self._send_json({"ok": False, "message": "内容不能为空"}, status=400)
                    return
                existing = ACCOUNTS_PATH.read_text(encoding="utf-8") if ACCOUNTS_PATH.exists() and append else ""
                new_content = (existing.rstrip() + "\n" + content if existing else content).strip() + "\n"
                ACCOUNTS_PATH.write_text(new_content, encoding="utf-8")
                self._send_json({"ok": True, "message": f"已写入 {ACCOUNTS_PATH.name}"})
                return

            if self.path == "/api/run/start":
                result = RUNTIME.start(count=_int_or_none(payload.get("count")), threads=_int_or_none(payload.get("threads")))
                self._send_json(result)
                return

            if self.path == "/api/run/stop":
                self._send_json(RUNTIME.stop())
                return

            if self.path == "/api/cliproxy/list":
                base_url = str(payload.get("base_url") or "")
                api_key = str(payload.get("api_key") or "")
                normalized = _normalize_base_url(base_url)
                data = _cliproxy_get_json(base_url, api_key, "/auth-files")
                files = _extract_auth_files(data)
                self._send_json({"ok": True, "normalized_base_url": normalized, "count": len(files), "files": files[:200]})
                return

            if self.path == "/api/cliproxy/import":
                base_url = str(payload.get("base_url") or "")
                api_key = str(payload.get("api_key") or "")
                normalized = _normalize_base_url(base_url)
                data = _cliproxy_get_json(base_url, api_key, "/auth-files")
                files = _extract_auth_files(data)
                if not files:
                    self._send_json({"ok": False, "message": "未获取到 auth-files"}, status=400)
                    return
                IMPORT_DIR.mkdir(parents=True, exist_ok=True)
                imported = []
                for item in files:
                    name = item["name"]
                    content = _cliproxy_download_auth_file(base_url, api_key, name)
                    target = IMPORT_DIR / f"{name}.json"
                    target.write_text(content, encoding="utf-8")
                    imported.append(str(target.relative_to(PROJECT_ROOT)))
                self._send_json({"ok": True, "normalized_base_url": normalized, "message": f"已导入 {len(imported)} 个 auth-files", "files": imported})
                return

        except Exception as exc:  # noqa: BLE001
            base_url = str(payload.get("base_url") or "")
            self._send_json({"ok": False, "normalized_base_url": _normalize_base_url(base_url), "message": str(exc)}, status=500)
            return

        self._send_json({"ok": False, "message": "Not found"}, status=404)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return


def _accounts_count() -> int:
    if not ACCOUNTS_PATH.exists():
        return 0
    return len([line for line in ACCOUNTS_PATH.read_text(encoding="utf-8").splitlines() if line.strip()])


def _accounts_preview() -> list[str]:
    if not ACCOUNTS_PATH.exists():
        return []
    return ACCOUNTS_PATH.read_text(encoding="utf-8").splitlines()[:20]


def _detect_luckmail_mode(env: dict[str, str]) -> str:
    if env.get("EMAIL_MODE") != "luckmail":
        return "prefetch"
    if env.get("LUCKMAIL_OWN_ONLY", "").lower() == "true":
        return "own"
    if env.get("LUCKMAIL_PURCHASED_ONLY", "").lower() == "true":
        return "purchased"
    if env.get("LUCKMAIL_AUTO_BUY", "").lower() != "true":
        return "order"
    if env.get("LUCKMAIL_SKIP_PURCHASED", "").lower() == "true":
        return "prefetch"
    return "realtime"


def main(host: str = "127.0.0.1", port: int = 8765) -> None:
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Web UI running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
