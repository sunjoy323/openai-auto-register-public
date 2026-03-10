# ==============================================================================
# 免责声明
# 本脚本仅供学习和技术研究使用，禁止用于任何商业用途或违反服务条款的行为。
# 使用本脚本所产生的一切后果由使用者自行承担，作者不承担任何法律责任。
# OpenAI 服务条款地址：https://openai.com/policies/terms-of-use
# ==============================================================================

import json
import os
import re
import sys
import time
import imaplib
import uuid
import math
import random
import string
import secrets
import hashlib
import base64
import email as email_module
import threading
import subprocess
import argparse
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, parse_qs, urlencode, quote
from dataclasses import dataclass, field
from email.header import decode_header
from email.message import Message
from email.utils import getaddresses, parsedate_to_datetime
from typing import Any, Dict, Optional
import urllib.parse
import urllib.request
import urllib.error

try:
    from curl_cffi import requests
except ModuleNotFoundError as exc:
    raise SystemExit("[Error] 缺少依赖 curl_cffi，请先执行 `pip install -r requirements.txt`，并确认使用的是项目虚拟环境。") from exc

# ==========================================
# Mail.tm 临时邮箱 API
# ==========================================

MAILTM_BASE = "https://api.mail.tm"

IMAP_TRUTHY = {"true", "1", "yes", "on"}
IMAP_FALSY = {"false", "0", "no", "off"}


@dataclass
class ImapConfig:
    host: str = ""
    port: int = 993
    user: str = ""
    password: str = ""
    folder: str = "INBOX"
    domain: str = ""
    id_mode: str = "auto"
    id_name: str = "openai-auto-register"
    id_version: str = "1.0.0"
    id_vendor: str = "openai-auto-register"
    id_support_email: str = ""


@dataclass
class MailProviderConfig:
    provider: str = "mailtm"
    email_prefix: str = "oc"
    imap: ImapConfig = field(default_factory=ImapConfig)


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _clean_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _config_value(raw_cfg: Dict[str, Any], nested_cfg: Dict[str, Any], key: str, default: Any = "") -> Any:
    if key in nested_cfg:
        return nested_cfg.get(key, default)
    return raw_cfg.get(key, default)


def build_mail_provider_config(raw_cfg: Optional[Dict[str, Any]], email_prefix: str = "oc") -> MailProviderConfig:
    config = raw_cfg if isinstance(raw_cfg, dict) else {}
    nested_imap = config.get("imap", {}) if isinstance(config.get("imap"), dict) else {}

    provider = _clean_text(config.get("mail_provider"), "mailtm").lower() or "mailtm"
    if provider not in {"mailtm", "imap"}:
        provider = "mailtm"

    imap = ImapConfig(
        host=_clean_text(_config_value(config, nested_imap, "imap_host")),
        port=_safe_int(_config_value(config, nested_imap, "imap_port", 993), 993),
        user=_clean_text(_config_value(config, nested_imap, "imap_user")),
        password=_clean_text(_config_value(config, nested_imap, "imap_pass")),
        folder=_clean_text(_config_value(config, nested_imap, "imap_folder"), "INBOX") or "INBOX",
        domain=_clean_text(_config_value(config, nested_imap, "domain")),
        id_mode=_clean_text(_config_value(config, nested_imap, "imap_id_mode"), "auto").lower() or "auto",
        id_name=_clean_text(_config_value(config, nested_imap, "imap_id_name"), "openai-auto-register") or "openai-auto-register",
        id_version=_clean_text(_config_value(config, nested_imap, "imap_id_version"), "1.0.0") or "1.0.0",
        id_vendor=_clean_text(_config_value(config, nested_imap, "imap_id_vendor"), "openai-auto-register") or "openai-auto-register",
        id_support_email=_clean_text(_config_value(config, nested_imap, "imap_id_support_email")),
    )

    return MailProviderConfig(
        provider=provider,
        email_prefix=_clean_text(email_prefix, "oc") or "oc",
        imap=imap,
    )


