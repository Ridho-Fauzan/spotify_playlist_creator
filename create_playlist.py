#!/usr/bin/env python3
"""
Spotify Playlist Creator
========================

A small command-line tool that creates a playlist on your own Spotify
account and fills it with songs. You can add songs in two ways:

  1. Search  — give it track names (optionally "Track - Artist") and it
     finds the best match for each and adds it.
  2. Recommend — give it seed artists / genres / tracks and it uses
     Spotify's recommendation engine to fill the playlist for you.

You can also combine both in a single playlist.

Setup instructions are in README.md.
"""

import argparse
import os
import sys

from dotenv import load_dotenv

try:
    import spotipy
    from spotipy.oauth2 import SpotifyOAuth
except ImportError:
    sys.exit(
        "The 'spotipy' package is not installed.\n"
        "Run:  pip install -r requirements.txt"
    )


# Scopes: what we are asking permission to do on the user's account.
#   playlist-modify-public  -> create/edit public playlists
#   playlist-modify-private -> create/edit private playlists
SCOPE = "playlist-modify-public playlist-modify-private"


def get_client() -> "spotipy.Spotify":
    """Authenticate and return a ready-to-use Spotify client.

    The first time this runs it opens a browser window asking you to log
    in and approve access. After that, a token is cached locally so you
    won't have to log in again until it expires.
    """
    load_dotenv()

    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
    redirect_uri = os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")

    missing = [
        name
        for name, value in (
            ("SPOTIFY_CLIENT_ID", client_id),
            ("SPOTIFY_CLIENT_SECRET", client_secret),
        )
        if not value
    ]
    if missing:
        sys.exit(
            "Missing required setting(s): "
            + ", ".join(missing)
            + "\nCopy .env.example to .env and fill in your credentials."
        )

    auth = SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scope=SCOPE,
        cache_path=".spotify_cache",
        open_browser=True,
    )
    return spotipy.Spotify(auth_manager=auth)


def search_tracks(sp, queries):
    """Turn a list of free-text song queries into Spotify track URIs.

    Each query can be just a title ("Bohemian Rhapsody") or
    "Title - Artist" ("Bohemian Rhapsody - Queen") for a better match.
    Returns (uris, not_found).
    """
    uris = []
    not_found = []
    for raw in queries:
        query = raw.strip()
        if not query:
            continue

        # Support "Title - Artist" syntax for more precise matching.
        if " - " in query:
            title, artist = (part.strip() for part in query.split(" - ", 1))
            search_str = f"track:{title} artist:{artist}"
        else:
            search_str = query

        result = sp.search(q=search_str, type="track", limit=1)
        items = result.get("tracks", {}).get("items", [])
        if items:
            track = items[0]
            artists = ", ".join(a["name"] for a in track["artists"])
            print(f"  ✓ Found: {track['name']} — {artists}")
            uris.append(track["uri"])
        else:
            print(f"  ✗ No match for: {query}")
            not_found.append(query)
    return uris, not_found


def recommend_tracks(sp, seed_artists, seed_genres, seed_tracks, limit):
    """Use Spotify's recommendation engine to get track URIs.

    Spotify allows up to 5 seeds total across artists + genres + tracks.
    """
    # Resolve artist names to IDs (the recommendations API needs IDs).
    artist_ids = []
    for name in seed_artists:
        res = sp.search(q=f"artist:{name}", type="artist", limit=1)
        items = res.get("artists", {}).get("items", [])
        if items:
            artist_ids.append(items[0]["id"])
            print(f"  ✓ Seed artist: {items[0]['name']}")
        else:
            print(f"  ✗ Artist not found: {name}")

    # Resolve track names to IDs.
    track_ids = []
    for name in seed_tracks:
        res = sp.search(q=name, type="track", limit=1)
        items = res.get("tracks", {}).get("items", [])
        if items:
            track_ids.append(items[0]["id"])
            print(f"  ✓ Seed track: {items[0]['name']}")
        else:
            print(f"  ✗ Track not found: {name}")

    total_seeds = len(artist_ids) + len(seed_genres) + len(track_ids)
    if total_seeds == 0:
        print("  No valid seeds — skipping recommendations.")
        return []
    if total_seeds > 5:
        sys.exit(
            "Spotify allows at most 5 seeds total (artists + genres + tracks). "
            f"You provided {total_seeds}."
        )

    rec = sp.recommendations(
        seed_artists=artist_ids or None,
        seed_genres=list(seed_genres) or None,
        seed_tracks=track_ids or None,
        limit=limit,
    )
    uris = []
    for track in rec.get("tracks", []):
        artists = ", ".join(a["name"] for a in track["artists"])
        print(f"  + Recommended: {track['name']} — {artists}")
        uris.append(track["uri"])
    return uris


