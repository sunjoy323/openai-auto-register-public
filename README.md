# openai-auto-register

OpenAI 账号自动注册工具，仅供学习与技术研究使用。

---

## ⚠️ 免责声明

本项目仅用于学习、研究和技术交流目的。使用本工具可能违反 [OpenAI 服务条款](https://openai.com/policies/terms-of-use)，请使用者自行评估风险并承担全部责任。作者不对任何直接或间接损失负责，也不鼓励任何滥用行为。

---

## 前置条件

- Python **3.10+**
- 可用的**境外代理**（需能访问 OpenAI，不支持 CN/HK 出口 IP）
- `curl_cffi` 依赖（见安装步骤）

---

## 安装

```bash
# 克隆仓库
git clone <this-repo>
cd openai-auto-register

# 创建虚拟环境（推荐）
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 复制并编辑配置文件
cp config.json.example config.json
# 修改 config.json 中的代理地址与收码方式
```

---

## 用法

### 通过 run.py（推荐，支持批量/并行）

```bash
# 注册 1 个账号
python3 run.py --once

# 注册 5 个账号（单线程）
python3 run.py --count 5

# 3 线程并行，注册 10 个
python3 run.py --count 10 --parallel 3

# 无限循环注册
python3 run.py
```

### 直接使用 register.py（单次测试）

```bash
python3 register.py --once --config config.json
```

### 通过 `team_login_run.py` 批量登录邮箱列表并换取 Team Token

```bash
python3 team_login_run.py --config config.json
```

---

## 文件说明

| 文件 | 说明 |
|------|------|
| `register.py` | 核心注册逻辑，可独立运行 |
| `run.py` | 批量/并行运行脚本，读取 config.json |
| `team_login_run.py` | 读取邮箱列表，使用一次性验证码登录后选择 Team 工作空间并保存 Token |
| `config.json.example` | 配置文件模板，复制为 config.json 后使用 |
| `requirements.txt` | Python 依赖列表 |
| `tokens/` | 注册成功的 Token 存放目录（自动创建） |
| `history.log` | 注册历史日志（自动创建） |

---

## 配置说明

```json
{
  "proxy": "http://127.0.0.1:7890",
  "mail_provider": "mailtm",
  "domain": "",
  "imap_host": "imap.163.com",
  "imap_port": 993,
  "imap_user": "",
  "imap_pass": "",
  "imap_folder": "INBOX",
  "team_login": {
    "workspace_id": "",
    "workspace_name": "",
    "prefer_team": true,
    "sleep_seconds": 3,
    "token_dir": "",
    "emails": []
  },
  "register": {
    "sleep_min": 5,
    "sleep_max": 30,
    "email_prefix": "gk"
  }
}
```

| 字段 | 说明 |
|------|------|
| `proxy` | HTTP 代理地址 |
| `mail_provider` | 收码方式，支持 `mailtm` / `imap`，默认 `mailtm` |
| `domain` | `imap` 模式下用于生成注册邮箱的域名；留空则直接使用 `imap_user` |
| `imap_host` | `imap` 模式下的 IMAP 服务器地址 |
| `imap_port` | `imap` 模式下的 IMAP 端口，默认 `993` |
| `imap_user` | `imap` 模式下的登录邮箱 |
| `imap_pass` | `imap` 模式下的登录密码或客户端授权码 |
| `imap_folder` | `imap` 模式下读取的文件夹，默认 `INBOX` |
| `team_login.workspace_id` | 批量登录脚本要选择的工作空间 ID，优先级最高 |
| `team_login.workspace_name` | 批量登录脚本要选择的工作空间名称，未填 `workspace_id` 时使用 |
| `team_login.prefer_team` | 未指定 ID/名称时是否优先选择看起来像 Team 的工作空间 |
| `team_login.sleep_seconds` | 邮箱列表脚本每个邮箱之间的等待秒数 |
| `team_login.token_dir` | 邮箱列表脚本保存 Token 的目录，留空则默认 `tokens/` |
| `team_login.emails` | 需要执行 OTP 登录的邮箱列表 |
| `register.sleep_min` | 两次注册之间最短等待秒数 |
| `register.sleep_max` | 两次注册之间最长等待秒数 |
| `register.email_prefix` | 注册邮箱前缀，`mailtm` 和 `imap + domain` 模式都会使用 |

当 `mail_provider=imap` 时，脚本会参考 `use_163mail/openai-auto-register` 的做法，通过 IMAP 轮询验证码邮件，并自动兼容 163/126 这类需要发送 `IMAP ID` 的邮箱服务器。

如果你配置了 `domain`，脚本会生成 `register.email_prefix + 随机串@domain` 这样的注册邮箱；如果 `domain` 留空，则直接使用 `imap_user` 作为注册邮箱。后者没法批量变邮箱，别头铁开高并发，不然自己跟自己抢验证码。

如果你使用 `team_login_run.py`，建议显式填写 `team_login.workspace_id` 或 `team_login.workspace_name`。不填也能跑，但只能靠脚本按字段猜哪个像 Team 工作空间，能用但不够稳，别把玄学当能力。

---

## 原理简述

整个注册流程分为以下几个阶段：

1. **邮箱准备**  
   默认调用 [mail.tm](https://mail.tm) 公开 API 动态创建临时邮箱；如果配置了 `mail_provider=imap`，则使用配置中的 IMAP 邮箱收取验证码。

2. **OAuth PKCE 授权流程**  
   模拟 OpenAI Codex CLI 的登录方式，使用 OAuth 2.0 + PKCE（Proof Key for Code Exchange）协议发起授权请求，获取 `state` 和 `code_verifier`。

3. **Sentinel 反爬过验证**  
   向 OpenAI Sentinel 端点发送设备指纹请求，获取 `sentinel token`，附带在后续注册请求的请求头中，绕过 bot 检测。

4. **OTP 邮箱验证**  
   提交注册表单后，OpenAI 会发送 6 位数字验证码（OTP）。脚本会根据配置轮询 Mail.tm API 或 IMAP 收件箱，自动提取验证码并提交校验。

5. **Workspace 选择 + Token 换取**  
   创建账号后自动选择默认 workspace，跟随重定向链，在 callback URL 中提取 `code`，最终通过 PKCE 换取 `access_token` / `refresh_token` / `id_token`。

---

## 输出格式

注册成功后，Token 以 JSON 文件保存在 `tokens/` 目录：

```json
{
  "id_token": "...",
  "access_token": "...",
  "refresh_token": "...",
  "account_id": "...",
  "last_refresh": "2025-01-01T00:00:00Z",
  "email": "xxx@mail.tm",
  "type": "codex",
  "expired": "2025-01-02T00:00:00Z"
}
```
