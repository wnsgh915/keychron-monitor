import os
import json
import requests
import urllib3
from pathlib import Path
from datetime import datetime, timedelta, timezone

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

API_URL = "https://brand.naver.com/n/v2/channels/2sWDw1c6bldrOqZFkyltv/products/13675091284?withWindow=false"
PAGE_URL = "https://brand.naver.com/keychron/products/13675091284"
STATE_FILE = Path("state.json")
HEARTBEAT_FILE = Path("heartbeat.json")
DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK"]
DISCORD_USER_ID = os.environ.get("DISCORD_USER_ID", "").strip()
TEST_MODE = os.environ.get("TEST_MODE", "false").lower() == "true"

# 노리는 옵션명 (부분일치, optionName1 기준)
TARGET_OPTION_KEYWORD = "적축"
HEARTBEAT_INTERVAL_HOURS = 3  # 재고 없음 알림 주기 (3시간)

print(f"[MODE] {'TEST' if TEST_MODE else 'PROD'}")

KST = timezone(timedelta(hours=9))
today = datetime.now(KST)

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/148.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": PAGE_URL,
}

resp = requests.get(API_URL, headers=headers, timeout=15, verify=False)
print(f"[DEBUG] HTTP {resp.status_code}")
resp.raise_for_status()
data = resp.json()

# 옵션 목록 뽑기
option_list = []
for group in data.get("combinationOptions", []):
    for opt in group.get("options", []):
        option_list.append(opt)

print(f"[DEBUG] Total options: {len(option_list)}")

# 타깃 옵션 찾기 (부분일치)
target_options = [
    o for o in option_list
    if TARGET_OPTION_KEYWORD in (o.get("optionName1") or "")
]

if not target_options:
    print(f"[WARN] No matching option found for keyword '{TARGET_OPTION_KEYWORD}'")
    print(f"[DEBUG] Available options: {[o.get('optionName1') for o in option_list]}")

def send_discord(content, mention=False):
    payload = {"content": content}
    if mention and DISCORD_USER_ID:
        payload["allowed_mentions"] = {"users": [DISCORD_USER_ID]}
    else:
        payload["allowed_mentions"] = {"parse": []}
    requests.post(DISCORD_WEBHOOK, json=payload, timeout=15)


# 재고 체크
in_stock = []
for opt in target_options:
    name = opt.get("optionName1", "?")
    qty = opt.get("stockQuantity", 0) or 0
    print(f"[DEBUG] {name}: stock={qty}")
    if qty > 0:
        in_stock.append((name, qty))

# 테스트 모드: 강제 재고 있음으로 처리
if TEST_MODE:
    in_stock = [("적축｜영문각인 [TEST]", 99)]
    print("[TEST] Forced in-stock")

# 이전 상태 로드
prev_state = {}
if STATE_FILE.exists():
    try:
        prev_state = json.loads(STATE_FILE.read_text())
    except Exception:
        pass
prev_in_stock = prev_state.get("in_stock", False)

now_in_stock = len(in_stock) > 0

# 알림 분기
if now_in_stock and not prev_in_stock:
    # 품절 → 재입고: 즉시 멘션 알림
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
    # 여전히 재고 있음: 알림 X (이미 알렸음)
    print("Still in stock, no new alert")

elif not now_in_stock and prev_in_stock:
    # 재입고 → 다시 품절: 간단 알림
    send_discord(f"💤 다시 품절됨 ({today.strftime('%m/%d %H:%M')} KST)", mention=False)
    print("Stock gone again")

else:
    # 계속 품절: heartbeat
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

# 상태 저장
if not TEST_MODE:
    prev_state["in_stock"] = now_in_stock
    STATE_FILE.write_text(json.dumps(prev_state, ensure_ascii=False))
