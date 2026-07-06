import argparse, json, os, sys, time, urllib.error, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

CLIENT_ID = os.environ.get("UNSPLASH_CLIENT_ID", "")
if not CLIENT_ID:
    print("ERROR: UNSPLASH_CLIENT_ID env not set (comMod should inject it)", file=sys.stderr)
    sys.exit(2)

API = "https://api.unsplash.com/search/photos"
ORIENTATIONS = {"landscape", "portrait", "squarish"}
RETRIES = 3
RETRY_SLEEP = 1
RETRY_CAP = 8
FETCH_TIMEOUT = 6
HEAD_TIMEOUT = 3
HEAD_RETRIES = 1

PEXELS_API = "https://api.pexels.com/v1/search"
PEXELS_KEY = os.environ.get("PEXELS_API_KEY", "")
PEXELS_SIZE_W = {"regular": 1080, "small": 400}
PEXELS_ORIENT = {"landscape": "landscape", "portrait": "portrait", "squarish": "square"}  # squarish -> square


def _backoff(i):
    return min(RETRY_SLEEP * (2 ** i), RETRY_CAP)


def _fetch_json(url, headers=None):
    for i in range(RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers=headers or {})
            with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if (e.code == 429 or 500 <= e.code < 600) and i < RETRIES:
                time.sleep(_backoff(i))
                continue
            print(f"ERROR: HTTP {e.code} {e.reason}", file=sys.stderr)
            return None
        except urllib.error.URLError as e:
            if i < RETRIES:
                time.sleep(_backoff(i))
                continue
            print(f"ERROR: network failed after {RETRIES + 1} tries: {e.reason}", file=sys.stderr)
            return None
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return None
    return None


def _head_ok(url):
    for i in range(HEAD_RETRIES + 1):
        try:
            req = urllib.request.Request(url, method="HEAD")
            if urllib.request.urlopen(req, timeout=HEAD_TIMEOUT).getcode() == 200:
                return True
        except Exception:
            if i < HEAD_RETRIES:
                time.sleep(_backoff(i))
                continue
    return False


def _search(query, size, count, orientation):
    url = API + "?" + urllib.parse.urlencode({
        "query": query, "per_page": count,
        "orientation": orientation, "client_id": CLIENT_ID})
    data = _fetch_json(url)
    if data is None:
        return []
    if "errors" in data:
        print(f"ERROR: [{query}] API: {data['errors']}", file=sys.stderr)
        return []
    out = []
    for p in data.get("results", []):
        img = p.get("urls", {}).get(size, "")
        alt = (p.get("alt_description") or "").replace("\t", " ").replace("\n", " ").replace("\r", " ").strip()
        if not img:
            continue
        if _head_ok(img):
            out.append((img, alt))
    return out


def _search_pexels(query, size, count, orientation):
    # Pexels fallback: Unsplash 无结果/失败时调用. key 缺失静默跳过.
    if not PEXELS_KEY:
        return []
    url = PEXELS_API + "?" + urllib.parse.urlencode({
        "query": query, "per_page": count,
        "orientation": PEXELS_ORIENT.get(orientation, orientation)})
    data = _fetch_json(url, {"Authorization": PEXELS_KEY, "User-Agent": "site_design-images/1.0"})
    if data is None:
        return []
    if data.get("errors"):
        print(f"ERROR: [{query}] Pexels: {data['errors']}", file=sys.stderr)
        return []
    w = PEXELS_SIZE_W.get(size, 1080)
    out = []
    for p in data.get("photos", []):
        original = p.get("src", {}).get("original", "")
        if not original:
            continue
        img = f"{original}?auto=compress&cs=tinysrgb&w={w}"
        alt = (p.get("alt") or "").replace("\t", " ").replace("\n", " ").replace("\r", " ").strip()
        if _head_ok(img):
            out.append((img, alt))
    return out


def fetch_block(primary, secondary, size, count, orientation):
    for q in (primary, secondary):
        if not q:
            continue
        found = _search(q, size, count, orientation)
        if found:
            return found
    # fallback
    for q in (primary, secondary):
        if not q:
            continue
        found = _search_pexels(q, size, count, orientation)
        if found:
            return found
    return []


def parse_block(s):
    p = [x.strip() for x in s.split("|")]
    if len(p) < 5:
        raise ValueError(f'--block needs label|primary|secondary|size|count (got: {s})')
    if len(p) > 6:
        raise ValueError(f'too many fields ({len(p)}): queries must not contain "|" (got: {s})')
    label, primary, secondary, size, count = p[0], p[1], p[2], p[3], p[4]
    orientation = p[5] if len(p) > 5 else "landscape"
    if not label:
        raise ValueError("label (1st field) must not be empty")
    if not primary and not secondary:
        raise ValueError("primary and secondary both empty — need at least one query")
    if size not in ("regular", "small"):
        raise ValueError(f"size must be regular|small (got {size})")
    if orientation not in ORIENTATIONS:
        raise ValueError(f"orientation must be landscape|portrait|squarish (got {orientation})")
    try:
        count = int(count)
    except ValueError:
        raise ValueError(f"count must be int (got {count})")
    if count < 1:
        raise ValueError(f"count must be >= 1 (got {count})")
    count = min(count, 30)
    return label, primary, secondary, size, count, orientation


def main():
    ap = argparse.ArgumentParser(description="Multi-block image search for Site Design skill")
    ap.add_argument("--block", action="append", required=True,
                    metavar='"label|primary|secondary|size|count[|orientation]"',
                    help="one per image block; primary first, secondary as fallback")
    a = ap.parse_args()
    blocks = []
    for s in a.block:
        try:
            blocks.append(parse_block(s))
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(2)

    def _run(b):
        label, primary, secondary, size, count, orientation = b
        try:
            return label, fetch_block(primary, secondary, size, count, orientation)
        except Exception as e:
            print(f"ERROR: [{label}] {e}", file=sys.stderr)
            return label, []

    with ThreadPoolExecutor(max_workers=min(8, len(blocks))) as ex:
        results = list(ex.map(_run, blocks))
    for label, rows in results:
        print(f"=== {label} ===")
        for img, alt in rows:
            print(f"{img}\t{alt}")


if __name__ == "__main__":
    main()
