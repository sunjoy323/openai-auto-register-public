# ==============================================================================
# Grok (xAI) 自动注册脚本 - 最终完善版 (复用原有 Email 逻辑)
# ==============================================================================

import json
import os
import re
import time
import secrets
import random
import struct
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import urljoin

from curl_cffi import requests
# 复用原有 OpenAI 注册脚本中的逻辑
from register import get_email_and_token, MAILTM_BASE, _mailtm_headers

# ==========================================
# 工具函数
# ==========================================

def grpc_web_encode(data: bytes) -> bytes:
    return struct.pack(">BI", 0, len(data)) + data

def pb_string(field_number: int, s: str) -> bytes:
    tag = (field_number << 3) | 2
    encoded_str = s.encode("utf-8")
    return bytes([tag, len(encoded_str)]) + encoded_str

def generate_random_name() -> str:
    return "".join(random.choices("abcdefghijklmnopqrstuvwxyz", k=random.randint(4, 7))).capitalize()

# ==========================================
# 注册类实现
# ==========================================

class GrokRegister:
    def __init__(self, proxy: Optional[str], email_prefix: str, config_full: dict):
        self.site_url = "https://accounts.x.ai"
        self.proxies = {"http": proxy, "https": proxy} if proxy else None
        self.prefix = email_prefix
        self.config_full = config_full
        self.session = requests.Session(proxies=self.proxies, impersonate="chrome120")
        self.params = {"action_id": None, "state_tree": None, "site_key": "0x4AAAAAAAhr9JGVDZbrZOo0"}

    def wait_for_grok_code(self, token: str, email: str, timeout: int = 60) -> Optional[str]:
        """复用 Mail.tm 逻辑获取 Grok 验证码"""
        print(f"[*] 正在等待 {email} 的验证码...", end="", flush=True)
        start = time.time()
        regex = r"([A-Z0-9]{3}-[A-Z0-9]{3})"
        
        while time.time() - start < timeout:
            print(".", end="", flush=True)
            try:
                # 使用 register.py 中定义的 headers
                m_resp = self.session.get(f"{MAILTM_BASE}/messages", headers=_mailtm_headers(token=token), timeout=10)
                messages = m_resp.json().get("hydra:member", [])
                if messages:
                    msg_id = messages[0]["id"]
                    detail = self.session.get(f"{MAILTM_BASE}/messages/{msg_id}", headers=_mailtm_headers(token=token), timeout=10).json()
                    content = str(detail.get("text", "")) + str(detail.get("html", ""))
                    match = re.search(regex, content)
                    if match:
                        code = match.group(1)
                        print(f" 抓到啦: {code}")
                        return code
            except: pass
            time.sleep(3)
        print(" 超时")
        return None

    def get_local_solver_token(self) -> Optional[str]:
        """对接根目录 api_solver.py"""
        solver_url = "http://127.0.0.1:5072"
        try:
            task_resp = requests.get(f"{solver_url}/turnstile?url={self.site_url}&sitekey={self.params['site_key']}", timeout=5)
            task_id = task_resp.json().get("taskId")
            for _ in range(30):
                res = requests.get(f"{solver_url}/result?id={task_id}", timeout=5).json()
                if res.get("status") == "ready":
                    return res.get("solution", {}).get("token")
                time.sleep(2)
        except:
            print("[-] 无法连接本地 Solver (127.0.0.1:5072)，请确保 api_solver.py 已启动")
        return None

    def run(self) -> Optional[str]:
        try:
            # 1. 初始化扫描
            print("[*] 正在扫描初始化参数...")
            resp = self.session.get(f"{self.site_url}/sign-up", timeout=15)
            if resp.status_code != 200:
                print(f"[-] 初始化访问失败，状态码: {resp.status_code} (可能被拦截)")
                return None
            
            init_html = resp.text
            tree_match = re.search(r'next-router-state-tree":"([^"]+)"', init_html)
            if not tree_match:
                print("[-] 无法在页面中找到 state_tree，请检查代理质量")
                return None
            self.params["state_tree"] = tree_match.group(1)

            js_files = re.findall(r'src="(/_next/static/[^"]+)"', init_html)
            for js_path in js_files:
                js_content = self.session.get(urljoin(self.site_url, js_path)).text
                action_match = re.search(r'7f[a-fA-F0-9]{40}', js_content)
                if action_match:
                    self.params["action_id"] = action_match.group(0)
                    break
            
            if not self.params["action_id"]:
                print("[-] 无法在 JS 文件中找到 Action ID")
                return None

            # 2. 获取邮箱 (调用 register.py 的函数)
            mail_token, email = get_email_and_token(self.proxies, self.prefix)
            if not email: return None

            # 3. gRPC 发送验证码
            grpc_headers = {"content-type": "application/grpc-web+proto", "x-grpc-web": "1", "x-user-agent": "connect-es/2.1.1"}
            self.session.post(f"{self.site_url}/auth_mgmt.AuthManagement/CreateEmailValidationCode", 
                              data=grpc_web_encode(pb_string(1, email)), headers=grpc_headers)

            # 4. 获取并验证
            raw_code = self.wait_for_grok_code(mail_token, email)
            if not raw_code: return None
            verify_code = raw_code.replace("-", "")
            self.session.post(f"{self.site_url}/auth_mgmt.AuthManagement/VerifyEmailValidationCode", 
                              data=grpc_web_encode(pb_string(1, email) + pb_string(2, verify_code)), headers=grpc_headers)

            # 5. 打码与提交
            ts_token = self.get_local_solver_token()
            if not ts_token: return None

            password = secrets.token_urlsafe(8)[:12] + "A1b2!"
            final_headers = {
                "accept": "text/x-component", "content-type": "text/plain;charset=UTF-8",
                "next-action": self.params["action_id"], "next-router-state-tree": self.params["state_tree"],
                "referer": f"{self.site_url}/sign-up"
            }
            payload = [{
                "emailValidationCode": verify_code,
                "createUserAndSessionRequest": {
                    "email": email, "givenName": generate_random_name(), "familyName": generate_random_name(),
                    "clearTextPassword": password, "tosAcceptedVersion": "$undefined"
                },
                "turnstileToken": ts_token, "promptOnDuplicateEmail": True
            }]
            
            resp = self.session.post(f"{self.site_url}/sign-up", data=json.dumps(payload), headers=final_headers)
            
            # 6. 提取 SSO
            if resp.status_code == 200:
                match = re.search(r'(https://[^" \s]+set-cookie\?q=[^:" \s]+)1:', resp.text)
                if match:
                    self.session.get(match.group(1), allow_redirects=True)
                    sso = self.session.cookies.get("sso")
                    if sso:
                        return json.dumps({"email": email, "password": password, "sso": sso})
            return None
        except Exception as e:
            print(f"[-] 注册异常: {e}")
            return None

def run(proxy: Optional[str], email_prefix: str = "gk", config_full: dict = None) -> Optional[str]:
    reg = GrokRegister(proxy, email_prefix, config_full)
    return reg.run()