def validate_mail_provider_config(mail_cfg: MailProviderConfig) -> None:
    if mail_cfg.provider != "imap":
        return

    missing = []
    if not mail_cfg.imap.host:
        missing.append("imap_host")
    if not mail_cfg.imap.user:
        missing.append("imap_user")
    if not mail_cfg.imap.password:
        missing.append("imap_pass")

    if missing:
        raise ValueError(f"当前 mail_provider=imap，缺少配置项: {', '.join(missing)}")

    if not mail_cfg.imap.domain and "@" not in mail_cfg.imap.user:
        raise ValueError("IMAP 模式需要配置 domain，或让 imap_user 直接填写完整邮箱地址")


def _mailtm_headers(*, token: str = "", use_json: bool = False) -> Dict[str, str]:
    headers = {"Accept": "application/json"}
    if use_json:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _mailtm_req(method: str, url: str, headers: dict, proxies: Any = None, timeout: int = 12, json_body=None) -> Any:
    """使用已安装的 curl_cffi.requests 发起 Mail.tm 请求"""

    class FakeResp:
        def __init__(self, body, status):
            self._body = body
            self.status_code = status
        def json(self):
            return __import__('json').loads(self._body)

    try:
        if method.upper() == "POST":
            r = requests.post(url, headers=headers, proxies=proxies, timeout=timeout, json=json_body)
        else:
            r = requests.get(url, headers=headers, proxies=proxies, timeout=timeout)
        return FakeResp(r.content, r.status_code)
    except Exception:
        return FakeResp(b'{}', 0)


def _mailtm_get(url: str, headers: dict, proxies: Any = None, timeout: int = 12) -> Any:
    return _mailtm_req("GET", url, headers, proxies, timeout)


def _mailtm_domains(proxies: Any = None) -> list[str]:
    resp = _mailtm_req("GET",
        f"{MAILTM_BASE}/domains",
        headers=_mailtm_headers(),
        proxies=proxies,
        timeout=15,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"获取 Mail.tm 域名失败，状态码: {resp.status_code}")

    data = resp.json()
    domains = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("hydra:member") or data.get("items") or []
    else:
        items = []

    for item in items:
        if not isinstance(item, dict):
            continue
        domain = str(item.get("domain") or "").strip()
        is_active = item.get("isActive", True)
        is_private = item.get("isPrivate", False)
        if domain and is_active and not is_private:
            domains.append(domain)

    return domains


def should_send_imap_id(imap_cfg: ImapConfig) -> bool:
    mode = imap_cfg.id_mode
    if mode in IMAP_TRUTHY:
        return True
    if mode in IMAP_FALSY:
        return False

    host = imap_cfg.host.lower()
    user = imap_cfg.user.lower()
    netease_hosts = ("163.com", "126.com", "yeah.net", "188.com")
    netease_domains = ("@163.com", "@126.com", "@yeah.net", "@188.com")
    return any(key in host for key in netease_hosts) or user.endswith(netease_domains)


