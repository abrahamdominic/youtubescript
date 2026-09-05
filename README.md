# NK Keyword Downloader (YouTube + Telegram)

A terminal-based tool that searches **YouTube** and **Telegram** for a keyword,
downloads the accessible matching media (video, audio, documents, images), and
saves per-item JSON metadata — all from a polished, Rich-powered CLI.

```bash
python media_finder.py "Apostle Babs Adewumi"
```

## Features

- **Polished Rich CLI** — branded startup banner, live download progress bars
  (percentage, size, speed, ETA), per-item download cards, summary panels and a
  final success screen.
- **YouTube source** — searches by keyword and processes the top results. Prefers
  MP4 up to 1080p (best video + best audio merged when FFmpeg is available) and
  3 automatic retries on failure.
- **`--audio-only` mode** — downloads the best audio stream and converts it to
  192 kbps MP3 (requires FFmpeg).
- **Telegram source** — searches the messages, captions and file names across
  the dialogs your account can access, filters by media type
  (video / audio / document / image), shows a **Telegram Search** panel with the
  keyword and the number of matches found, and downloads the media.
- **Duplicate protection & resume** — already-downloaded YouTube videos (by video
  ID) and Telegram media (by `chat_id:message_id`) are always skipped; re-running
  a command resumes without re-downloading completed files.
- **Per-item JSON metadata** — YouTube: title, URL, video ID, channel, upload
  date, duration, view count, description, thumbnail. Telegram: message ID,
  channel, date, message text, media type, filename, file size.
- **Resilient** — a single failing item never aborts a run; failures are
  collected into `failed_downloads.json` and reported, and the exit code reflects
  the outcome.
- **Respectful by design** — Telegram flood-wait (rate limit) requests are shown
  clearly and waited out, never bypassed; only content the authenticated account
  is allowed to access is touched.
