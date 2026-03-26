#!/usr/bin/env python3
import json
import os
import time
import argparse
from datetime import datetime

from register import login_with_email_otp


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
TOKENS_DIR = os.path.join(SCRIPT_DIR, "tokens")
LOG_PATH = os.path.join(SCRIPT_DIR, "personal_login_history.log")


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def to_bool(value, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"true", "1", "yes", "on"}:
        return True
    if text in {"false", "0", "no", "off"}:
        return False
    return default


def save_token(token_json: str, token_dir: str) -> tuple[str, str, str]:
    token_data = json.loads(token_json)
    email = str(token_data.get("email") or "unknown").strip() or "unknown"
    account_id = str(token_data.get("account_id") or "").strip()
    os.makedirs(token_dir, exist_ok=True)
    file_name = f"personal_token_{email.replace('@', '_')}_{int(time.time())}.json"
    file_path = os.path.join(token_dir, file_name)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(token_json)
    return email, account_id, file_path


def log_result(email: str, success: bool, account_id: str = "", detail: str = "") -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status = "OK" if success else "FAIL"
    line = f"[{ts}] {status} {email} {account_id} {detail}".rstrip() + "\n"
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line)


def main() -> None:
    parser = argparse.ArgumentParser(description="邮箱列表 OTP 登录并换取个人空间 Token")
    parser.add_argument("--config", default=CONFIG_PATH, help="配置文件路径，默认读取同目录 config.json")
    args = parser.parse_args()

    cfg = load_config(args.config)
    login_cfg = cfg.get("personal_login", {}) if isinstance(cfg.get("personal_login"), dict) else {}
    emails = login_cfg.get("emails", [])
    workspace_id = str(login_cfg.get("workspace_id") or "").strip()
    workspace_name = str(login_cfg.get("workspace_name") or "").strip()
    prefer_personal = to_bool(login_cfg.get("prefer_personal"), True)
    proxy = cfg.get("proxy")
    token_dir = str(login_cfg.get("token_dir") or TOKENS_DIR).strip() or TOKENS_DIR
    sleep_seconds = max(0, int(login_cfg.get("sleep_seconds", 3) or 0))

    if not isinstance(emails, list) or not emails:
        raise SystemExit("[Error] 请在 config.json 的 personal_login.emails 中配置邮箱列表")

    emails = [str(item).strip() for item in emails if str(item).strip()]
    if not emails:
        raise SystemExit("[Error] personal_login.emails 里没有有效邮箱")

    print("[Info] 邮箱列表 OTP 登录换个人空间 Token")
    print(f"[Info] 邮箱数量: {len(emails)}")
    print(f"[Info] 代理: {proxy or '无'}")
    print(f"[Info] 个人空间优先: {prefer_personal}")
    print(f"[Info] 目标工作空间 ID: {workspace_id or '未指定'}")
    print(f"[Info] 目标工作空间名称: {workspace_name or '未指定'}")
    print()

    success = 0
    total = 0

    for login_email in emails:
        total += 1
        print(f"\n{'=' * 60}")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 第 {total} 个邮箱: {login_email}")
        print(f"{'=' * 60}")

        token_json = login_with_email_otp(
            email=login_email,
            proxy=proxy,
            config=cfg,
            workspace_id=workspace_id,
            workspace_name=workspace_name,
            prefer_team=False,
            prefer_personal=prefer_personal,
        )

        if not token_json:
            print(f"[-] 登录失败: {login_email}")
            log_result(login_email, False)
        else:
            token_email, account_id, file_path = save_token(token_json, token_dir)
            print(f"[*] Token 已保存: {file_path}")
            log_result(token_email, True, account_id, file_path)
            success += 1

        if sleep_seconds > 0 and total < len(emails):
            print(f"[*] 等待 {sleep_seconds} 秒后继续下一个邮箱...")
            time.sleep(sleep_seconds)

    print()
    print(f"[Done] 总计 {total} 个邮箱，成功 {success} 个")


if __name__ == "__main__":
    main()
