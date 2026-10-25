# 🎵 Spotify Playlist Creator

A small web app (and optional CLI) that creates a playlist on **your own
Spotify account** and fills it with songs — either by listing specific
tracks or by using Spotify's recommendation engine.

![Built with Flask](https://img.shields.io/badge/built%20with-Flask-000?logo=flask)
![Spotify Web API](https://img.shields.io/badge/Spotify-Web%20API-1db954?logo=spotify&logoColor=white)

---

## What's inside

| File | Purpose |
|------|---------|
| `app.py` | Flask web app (recommended) |
| `create_playlist.py` | Command-line version |
| `static/` | Web app frontend (HTML/CSS/JS) |
| `.env.example` | Template for your Spotify credentials |
| `songs.example.txt` | Sample song list for the CLI `--tracks-file` option |

---

## Part 1 — Set up a Spotify Developer app (one time)

Spotify requires any app that modifies your account to be registered.
It's free and takes ~3 minutes.

1. Go to the **[Spotify Developer Dashboard](https://developer.spotify.com/dashboard)**
   and log in with your normal Spotify account.
2. Click **Create app**.
3. Fill in the form:
   - **App name:** anything, e.g. `My Playlist Maker`
   - **App description:** anything
   - **Redirect URI:** enter exactly this and click **Add**:
     ```
     http://127.0.0.1:8888/callback
     ```
     ⚠️ This must match *exactly* — same scheme, host, port, and path.
   - **Which API/SDKs are you planning to use?** check **Web API**.
4. Accept the terms and click **Save**.
5. Open your new app → **Settings**. Copy the **Client ID**, then click
   **View client secret** and copy the **Client Secret**.

> 🔒 Keep the Client Secret private — treat it like a password. Never
> paste it into chats, screenshots, or commit it to Git.

---

## Part 2 — Configure the project

1. Install Python 3.8+ : https://www.python.org/downloads/
2. (Recommended) Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate        # Windows: .venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Create your `.env` file from the template and fill it in:
   ```bash
   cp .env.example .env
   ```
   Paste your **Client ID** and **Client Secret** into `.env`. Leave the
   redirect URI as-is (it must match the dashboard).

---

## Part 3 — Run the web app ✨

```bash
python app.py
```

Then open **http://127.0.0.1:8888** in your browser and:

1. Click **Log in with Spotify** and approve access (first time only).
2. Give your playlist a name.
3. Add songs by typing them (one per line, `Title - Artist` works best)
   **and/or** fill in recommendation seeds (artists / genres / tracks).
4. Click **Create playlist** — you'll get a direct link to open it in Spotify. 🎉

---

## Prefer the command line?

The original CLI still works too:

```bash
# Specific songs
python create_playlist.py --name "Road Trip" \
    --track "Bohemian Rhapsody - Queen" --track "Africa - Toto"

# From a file (one song per line)
python create_playlist.py --name "Road Trip" --tracks-file songs.example.txt

# Recommendations (max 5 seeds total)
python create_playlist.py --name "Chill" \
    --seed-artist "Bon Iver" --seed-genre acoustic --count 25
```

Run `python create_playlist.py --help` for all options.

---

## Troubleshooting

- **`INVALID_CLIENT: Invalid redirect URI`** — the redirect URI in `.env`
  must match the one in the dashboard *exactly*.
- **Want to switch Spotify accounts?** Click **Log out** in the web app
  (or delete `.spotify_cache` for the CLI) and log in again.
- **Secrets:** `.env` and token caches are in `.gitignore`, so they won't
  be committed.
