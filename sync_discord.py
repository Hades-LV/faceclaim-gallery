import os
import json
import requests

TOKEN = os.environ["DISCORD_TOKEN"]
CHANNEL_ID = os.environ["FORUM_CHANNEL_ID"]
HEADERS = {"Authorization": f"Bot {TOKEN}"}
API_BASE = "https://discord.com/api/v10"

DATA_FILE = "data.json"
IMG_DIR = "images"
os.makedirs(IMG_DIR, exist_ok=True)

# Load existing data to prevent duplicates and keep existing tags
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        db = json.load(f)
else:
    db = {"categories": {}, "entries": []}

existing_ids = {entry["id"] for entry in db["entries"]}

# Get guild_id from channel info
chan_resp = requests.get(f"{API_BASE}/channels/{CHANNEL_ID}", headers=HEADERS).json()
guild_id = chan_resp.get("guild_id")

# Fetch active threads in the guild and filter by forum channel
active_resp = requests.get(f"{API_BASE}/guilds/{guild_id}/threads/active", headers=HEADERS).json()
threads = [t for t in active_resp.get("threads", []) if t.get("parent_id") == CHANNEL_ID]

# Fetch public archived threads in the forum
archived_resp = requests.get(f"{API_BASE}/channels/{CHANNEL_ID}/threads/archived/public", headers=HEADERS).json()
threads.extend(archived_resp.get("threads", []))

# Deduplicate thread list by ID
unique_threads = {t["id"]: t for t in threads}.values()

new_count = 0
for thread in unique_threads:
    tid = thread["id"]
    if tid in existing_ids:
        continue

    # In Discord forums, the starter message ID equals the thread ID
    msg_resp = requests.get(f"{API_BASE}/channels/{tid}/messages/{tid}", headers=HEADERS)
    if msg_resp.status_code != 200:
        continue
    msg = msg_resp.json()

    # Find the first image attachment or embed
    img_url = None
    if msg.get("attachments"):
        img_url = msg["attachments"][0]["url"]
    elif msg.get("embeds"):
        for embed in msg["embeds"]:
            if "image" in embed:
                img_url = embed["image"]["url"]
                break
            elif "thumbnail" in embed:
                img_url = embed["thumbnail"]["url"]
                break

    local_img_path = ""
    if img_url:
        ext = img_url.split("?")[0].split(".")[-1]
        if ext.lower() not in ["png", "jpg", "jpeg", "webp", "gif"]:
            ext = "jpg"
        local_img_path = f"{IMG_DIR}/{tid}.{ext}"
        img_data = requests.get(img_url).content
        with open(local_img_path, "wb") as img_file:
            img_file.write(img_data)

    db["entries"].append({
        "id": tid,
        "name": thread["name"],
        "image": local_img_path,
        "url": f"https://discord.com/channels/{guild_id}/{tid}",
        "tags": {}
    })
    new_count += 1
    print(f"Imported: {thread['name']}")

with open(DATA_FILE, "w", encoding="utf-8") as f:
    json.dump(db, f, indent=2, ensure_ascii=False)

print(f"Sync complete. Added {new_count} new entries.")
