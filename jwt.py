#!/usr/bin/env python3
"""
accounts.json se accounts leke API se token fetch karta hai.
Region ke hisaab se different files me save karta hai:
  - IND                -> token_ind.json
  - BR / SAC / NA / US -> token_br.json
  - BD / others        -> token_bd.json

Retry logic:
  Pass 1 : sabhi accounts
  Pass 2 : jo fail hue (2 sec baad)
  Pass 3 : jo abhi bhi fail hain (2 sec baad)
  ... max MAX_RETRIES rounds tak

Last me failed UIDs comma-separated print.
"""

import json
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

# ---------------- CONFIG ----------------
API_URL         = "https://ff-jwt-gen.stargmr.xyz/api/public/token"
ACCOUNTS_FILE   = "accounts_visit.json"

MAX_WORKERS     = 10      # thread limit
MAX_RETRIES     = 3       # total rounds (1 initial + 2 retries)
RETRY_DELAY     = 2       # seconds between rounds
REQUEST_TIMEOUT = 30      # seconds

# ---------------- REGION MAP ----------------
def get_token_file(region: str) -> str:
    r = (region or "").strip().upper()
    if r == "IND":
        return "token_ind_visit.json"
    if r in ("BR", "SAC", "NA", "US"):
        return "token_br_visit.json"
    return "token_bd_visit.json"

# ---------------- FILE IO (thread-safe) ----------------
write_lock = threading.Lock()

def load_existing(filename: str):
    try:
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def save_token_to_file(result: dict, filename: str):
    uid = str(result["uid"])
    with write_lock:
        data = load_existing(filename)
        data = [d for d in data if str(d.get("uid")) != uid]
        data.append(result)
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

# ---------------- SINGLE-SHOT FETCH (no internal retry) ----------------
def fetch_token_once(account: dict):
    uid = str(account.get("uid", "")).strip()
    password = account.get("password", "").strip()
    if not uid or not password:
        return uid, None, "missing uid/password"

    params = {"uid": uid, "password": password}
    try:
        r = requests.get(API_URL, params=params, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.RequestException as e:
        return uid, None, f"request error: {e}"

    if r.status_code == 200:
        try:
            j = r.json()
        except Exception:
            return uid, None, "invalid JSON response"
        if j.get("token"):
            return uid, j, None
        return uid, None, f"no token: {str(j)[:150]}"

    return uid, None, f"HTTP {r.status_code}: {r.text[:150]}"

# ---------------- PROCESS ONE BATCH (ek round) ----------------
def run_round(accounts, round_num, total):
    """Ek round me accounts process karta hai. Failed list return karta hai."""
    ok = 0
    failed = []
    done = 0
    n = len(accounts)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(fetch_token_once, acc): acc for acc in accounts}

        for fut in as_completed(futures):
            uid, data, err = fut.result()
            done += 1

            if data:
                result = {
                    "uid":          uid,
                    "token":        data.get("token"),
                    "token_access": data.get("token_access", ""),
                    "region":       data.get("region", ""),
                    "account_id":   data.get("account_id", ""),
                }
                target = get_token_file(result["region"])
                save_token_to_file(result, target)
                ok += 1
                print(f"  [R{round_num}] [{done:>3}/{n}] ✅ uid={uid} region={result['region']:<4} -> {target}")
            else:
                # original account dict wapas so we can retry
                acc = futures[fut]
                failed.append((acc, err))
                print(f"  [R{round_num}] [{done:>3}/{n}] ❌ uid={uid} err={err}")

    return ok, failed

# ---------------- MAIN ----------------
def main():
    with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
        accounts = json.load(f)

    # dedupe by uid
    seen, unique = set(), []
    for a in accounts:
        uid = str(a.get("uid", "")).strip()
        if uid and uid not in seen:
            seen.add(uid)
            unique.append(a)
    accounts = unique

    total = len(accounts)
    print(f"[*] Loaded {total} unique accounts")
    print(f"[*] Threads = {MAX_WORKERS} | Rounds = {MAX_RETRIES} | Delay = {RETRY_DELAY}s\n")

    current = accounts
    total_ok = 0
    last_errors = {}

    for round_num in range(1, MAX_RETRIES + 1):
        print(f"\n========== ROUND {round_num}/{MAX_RETRIES}  ({len(current)} accounts) ==========")
        ok, failed = run_round(current, round_num, total)
        total_ok += ok
        print(f"[*] Round {round_num} done — success={ok} failed={len(failed)}")

        if not failed:
            print(f"[✓] All accounts done in round {round_num} 🎉")
            current = []
            break

        # next round ke liye sirf failed accounts
        last_errors = {str(acc.get("uid")): err for acc, err in failed}
        current = [acc for acc, _ in failed]

        if round_num < MAX_RETRIES:
            print(f"[*] Waiting {RETRY_DELAY}s before retrying {len(current)} failed account(s)...")
            time.sleep(RETRY_DELAY)

    # Final summary
    print(f"\n[✓] DONE — success={total_ok} failed={len(current)} total={total}")

    if current:
        failed_uids = [str(acc.get("uid")) for acc in current]
        print(f"\n[!] FAILED UIDs ({len(failed_uids)}):")
        print(",".join(failed_uids))

        # optional: error bhi dikha do
        print("\n[!] Last errors:")
        for u in failed_uids:
            print(f"   {u} -> {last_errors.get(u, '?')}")
    else:
        print("\n[!] No failed UIDs 🎉")

if __name__ == "__main__":
    main()
