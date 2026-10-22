import json
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse

import requests
from flask import Flask, jsonify, render_template, request

APP_DIR = Path(__file__).parent
CONFIG_PATH = APP_DIR / "config.json"

UA = {"User-Agent": "Mozilla/5.0 (watchlist-to-radarr)"}

app = Flask(__name__)


def load_config():
    defaults = {
        "radarr_url": os.environ.get("RADARR_URL", ""),
        "radarr_api_key": os.environ.get("RADARR_API_KEY", ""),
        "quality_profile_id": None,
        "root_folder_path": os.environ.get("RADARR_ROOT_FOLDER", ""),
    }
    if CONFIG_PATH.exists():
        try:
            defaults.update(json.loads(CONFIG_PATH.read_text()))
        except (ValueError, OSError):
            pass
    return defaults


def save_config(cfg):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def radarr_request(cfg, method, endpoint, params=None, body=None):
    base = cfg["radarr_url"].rstrip("/")
    url = f"{base}/api/v3{endpoint}"
    headers = {"X-Api-Key": cfg["radarr_api_key"]}
    resp = requests.request(method, url, params=params, json=body,
                             headers=headers, timeout=30)
    if resp.status_code == 401:
        raise RuntimeError("Radarr rejected the API key (401).")
    if resp.status_code == 400:
        try:
            msg = resp.json().get("message", resp.text)
        except ValueError:
            msg = resp.text
        raise RuntimeError(f"Radarr 400: {msg}")
    resp.raise_for_status()
    return resp.json() if resp.content else None


def watchlist_username(url):
    path = urlparse(url).path.strip("/")
    m = re.match(r"^([A-Za-z0-9_.-]+)/watchlist", path)
    if not m:
        raise ValueError(
            "Not a watchlist URL. Expected https://letterboxd.com/<username>/watchlist/"
        )
    return m.group(1)


def fetch_watchlist_rss(username, origin="https://letterboxd.com"):
    feed_url = f"{origin}/{username}/watchlist/rss/"
    resp = requests.get(feed_url, headers=UA, timeout=30)
    if resp.status_code != 200:
        return None
    root = ET.fromstring(resp.content)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    items = []
    for entry in root.findall("a:entry", ns):
        title = (entry.findtext("a:title", namespaces=ns) or "").strip()
        link_el = entry.find("a:link", ns)
        link = (link_el.get("href", "") if link_el is not None else "").strip()
        if title:
            items.append({"letterboxd_title": title, "letterboxd_url": link})
    return items


def fetch_watchlist_html(username, origin="https://letterboxd.com"):
    items = []
    page = 1
    while True:
        url = f"{origin}/{username}/watchlist/page/{page}/"
        resp = requests.get(url, headers=UA, timeout=30)
        if resp.status_code != 200:
            break
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(resp.text, "html.parser")
        posters = soup.select("ul.poster-list li.poster-container > div.poster")
        if not posters:
            break
        for poster in posters:
            title = poster.get("data-original-title") or poster.get("alt") or ""
            film_slug = None
            target = poster.find("a", href=True)
            if target:
                film_slug = target["href"]
            if title:
                items.append({
                    "letterboxd_title": title.strip(),
                    "letterboxd_url": f"https://letterboxd.com{film_slug}" if film_slug else "",
                })
        older = soup.select_one("li.paginatedpage-prev a")
        if not older:
            break
        page += 1
    return items


def fetch_watchlist(url):
    username = watchlist_username(url)
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    items = fetch_watchlist_rss(username, origin)
    if not items:
        items = fetch_watchlist_html(username, origin)
    if not items:
        raise RuntimeError(
            f"Could not read {username}'s watchlist. Make sure it is public, "
            "and that this server isn't blocked by Letterboxd (datacenter IPs "
            "are sometimes blocked by Cloudflare)."
        )
    return username, items


def parse_letterboxd_title(raw):
    # Format: "Film Title, 2023" (year may be absent for unreleased films)
    m = re.match(r"^(.*?),\s*(\d{4})(?:\s*[-–].*)?$", raw)
    if m:
        return m.group(1).strip(), m.group(2)
    return raw, None