def imap_quote(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def send_imap_id_if_needed(mailbox: imaplib.IMAP4_SSL, imap_cfg: ImapConfig) -> None:
    if not should_send_imap_id(imap_cfg):
        return

    support_email = imap_cfg.id_support_email or (imap_cfg.user if "@" in imap_cfg.user else "noreply@example.com")
    id_pairs = [
        ("name", imap_cfg.id_name),
        ("version", imap_cfg.id_version),
        ("vendor", imap_cfg.id_vendor),
        ("support-email", support_email),
    ]
    payload = " ".join(f'"{key}" "{imap_quote(val)}"' for key, val in id_pairs if val)
    if not payload:
        return

    try:
        typ, data = mailbox.xatom("ID", f"({payload})")
        if str(typ).upper() == "OK":
            print("[*] 已发送 IMAP ID 标识")
        else:
            print(f"[Warn] IMAP ID 返回异常: {typ} {data}")
    except Exception as e:
        print(f"[Warn] 发送 IMAP ID 失败，已忽略: {e}")


def build_imap_registration_email(mail_cfg: MailProviderConfig) -> str:
    domain = mail_cfg.imap.domain
    if domain:
        local = f"{mail_cfg.email_prefix}{secrets.token_hex(5)}"
        return f"{local}@{domain}"

    user = mail_cfg.imap.user
    if "@" in user:
        return user

    return ""


def _decode_mime_value(value: str) -> str:
    if not value:
        return ""

    parts = []
    for chunk, encoding in decode_header(value):
        if isinstance(chunk, bytes):
            try:
                parts.append(chunk.decode(encoding or "utf-8", errors="ignore"))
            except LookupError:
                parts.append(chunk.decode("utf-8", errors="ignore"))
        else:
            parts.append(str(chunk))
    return "".join(parts)


def _extract_message_body(msg: Message) -> str:
    bodies = []
    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        content_type = part.get_content_type()
        disposition = str(part.get("Content-Disposition") or "").lower()
        if "attachment" in disposition:
            continue
        if content_type not in {"text/plain", "text/html"}:
            continue

        payload = part.get_payload(decode=True)
        if payload is None:
            bodies.append(str(part.get_payload() or ""))
            continue

        charset = part.get_content_charset() or "utf-8"
        try:
            bodies.append(payload.decode(charset, errors="ignore"))
        except LookupError:
            bodies.append(payload.decode("utf-8", errors="ignore"))
    return "\n".join(body for body in bodies if body)


def _message_timestamp(msg: Message) -> Optional[float]:
    date_header = msg.get("Date")
    if not date_header:
        return None
    try:
        parsed = parsedate_to_datetime(date_header)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _recipient_matches(msg: Message, email_addr: str, body: str) -> bool:
    email_lower = email_addr.lower()
    header_values = []
    for header_name in ("To", "Cc", "Delivered-To", "X-Original-To", "X-Forwarded-To"):
        for header_value in msg.get_all(header_name, []):
            header_values.append(_decode_mime_value(header_value))

    addresses = [addr.lower() for _, addr in getaddresses(header_values) if addr]
    if any(email_lower == addr or email_lower in addr for addr in addresses):
        return True
    if any(email_lower in value.lower() for value in header_values):
        return True
    return email_lower in body.lower()


def get_email_and_token(proxies: Any = None, prefix: str = "oc", mail_cfg: Optional[MailProviderConfig] = None) -> tuple[str, str]:
    """根据配置获取注册邮箱；Mail.tm 返回邮箱+Token，IMAP 返回邮箱"""
    if mail_cfg and mail_cfg.provider == "imap":
        email_addr = build_imap_registration_email(mail_cfg)
        if not email_addr:
            print("[Error] IMAP 模式未能生成注册邮箱，请检查 domain 或 imap_user 配置")
            return "", ""
        if mail_cfg.imap.domain:
            print(f"[*] IMAP 模式已生成注册邮箱: {email_addr}")
        else:
            print(f"[*] IMAP 模式将直接使用邮箱: {email_addr}")
        return email_addr, ""

    try:
        domains = _mailtm_domains(proxies)
        if not domains:
            print("[Error] Mail.tm 没有可用域名")
            return "", ""
        domain = random.choice(domains)

        for _ in range(5):
            local = f"{prefix}{secrets.token_hex(5)}"
            email = f"{local}@{domain}"
            password = secrets.token_urlsafe(18)

            create_resp = _mailtm_req("POST",
                f"{MAILTM_BASE}/accounts",
                headers=_mailtm_headers(use_json=True),
                proxies=proxies,
                timeout=15,
                json_body={"address": email, "password": password},
            )

            if create_resp.status_code not in (200, 201):
                continue

            token_resp = _mailtm_req("POST",
                f"{MAILTM_BASE}/token",
                headers=_mailtm_headers(use_json=True),
                proxies=proxies,
                timeout=15,
                json_body={"address": email, "password": password},
            )

            if token_resp.status_code == 200:
                token = str(token_resp.json().get("token") or "").strip()
                if token:
                    return email, token

        print("[Error] Mail.tm 邮箱创建成功但获取 Token 失败")
        return "", ""
    except Exception as e:
        print(f"[Error] 请求 Mail.tm API 出错: {e}")
        return "", ""


def get_oai_code_imap(mail_cfg: MailProviderConfig, email_addr: str, timeout: int = 120) -> str:
    regex = r"(?<!\d)(\d{6})(?!\d)"
    seen_ids: set[bytes] = set()
    start_ts = time.time()
    mailbox: Optional[imaplib.IMAP4_SSL] = None

    print(f"[*] 正在等待邮箱 {email_addr} 的验证码 (IMAP)...", end="", flush=True)

    try:
        mailbox = imaplib.IMAP4_SSL(mail_cfg.imap.host, mail_cfg.imap.port, timeout=15)
        try:
            mailbox.login(mail_cfg.imap.user, mail_cfg.imap.password)
        except imaplib.IMAP4.error as e:
            if "Unsafe Login" in str(e):
                print(" [Error] IMAP 登录被拒绝: Unsafe Login，请确认已启用 IMAP、使用客户端授权码，并保留 imap_id_mode=true")
            raise
        send_imap_id_if_needed(mailbox, mail_cfg.imap)

        status, data = mailbox.select(mail_cfg.imap.folder)
        if status != "OK":
            detail = ""
            if isinstance(data, (list, tuple)) and data:
                first = data[0]
                if isinstance(first, bytes):
                    detail = first.decode("utf-8", errors="ignore")
                else:
                    detail = str(first)
            print(f" [Error] 无法打开 IMAP 收件箱: {mail_cfg.imap.folder} {detail}".rstrip())
            return ""

        while time.time() - start_ts < timeout:
            print(".", end="", flush=True)
            try:
                mailbox.noop()
            except Exception:
                pass

            status, data = mailbox.search(None, "ALL")
            if status != "OK" or not data:
                time.sleep(3)
                continue

            message_ids = data[0].split()
            for msg_id in reversed(message_ids[-20:]):
                if msg_id in seen_ids:
                    continue
                seen_ids.add(msg_id)

                fetch_status, fetch_data = mailbox.fetch(msg_id, "(RFC822)")
                if fetch_status != "OK" or not fetch_data:
                    continue

                raw_message = None
                for item in fetch_data:
                    if isinstance(item, tuple) and len(item) >= 2:
                        raw_message = item[1]
                        break
                if not raw_message:
                    continue

                msg = email_module.message_from_bytes(raw_message)
                msg_ts = _message_timestamp(msg)
                if msg_ts is not None and msg_ts < (start_ts - 120):
                    continue

                sender = _decode_mime_value(msg.get("From", ""))
                subject = _decode_mime_value(msg.get("Subject", ""))
                body = _extract_message_body(msg)
                content = "\n".join([sender, subject, body])

                if "openai" not in content.lower():
                    continue
                if not _recipient_matches(msg, email_addr, body):
                    continue

                match = re.search(regex, content)
                if not match:
                    continue

                otp_code = match.group(1)
                print(" 抓到啦! 验证码:", otp_code)
                try:
                    mailbox.store(msg_id, "+FLAGS", r"(\Deleted)")
                    mailbox.expunge()
                except Exception:
                    pass
                return otp_code

            time.sleep(3)
    except imaplib.IMAP4.error as e:
        print(f" [Error] IMAP 登录或读取失败: {e}")
    except Exception as e:
        print(f" [Error] IMAP 获取验证码失败: {e}")
    finally:
        print("", flush=True)
        if mailbox is not None:
            try:
                mailbox.close()
            except Exception:
                pass
            try:
                mailbox.logout()
            except Exception:
                pass

    print(" 超时，未收到验证码")
    return ""


def get_oai_code(token: str, email: str, proxies: Any = None, mail_cfg: Optional[MailProviderConfig] = None) -> str:
    """按收件方式轮询获取 OpenAI 验证码"""
    if mail_cfg and mail_cfg.provider == "imap":
        return get_oai_code_imap(mail_cfg, email)

    url_list = f"{MAILTM_BASE}/messages"
    regex = r"(?<!\d)(\d{6})(?!\d)"
    seen_ids: set[str] = set()

    print(f"[*] 正在等待邮箱 {email} 的验证码...", end="", flush=True)

    for _ in range(40):
        print(".", end="", flush=True)
        try:
            resp = _mailtm_get(
                url_list,
                headers=_mailtm_headers(token=token),
                proxies=proxies,
                timeout=12,
            )
            if resp.status_code != 200:
                time.sleep(3)
                continue

            data = resp.json()
            if isinstance(data, list):
                messages = data
            elif isinstance(data, dict):
                messages = data.get("hydra:member") or data.get("messages") or []
            else:
                messages = []

            for msg in messages:
                if not isinstance(msg, dict):
                    continue
                msg_id = str(msg.get("id") or "").strip()
                if not msg_id or msg_id in seen_ids:
                    continue
                seen_ids.add(msg_id)

                read_resp = _mailtm_get(
                    f"{MAILTM_BASE}/messages/{msg_id}",
                    headers=_mailtm_headers(token=token),
                    proxies=proxies,
                    timeout=12,
                )
                if read_resp.status_code != 200:
                    continue

                mail_data = read_resp.json()
                sender = str(
                    ((mail_data.get("from") or {}).get("address") or "")
                ).lower()
                subject = str(mail_data.get("subject") or "")
                intro = str(mail_data.get("intro") or "")
                text = str(mail_data.get("text") or "")
                html = mail_data.get("html") or ""
                if isinstance(html, list):
                    html = "\n".join(str(x) for x in html)
                content = "\n".join([subject, intro, text, str(html)])

                if "openai" not in sender and "openai" not in content.lower():
                    continue

                m = re.search(regex, content)
                if m:
                    print(" 抓到啦! 验证码:", m.group(1))
                    return m.group(1)
        except Exception:
            pass

        time.sleep(3)

    print(" 超时，未收到验证码")
    return ""


# ==========================================
# OAuth 授权与辅助函数
# ==========================================

AUTH_URL = "https://auth.openai.com/oauth/authorize"
TOKEN_URL = "https://auth.openai.com/oauth/token"
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"

DEFAULT_REDIRECT_URI = "http://localhost:1455/auth/callback"
DEFAULT_SCOPE = "openid email profile offline_access"


def _b64url_no_pad(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _sha256_b64url_no_pad(s: str) -> str:
    return _b64url_no_pad(hashlib.sha256(s.encode("ascii")).digest())


def _random_state(nbytes: int = 16) -> str:
    return secrets.token_urlsafe(nbytes)


def _pkce_verifier() -> str:
    return secrets.token_urlsafe(64)


def _parse_callback_url(callback_url: str) -> Dict[str, str]:
    candidate = callback_url.strip()
    if not candidate:
        return {"code": "", "state": "", "error": "", "error_description": ""}

    if "://" not in candidate:
        if candidate.startswith("?"):
            candidate = f"http://localhost{candidate}"
        elif any(ch in candidate for ch in "/?#") or ":" in candidate:
            candidate = f"http://{candidate}"
        elif "=" in candidate:
            candidate = f"http://localhost/?{candidate}"

    parsed = urllib.parse.urlparse(candidate)
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    fragment = urllib.parse.parse_qs(parsed.fragment, keep_blank_values=True)

    for key, values in fragment.items():
        if key not in query or not query[key] or not (query[key][0] or "").strip():
            query[key] = values

    def get1(k: str) -> str:
        v = query.get(k, [""])
        return (v[0] or "").strip()

    code = get1("code")
    state = get1("state")
    error = get1("error")
    error_description = get1("error_description")

    if code and not state and "#" in code:
        code, state = code.split("#", 1)

    if not error and error_description:
        error, error_description = error_description, ""

    return {
        "code": code,
        "state": state,
        "error": error,
        "error_description": error_description,
    }


def _jwt_claims_no_verify(id_token: str) -> Dict[str, Any]:
    if not id_token or id_token.count(".") < 2:
        return {}
    payload_b64 = id_token.split(".")[1]
    pad = "=" * ((4 - (len(payload_b64) % 4)) % 4)
    try:
        payload = base64.urlsafe_b64decode((payload_b64 + pad).encode("ascii"))
        return json.loads(payload.decode("utf-8"))
    except Exception:
        return {}


def _decode_jwt_segment(seg: str) -> Dict[str, Any]:
    raw = (seg or "").strip()
    if not raw:
        return {}
    pad = "=" * ((4 - (len(raw) % 4)) % 4)
    try:
        decoded = base64.urlsafe_b64decode((raw + pad).encode("ascii"))
        return json.loads(decoded.decode("utf-8"))
    except Exception:
        return {}


def _to_int(v: Any) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _post_form(url: str, data: Dict[str, str], timeout: int = 30) -> Dict[str, Any]:
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if resp.status != 200:
                raise RuntimeError(
                    f"token exchange failed: {resp.status}: {raw.decode('utf-8', 'replace')}"
                )
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        raise RuntimeError(
            f"token exchange failed: {exc.code}: {raw.decode('utf-8', 'replace')}"
        ) from exc


@dataclass(frozen=True)
class OAuthStart:
    auth_url: str
    state: str
    code_verifier: str
    redirect_uri: str


def generate_oauth_url(
    *, redirect_uri: str = DEFAULT_REDIRECT_URI, scope: str = DEFAULT_SCOPE
) -> OAuthStart:
    state = _random_state()
    code_verifier = _pkce_verifier()
    code_challenge = _sha256_b64url_no_pad(code_verifier)

    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "prompt": "login",
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
    }
    auth_url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"
    return OAuthStart(
        auth_url=auth_url,
        state=state,
        code_verifier=code_verifier,
        redirect_uri=redirect_uri,
    )


def submit_callback_url(
    *,
    callback_url: str,
    expected_state: str,
    code_verifier: str,
    redirect_uri: str = DEFAULT_REDIRECT_URI,
) -> str:
    cb = _parse_callback_url(callback_url)
    if cb["error"]:
        desc = cb["error_description"]
        raise RuntimeError(f"oauth error: {cb['error']}: {desc}".strip())

    if not cb["code"]:
        raise ValueError("callback url missing ?code=")
    if not cb["state"]:
        raise ValueError("callback url missing ?state=")
    if cb["state"] != expected_state:
        raise ValueError("state mismatch")

    token_resp = _post_form(
        TOKEN_URL,
        {
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": cb["code"],
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        },
    )

    access_token = (token_resp.get("access_token") or "").strip()
    refresh_token = (token_resp.get("refresh_token") or "").strip()
    id_token = (token_resp.get("id_token") or "").strip()
    expires_in = _to_int(token_resp.get("expires_in"))

    claims = _jwt_claims_no_verify(id_token)
    email = str(claims.get("email") or "").strip()
    auth_claims = claims.get("https://api.openai.com/auth") or {}
    account_id = str(auth_claims.get("chatgpt_account_id") or "").strip()

    now = int(time.time())
    expired_rfc3339 = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + max(expires_in, 0))
    )
    now_rfc3339 = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))

    config = {
        "id_token": id_token,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "account_id": account_id,
        "last_refresh": now_rfc3339,
        "email": email,
        "type": "codex",
        "expired": expired_rfc3339,
    }

    return json.dumps(config, ensure_ascii=False, separators=(",", ":"))


