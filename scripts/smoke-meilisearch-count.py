"""Exercise the built test image against disposable, real Meilisearch data."""

import json
import time
import urllib.error
import urllib.request


def request(base, path, method="GET", data=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = token
    payload = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request(base + path, payload, headers, method=method)
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.load(response)


def wait_for(label, action, predicate, timeout=120):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = action()
            if predicate(last):
                return last
        except (urllib.error.URLError, TimeoutError) as error:
            last = str(error)
        time.sleep(1)
    raise RuntimeError(f"{label} timed out: {last}")


openlist = "http://127.0.0.1:15244"
meili = "http://127.0.0.1:17700"
wait_for("Meilisearch startup", lambda: request(meili, "/health"),
         lambda result: result.get("status") == "available")
login = wait_for("OpenList startup", lambda: request(
    openlist, "/api/auth/login", "POST",
    {"username": "admin", "password": "openlist-count-ci-test-only"}),
    lambda result: result.get("code") == 200)
token = login["data"]["token"]


def api(path, method="GET", data=None):
    result = request(openlist, "/api/admin/" + path, method, data, token)
    if result.get("code") != 200:
        raise RuntimeError(f"OpenList {path}: {result}")
    return result.get("data")


setting = api("setting/get?key=search_index")
setting["value"] = "meilisearch"
api("setting/save", "POST", [setting])

# Deliberately retain a stale saved total. Reading progress must return the
# committed Meilisearch total without overwriting saved build history.
saved = json.dumps({"obj_count": 8, "is_done": True,
                    "last_done_time": "2026-01-01T00:00:00Z", "error": ""})
progress_setting = api("setting/get?key=index_progress")
progress_setting["value"] = saved
api("setting/save", "POST", [progress_setting])


def wait_task(task):
    result = wait_for("Meilisearch task", lambda: request(
        meili, f'/tasks/{task["taskUid"]}'),
        lambda value: value.get("status") in ("succeeded", "failed", "canceled"))
    if result["status"] != "succeeded":
        raise RuntimeError(f"Meilisearch task failed: {result}")


wait_task(request(meili, "/indexes/openlist_count_smoke/documents", "POST", [
    {"id": "smoke_1", "parent": "/smoke", "name": "one.mkv", "is_dir": False},
    {"id": "smoke_2", "parent": "/smoke", "name": "two.mkv", "is_dir": False},
]))
progress = wait_for("live count 2", lambda: api("index/progress"),
                    lambda value: value["is_done"] and value["obj_count"] == 2)
assert progress["last_done_time"] == "2026-01-01T00:00:00Z", progress
assert api("setting/get?key=index_progress")["value"] == saved

wait_task(request(meili, "/indexes/openlist_count_smoke/documents", "DELETE"))
wait_for("live count 0", lambda: api("index/progress"),
         lambda value: value["is_done"] and value["obj_count"] == 0)
assert api("setting/get?key=index_progress")["value"] == saved

with urllib.request.urlopen(openlist + "/", timeout=10) as response:
    page = response.read().decode()
    assert response.status == 200 and "<html" in page.lower()

print("PASS: embedded frontend, login, real Meilisearch totals 2 -> 0, "
      "and unchanged saved progress; no storage configured or scanned")