def movie_status(cfg):
    try:
        root_folders = radarr_request(cfg, "GET", "/rootfolder")
        profiles = radarr_request(cfg, "GET", "/qualityprofile")
    except RuntimeError as e:
        return {"error": str(e)}

    cfg["root_folder_path"] = (
        cfg.get("root_folder_path")
        or (root_folders[0]["path"] if root_folders else "")
    )
    cfg["quality_profile_id"] = (
        cfg.get("quality_profile_id")
        or (profiles[0]["id"] if profiles else None)
    )
    return {
        "ok": True,
        "root_folders": [{"path": f["path"]} for f in root_folders],
        "quality_profiles": [{"id": p["id"], "name": p["name"]} for p in profiles],
    }


def add_movie(cfg, query, year):
    matches = radarr_request(
        cfg, "GET", "/movie/lookup", params={"term": f"{query} {year or ''}".strip()},
    )
    if not matches:
        return {"status": "not_found"}
    if year:
        exact = next((m for m in matches if m.get("year") == int(year)), None)
        best = exact or matches[0]
    else:
        best = matches[0]
    if best.get("hasFile") or not best.get("isAvailable", True):
        pass
    existing = radarr_request(
        cfg, "GET", "/movie", params={"tmdbId": best["tmdbId"]}
    )
    if existing:
        return {"status": "already_added",
                "radarr_title": f"{existing[0]['title']} ({existing[0]['year']})"}
    body = {
        "title": best["title"],
        "tmdbId": best["tmdbId"],
        "qualityProfileId": int(cfg["quality_profile_id"]),
        "rootFolderPath": cfg["root_folder_path"],
        "monitored": True,
        "addOptions": {"searchForMovie": True},
    }
    radarr_request(cfg, "POST", "/movie", body=body)
    return {"status": "added",
            "radarr_title": f"{best['title']} ({best.get('year', '?')})"}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/config", methods=["GET"])
def get_config():
    cfg = load_config()
    return jsonify({
        "radarr_url": cfg["radarr_url"],
        "root_folder_path": cfg["root_folder_path"],
        "quality_profile_id": cfg["quality_profile_id"],
        "connected": bool(cfg["radarr_url"] and cfg["radarr_api_key"]),
    })


@app.route("/api/config", methods=["POST"])
def post_config():
    data = request.get_json(force=True)
    cfg = load_config()
    cfg["radarr_url"] = (data.get("radarr_url") or "").strip().rstrip("/")
    cfg["radarr_api_key"] = (data.get("radarr_api_key") or "").strip()
    if data.get("root_folder_path"):
        cfg["root_folder_path"] = data["root_folder_path"]
    if data.get("quality_profile_id"):
        cfg["quality_profile_id"] = int(data["quality_profile_id"])
    save_config(cfg)
    status = movie_status(cfg)
    save_config(cfg)
    if "error" in status:
        return jsonify(status), 400
    return jsonify(status)


@app.route("/api/preview", methods=["POST"])
def preview():
    data = request.get_json(force=True)
    cfg = load_config()
    if not (cfg["radarr_url"] and cfg["radarr_api_key"]):
        return jsonify({"error": "Connect Radarr first."}), 400
    try:
        username, items = fetch_watchlist(data["url"])
    except (ValueError, RuntimeError) as e:
        return jsonify({"error": str(e)}), 400
    results = []
    for item in items:
        title, year = parse_letterboxd_title(item["letterboxd_title"])
        results.append({
            "letterboxd_title": item["letterboxd_title"],
            "title": title,
            "year": year,
            "letterboxd_url": item["letterboxd_url"],
        })
    return jsonify({"username": username, "movies": results})


@app.route("/api/import", methods=["POST"])
def import_watchlist():
    data = request.get_json(force=True)
    cfg = load_config()
    if not (cfg["radarr_url"] and cfg["radarr_api_key"]):
        return jsonify({"error": "Connect Radarr first."}), 400
    try:
        status = movie_status(cfg)
        save_config(cfg)
        if "error" in status:
            return jsonify(status), 400
        username, items = fetch_watchlist(data["url"])
    except (ValueError, RuntimeError) as e:
        return jsonify({"error": str(e)}), 400

    results = []
    for item in items:
        title, year = parse_letterboxd_title(item["letterboxd_title"])
        try:
            result = add_movie(cfg, title, year)
        except RuntimeError as e:
            result = {"status": "error", "detail": str(e)}
        result["letterboxd_title"] = item["letterboxd_title"]
        result["letterboxd_url"] = item["letterboxd_url"]
        results.append(result)
    return jsonify({"username": username, "results": results})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