# ==========================================
# 核心注册逻辑
# ==========================================


def run(proxy: Optional[str], email_prefix: str = "oc", config: Optional[Dict[str, Any]] = None) -> Optional[str]:
    proxies: Any = None
    if proxy:
        proxies = {"http": proxy, "https": proxy}

    mail_cfg = build_mail_provider_config(config, email_prefix)
    try:
        validate_mail_provider_config(mail_cfg)
    except ValueError as e:
        print(f"[Error] {e}")
        return None

    s = requests.Session(proxies=proxies, impersonate="chrome")

    try:
        trace = s.get("https://cloudflare.com/cdn-cgi/trace", timeout=10)
        trace = trace.text
        loc_re = re.search(r"^loc=(.+)$", trace, re.MULTILINE)
        loc = loc_re.group(1) if loc_re else None
        print(f"[*] 当前 IP 所在地: {loc}")
        if loc == "CN" or loc == "HK":
            raise RuntimeError("检查代理哦 - 所在地不支持")
    except Exception as e:
        print(f"[Error] 网络连接检查失败: {e}")
        return None

    email, dev_token = get_email_and_token(proxies, email_prefix, mail_cfg)
    if not email or not dev_token:
        if mail_cfg.provider != "imap":
            return None
        if not email:
            return None
    elif mail_cfg.provider == "mailtm":
        print(f"[*] 成功获取 Mail.tm 邮箱与授权: {email}")

    oauth = generate_oauth_url()
    url = oauth.auth_url

    try:
        resp = s.get(url, timeout=15)
        did = s.cookies.get("oai-did")
        print(f"[*] Device ID: {did}")

        signup_body = f'{{"username":{{"value":"{email}","kind":"email"}},"screen_hint":"signup"}}'
        sen_req_body = f'{{"p":"","id":"{did}","flow":"authorize_continue"}}'

        sen_resp = requests.post(
            "https://sentinel.openai.com/backend-api/sentinel/req",
            headers={
                "origin": "https://sentinel.openai.com",
                "referer": "https://sentinel.openai.com/backend-api/sentinel/frame.html?sv=20260219f9f6",
                "content-type": "text/plain;charset=UTF-8",
            },
            data=sen_req_body,
            proxies=proxies,
            impersonate="chrome",
            timeout=15,
        )

        if sen_resp.status_code != 200:
            print(f"[Error] Sentinel 异常拦截，状态码: {sen_resp.status_code}")
            return None

        sen_token = sen_resp.json()["token"]
        sentinel = f'{{"p": "", "t": "", "c": "{sen_token}", "id": "{did}", "flow": "authorize_continue"}}'

        signup_resp = s.post(
            "https://auth.openai.com/api/accounts/authorize/continue",
            headers={
                "referer": "https://auth.openai.com/create-account",
                "accept": "application/json",
                "content-type": "application/json",
                "openai-sentinel-token": sentinel,
            },
            data=signup_body,
        )
        print(f"[*] 提交注册表单状态: {signup_resp.status_code}")

        otp_resp = s.post(
            "https://auth.openai.com/api/accounts/passwordless/send-otp",
            headers={
                "referer": "https://auth.openai.com/create-account/password",
                "accept": "application/json",
                "content-type": "application/json",
            },
        )
        print(f"[*] 验证码发送状态: {otp_resp.status_code}")

        code = get_oai_code(dev_token, email, proxies, mail_cfg)
        if not code:
            return None

        code_body = f'{{"code":"{code}"}}'
        code_resp = s.post(
            "https://auth.openai.com/api/accounts/email-otp/validate",
            headers={
                "referer": "https://auth.openai.com/email-verification",
                "accept": "application/json",
                "content-type": "application/json",
            },
            data=code_body,
        )
        print(f"[*] 验证码校验状态: {code_resp.status_code}")

        create_account_body = '{"name":"Neo","birthdate":"2000-02-20"}'
        create_account_resp = s.post(
            "https://auth.openai.com/api/accounts/create_account",
            headers={
                "referer": "https://auth.openai.com/about-you",
                "accept": "application/json",
                "content-type": "application/json",
            },
            data=create_account_body,
        )
        create_account_status = create_account_resp.status_code
        print(f"[*] 账户创建状态: {create_account_status}")

        if create_account_status != 200:
            print(create_account_resp.text)
            return None

        auth_cookie = s.cookies.get("oai-client-auth-session")
        if not auth_cookie:
            print("[Error] 未能获取到授权 Cookie")
            return None

        auth_json = _decode_jwt_segment(auth_cookie.split(".")[0])
        workspaces = auth_json.get("workspaces") or []
        if not workspaces:
            print("[Error] 授权 Cookie 里没有 workspace 信息")
            return None
        workspace_id = str((workspaces[0] or {}).get("id") or "").strip()
        if not workspace_id:
            print("[Error] 无法解析 workspace_id")
            return None

        select_body = f'{{"workspace_id":"{workspace_id}"}}'
        select_resp = s.post(
            "https://auth.openai.com/api/accounts/workspace/select",
            headers={
                "referer": "https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
                "content-type": "application/json",
            },
            data=select_body,
        )

        if select_resp.status_code != 200:
            print(f"[Error] 选择 workspace 失败，状态码: {select_resp.status_code}")
            print(select_resp.text)
            return None

        continue_url = str((select_resp.json() or {}).get("continue_url") or "").strip()
        if not continue_url:
            print("[Error] workspace/select 响应里缺少 continue_url")
            return None

        current_url = continue_url
        for _ in range(6):
            final_resp = s.get(current_url, allow_redirects=False, timeout=15)
            location = final_resp.headers.get("Location") or ""

            if final_resp.status_code not in [301, 302, 303, 307, 308]:
                break
            if not location:
                break

            next_url = urllib.parse.urljoin(current_url, location)
            if "code=" in next_url and "state=" in next_url:
                return submit_callback_url(
                    callback_url=next_url,
                    code_verifier=oauth.code_verifier,
                    redirect_uri=oauth.redirect_uri,
                    expected_state=oauth.state,
                )
            current_url = next_url

        print("[Error] 未能在重定向链中捕获到最终 Callback URL")
        return None

    except Exception as e:
        print(f"[Error] 运行时发生错误: {e}")
        return None


