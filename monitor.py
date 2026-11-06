import os
import json
import time
import requests
import urllib3
from pathlib import Path
from datetime import datetime, timedelta, timezone

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

API_URL = "https://brand.naver.com/n/v2/channels/2sWDw1c6bldrOqZFkyltv/products/13675091284?withWindow=false"
PAGE_URL = "https://brand.naver.com/keychron/products/13675091284"
STATE_FILE = Path("state.json")
DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK"]
DISCORD_USER_ID = os.environ.get("DISCORD_USER_ID", "").strip()
TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true"

TARGET_OPTION_KEYWORD = "적축"
HEARTBEAT_INTERVAL_HOURS = 3

print(f"[MODE] {'TEST' if TEST_MODE else 'PROD'}")

KST = timezone(timedelta(hours=9))
today = datetime.now(KST)

headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": PAGE_URL,
    "Origin": "https://brand.naver.com",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}

session = requests.Session()
session.headers.update(headers)

# 1. 상품 페이지 먼저 호출해서 쿠키 획득
try:
    session.get(PAGE_URL, timeout=15, verify=False)
    print(f"[DEBUG] Cookies: {len(session.cookies)} cookies acquired")
    time.sleep(2)  # 사람처럼 잠깐 대기
except Exception as e:
    print(f"[WARN] Page fetch failed: {e}")

# 2. 실제 API 호출
resp = session.get(API_URL, timeout=15, verify=False)
print(f"[DEBUG] HTTP {resp.status_code}")

if resp.status_code == 429:
    print("[WARN] Rate limited by Naver. Skipping this cycle.")
    exit(0)  # 실패로 안 찍히게 정상 종료

resp.raise_for_status()
data = resp.json()

option_list = []
for group in data.get("combinationOptions", []):
    for opt in group.get("options", []):
        option_list.append(opt)

print(f"[DEBUG] Total options: {len(option_list)}")

target_options = [
    o for o in option_list
    if TARGET_OPTION_KEYWORD in (o.get("optionName1") or "")
]

def send_discord(content, mention=False):
    payload = {"content": content}
    if mention and DISCORD_USER_ID:
        payload["allowed_mentions"] = {"users": [DISCORD_USER_ID]}
    else:
        payload["allowed_mentions"] = {"parse": []}
    requests.post(DISCORD_WEBHOOK, json=payload, timeout=15)


in_stock = []
for opt in target_options:
    name = opt.get("optionName1", "?")
    qty = opt.get("stockQuantity", 0) or 0
    print(f"[DEBUG] {name}: stock={qty}")
    if qty > 0:
        in_stock.append((name, qty))

if TEST_MODE:
    in_stock = [("적축｜영문각인 [TEST]", 99)]
    print("[TEST] Forced in-stock")

prev_state = {}
if STATE_FILE.exists():
    try:
        prev_state = json.loads(STATE_FILE.read_text())
    except Exception:
        pass
prev_in_stock = prev_state.get("in_stock", False)

now_in_stock = len(in_stock) > 0

if now_in_stock and not prev_in_stock:
    product_name = data.get("name", "키크론 상품")
    lines = []
    if DISCORD_USER_ID:
        lines.append(f"<@{DISCORD_USER_ID}>")
    prefix = "[TEST] " if TEST_MODE else ""
    lines.append(f"🚨 **{prefix}재입고 알림!**\n")
    lines.append(f"**{product_name}**\n")
    for name, qty in in_stock:
        lines.append(f"✅ **{name}** (재고 {qty}개)")
    lines.append(f"\n{PAGE_URL}")
    send_discord("\n".join(lines), mention=True)
    print(f"Alerted restock: {len(in_stock)} options")
elif now_in_stock and prev_in_stock:
    print("Still in stock, no new alert")
elif not now_in_stock and prev_in_stock:
    send_discord(f"💤 다시 품절됨 ({today.strftime('%m/%d %H:%M')} KST)", mention=False)
    print("Stock gone again")
else:
    if not TEST_MODE:
        last_hb = prev_state.get("last_heartbeat", 0)
        hours_since = (today.timestamp() - last_hb) / 3600
        if hours_since >= HEARTBEAT_INTERVAL_HOURS:
            send_discord(
                f"💤 아직 품절 ({today.strftime('%m/%d %H:%M')} KST, 모니터링 중)",
                mention=False
            )
            prev_state["last_heartbeat"] = today.timestamp()
            print(f"Heartbeat sent (last was {hours_since:.1f}h ago)")
        else:
            print(f"Skip heartbeat (last was {hours_since:.1f}h ago)")

if not TEST_MODE:
    prev_state["in_stock"] = now_in_stock
    STATE_FILE.write_text(json.dumps(prev_state, ensure_ascii=False))
