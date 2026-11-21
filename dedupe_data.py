import hashlib
import json
import os

DATA_FILE = "data.json"
IMG_DIR = "images"


def file_md5(path):
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


with open(DATA_FILE, "r", encoding="utf-8") as f:
    db = json.load(f)

removed_refs = 0
deleted_files = 0
kept_files = set()

for entry in db.get("entries", []):
    cover = entry.get("image") or ""
    raw_images = entry.get("images") if isinstance(entry.get("images"), list) else []

    ordered = []
    if cover:
        ordered.append(cover)
    for p in raw_images:
        if p and p not in ordered:
            ordered.append(p)

    deduped = []
    seen_hashes = set()
    seen_paths = set()

    for path in ordered:
        norm_path = path.lstrip("./")
        if norm_path in seen_paths:
            removed_refs += 1
            continue

        if os.path.exists(path):
            h = file_md5(path)
            if h in seen_hashes:
                removed_refs += 1
                # Remove duplicate file on disk if nothing else references it
                try:
                    os.remove(path)
                    deleted_files += 1
                except OSError:
                    pass
                continue
            seen_hashes.add(h)
            kept_files.add(os.path.abspath(path))

        seen_paths.add(norm_path)
        deduped.append(path)

    entry["images"] = deduped
    if not entry.get("image") and deduped:
        entry["image"] = deduped[0]

with open(DATA_FILE, "w", encoding="utf-8") as f:
    json.dump(db, f, indent=2, ensure_ascii=False)

print(f"Removed {removed_refs} duplicate image entries and deleted {deleted_files} duplicate files.")