- **Modular code** — Telegram logic lives in its own `src/telegram.py` module
  (see [Architecture](#architecture)).

## Requirements

- Python 3.10 or newer
- [FFmpeg](https://ffmpeg.org) — to merge video/audio streams, produce MP4
  containers and extract MP3 audio (see below)
- An internet connection
- `yt-dlp` (YouTube), `rich` (terminal UI), `Telethon` (Telegram) and
  `python-dotenv` (`.env` loading) — all installed via
  `pip install -r requirements.txt`

### FFmpeg

FFmpeg merges separate video/audio streams into a single MP4 and converts audio
to MP3. The tool still runs without it, but:

- videos fall back to the best single-stream MP4 (lower quality),
- `--audio-only` saves the raw audio stream instead of converting to MP3,
- a warning panel is shown at startup.

Install it on your platform:

- **Windows:** `winget install Gyan.FFmpeg` (or grab the latest build from
  <https://www.gyan.dev/ffmpeg/builds/> and add its `bin/` folder to `PATH`).
- **Linux (Debian/Ubuntu):** `sudo apt update && sudo apt install ffmpeg`
- **Linux (Fedora):** `sudo dnf install ffmpeg`
- **macOS:** `brew install ffmpeg` (requires [Homebrew](https://brew.sh))

Verify with `ffmpeg -version`.

### Telegram credentials

Telegram requires a free **API ID** and **API hash** from Telegram's official
developer process:

1. Log in at <https://my.telegram.org/apps>.
2. Create an application to get your `api_id` and `api_hash`.
3. Copy `.env.example` to `.env` and fill in the values:

   ```env
   TELEGRAM_API_ID=1234567
   TELEGRAM_API_HASH=abcdef...
   TELEGRAM_SESSION_NAME=media_finder
   ```

> **Bot API vs User API.** Telegram offers two kinds of accounts:
>
> - **Bot API** — a separate HTTP API for server-side bots. Bot accounts are not
>   part of your conversations and **cannot** search or read your dialogs.
> - **User API / MTProto** — the protocol the official apps use, accessed here
>   through **Telethon**. It operates as *your* account and can search the
>   content your account is allowed to see.
>
> This tool uses the **user API through Telethon**, so get credentials from
> <https://my.telegram.org/apps>, not BotFather.

On the **first Telegram run** the script starts the normal Telethon
authentication flow: it asks for your phone number, the verification code sent
by Telegram, and (if enabled) your 2FA password, then saves a **local session
file** (`media_finder.session`, in the directory you run the command from).
Later runs reuse that session and never ask again. Your password is never
stored, and `.env` / `*.session` files are already in `.gitignore`.
If the terminal is not interactive (e.g. output is piped), the script refuses to
prompt and exits with a clear message instead.

Missing credentials never crash — Telegram runs stop with a helpful error panel,
and `--source youtube` / `--source all` keep working regardless.

## Installation

```bash
git clone <repository-url>
cd youtube-keyword-downloader

python -m venv venv
```

Activate the virtual environment:

- **Windows (Cmd):** `venv\Scripts\activate`
- **Windows (PowerShell):** `venv\Scripts\Activate.ps1`
- **Linux / macOS (bash/zsh):** `source venv/bin/activate`

Then install the dependencies:

```bash
pip install -r requirements.txt
```

or

```bash
python3 -m pip install -r requirements.txt
```

> **Prefer automation?** `run.sh` does this for you — it creates the virtual
> environment if missing and installs every missing dependency (including
> yt-dlp, rich and Telethon) before running the script:

```bash
./run.sh "Apostle Babs Adewumi"
```

Copy `.env.example` to `.env` (and fill in your Telegram credentials) only if you
want to use the Telegram source — YouTube works without it.

## Basic Usage

Use the `run.sh` launcher — it automatically creates the virtual environment,
installs any missing dependency (yt-dlp, rich, Telethon, python-dotenv) and then
runs the main script:

```bash
./run.sh "Apostle Babs Adewumi"
```

Or run it directly when your dependencies are already set up:

```bash
python3 media_finder.py "Apostle Babs Adewumi"
```

Searches YouTube, downloads the first 50 videos into
`downloads/Apostle Babs Adewumi/`, and saves their metadata. Re-running the same
command skips videos that were already downloaded.

A `youtube_downloader.py` compatibility wrapper is also provided — it behaves
exactly the same (`python youtube_downloader.py "keyword"`).

## Source selection

`--source` chooses where to search:

```bash
# YouTube only (default)
python3 media_finder.py "apostle babs" --source youtube

# Telegram only
python3 media_finder.py "apostle babs" --source telegram

# Both sources
python3 media_finder.py "apostle babs" --source all
```

Telegram defaults to the 20 best matches and asks for confirmation before
downloading. To download everything without asking:

```bash
python3 media_finder.py "apostle babs" --source telegram --yes
```

## Limiting results

```bash
python3 media_finder.py "apostle babs" --limit 20
```

Defaults: **50** for YouTube, **20** for Telegram.

## Telegram media type filter

```bash
python3 media_finder.py "apostle babs" --source telegram --type video
python3 media_finder.py "apostle babs" --source telegram --type audio
python3 media_finder.py "apostle babs" --source telegram --type document
python3 media_finder.py "apostle babs" --source telegram --type image
python3 media_finder.py "apostle babs" --source telegram --type all   # default
```

## Audio download

```bash
python3 media_finder.py "apostle babs" --audio-only
```

Downloads the best audio stream and converts it to 192 kbps MP3 (requires
FFmpeg). Without FFmpeg it saves the raw audio stream as-is.

## Custom output directory

```bash
python3 media_finder.py "apostle babs" --output ./my-downloads
```

The keyword-based folder is created automatically inside the given directory
(default: `downloads/`). The keyword is sanitized into a safe folder name.

## CLI options

```
-h, --help            Show the help menu
--limit LIMIT         Maximum number of results to process
                      (default: YouTube 50, Telegram 20)
--output OUTPUT       Base output directory (default: downloads)
--source {youtube,telegram,all}
                      Which source to search (default: youtube)
--type {video,audio,document,image,all}
                      Telegram media type filter (default: all)
--yes                 Auto-download all Telegram results without asking
--format FORMAT       yt-dlp format selector (overrides the automatic choice)
--audio-only          Download audio instead of video
```

## Output structure

```text
downloads/
└── Apostle Babs Adewumi/
    ├── videos/                 Downloaded MP4/MP3 files (YouTube)
    ├── metadata/               video_001.json, video_002.json, ...
    ├── metadata.json           Combined metadata for every processed video
    ├── failed_downloads.json   Details of videos that could not be saved
    ├── downloaded.json         Manifest of downloaded video IDs (for resume)
    ├── README.txt              Summary of the run
    └── telegram/               Telegram results
        ├── videos/  audio/  documents/  images/
        ├── metadata/           1234.json, -100123..._5678.json, ...
        ├── metadata.json       Combined Telegram metadata
        ├── downloaded.json     Manifest of downloaded messages (for resume)
        └── failed_downloads.json
```

Telegram files keep the original media filename where available; otherwise a
safe `ChannelTitle_messageid_Title` name is generated. Telegram metadata per
item includes: source, keyword, message ID, channel name, date, message text,
media type, filename and file size.

## Architecture

The code is split so the YouTube-focused module stays free of Telegram/Telethon
imports, while both share one set of UI/JSON/path helpers:

```text
media_finder.py        Main entry point — CLI, YouTube source, shared Rich
                       UI/JSON/path helpers, FFmpeg detection, summary + logs
src/telegram.py        Isolated Telegram source: Telethon credentials, auth,
                       search, media classification, downloads and metadata
run.sh                 Auto-setup launcher: creates the venv, installs any
                       missing dependencies (incl. yt-dlp), then runs the script
youtube_downloader.py  Compatibility wrapper re-exporting the main CLI
requirements.txt       Python dependencies
.env.example           Template for Telegram credentials (TELEGRAM_API_ID/HASH)
```

- `src/telegram.py` imports the shared helpers directly from `media_finder`
  (e.g. `console`, `show_results_table`, `build_telegram_dirs`).
- `media_finder.py` imports `run_telegram_source` **lazily**, only when
  `--source telegram` or `--source all` is used — so plain YouTube runs never
  touch Telethon. This keeps the two modules free of import cycles.
- Telegram search results are shown with a **Telegram Search** panel (keyword +
  "Found N matching messages") followed by the shared results table.

## Troubleshooting

- **`python` / `pip` not found** — install Python 3.10+; on some systems use
  `python -m pip`.
- **`ModuleNotFoundError: rich/yt-dlp/Telethon`** — activate your virtual
  environment and run `pip install -r requirements.txt`.
- **FFmpeg missing** — install it as described above; without it `--audio-only`
  cannot produce MP3 and video quality may be lower.
- **Telegram credentials error at startup** — copy `.env.example` to `.env` and
  fill in `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` from
  <https://my.telegram.org/apps>.
- **Telegram asks for phone/code again** — the `.session` file must remain in
  the directory you run the command from; keep it so you authenticate only once.
- **Telegram non-interactive error** — the tool cannot prompt for a code when
  output is piped; run once in an interactive terminal to create the session.
- **Unavailable / private / deleted videos** — logged in `failed_downloads.json`
  and the run continues.
- **Network failures / `Unable to download webpage`** — downloads are retried up
  to 3 times automatically; check your connection for persistent failures.
- **YouTube rate limiting / `Too Many Requests`** — wait a while, lower `--limit`
  or use a different network.
- **Telegram rate limiting (flood-wait)** — the tool shows a clear message and
  waits the exact time Telegram requests, then resumes automatically.
- **Age-restricted videos** — YouTube may block these without a signed-in
  session; they are reported as failures.
- **`Sign in to confirm you're not a bot`** — use a `cookies.txt` file by
  uncommenting the `"cookiefile"` option in `build_downloader_options()` or see
  <https://github.com/yt-dlp/yt-dlp#how-do-i-pass-cookies-to-yt-dlp>.

## Updating yt-dlp

yt-dlp changes frequently to keep pace with YouTube, so update it regularly:

```bash
pip install -U yt-dlp
```

## Legal / copyright notice

This tool only downloads content you are authorized to download. Respect
YouTube's Terms of Service, applicable copyright laws and Telegram's terms; do
not use this tool to download or redistribute content you do not have permission
to use.