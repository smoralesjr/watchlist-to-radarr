# Letterboxd → Radarr

Self-hosted web app: paste a public [Letterboxd](https://letterboxd.com) watchlist URL and import every film into your [Radarr](https://radarr.video) server as a monitored movie. Newly added monitored movies show up under Radarr's **Wanted** view, and each addition triggers an automatic search.

> Why not Sonarr? Sonarr only manages TV series; Letterboxd watchlists are movies, so Radarr is the correct target. (Radarr's "Wanted" page is the movie equivalent of Sonarr's.)

## Features

- Reads any **public** Letterboxd watchlist (RSS feed, with HTML scraping fallback for lists > 40 items)
- Config UI for Radarr URL, API key, root folder, and quality profile (saved to `config.json`)
- Preview the watchlist before importing
- Per-film results: added / already added / not found, with a summary and links back to Letterboxd
- Skips movies already in Radarr; matches by title and year via TMDb through Radarr's lookup API

## Requirements

- Python 3.9+
- `flask`, `requests` (`beautifulsoup4` used if available for long lists)

```bash
pip install flask requests beautifulsoup4
```

## Run

```bash
python app.py
# then open http://localhost:5000
```

The app binds to `127.0.0.1:5000` only. Put it behind your existing reverse proxy (e.g. nginx/Traefik) if you want remote access — it has no authentication of its own, so don't expose it directly to the internet.

Optional environment overrides: `RADARR_URL`, `RADARR_API_KEY`, `RADARR_ROOT_FOLDER`.

## Usage

1. Enter your Radarr URL and API key (Radarr → Settings → General → API Key) and click **Save & connect**. Pick a root folder and quality profile if you have several.
2. Paste a watchlist URL like `https://letterboxd.com/username/watchlist/`.
3. Click **Preview** to see the parsed films, then **Import to Radarr**.
4. Watch the results table; everything added appears in Radarr under **Wanted → Missing**.

The watchlist must be public — private lists can't be read without login.

## Notes

- `config.json` is created next to `app.py` and stores your API key in plain text; protect the file accordingly.
- Unreleased films (no year on Letterboxd) are matched on title alone and added as monitored, so Radarr will pick them up when they become available.
