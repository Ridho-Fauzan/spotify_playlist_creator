#!/usr/bin/env python3
"""
Spotify Playlist Creator — Web App
==================================

A small Flask web app that lets you create a playlist on your own Spotify
account from a browser. It handles the Spotify OAuth login flow, then lets
you build a playlist either by listing specific songs or by using
Spotify's recommendation engine.

Run:
    python app.py
Then open http://127.0.0.1:8888 in your browser.

Setup instructions are in README.md.
"""

import os
import uuid

from dotenv import load_dotenv
from flask import (
    Flask,
    jsonify,
    redirect,
    request,
    send_from_directory,
    session,
    url_for,
)

import spotipy
from spotipy.oauth2 import SpotifyOAuth

load_dotenv()

# Scopes: permission to create/edit public and private playlists.
SCOPE = "playlist-modify-public playlist-modify-private"

# Frontend assets live in public/ so Vercel's CDN serves style.css and
# app.js directly. Flask only needs to serve index.html at the root route.
# Paths are absolute so they resolve regardless of working directory.
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_PUBLIC_DIR = os.path.join(_BASE_DIR, "public")

app = Flask(__name__)
# Session secret just needs to be stable per-run for the login cookie.
# On serverless (Vercel), set FLASK_SECRET_KEY so logins survive restarts.
app.secret_key = os.getenv("FLASK_SECRET_KEY", uuid.uuid4().hex)


def make_oauth(cache_handler=None):
    """Build a SpotifyOAuth helper from environment config."""
    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
    redirect_uri = os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")

    if not client_id or not client_secret:
        raise RuntimeError(
            "Missing SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET. "
            "Copy .env.example to .env and fill them in."
        )

    return SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scope=SCOPE,
        cache_handler=cache_handler,
        show_dialog=False,
    )


def cache_handler():
    """Store the Spotify token inside the Flask session (per browser)."""
    return spotipy.cache_handler.FlaskSessionCacheHandler(session)


def get_spotify():
    """Return an authenticated Spotify client, or None if not logged in."""
    oauth = make_oauth(cache_handler())
    token_info = oauth.validate_token(cache_handler().get_cached_token())
    if not token_info:
        return None
    return spotipy.Spotify(auth=token_info["access_token"])


# --------------------------------------------------------------------------
# Auth routes
# --------------------------------------------------------------------------

@app.route("/login")
def login():
    oauth = make_oauth(cache_handler())
    return redirect(oauth.get_authorize_url())


