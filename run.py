#!/usr/bin/env python3
"""
OpenAI 自动注册脚本
用法:
  python3 run.py                          # 循环注册
  python3 run.py --once                   # 只跑一次
  python3 run.py --count 5                # 跑5个
  python3 run.py --parallel 3             # 3线程无限循环
  python3 run.py --count 10 --parallel 3  # 3线程跑10个
"""
import json
import os
import sys
import time
import random
import argparse
import threading
from datetime import datetime

# 同目录下的注册脚本
from register import run as register_run

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
TOKENS_DIR = os.path.join(SCRIPT_DIR, "tokens")
LOG_PATH = os.path.join(SCRIPT_DIR, "history.log")

# 线程安全锁
_print_lock = threading.Lock()
_log_lock = threading.Lock()
_counter_lock = threading.Lock()


def _tprint(msg: str):
    """线程安全的 print"""
    with _print_lock:
        print(msg, flush=True)


def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def log_result(email: str, success: bool, account_id: str = ""):
    """记录到历史日志（线程安全）"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status = "OK" if success else "FAIL"
    line = f"[{ts}] {status} {email} {account_id}\n"
    with _log_lock:
        with open(LOG_PATH, "a") as f:
            f.write(line)


def run_once(cfg: dict, tag: str = "") -> bool:
    """注册一个账号并保存 Token"""
    proxy = cfg.get("proxy")
    reg_cfg = cfg.get("register", {})
    prefix = reg_cfg.get("email_prefix", "oc")
    
    token_json = register_run(proxy, prefix, cfg)

    if not token_json:
        log_result("unknown", False)
        return False

    token_data = json.loads(token_json)
    email = token_data.get("email", "unknown")

    # 保存 token 文件
    os.makedirs(TOKENS_DIR, exist_ok=True)
    fname = f"token_{email.replace('@', '_')}_{int(time.time())}.json"
    fpath = os.path.join(TOKENS_DIR, fname)
    with open(fpath, "w") as f:
        f.write(token_json)
    _tprint(f"{tag}[*] Token 已保存: {fpath}")

    log_result(email, True, token_data.get("account_id", ""))
    return True


def main():
    parser = argparse.ArgumentParser(description="OpenAI 自动注册工具")
    parser.add_argument("--once", action="store_true", help="只跑一次")
    parser.add_argument("--count", type=int, default=0, help="跑指定次数（0=无限循环）")
    parser.add_argument("--parallel", type=int, default=1, help="并行线程数（默认1）")
    args = parser.parse_args()

    cfg = load_config()
    reg_cfg = cfg.get("register", {})
    mail_provider = str(cfg.get("mail_provider", "mailtm") or "mailtm").strip().lower()
    sleep_min = reg_cfg.get("sleep_min", 5)
    sleep_max = reg_cfg.get("sleep_max", 30)

    target = 1 if args.once else args.count
    parallel = max(1, args.parallel)

    print(f"[Info] OpenAI 自动注册工具")
    print(f"[Info] 代理: {cfg.get('proxy', '无')}")
    print(f"[Info] 收码方式: {'IMAP' if mail_provider == 'imap' else 'Mail.tm'}")
    print(f"[Info] 目标: {'无限循环' if target == 0 else f'{target} 个'}")
    print(f"[Info] 并行: {parallel} 线程")
    print()

    if parallel == 1:
        # 单线程模式
        total = 0
        success = 0
        while True:
            total += 1
            print(f"\n{'='*50}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 第 {total} 次 (成功 {success})")
            print(f"{'='*50}")

            if run_once(cfg):
                success += 1

            if target > 0 and total >= target:
                break

            wait = random.randint(sleep_min, sleep_max)
            print(f"\n[*] 休息 {wait} 秒...")
            time.sleep(wait)

        print(f"\n[Done] 总计 {total} 次，成功 {success} 次")
    else:
        # 多线程并行模式
        counters = {"total": 0, "success": 0, "done": False}

        def worker(worker_id: int):
            tag = f"[W{worker_id}] "
            while True:
                with _counter_lock:
                    if counters["done"]:
                        return
                    counters["total"] += 1
                    seq = counters["total"]
                    if target > 0 and seq > target:
                        counters["total"] -= 1
                        counters["done"] = True
                        return

                _tprint(f"\n{tag}{'='*46}")
                _tprint(f"{tag}[{datetime.now().strftime('%H:%M:%S')}] 第 {seq} 次")
                _tprint(f"{tag}{'='*46}")

                if run_once(cfg, tag):
                    with _counter_lock:
                        counters["success"] += 1

                with _counter_lock:
                    if counters["done"]:
                        return
                    if target > 0 and counters["total"] >= target:
                        counters["done"] = True
                        return

                wait = random.randint(sleep_min, sleep_max)
                _tprint(f"{tag}休息 {wait} 秒...")
                time.sleep(wait)

        threads = []
        for i in range(1, parallel + 1):
            t = threading.Thread(target=worker, args=(i,), daemon=True)
            t.start()
            threads.append(t)
            time.sleep(1)  # 错开启动，避免同时请求

        try:
            for t in threads:
                t.join()
        except KeyboardInterrupt:
            _tprint("\n[!] 收到中断信号，等待当前任务完成...")
            with _counter_lock:
                counters["done"] = True
            for t in threads:
                t.join(timeout=30)

        _tprint(f"\n[Done] 总计 {counters['total']} 次，成功 {counters['success']} 次")


if __name__ == "__main__":
    main()
