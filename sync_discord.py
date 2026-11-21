import hashlib
import json
import os
import re
import time
import requests

TOKEN = os.environ["DISCORD_TOKEN"]
CHANNEL_ID = os.environ["FORUM_CHANNEL_ID"]
HEADERS = {"Authorization": f"Bot {TOKEN}"}
API_BASE = "https://discord.com/api/v10"

DATA_FILE = "data.json"
IMG_DIR = "images"
os.makedirs(IMG_DIR, exist_ok=True)

IMAGE_EXTS = {"png", "jpg", "jpeg", "webp", "gif"}


def api_get(path, params=None):
    while True:
        resp = requests.get(f"{API_BASE}{path}", headers=HEADERS, params=params, timeout=30)
        if resp.status_code == 429:
            retry_after = float(resp.json().get("retry_after", 1.5))
            time.sleep(retry_after + 0.1)
            continue
        return resp


def guess_ext(url):
    raw_ext = url.split("?")[0].split(".")[-1].lower()
    return raw_ext if raw_ext in IMAGE_EXTS else "jpg"


def extract_message_image_urls(msg):
    urls = []
    for att in msg.get("attachments", []):
        content_type = (att.get("content_type") or "").lower()
        url = att.get("url")
        if url and (content_type.startswith("image/") or guess_ext(url) in IMAGE_EXTS):
            if url not in urls:
                urls.append(url)

    for embed in msg.get("embeds", []):
        for key in ("image", "thumbnail"):
            media = embed.get(key) or {}
            url = media.get("url") or media.get("proxy_url")
            if url and url not in urls:
                urls.append(url)

    return urls


def fetch_thread_messages(tid):
    messages = []
    before_id = None

    while True:
        params = {"limit": 100}
        if before_id:
            params["before"] = before_id

        resp = api_get(f"/channels/{tid}/messages", params=params)
        if resp.status_code != 200:
            break

        batch = resp.json()
        if not batch:
            break

        messages.extend(batch)
        if len(batch) < 100:
            break

        before_id = batch[-1]["id"]

    messages.reverse()  # oldest -> newest
    return messages


def sync_entry_from_thread(entry, tid, guild_id):
    changed = False

    if not entry.get("url") and guild_id:
        entry["url"] = f"https://discord.com/channels/{guild_id}/{tid}"
        changed = True

    if not isinstance(entry.get("tags"), dict):
        entry["tags"] = {}
        changed = True

    images = entry.get("images")
    if not isinstance(images, list):
        images = []
        changed = True

    if entry.get("image") and entry["image"] not in images:
        images.insert(0, entry["image"])
        changed = True

    seen_hashes = set()
    for existing_path in images:
        if existing_path and os.path.exists(existing_path):
            with open(existing_path, "rb") as f:
                seen_hashes.add(hashlib.md5(f.read()).hexdigest())

    existing_notes = (entry.get("notes") or "").strip()
    note_parts = [existing_notes] if existing_notes else []

    messages = fetch_thread_messages(tid)
    photo_counter = len(images) + 1

    for msg in messages:
        for img_url in extract_message_image_urls(msg):
            img_resp = requests.get(img_url, timeout=30)
            if img_resp.status_code != 200:
                continue

            img_bytes = img_resp.content
            img_hash = hashlib.md5(img_bytes).hexdigest()
            if img_hash in seen_hashes:
                continue

            ext = guess_ext(img_url)
            if len(images) == 0 and entry.get("image"):
                local_path = entry["image"]
            else:
                local_path = f"{IMG_DIR}/{tid}_{photo_counter}.{ext}"

            while local_path in images and local_path != entry.get("image"):
                photo_counter += 1
                local_path = f"{IMG_DIR}/{tid}_{photo_counter}.{ext}"

            with open(local_path, "wb") as img_file:
                img_file.write(img_bytes)

            seen_hashes.add(img_hash)
            if local_path not in images:
                images.append(local_path)
                photo_counter += 1
                changed = True

        raw_text = (msg.get("content") or "").strip()
        if raw_text:
            norm_text = re.sub(r"\s+", " ", raw_text)
            already_there = any(
                raw_text == part or raw_text in part or (norm_text and norm_text in re.sub(r"\s+", " ", part))
                for part in note_parts
            )
            if not already_there:
                note_parts.append(raw_text)
                changed = True

    entry["images"] = images
    if images and not entry.get("image"):
        entry["image"] = images[0]
        changed = True

    combined_notes = "\n\n".join(note_parts).strip()
    if combined_notes and combined_notes != existing_notes:
        entry["notes"] = combined_notes
        changed = True

    return changed


if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        db = json.load(f)
else:
    db = {"categories": {}, "entries": []}

if not isinstance(db.get("categories"), dict):
    db["categories"] = {}
if not isinstance(db.get("entries"), list):
    db["entries"] = []

entries_by_id = {str(entry["id"]): entry for entry in db["entries"] if entry.get("id")}

chan_resp = api_get(f"/channels/{CHANNEL_ID}").json()
guild_id = chan_resp.get("guild_id")

active_resp = api_get(f"/guilds/{guild_id}/threads/active").json() if guild_id else {}
threads = [t for t in active_resp.get("threads", []) if str(t.get("parent_id")) == str(CHANNEL_ID)]

# Fetch ALL public archived threads in the forum (paginating past the default 50)
before_ts = None
while True:
    params = {"limit": 100}
    if before_ts:
        params["before"] = before_ts

    arch_req = api_get(f"/channels/{CHANNEL_ID}/threads/archived/public", params=params)
    if arch_req.status_code != 200:
        break

    archived_resp = arch_req.json()
    arch_threads = archived_resp.get("threads", [])
    threads.extend(arch_threads)

    if not archived_resp.get("has_more") or not arch_threads:
        break

    oldest = min(
        arch_threads,
        key=lambda t: t.get("thread_metadata", {}).get("archive_timestamp", ""),
    )
    before_ts = oldest.get("thread_metadata", {}).get("archive_timestamp")
    if not before_ts:
        break

unique_threads = {str(t["id"]): t for t in threads}

# Queue all discovered forum threads plus any existing entries in data.json
threads_to_process = dict(unique_threads)
for tid in entries_by_id:
    threads_to_process.setdefault(tid, None)

new_count = 0
updated_count = 0

for tid, thread in threads_to_process.items():
    is_new = tid not in entries_by_id
    if is_new:
        title = (thread or {}).get("name") or f"Thread {tid}"
        entry = {
            "id": tid,
            "name": title,
            "image": "",
            "images": [],
            "url": f"https://discord.com/channels/{guild_id}/{tid}" if guild_id else "",
            "tags": {},
        }
        db["entries"].append(entry)
        entries_by_id[tid] = entry
        new_count += 1
        print(f"Imported: {title}")
    else:
        entry = entries_by_id[tid]
        if thread and thread.get("name") and not entry.get("name"):
            entry["name"] = thread["name"]

    if sync_entry_from_thread(entry, tid, guild_id):
        if not is_new:
            updated_count += 1
            print(f"Updated thread content: {entry.get('name', tid)}")

with open(DATA_FILE, "w", encoding="utf-8") as f:
    json.dump(db, f, indent=2, ensure_ascii=False)

print(f"Sync complete. Added {new_count} new entries, updated {updated_count} existing entries.")