def add_in_batches(sp, playlist_id, uris):
    """Add tracks to a playlist. Spotify accepts max 100 per request."""
    for i in range(0, len(uris), 100):
        sp.playlist_add_items(playlist_id, uris[i : i + 100])


def main():
    parser = argparse.ArgumentParser(
        description="Create a Spotify playlist and fill it with songs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            '  # From a list of songs:\n'
            '  python create_playlist.py --name "My Mix" \\\n'
            '      --track "Bohemian Rhapsody - Queen" --track "Africa - Toto"\n\n'
            '  # From a file (one song per line):\n'
            '  python create_playlist.py --name "My Mix" --tracks-file songs.txt\n\n'
            '  # From recommendations:\n'
            '  python create_playlist.py --name "Chill" \\\n'
            '      --seed-artist "Bon Iver" --seed-genre acoustic --count 25\n'
        ),
    )
    parser.add_argument("--name", required=True, help="Name of the playlist to create.")
    parser.add_argument("--description", default="", help="Playlist description.")
    parser.add_argument(
        "--public",
        action="store_true",
        help="Make the playlist public (default is private).",
    )

    # Ways to add songs by search.
    parser.add_argument(
        "--track",
        action="append",
        default=[],
        metavar='"Title - Artist"',
        help="A song to search for and add. Repeatable.",
    )
    parser.add_argument(
        "--tracks-file",
        help="Path to a text file with one song per line.",
    )

    # Ways to add songs by recommendation.
    parser.add_argument(
        "--seed-artist", action="append", default=[], help="Seed artist name. Repeatable."
    )
    parser.add_argument(
        "--seed-genre", action="append", default=[], help="Seed genre. Repeatable."
    )
    parser.add_argument(
        "--seed-track", action="append", default=[], help="Seed track name. Repeatable."
    )
    parser.add_argument(
        "--count",
        type=int,
        default=20,
        help="How many recommended tracks to add (default 20, max 100).",
    )

    args = parser.parse_args()

    # Gather search queries from --track flags and/or a file.
    queries = list(args.track)
    if args.tracks_file:
        try:
            with open(args.tracks_file, encoding="utf-8") as fh:
                queries.extend(line for line in (l.strip() for l in fh) if line)
        except OSError as err:
            sys.exit(f"Could not read tracks file: {err}")

    using_recs = bool(args.seed_artist or args.seed_genre or args.seed_track)
    if not queries and not using_recs:
        sys.exit(
            "Nothing to add. Provide songs with --track / --tracks-file, "
            "or seeds with --seed-artist / --seed-genre / --seed-track."
        )

    sp = get_client()
    user = sp.current_user()
    user_id = user["id"]
    print(f"\nLogged in as: {user.get('display_name') or user_id}")

    # Collect track URIs.
    all_uris = []

    if queries:
        print("\nSearching for your songs...")
        found, _ = search_tracks(sp, queries)
        all_uris.extend(found)

    if using_recs:
        print("\nGetting recommendations...")
        count = max(1, min(args.count, 100))
        rec_uris = recommend_tracks(
            sp, args.seed_artist, args.seed_genre, args.seed_track, count
        )
        all_uris.extend(rec_uris)

    # De-duplicate while preserving order.
    seen = set()
    unique_uris = []
    for uri in all_uris:
        if uri not in seen:
            seen.add(uri)
            unique_uris.append(uri)

    if not unique_uris:
        sys.exit("\nNo tracks could be found. Playlist not created.")

    # Create the playlist and add the tracks.
    print(f"\nCreating playlist '{args.name}'...")
    playlist = sp.user_playlist_create(
        user=user_id,
        name=args.name,
        public=args.public,
        description=args.description,
    )
    add_in_batches(sp, playlist["id"], unique_uris)

    print(f"\n✅ Done! Added {len(unique_uris)} track(s).")
    print(f"   Open it here: {playlist['external_urls']['spotify']}")


if __name__ == "__main__":
    main()
