# OpenAI 自动注册工具

> 免责声明
>
> 本项目仅供学习与技术研究使用，请勿用于任何违反服务条款、法律法规或他人权益的用途。

自动批量注册 OpenAI 账号，支持多代理轮换、多线程并发。

当前支持 4 种邮箱来源：

- `luckmail`：LuckMail API（推荐）
- `cf`：自建邮箱 / Cloudflare Worker
- `local_outlook`：本地导入 Outlook 凭据
- `hotmail007`：Hotmail007 API

当前还提供一个 **Web UI（实验版）**：

- 入口：`python web_ui.py`
- 能力：配置切换、任务启动/停止、日志查看、CLIProxyAPI 导入
- **当前建议优先使用终端版**（`start.py` / `gpt.py`），Web UI 仍在持续改进中

终端版已新增 **微软邮箱多别名生成器**：

- 入口 1：`uv run python start.py` 后选择 `微软邮箱多别名生成器`
- 入口 2：`uv run python alias_generator.py`
- 支持 `hotmail.*` / `outlook.*` 邮箱
- 支持保留原字段、打乱输出、可选从源文件移除已处理原邮箱
- 支持**直接覆盖 `accounts.txt`**（会自动创建 `.bak` 备份）

---

> 默认推荐方案：`LuckMail`
>
> 这套 README 的快速开始、默认示例和一键启动器都优先按 `LuckMail` 配置。

## 首页推荐：使用 LuckMail 接码平台