@app.route("/callback")
def callback():
    oauth = make_oauth(cache_handler())
    code = request.args.get("code")
    if not code:
        error = request.args.get("error", "kesalahan tidak diketahui")
        return f"Otorisasi gagal: {error}", 400
    # Exchanging the code stores the token via the cache handler (session).
    oauth.get_access_token(code, as_dict=False)
    return redirect(url_for("index"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/api/me")
def api_me():
    sp = get_spotify()
    if not sp:
        return jsonify({"logged_in": False})
    user = sp.current_user()
    return jsonify(
        {
            "logged_in": True,
            "display_name": user.get("display_name") or user["id"],
        }
    )


# --------------------------------------------------------------------------
# Playlist creation
# --------------------------------------------------------------------------

def search_tracks(sp, queries):
    """Resolve free-text song queries to Spotify track URIs."""
    uris, not_found = [], []
    for raw in queries:
        query = (raw or "").strip()
        if not query:
            continue
        if " - " in query:
            title, artist = (p.strip() for p in query.split(" - ", 1))
            search_str = f"track:{title} artist:{artist}"
        else:
            search_str = query
        res = sp.search(q=search_str, type="track", limit=1)
        items = res.get("tracks", {}).get("items", [])
        if items:
            uris.append(items[0]["uri"])
        else:
            not_found.append(query)
    return uris, not_found


def recommend_tracks(sp, seed_artists, seed_genres, seed_tracks, limit):
    """Use Spotify's recommendation engine to get track URIs."""
    artist_ids = []
    for name in seed_artists:
        res = sp.search(q=f"artist:{name}", type="artist", limit=1)
        items = res.get("artists", {}).get("items", [])
        if items:
            artist_ids.append(items[0]["id"])

    track_ids = []
    for name in seed_tracks:
        res = sp.search(q=name, type="track", limit=1)
        items = res.get("tracks", {}).get("items", [])
        if items:
            track_ids.append(items[0]["id"])

    total = len(artist_ids) + len(seed_genres) + len(track_ids)
    if total == 0:
        return []
    if total > 5:
        raise ValueError(
            "Spotify hanya mengizinkan maksimal 5 acuan total (artis + genre + lagu)."
        )

    rec = sp.recommendations(
        seed_artists=artist_ids or None,
        seed_genres=list(seed_genres) or None,
        seed_tracks=track_ids or None,
        limit=limit,
    )
    return [t["uri"] for t in rec.get("tracks", [])]


def add_in_batches(sp, playlist_id, uris):
    for i in range(0, len(uris), 100):
        sp.playlist_add_items(playlist_id, uris[i : i + 100])


@app.route("/api/create", methods=["POST"])
def api_create():
    sp = get_spotify()
    if not sp:
        return jsonify({"error": "Belum masuk/login."}), 401

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Nama playlist wajib diisi."}), 400

    description = (data.get("description") or "").strip()
    public = bool(data.get("public"))

    # Songs typed into the textarea (one per line).
    songs_text = data.get("songs") or ""
    queries = [line.strip() for line in songs_text.splitlines() if line.strip()]

    # Recommendation seeds (comma-separated strings).
    def split_csv(value):
        return [s.strip() for s in (value or "").split(",") if s.strip()]

    seed_artists = split_csv(data.get("seed_artists"))
    seed_genres = split_csv(data.get("seed_genres"))
    seed_tracks = split_csv(data.get("seed_tracks"))
    try:
        count = int(data.get("count") or 20)
    except (TypeError, ValueError):
        count = 20
    count = max(1, min(count, 100))

    using_recs = bool(seed_artists or seed_genres or seed_tracks)
    if not queries and not using_recs:
        return jsonify({"error": "Tambahkan beberapa lagu atau acuan rekomendasi."}), 400

    uris, not_found = [], []
    if queries:
        found, nf = search_tracks(sp, queries)
        uris.extend(found)
        not_found.extend(nf)

    if using_recs:
        try:
            uris.extend(
                recommend_tracks(sp, seed_artists, seed_genres, seed_tracks, count)
            )
        except ValueError as err:
            return jsonify({"error": str(err)}), 400

    # De-duplicate, preserve order.
    seen, unique = set(), []
    for u in uris:
        if u not in seen:
            seen.add(u)
            unique.append(u)

    if not unique:
        return jsonify({"error": "Tidak ada lagu yang bisa ditemukan.", "not_found": not_found}), 400

    user_id = sp.current_user()["id"]
    playlist = sp.user_playlist_create(
        user=user_id, name=name, public=public, description=description
    )
    add_in_batches(sp, playlist["id"], unique)

    return jsonify(
        {
            "ok": True,
            "added": len(unique),
            "not_found": not_found,
            "url": playlist["external_urls"]["spotify"],
            "name": name,
        }
    )


@app.route("/")
def index():
    # Serve the single-page frontend. On Vercel, style.css/app.js are served
    # directly by the CDN from public/; here we serve the HTML entry point.
    return send_from_directory(_PUBLIC_DIR, "index.html")


@app.route("/style.css")
@app.route("/app.js")
def public_asset():
    # Fallback for local dev (`python app.py`). On Vercel these paths are
    # served straight from the CDN and never reach Flask.
    filename = request.path.lstrip("/")
    return send_from_directory(_PUBLIC_DIR, filename)


if __name__ == "__main__":
    # Port 8888 matches the redirect URI in the setup instructions.
    app.run(host="127.0.0.1", port=8888, debug=True)
