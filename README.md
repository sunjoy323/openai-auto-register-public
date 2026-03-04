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
# 修改 config.json 中的代理地址
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
python3 register.py --once --proxy http://127.0.0.1:7890
```

---

## 文件说明

| 文件 | 说明 |
|------|------|
| `register.py` | 核心注册逻辑，可独立运行 |
| `run.py` | 批量/并行运行脚本，读取 config.json |
| `config.json.example` | 配置文件模板，复制为 config.json 后使用 |
| `requirements.txt` | Python 依赖列表 |
| `tokens/` | 注册成功的 Token 存放目录（自动创建） |
| `history.log` | 注册历史日志（自动创建） |

---

## 配置说明

```json
{
  "proxy": "http://127.0.0.1:7890",
  "register": {
    "sleep_min": 5,
    "sleep_max": 30
  }
}
```

| 字段 | 说明 |
|------|------|
| `proxy` | HTTP 代理地址 |
| `register.sleep_min` | 两次注册之间最短等待秒数 |
| `register.sleep_max` | 两次注册之间最长等待秒数 |

---

## 原理简述

整个注册流程分为以下几个阶段：

1. **Mail.tm 临时邮箱**  
   调用 [mail.tm](https://mail.tm) 公开 API，动态创建一个临时邮箱地址，用于接收 OpenAI 发送的验证码。

2. **OAuth PKCE 授权流程**  
   模拟 OpenAI Codex CLI 的登录方式，使用 OAuth 2.0 + PKCE（Proof Key for Code Exchange）协议发起授权请求，获取 `state` 和 `code_verifier`。

3. **Sentinel 反爬过验证**  
   向 OpenAI Sentinel 端点发送设备指纹请求，获取 `sentinel token`，附带在后续注册请求的请求头中，绕过 bot 检测。

4. **OTP 邮箱验证**  
   提交注册表单后，OpenAI 会向临时邮箱发送 6 位数字验证码（OTP）。脚本轮询 Mail.tm API，自动提取验证码并提交校验。

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