**强烈推荐使用 [LuckMail](https://mails.luckyous.com/EC36F88F) 接码平台！**

- 注册地址：https://mails.luckyous.com/EC36F88F
- 只需填写 API Key，其他配置代码已帮你搞定！
- **智能预检测**：自动购买邮箱并检测活跃度，只使用活跃邮箱注册
- **自动禁用**：不活跃邮箱自动禁用，避免浪费

最小配置：

```env
EMAIL_MODE=luckmail
LUCKMAIL_API_KEY=你的API密钥
TOKEN_OUTPUT_DIR=./tokens
CODEX2API_BASE_URL=
CODEX2API_ADMIN_SECRET=
```

---

## 代理推荐

**高质量代理服务商，支持免费测试，先充值后付费**

- 微信: `ytip886`
- Telegram: `yitong886`

![代理产品](./image.png)

---

## 快速开始

```bash
# 1. 安装 uv
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows PowerShell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# 2. 创建虚拟环境并安装依赖
uv sync

# 3. 复制配置模板
cp .env.example .env

# 4. 编辑 .env，填写 LuckMail API Key
# LUCKMAIL_API_KEY=你的API密钥

# 5. 运行
uv run python gpt.py --once
```

或使用一键启动器（推荐）：

```bash
uv run python start.py
```

`start.py` 现已支持：
- LuckMail
- 自建邮箱 / Cloudflare Worker
- 本地 Outlook 导入
- Hotmail007

推荐优先用 `start.py` 生成 `.env`，再按需手工微调。

如需体验 Web UI（实验版）：

```bash
uv run python web_ui.py
```

默认地址：

```text
http://127.0.0.1:8765
```

> 说明：Web UI 目前可用，但交互和导入流程仍在持续打磨；如果你追求稳定性，建议优先使用终端版。

---

## 环境要求

- 推荐使用 `uv` 自动管理 Python 版本和虚拟环境
- 项目内置 `.python-version`，默认使用 Python 3.11
- 若不用 `uv`，也可以手动准备 Python 3.10+

### 使用 uv

```bash
uv sync
```

首次执行会自动创建 `.venv/` 并安装依赖。

### 手动安装依赖

```bash
pip install curl_cffi
```

---

## 文件说明

| 文件          | 作用                              |
| ------------- | --------------------------------- |
| `gpt.py`      | 主程序                                                     |
| `start.py`    | 一键启动器（带交互式配置，支持 4 种邮箱模式）              |
| `alias_generator.py` | 微软邮箱多别名生成器（终端版）                       |
| `web_ui.py`   | Web UI 启动入口（实验版，本地面板）                        |
| `.env`        | 配置文件 (邮箱、代理、输出路径等)                          |
| `accounts.txt`| 输入账号文件；`file`/`local_outlook` 模式会读取它          |
| `proxies.txt` | 代理列表文件 (每行一个代理)                                |
| `tokens/`     | 输出目录；成功 token、成功账号密码、压缩包等都在这里       |

---

## 配置文件 (.env)

### Codex2Api 同步（可选）

如果你希望注册成功后自动把账号同步到 Codex2Api 管理端，可额外配置：

```env
CODEX2API_BASE_URL=http://localhost:8080
CODEX2API_ADMIN_SECRET=your-admin-secret
```

- 程序会在本地保存 token、sub 导出和 `tokens/accounts.txt` 后，再调用 `POST /api/admin/accounts`
- 上传字段固定为：
  - `name`: 注册邮箱
  - `refresh_token`: 新账号的 Refresh Token
  - `proxy_url`: 当前线程实际使用的代理，直连时为空字符串
- 未配置上述变量时自动跳过同步
- 同步失败只打印警告，不影响本地保存和注册成功统计

### 邮箱模式

支持四种邮箱来源，通过 `EMAIL_MODE` 切换：

| 模式              | 值           | 说明                                                                                        |
| ----------------- | ------------ | ------------------------------------------------------------------------------------------- |
| Cloudflare Worker | `cf`         | 使用自有域名随机生成邮箱，需配置 `MAIL_DOMAIN` / `MAIL_WORKER_BASE` / `MAIL_ADMIN_PASSWORD` |
| 本地 Outlook 导入 | `local_outlook` | 从 `accounts.txt` 读取 `邮箱----密码----client_id----refresh_token`，直接用本地 Outlook 凭据收信 |
| Hotmail007 API    | `hotmail007` | 通过 API 拉取微软邮箱，需配置 `HOTMAIL007_API_KEY`                                          |
| **LuckMail API**  | `luckmail`   | **推荐** 智能购买+预检测活跃邮箱，需配置 `LUCKMAIL_API_KEY`                                 |

**Cloudflare 模式配置：**

```env
EMAIL_MODE=cf
MAIL_DOMAIN=your-domain.com
MAIL_WORKER_BASE=https://mail-worker.your-domain.com
MAIL_ADMIN_PASSWORD=your-password
```

说明：

- 程序会随机生成 `prefix@MAIL_DOMAIN`
- 收验证码时访问：
  - `GET {MAIL_WORKER_BASE}/admin/mails`
  - `DELETE {MAIL_WORKER_BASE}/admin/mails/{id}`
- 请求头中使用：
  - `x-admin-auth: MAIL_ADMIN_PASSWORD`

**本地 Outlook 导入模式配置：**

```env
EMAIL_MODE=local_outlook
ACCOUNTS_FILE=accounts.txt
LOCAL_OUTLOOK_MAIL_MODE=graph
LOCAL_OUTLOOK_BAD_FILE=bad_local_outlook.txt
# 可选：仅 Outlook/Hotmail 相关 HTTP 请求走这个代理
OUTLOOK_PROXY=http://127.0.0.1:7890
```

`accounts.txt` 每行格式：

```txt
邮箱----密码----client_id----refresh_token
```

- `LOCAL_OUTLOOK_MAIL_MODE` 支持 `graph` / `imap`
- 失效账号会自动写入 `LOCAL_OUTLOOK_BAD_FILE`
- 程序读取的是**项目根目录**下的 `accounts.txt`
- 成功注册后写入的是 `tokens/accounts.txt`，两者不是同一个文件
- 如配置 `OUTLOOK_PROXY`，Microsoft Graph / OAuth 等 Outlook 相关 HTTP 请求会优先走这个代理

**Hotmail007 模式配置：**

```env
EMAIL_MODE=hotmail007
HOTMAIL007_API_URL=https://gapi.hotmail007.com
HOTMAIL007_API_KEY=你的API密钥
HOTMAIL007_MAIL_TYPE=outlook-premium
HOTMAIL007_MAIL_MODE=imap
# 是否开启邮箱裂变（true=购买 1 个原始邮箱后裂变成 5 个别名并依次使用）
HOTMAIL007_ALIAS_SPLIT_ENABLED=false
# 裂变子邮箱库存队列文件
HOTMAIL007_QUEUE_FILE=hotmail007.txt
# 拉取邮箱失败时的最大重试次数
HOTMAIL007_MAX_RETRY=3
# 可选：仅 Hotmail007 / Outlook 相关 HTTP 请求走这个代理
OUTLOOK_PROXY=http://127.0.0.1:7890
```

`HOTMAIL007_MAIL_MODE` 支持 `graph` (Microsoft Graph API) 和 `imap` (IMAP 协议) 两种收信方式。
- `HOTMAIL007_ALIAS_SPLIT_ENABLED=true` 时，程序会优先消费 `HOTMAIL007_QUEUE_FILE` 指向的库存文件，默认是项目根目录下的 `hotmail007.txt`
- 裂变库存队列按文本文件持久化，消费时从文件头顺序读取，用掉一个就立刻从文件中删除，避免未用完的子邮箱丢失
- 开启裂变后，购买和注册会拆分成两个流程：先把号池暖到至少 21 个子邮箱，再启动注册；只有达到这个门槛才会进入注册阶段
- 有限批量注册时，即使本次 `count` 小于 21，也会先暖池到 21；注册开始后只在低水位 `<= 5` 时按剩余待注册次数做增量补货，不会在启动前一次性补到 `count`
- 如果注册线程临时把号池用空，会阻塞等待后台购买线程补货，不会回退成前台同步购买
- 无限模式运行时，启动前同样先暖池到 21，运行中则持续维持 `hotmail007.txt` 中的可用子邮箱数量大于 20；低于等于 20 时后台会继续补货
- 每次新购买并裂变出的 5 个子邮箱会先打乱，再随机插入现有队列；实际注册时仍按文件顺序消费
- `hotmail007.txt` 每行格式固定为：`alias_email----primary_email----password----client_id----mail_mode----refresh_token`
- 开启裂变后，注册流程消费的是别名邮箱，验证码仍通过对应原始邮箱的微软 OAuth 凭据轮询获取
- Hotmail007 模式注册成功后，除了写入 `tokens/accounts.txt`，还会额外写入 `tokens/emails.txt`
- `tokens/emails.txt` 每行格式为 `原始邮箱----邮箱密码----client_id----refresh_token`
- 如配置 `OUTLOOK_PROXY`，Hotmail007 的余额/库存/购买查询和 Outlook Graph / OAuth 请求会优先走这个代理

**LuckMail 模式配置（推荐）：**

```env
EMAIL_MODE=luckmail
LUCKMAIL_API_URL=https://mails.luckyous.com/api/v1/openapi
LUCKMAIL_API_KEY=你的API密钥

# 邮箱类型: ms_imap (IMAP协议) 或 ms_graph (Microsoft Graph API)
LUCKMAIL_EMAIL_TYPE=ms_imap
# 自动购买邮箱并检测活跃度（推荐开启）
LUCKMAIL_AUTO_BUY=true
# 只使用已购邮箱
LUCKMAIL_PURCHASED_ONLY=false
# 跳过已购邮箱检查，直接买新邮箱
LUCKMAIL_SKIP_PURCHASED=false
# 只使用自己导入到 LuckMail 的邮箱（true=只读“我的邮箱”，用完即停）
LUCKMAIL_OWN_ONLY=false
# 已购/预检测邮箱活跃度检测并发数
LUCKMAIL_CHECK_WORKERS=20
# 调试 LuckMail 收信轮询（建议排查收不到验证码时临时开启）
LUCKMAIL_MAIL_DEBUG=false
# 邮箱不活跃时的最大重试次数
LUCKMAIL_MAX_RETRY=3
```

**LuckMail 工作模式说明：**

1. **预检测模式** (`LUCKMAIL_AUTO_BUY=true`)：
   - 启动时自动创建后台线程
   - **优先检查已购邮箱**：获取用户已购买的非禁用邮箱，默认只筛选 `@hotmail.com`
   - 批量购买新邮箱（默认20个）补充号池
   - **并行检测活跃度**（默认 `20` 线程，可用 `LUCKMAIL_CHECK_WORKERS` 调整）
   - **检测通过即刻入队**，不必等待整批检测结束
   - **自动禁用不活跃邮箱**
   - 注册时直接从队列取活跃邮箱使用
   - 队列不足时自动补充

2. **实时购买模式** (`LUCKMAIL_AUTO_BUY=true`，跳过预检测)：
   - 注册时实时购买邮箱
   - 购买后立即检测活跃度
   - 不活跃则禁用并重新购买

3. **接码模式** (`LUCKMAIL_AUTO_BUY=false`)：
   - 每次注册时创建接码订单
   - 平台自动分配临时邮箱
   - 适合快速测试

4. **已购邮箱模式**（推荐已有大量邮箱的用户）：
   - 只使用用户已购买的邮箱
   - **当前默认只使用 `@hotmail.com` 的已购邮箱**
   - 启动时批量检测已购邮箱活跃度，**谁先检测通过谁先入队**
   - 活跃的加入号池，不活跃的自动禁用
   - 若首轮没有筛到可用 Hotmail 活跃邮箱，则直接停止，不再空转线程

5. **我的邮箱模式**（适合已把 Outlook/Hotmail 导入 LuckMail 的用户）：
   - 只使用用户在 **“我的邮箱”** 中导入的邮箱
   - 启动时批量读取状态正常的邮箱并加入号池
   - 注册时直接从号池取邮箱，并通过对应邮箱邮件列表轮询验证码
   - 用完后直接停止，不购买新邮箱

### 代理配置

如果你希望把 Outlook 邮箱相关 HTTP 请求单独走一条代理，可额外配置：

```env
OUTLOOK_PROXY=http://127.0.0.1:7890
```

- 仅影响 Hotmail007 查询/购买、Microsoft Graph 收信、Microsoft OAuth 刷新等 Outlook 相关 HTTP 请求
- 未配置时，这些请求会继续复用下面的通用代理链

代理优先级：

- `--proxy` / `PROXY`
- `RESIN_URL` + `RESIN_PLATFORM_NAME`
- `--proxy-file` / `PROXY_FILE`
- 直连

#### 1. 单代理 / 代理文件

```env
# 方式一：单代理
PROXY=http://127.0.0.1:7890

# 方式二：代理列表文件 (批量注册时自动轮换)
PROXY_FILE=proxies.txt
```

#### 2. Resin 粘性代理

```env
RESIN_URL=http://127.0.0.1:2260/my-token
RESIN_PLATFORM_NAME=reg
```

- 配置了 Resin 后，会自动忽略 `PROXY_FILE` 和 `--proxy-file`
- `RESIN_URL` 格式为 `scheme://host:port/token`
- 程序会自动组装为：
  - `http://{platform.account}:{token}@{host}:{port}`
- 例如：
  - `RESIN_URL=http://127.0.0.1:2260/my-token`
  - `RESIN_PLATFORM_NAME=reg`
  - 当前账号标识为 `user_1`
  - 最终代理 URL 为 `http://reg.user_1:my-token@127.0.0.1:2260`
- 当账号邮箱已经可用时，优先使用邮箱账号部分（`@` 前缀）作为 Resin `Account`
- 若注册流程进入“请求失败后切换代理”的恢复分支，程序会放弃当前邮箱 `Account`，重新生成一个新的 6 位 startup account，并基于它重建 Resin 代理继续后续请求
- 对于启动前或尚未拿到邮箱的请求，程序会自动生成一个随机 6 位 startup account

### 批量注册配置

```env
BATCH_COUNT=10
BATCH_THREADS=2
```

### 输出路径

```env
TOKEN_OUTPUT_DIR=./tokens
CLI_PROXY_AUTHS_DIR=/path/to/auths
```

- `TOKEN_OUTPUT_DIR` -- Token JSON 文件保存目录
- 默认值为 `./tokens`，目录不存在时会自动创建
- `CLI_PROXY_AUTHS_DIR` -- 若配置，注册成功后自动拷贝 token 到该目录并删除本地副本

---

## 代理列表文件 (proxies.txt)

每行一个代理地址，空行和 `#` 开头的注释行会被忽略。

```
# HTTP 代理
http://127.0.0.1:7890
http://user:pass@proxy1.com:8080

# SOCKS5 代理
socks5://127.0.0.1:1080
socks5://user:pass@proxy2.com:1080
```

批量注册时会按 **round-robin** 顺序自动轮换使用这些代理。

---

## 命令行参数

`uv run python gpt.py [参数]`

| 参数                     | 默认值               | 说明                                        |
| ------------------------ | -------------------- | ------------------------------------------- |
| `--proxy`                | 无                   | 单个代理地址                                |
| `--proxy-file`           | 读 .env `PROXY_FILE` | 代理列表文件路径；启用 Resin 时忽略         |
| `--count`                | 无 (无限循环)        | 批量注册数量，注册够了自动停止              |
| `--threads`              | 1                    | 并发线程数                                  |
| `--once`                 | -                    | 只运行一次 (等同 `--count 1`)               |
| `--check`                | -                    | 先检测已有 token 状态，不足阈值时自动补注册 |
| `--sleep-min`            | 5                    | 每次注册间隔最短秒数                        |
| `--sleep-max`            | 30                   | 每次注册间隔最长秒数                        |
| `--email-mode`           | 读 .env              | 邮箱模式: `cf` / `hotmail007` / `luckmail` / `local_outlook` |
| `--local-outlook-mail-mode` | 读 .env           | 本地 Outlook 收信模式: `graph` / `imap`         |
| `--hotmail007-key`       | 读 .env              | 覆盖 .env 中的 Hotmail007 API Key           |
| `--hotmail007-type`      | 读 .env              | 覆盖 .env 中的邮箱类型                      |
| `--hotmail007-mail-mode` | 读 .env              | 收信模式: `graph` / `imap`                  |
| `--luckmail-key`         | 读 .env              | 覆盖 .env 中的 LuckMail API Key             |

---

## 使用示例

### 1. 单次注册 (直连)

```bash
uv run python gpt.py --once
```

### 2. 单代理注册一个

```bash
uv run python gpt.py --proxy http://127.0.0.1:7890 --once
```

### 3. 单代理批量注册 10 个

```bash
uv run python gpt.py --proxy http://127.0.0.1:7890 --count 10
```

### 4. 多代理轮换 + 批量注册

```bash
uv run python gpt.py --proxy-file proxies.txt --count 20
```

### 5. 多代理 + 3 线程并发批量注册

```bash
uv run python gpt.py --proxy-file proxies.txt --count 20 --threads 3
```

### 6. 全部配置写在 .env，直接运行

```env
PROXY_FILE=proxies.txt
BATCH_COUNT=10
BATCH_THREADS=2
```

```bash
uv run python gpt.py
```

### 7. 检测已有 token + 自动补注册

```bash
uv run python gpt.py --check --proxy-file proxies.txt
```

先扫描 `CLI_PROXY_AUTHS_DIR` 下的 token 文件，刷新过期的、删除无效的，可用数低于阈值 (默认 10) 时自动补注册。

### 8. 无限循环模式 (持续注册)

```bash
uv run python gpt.py --proxy-file proxies.txt --threads 2
```

不指定 `--count` 时为无限循环模式，按 `Ctrl+C` 停止。

### 9. 使用 Resin 粘性代理

```env
RESIN_URL=http://127.0.0.1:2260/my-token
RESIN_PLATFORM_NAME=reg
```

```bash
uv run python gpt.py --once
```

启用后不需要再传 `--proxy-file`，程序会按账号动态组装 Resin 代理。

### 10. 本地 Outlook 导入模式

```env
EMAIL_MODE=local_outlook
ACCOUNTS_FILE=accounts.txt
LOCAL_OUTLOOK_MAIL_MODE=graph
LOCAL_OUTLOOK_BAD_FILE=bad_local_outlook.txt
```

```txt
# accounts.txt
your@hotmail.com----your_password----client_id----refresh_token
```

```bash
uv run python gpt.py --count 1 --threads 1
```

### 11. 自建邮箱 / Cloudflare Worker 模式

```env
EMAIL_MODE=cf
MAIL_DOMAIN=your-domain.com
MAIL_WORKER_BASE=https://mail-worker.your-domain.com
MAIL_ADMIN_PASSWORD=your-password
CODEX2API_BASE_URL=http://localhost:8080
CODEX2API_ADMIN_SECRET=your-admin-secret
```

```bash
uv run python gpt.py --count 1 --threads 1
```

### 11. 微软邮箱多别名生成器

支持将：

```txt
email----password----client_id----refresh_token
```

或：

```txt
email:password:refresh_token:client_id
```

批量转换为：

```txt
email+suffix----password----client_id----refresh_token
```

使用方式：

```bash
uv run python alias_generator.py --input accounts.txt --per-email 5 --overwrite-accounts
```

也可以直接：

```bash
uv run python start.py
```

然后选择：

```text
5. 微软邮箱多别名生成器
```

推荐直接覆盖 `accounts.txt`：

- 生成结果会直接写回 `accounts.txt`
- 原始输入会自动备份为 `accounts.txt.bak`
- 后续 `local_outlook` / `file` 模式本来就是从 `accounts.txt` 读取，因此生成后可直接跑注册

---

## 输出示例

### 当前终端输出风格

- 顶部彩色配置面板
- 业务日志按时间顺序输出
- 实时状态仅在关键节点打印，不再周期性刷屏
- 结束时输出彩色统计面板

### LuckMail 预检测模式输出（含已购邮箱检测）

```
[*] 启动预检测后台线程，维护活跃邮箱池...
[*] 等待预检测线程准备活跃邮箱...

[*] [预检测] 首先检查已购邮箱...
[*] 获取已购邮箱列表...
[*] 获取到 50 个已购邮箱，开始检测活跃度...
[*] 已购邮箱检测完成: ✓活跃 35/50 个, 已禁用 15 个不活跃邮箱
[*] [预检测] ✓ 已从已购邮箱中添加 35 个活跃邮箱 | 队列: 35 个
==================================================
[*] [预检测] 活跃邮箱池不足 (35/10)，批量购买 20 个...
==================================================
[*] 批量购买 20 个邮箱 (类型: ms_imap)...
[*] 成功购买 20 个邮箱，开始并行检测活跃度...
[*] 检测完成: ✓活跃 3 个, ✗不活跃 17 个(已禁用17个)
[*] 活跃邮箱列表:
    ✓ example1@hotmail.com
    ✓ example2@hotmail.com
    ✓ example3@hotmail.com
[*] [预检测] ✓ 已补充 3 个活跃邮箱 | 队列: 38 个

[T1#1] [12:28:05] 开始注册 (代理: http://127.0.0.1:1082)
[*] 当前 IP 所在地: JP
[*] ✓ 使用预检测活跃邮箱: example1@hotmail.com
[*] 活跃邮箱池: 37 个待使用
...
```

---

## 输出文件

| 文件                        | 说明                                                               |
| --------------------------- | ------------------------------------------------------------------ |
| `token_xxx@xxx_时间戳.json` | 注册成功的 Token JSON (含 access_token / refresh_token / email 等) |
| `accounts.txt`              | 输入账号文件；`file` 或 `local_outlook` 模式会读取它               |
| `tokens/accounts.txt`       | 所有成功注册的账号密码，格式: `邮箱----密码`                       |
| `tokens/emails.txt`         | Hotmail007 成功注册时导出的原始微软邮箱凭据，格式: `原始邮箱----邮箱密码----client_id----refresh_token` |
| `bad_local_outlook.txt`     | 本地 Outlook 模式失效账号记录                                      |

---

## 注意事项

1. **代理必须为非 CN/HK 地区的 IP**，否则网络检查会拦截
2. **多线程数建议不超过代理数量**，避免同一代理并发过多被风控
3. `Ctrl+C` 可随时优雅中断所有线程
4. `--sleep-min` / `--sleep-max` 控制注册间隔，防止频率过高
5. **LuckMail 预检测模式**会优先检测已购邮箱活跃度，再批量购买新邮箱补充号池
6. **已购邮箱模式**当前默认只筛选 `@hotmail.com`，并把检测通过的邮箱立即加入号池
7. 可用 `LUCKMAIL_CHECK_WORKERS` 调整已购/预检测活跃度检测并发数（默认 `20`）
8. 排查 LuckMail 收不到验证码时，可临时开启 `LUCKMAIL_MAIL_DEBUG=true` 查看 `token/mails` 摘要、最近邮件主题与 fallback 状态
9. `local_outlook` 模式下，`accounts.txt` 读取后会被消费；失效号会追加到 `LOCAL_OUTLOOK_BAD_FILE`
10. `cf` 模式下如果收不到验证码，优先检查 `MAIL_WORKER_BASE` 是否包含协议（例如 `https://`）以及 `/admin/mails` 是否能返回目标邮箱邮件
11. Web UI 当前属于**实验版**，建议用于辅助查看与导入；批量注册、稳定运行、问题排查仍推荐优先使用终端版
12. 多别名生成器当前默认只处理 `@hotmail.*` 和 `@outlook.*`，其他域名会自动跳过