def main() -> None:
    default_config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    parser = argparse.ArgumentParser(description="OpenAI 自动注册脚本")
    parser.add_argument("--config", default=default_config_path, help="配置文件路径，默认读取同目录 config.json")
    parser.add_argument(
        "--proxy", default=None, help="代理地址，如 http://127.0.0.1:7890"
    )
    parser.add_argument("--once", action="store_true", help="只运行一次")
    parser.add_argument("--sleep-min", type=int, default=5, help="循环模式最短等待秒数")
    parser.add_argument(
        "--sleep-max", type=int, default=30, help="循环模式最长等待秒数"
    )
    args = parser.parse_args()

    file_cfg: Dict[str, Any] = {}
    if args.config and os.path.exists(args.config):
        try:
            with open(args.config, "r", encoding="utf-8") as f:
                file_cfg = json.load(f)
        except Exception as e:
            print(f"[Warn] 读取配置文件失败，继续使用命令行参数: {e}")

    reg_cfg = file_cfg.get("register", {}) if isinstance(file_cfg.get("register"), dict) else {}
    proxy = args.proxy if args.proxy else file_cfg.get("proxy")
    email_prefix = _clean_text(reg_cfg.get("email_prefix"), "oc") or "oc"

    sleep_min = max(1, args.sleep_min)
    sleep_max = max(sleep_min, args.sleep_max)

    count = 0
    print("[Info] OpenAI Auto-Register Started")

    while True:
        count += 1
        print(
            f"\n[{datetime.now().strftime('%H:%M:%S')}] >>> 开始第 {count} 次注册流程 <<<"
        )

        try:
            token_json = run(proxy, email_prefix, file_cfg)

            if token_json:
                try:
                    t_data = json.loads(token_json)
                    fname_email = t_data.get("email", "unknown").replace("@", "_")
                except Exception:
                    fname_email = "unknown"

                os.makedirs("tokens", exist_ok=True)
                file_name = os.path.join("tokens", f"token_{fname_email}_{int(time.time())}.json")

                with open(file_name, "w", encoding="utf-8") as f:
                    f.write(token_json)

                print(f"[*] 成功! Token 已保存至: {file_name}")
            else:
                print("[-] 本次注册失败。")

        except Exception as e:
            print(f"[Error] 发生未捕获异常: {e}")

        if args.once:
            break

        wait_time = random.randint(sleep_min, sleep_max)
        print(f"[*] 休息 {wait_time} 秒...")
        time.sleep(wait_time)


if __name__ == "__main__":
    main()
