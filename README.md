# ha-navidrome

Home Assistant integration for [Navidrome](https://www.navidrome.org/) music server.

Uses Navidrome's Server-Sent Events for real-time playback detection and JWT authentication — no polling, instant state changes.

## Features

- **Media player entity** — shows what's currently playing with album art
- **Real-time updates** — SSE-driven, media player appears/disappears instantly
- **Library sensors** — total songs, artists, genres, playlists
- **Scan control** — trigger and monitor library scans
- **Single auth** — JWT authentication for all API surfaces

## Installation

Add this repository as a custom repository in HACS, then install.

## Configuration

Add via Settings → Devices & Services → Add Integration → Navidrome.

Enter your Navidrome server URL, username, and password.
