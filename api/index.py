#!/usr/bin/env python3
"""
Spotify Playlist Creator — Web App (Vercel entry point)
=======================================================

Vercel auto-detects the Flask instance named `app` in this file and runs
it as a serverless function. The rewrite in vercel.json sends *every*
request here, so this one app serves both the HTML/JS/CSS frontend and the
JSON API.

Local development:
    python api/index.py
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

# Frontend assets live in the repo-root public/ folder. We resolve its
# absolute path from this file (api/index.py -> ../public) so it works no
# matter what the serverless working directory is.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PUBLIC_DIR = os.path.join(os.path.dirname(_THIS_DIR), "public")

app = Flask(__name__)
# Session secret just needs to be stable per deployment for the login
# cookie. On serverless (Vercel), set FLASK_SECRET_KEY as an env var so
# logins survive across function invocations.
app.secret_key = os.getenv("FLASK_SECRET_KEY", uuid.uuid4().hex)


class _VercelPathFix:
    """WSGI middleware: restore the original request path on Vercel.

    When vercel.json rewrites everything to the function file, some Vercel
    configurations pass the function's own path (e.g. "/api/index" or
    "/api/index.py") to the WSGI app instead of the URL the visitor typed
    (e.g. "/login"). Vercel preserves the real URL in the
    `x-forwarded-uri` / `x-vercel-*` headers, so we read it back and set
    PATH_INFO accordingly. If the path already looks normal, we leave it
    alone — so this is a no-op locally and harmless in every case.
    """

    _FUNCTION_PATHS = {"/api/index", "/api/index.py"}

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "")
        if path in self._FUNCTION_PATHS:
            # Try the headers Vercel forwards with the original URL.
            forwarded = (
                environ.get("HTTP_X_FORWARDED_URI")
                or environ.get("HTTP_X_VERCEL_FORWARDED_FOR_PATH")
                or environ.get("HTTP_X_ORIGINAL_URL")
                or ""
            )
            if forwarded:
                # Strip any query string; Flask reads QUERY_STRING separately.
                environ["PATH_INFO"] = forwarded.split("?", 1)[0]
            else:
                # No header available — default to the home page rather than
                # a confusing 404 on the function's own path.
                environ["PATH_INFO"] = "/"
        return self.wsgi_app(environ, start_response)


app.wsgi_app = _VercelPathFix(app.wsgi_app)


def make_oauth(cache=None):
    """Build a SpotifyOAuth helper from environment config."""
    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
    redirect_uri = os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")

    if not client_id or not client_secret:
        raise RuntimeError(
            "Missing SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET. "
            "Set them as environment variables (or in a local .env file)."
        )

    return SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scope=SCOPE,
        cache_handler=cache,
        show_dialog=False,
        # Belt-and-suspenders: if spotipy ever falls back to a file cache,
        # point it at /tmp — the only writable directory on Vercel's
        # read-only serverless filesystem. The session cache handler above
        # is what we actually use; this just prevents a crash on import.
        cache_path="/tmp/.spotipy_cache",
    )


def make_session_cache():
    """Store the Spotify token inside the Flask session (per browser).

    Using the session (a signed cookie) means no disk writes, which is
    essential on serverless where the filesystem is read-only.
    """
    return spotipy.cache_handler.FlaskSessionCacheHandler(session)


def get_spotify():
    """Return an authenticated Spotify client, or None if not logged in."""
    cache = make_session_cache()
    oauth = make_oauth(cache)
    token_info = oauth.validate_token(cache.get_cached_token())
    if not token_info:
        return None
    return spotipy.Spotify(auth=token_info["access_token"])


# --------------------------------------------------------------------------
# Auth routes
# --------------------------------------------------------------------------

@app.route("/login")
def login():
    oauth = make_oauth(make_session_cache())
    return redirect(oauth.get_authorize_url())


@app.route("/callback")
def callback():
    oauth = make_oauth(make_session_cache())
    code = request.args.get("code")
    if not code:
        error = request.args.get("error", "kesalahan tidak diketahui")
        return f"Otorisasi gagal: {error}", 400
    # Exchanging the code stores the token via the session cache handler.
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
        return jsonify(
            {"error": "Tidak ada lagu yang bisa ditemukan.", "not_found": not_found}
        ), 400

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


# --------------------------------------------------------------------------
# Frontend (served by this same function, so nothing depends on CDN routing)
# --------------------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(_PUBLIC_DIR, "index.html")


@app.route("/style.css")
def style_css():
    return send_from_directory(_PUBLIC_DIR, "style.css")


@app.route("/app.js")
def app_js():
    return send_from_directory(_PUBLIC_DIR, "app.js")


# --------------------------------------------------------------------------
# Error handlers — keep /api/* responses as JSON even on failure, so the
# frontend never chokes on an HTML error page ("Unexpected token '<'").
# --------------------------------------------------------------------------

@app.errorhandler(404)
def handle_404(err):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Endpoint tidak ditemukan.", "path": request.path}), 404
    # For non-API routes, fall back to serving the single-page app.
    return send_from_directory(_PUBLIC_DIR, "index.html")


@app.errorhandler(Exception)
def handle_exception(err):
    """Catch-all so errors surface clearly instead of a bare 500 page.

    We log the full traceback (visible in Vercel Runtime Logs) and return a
    readable message. Set DEBUG_ERRORS=1 as a Vercel env var to include the
    traceback in the HTTP response while diagnosing, then remove it.
    """
    import traceback

    # Let Flask handle normal HTTP errors (404, redirects, etc.) as usual.
    from werkzeug.exceptions import HTTPException

    if isinstance(err, HTTPException):
        return err

    tb = traceback.format_exc()
    app.logger.error("Unhandled error on %s:\n%s", request.path, tb)

    show_tb = os.getenv("DEBUG_ERRORS") == "1"
    if request.path.startswith("/api/"):
        body = {"error": "Terjadi kesalahan di server."}
        if show_tb:
            body["traceback"] = tb
        return jsonify(body), 500

    message = "Terjadi kesalahan di server."
    if show_tb:
        message += "\n\n" + tb
    return (message, 500, {"Content-Type": "text/plain; charset=utf-8"})


if __name__ == "__main__":
    # Port 8888 matches the default redirect URI in the setup instructions.
    app.run(host="127.0.0.1", port=8888, debug=True)
