# Fetch ALL public archived threads in the forum (paginating past the default 50)
before_ts = None
while True:
    params = {"limit": 100}
    if before_ts:
        params["before"] = before_ts

    arch_req = requests.get(
        f"{API_BASE}/channels/{CHANNEL_ID}/threads/archived/public",
        headers=HEADERS,
        params=params,
    )
    if arch_req.status_code != 200:
        break

    archived_resp = arch_req.json()
    arch_threads = archived_resp.get("threads", [])
    threads.extend(arch_threads)

    if not archived_resp.get("has_more") or not arch_threads:
        break

    # Advance cursor using the oldest thread's archive_timestamp
    oldest = min(
        arch_threads,
        key=lambda t: t.get("thread_metadata", {}).get("archive_timestamp", ""),
    )
    before_ts = oldest.get("thread_metadata", {}).get("archive_timestamp")
    if not before_ts:
        break
