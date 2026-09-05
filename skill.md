I have an existing Python YouTube keyword downloader script. I want you to redesign ONLY the terminal user interface and presentation so that it looks like a beautiful, modern, premium CLI application.

The project name is:

**NK YouTube Keyword Downloader**

Do NOT rewrite or remove the existing download functionality. Preserve the existing behavior, yt-dlp integration, metadata generation, manifest handling, duplicate detection, retry logic, FFmpeg detection, audio-only mode, command-line arguments, output structure, and error handling.

Use the existing Python file as the source of truth.

## MAIN GOAL

Transform the current plain terminal interface into a polished, colorful and professional CLI using the **Rich** Python library.

Install/use:

```bash
pip install rich
```

If the project has a `requirements.txt`, add:

```text
rich
```

Do not introduce unnecessary frameworks.

---

# 1. PROJECT BRANDING

Replace the current:

**NK YouTube Keyword Downloader**

branding with:

**NK YouTube Keyword Downloader**

The application should feel like a professional media utility rather than a basic Python script.

Use a consistent visual identity throughout the terminal.

Suggested visual style:

* Cyan
* Bright blue
* Purple
* Green for success
* Yellow for warnings
* Red for errors
* White/light gray for normal information
* Dim gray for secondary information

Do not use excessive emojis.

Use tasteful Unicode symbols where they improve readability, such as:

✓
✗
→
•
│
─
╭
╰
├
└

---

# 2. BEAUTIFUL STARTUP BANNER

Replace the current simple `=====` banner with a Rich-powered startup screen.

Create a large ASCII-art style banner for:

**NK TERMINAL TOOL**

Under it display something similar to:

```text
YouTube Media Downloader
Search • Download • Organize • Archive
```

Include a small status section:

```text
YT-DLP     ✓ Ready
FFmpeg     ✓ Available
Output     ./downloads
```

The banner should be visually centered where practical.

Do NOT make the banner so large that it takes up most of the terminal.

---

# 3. SEARCH INFORMATION PANEL

Before searching, display a Rich Panel containing:

```text
SEARCH CONFIGURATION

Keyword     Apostle Babs Adewumi
Limit       50
Mode        Video
Output      downloads/Apostle Babs Adewumi
FFmpeg      Available
```

Use Rich formatting to visually distinguish labels and values.

For example:

* Labels → dim/white
* Values → cyan/bright
* Status → green/yellow/red

---

# 4. SEARCHING EXPERIENCE

Replace:

```text
Searching YouTube...
```

with a Rich spinner/status animation.

Example:

```text
⠋ Searching YouTube for "Apostle Babs Adewumi"...
```

When complete:

```text
✓ Search completed
✓ Found 37 videos
```

Use Rich's `console.status()` or an equivalent Rich spinner.

Do not leave broken spinner characters behind after completion.

---

# 5. DOWNLOAD DISPLAY

The current downloader prints simple messages such as:

```text
[1/50] Downloading:
Video title
[OK] Download completed
```

Replace this with a much cleaner Rich layout.

Each download should have something like:

```text
╭─ [01/50] Downloading ─────────────────────────╮
│                                               │
│  Title   Apostle Babs Adewumi - Message       │
│  Status  Downloading...                       │
│                                               │
╰───────────────────────────────────────────────╯
```

After completion:

```text
✓ Download completed
```

For skipped downloads:

```text
→ Already downloaded
```

For failures:

```text
✗ Download failed
  Reason: <error>
```

Keep the output readable even when downloading many files.

---

# 6. PROGRESS BAR

Where technically possible, integrate Rich progress bars with yt-dlp.

Show:

```text
Downloading
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 72%
Speed: 4.2 MB/s
ETA: 00:08
```

Include:

* Percentage
* Downloaded size
* Total size when available
* Download speed
* ETA
* Current filename/title

Use yt-dlp progress hooks rather than trying to estimate progress manually.

IMPORTANT:

Do not break yt-dlp's actual download process.

The progress display must update dynamically.

If progress hooks cannot safely support a particular operation, gracefully fall back to a clean Rich status message instead of breaking the download.

---

# 7. DOWNLOAD STATISTICS

At the end of the process, create a beautiful summary panel.

Instead of:

```text
==================================================
Download Complete
==================================================
Total found: 37
Downloaded: 30
Skipped: 5
Failed: 2
```

display something similar to:

```text
╭────────────── DOWNLOAD SUMMARY ───────────────╮
│                                               │
│  Total Found       37                         │
│  Downloaded        30        ✓                │
│  Skipped            5        →                │
│  Failed             2        ✗                │
│                                               │
│  Output Folder                                │
│  downloads/Apostle Babs Adewumi               │
│                                               │
╰───────────────────────────────────────────────╯
```

Use appropriate colours for each statistic.

---

# 8. SUCCESS SCREEN

When everything succeeds, show a prominent success message:

```text
╭──────────────────────────────────────────────╮
│                                              │
│       ✓ DOWNLOAD SESSION COMPLETE            │
│                                              │
│       37 videos processed                    │
│       37 successfully downloaded             │
│                                              │
╰──────────────────────────────────────────────╯
```

If there are failures, use a different warning/error presentation.

---

# 9. FFmpeg WARNING

Currently the application prints a plain FFmpeg warning.

Replace it with a Rich warning panel.

Example:

```text
╭─ ⚠ FFmpeg Not Found ─────────────────────────╮
│                                              │
│  Some features will be limited:             │
│  • Video/audio merging                       │
│  • MP4 conversion                            │
│  • MP3 extraction                            │
│                                              │
│  Install FFmpeg and make sure it is          │
│  available on your PATH.                    │
│                                              │
╰──────────────────────────────────────────────╯
```

Do not display this warning when FFmpeg is available.

---

# 10. ERROR HANDLING

Make errors much easier to read.

Instead of:

```text
[ERROR] Could not reach YouTube.
```

use a Rich error panel:

```text
╭─ ✗ ERROR ────────────────────────────────────╮
│                                              │
│  Could not reach YouTube.                   │
│                                              │
│  Check your internet connection and          │
│  try again.                                  │
│                                              │
╰──────────────────────────────────────────────╯
```

Do not expose unnecessary Python tracebacks to normal users.

Keep useful technical information available when needed.

---

# 11. COMMAND HELP

Improve the argparse help output so that:

```bash
python youtube_downloader.py --help
```

also looks professional.

Use a clean description:

```text
NK Terminal Tool
YouTube Media Downloader
```

Keep all existing arguments:

```text
keyword
--limit
--output
--format
--audio-only
```

Do not remove or rename existing arguments unless absolutely necessary.

If changing the executable/program name is useful, make sure existing usage remains functional.

---

# 12. TERMINAL RESPONSIVENESS

The UI must work correctly in:

* Linux terminal
* macOS terminal
* Windows Terminal
* VS Code integrated terminal
* SSH sessions where possible

Do not assume true-color support.

Rich should automatically handle terminal capabilities.

The application must also remain usable when output is redirected or when color is unavailable.

Respect:

```text
NO_COLOR
```

where appropriate.

---

# 13. KEEP THE CURRENT FILE STRUCTURE

Do not unnecessarily split the application into many files.

Prefer a clean structure such as:

```text
Imports
Constants
Rich Console / UI helpers
Path helpers
JSON helpers
YouTube search
Download functions
Metadata functions
UI functions
Argument parsing
Main workflow
```

Keep the code maintainable.

---

# 14. IMPORTANT FUNCTIONALITY PRESERVATION

DO NOT break any of these existing features:

* YouTube keyword searching
* Search result limit
* Video downloading
* Audio-only downloading
* MP3 conversion when FFmpeg exists
* MP4 merging
* Custom format selection
* FFmpeg detection
* Duplicate detection
* Download manifest
* Metadata JSON
* Individual video metadata
* Failed downloads JSON
* README generation
* Retry logic
* Output folder structure
* Existing command-line arguments

The application must still perform exactly the same core job.

ONLY improve the terminal presentation and make minimal code changes required for Rich integration.

---

# 15. DEPENDENCY HANDLING

If Rich is not installed, the program should fail gracefully with a useful message such as:

```text
Rich is not installed.

Install it with:

pip install rich
```

However, since this project should use Rich, make sure `requirements.txt` includes it.

Do not silently install packages from inside the Python application.

---

# 16. CODE QUALITY

After making the changes:

1. Run a Python syntax check.
2. Run the application with `--help`.
3. Test a small YouTube search/download.
4. Verify the Rich UI does not interfere with yt-dlp.
5. Verify audio-only mode.
6. Verify duplicate detection.
7. Verify FFmpeg warning behavior.
8. Verify failed-download handling.
9. Verify metadata files are still generated.
10. Verify the program exits with the correct status code.

Fix any errors you encounter.

---

# FINAL REQUIREMENT

The finished terminal application should feel like a polished tool called:

# NK YouTube Keyword Downloader

It should look **beautiful, colorful, modern, clean and professional**, while remaining lightweight and practical.

Do NOT add unnecessary features unrelated to terminal UI.

Do NOT replace yt-dlp.

Do NOT remove existing functionality.

Do NOT change the actual download behavior unless required to integrate the progress display.

Focus heavily on **UI/UX, Rich styling, progress feedback, panels, status messages, and professional terminal presentation.**



-------------------------


I already have a working terminal-based YouTube downloader in this project.

**Do NOT rebuild, replace, or unnecessarily modify the existing YouTube functionality.**

I only want you to add a **Telegram search and media downloader** to the existing project.

## OBJECTIVE

Extend the existing terminal application so it can search Telegram for media related to a keyword and download accessible matching media.

For example:

```bash
python media_finder.py "Apostle Babs Adewumi"
```

The existing YouTube functionality should continue working exactly as it does now.

Add Telegram as an additional source.

---

# 1. TELEGRAM LIBRARY

Use:

```text
Telethon
```

for Telegram API access.

Do NOT scrape Telegram's website.

Do NOT attempt to bypass private channels, restricted content, authentication, permissions, or other Telegram security mechanisms.

Only search and download content that the authenticated Telegram account is allowed to access.

---

# 2. TELEGRAM API CREDENTIALS

Use environment variables.

Add these to `.env.example`:

```env
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
TELEGRAM_SESSION_NAME=media_finder
```

Do NOT hardcode credentials.

Add these to `.gitignore`:

```text
.env
*.session
```

The Telegram session file must never be committed to GitHub.

---

# 3. TELEGRAM AUTHENTICATION

On the first Telegram operation, check whether a Telegram session exists.

If there is no session, start the normal Telethon authentication flow.

The terminal should display something similar to:

```text
==================================================
Telegram Authentication
==================================================

No Telegram session found.

Enter your phone number:
```

Then handle:

* phone number
* Telegram verification code
* 2FA password if enabled

After successful authentication, save the session locally.

On subsequent runs, reuse the existing session instead of asking the user to log in again.

Do not store the Telegram password.

---

# 4. TELEGRAM SEARCH

Add a Telegram search function.

If the user runs:

```bash
python media_finder.py "Apostle Babs Adewumi" --source telegram
```

search Telegram for the keyword:

```text
Apostle Babs Adewumi
```

Search content accessible to the authenticated account.

Look for the keyword in:

* message text
* captions
* filenames
* media information where available

Prioritize exact and strong matches.

---

# 5. TELEGRAM MEDIA

Detect available media types including:

* Video
* Audio
* Voice/audio files
* Documents
* Images

For example:

```text
Apostle Babs Adewumi Message.mp4
Apostle Babs Adewumi Sermon.mp3
Apostle Babs Adewumi.pdf
```

Only download media that is accessible to the authenticated account.

---

# 6. TELEGRAM RESULT DISPLAY

Before downloading, display the discovered results.

Example:

```text
==================================================
TELEGRAM SEARCH
==================================================

Keyword:
Apostle Babs Adewumi

Found 12 matching messages.

[1]
Title: Apostle Babs Adewumi - Powerful Message
Channel: Example Channel
Type: Video
Size: 350 MB

[2]
Title: Apostle Babs Adewumi Teaching
Channel: Another Channel
Type: Audio
Size: 82 MB

[3]
Title: Apostle Babs Adewumi Sermon
Channel: Example Channel
Type: Video
Size: 420 MB
```

Then ask:

```text
Download all results? [Y/n]
```

---

# 7. NON-INTERACTIVE MODE

Support:

```bash
--yes
```

Example:

```bash
python media_finder.py "Apostle Babs Adewumi" --source telegram --yes
```

This should automatically download all matching results without asking for confirmation.

---

# 8. SOURCE OPTION

Add:

```bash
--source telegram
```

The existing YouTube source must remain unchanged.

If the current project already has a `--source` option, extend it rather than replacing it.

Supported values should become:

```text
youtube
telegram
all
```

Examples:

```bash
python media_finder.py "Apostle Babs Adewumi" --source youtube
```

```bash
python media_finder.py "Apostle Babs Adewumi" --source telegram
```

```bash
python media_finder.py "Apostle Babs Adewumi" --source all
```

If `all` is selected:

```text
YouTube
+
Telegram
```

should both be searched.

---

# 9. TELEGRAM OUTPUT FOLDER

Do not change the existing YouTube output structure.

Add Telegram alongside it.

For example:

```text
downloads/
└── Apostle Babs Adewumi/
    │
    ├── youtube/
    │   └── ...
    │
    └── telegram/
        ├── videos/
        ├── audio/
        ├── documents/
        ├── images/
        └── metadata/
```

Create only the directories that are actually needed.

---

# 10. TELEGRAM FILENAMES

Use the Telegram media filename where available.

If there is no filename, generate a safe filename using:

```text
channel_messageid_title
```

For example:

```text
ExampleChannel_1234_Apostle_Babs_Adewumi.mp4
```

Sanitize filenames for Windows/Linux compatibility.

---

# 11. DOWNLOAD PROGRESS

Show useful progress in the terminal.

Example:

```text
[Telegram 3/12]

Downloading:
Apostle Babs Adewumi - Teaching.mp4

Progress: 43%
Downloaded: 172 MB / 400 MB
Speed: 5.2 MB/s
```

Do not load entire large media files into memory.

Use Telethon's appropriate file-download functionality.

---

# 12. DUPLICATE DETECTION

Do not download the same Telegram media repeatedly.

Use a combination of:

```text
chat/channel ID
+
message ID
```

as the primary Telegram media identifier.

If already downloaded:

```text
[SKIP] Already downloaded
```

Continue to the next result.

---

# 13. RESUME SUPPORT

If the program is interrupted:

```text
Ctrl+C
```

running:

```bash
python media_finder.py "Apostle Babs Adewumi" --source telegram
```

again should not redownload files that have already completed.

---

# 14. METADATA

Save metadata for every Telegram download.

Example:

```text
telegram/metadata/
├── 1234.json
├── 1235.json
└── 1236.json
```

Metadata should include, where available:

```json
{
  "source": "telegram",
  "keyword": "Apostle Babs Adewumi",
  "message_id": 1234,
  "channel_name": "Example Channel",
  "date": "...",
  "message_text": "...",
  "media_type": "video",
  "filename": "...",
  "file_size": 123456789
}
```

Do not expose sensitive authentication information in metadata.

---

# 15. SEARCH LIMIT

Support:

```bash
--limit 50
```

Example:

```bash
python media_finder.py "Apostle Babs Adewumi" --source telegram --limit 50
```

Use a sensible default such as 20.

---

# 16. MEDIA TYPE FILTER

Add:

```bash
--type video
```

```bash
--type audio
```

```bash
--type document
```

```bash
--type image
```

```bash
--type all
```

Example:

```bash
python media_finder.py "Apostle Babs Adewumi" --source telegram --type video
```

---

# 17. ERROR HANDLING

One failed Telegram download must not stop the entire process.

Example:

```text
[ERROR] Unable to download media

Channel: Example Channel
Message: 1234
Reason: Media unavailable

Continuing...
```

At the end show:

```text
==================================================
TELEGRAM DOWNLOAD COMPLETE
==================================================

Found: 20
Downloaded: 16
Skipped: 2
Failed: 2
```

Save failures to:

```text
telegram/failed_downloads.json
```

---

# 18. RATE LIMITS

Handle Telegram rate limits correctly.

If Telegram returns a flood-wait/rate-limit response:

* Respect the requested wait time.
* Do not attempt to bypass it.
* Display a clear message.
* Resume when appropriate.

Do not aggressively send search/download requests.

---

# 19. SECURITY

Never print or save:

* Telegram API hash
* Telegram phone number unnecessarily
* Telegram 2FA password
* Session credentials

Do not commit:

```text
.env
*.session
```

---

# 20. REQUIREMENTS

Update the existing `requirements.txt`.

Add the required Telegram dependency, preferably:

```text
Telethon
```

Do not remove existing YouTube dependencies.

After modification, verify:

```bash
python -m pip install -r requirements.txt
```

works inside the project's virtual environment.

---

# 21. README

Update the existing `README.md`.

Do not replace useful existing documentation.

Add a Telegram section covering:

## Telegram requirements

Explain that Telegram functionality requires:

```text
TELEGRAM_API_ID
TELEGRAM_API_HASH
```

obtained through Telegram's official API developer process.

Explain the difference between:

* Telegram Bot API
* Telegram user API / MTProto

For this application, use the Telegram user API through Telethon.

Explain the first-time authentication process.

---

# 22. EXISTING YOUTUBE FUNCTIONALITY

This is extremely important.

The current YouTube implementation is already working.

DO NOT:

* rewrite it
* replace it
* remove it
* change its download logic unnecessarily
* break its CLI
* change its folder structure unnecessarily

Only refactor existing code if absolutely necessary to integrate Telegram cleanly.

Before finishing, verify that:

```bash
python media_finder.py "Apostle Babs Adewumi" --source youtube
```

still works exactly as before.

Then verify:

```bash
python media_finder.py "Apostle Babs Adewumi" --source telegram
```

works.

Finally verify:

```bash
python media_finder.py "Apostle Babs Adewumi" --source all
```

runs both sources.

---

# 23. FINAL TESTS

Run:

```bash
python -m py_compile media_finder.py
```

Then:

```bash
python media_finder.py --help
```

Then test YouTube:

```bash
python media_finder.py "Apostle Babs Adewumi" --source youtube --limit 5
```

Test Telegram:

```bash
python media_finder.py "Apostle Babs Adewumi" --source telegram --limit 5
```

Test combined:

```bash
python media_finder.py "Apostle Babs Adewumi" --source all --limit 5
```

---

# 24. IMPLEMENTATION APPROACH

First inspect the existing project.

Understand:

* current file structure
* existing CLI
* existing YouTube downloader
* existing output directories
* existing configuration
* existing requirements
* existing error handling

Then add Telegram in the cleanest way possible.

Prefer creating a separate module such as:

```text
src/telegram.py
```

and keep Telegram-specific logic isolated from the YouTube implementation.

For example:

```text
src/
├── youtube.py
├── telegram.py
├── downloader.py
├── metadata.py
└── utils.py
```

Do not duplicate functionality unnecessarily.

---

# FINAL RESULT

I should be able to run:

```bash
python media_finder.py "Apostle Babs Adewumi" --source telegram
```

and have the program:

```text
Authenticate Telegram if necessary
        ↓
Search accessible Telegram content
        ↓
Find relevant messages/media
        ↓
Display results
        ↓
Ask whether to download
        ↓
Download matching media
        ↓
Organize files
        ↓
Save metadata
        ↓
Skip duplicates
        ↓
Handle errors
        ↓
Show final summary
```

And the existing YouTube command must continue working.

Build and integrate **only the Telegram functionality** now.

use the same features in the YouTube downloader, such as:

# 7. DOWNLOAD STATISTICS

At the end of the process, create a beautiful summary panel.

Instead of:

```text
==================================================
Download Complete
==================================================
Total found: 37
Downloaded: 30
Skipped: 5
Failed: 2
```

display something similar to:

```text
╭────────────── DOWNLOAD SUMMARY ───────────────╮
│                                               │
│  Total Found       37                         │
│  Downloaded        30        ✓                │
│  Skipped            5        →                │
│  Failed             2        ✗                │
│                                               │
│  Output Folder                                │
│  downloads/Apostle Babs Adewumi               │
│                                               │
╰───────────────────────────────────────────────╯
```

Use appropriate colours for each statistic.

---

and other features like the one above

### Multi-Platform Downloader Selection Flow

Update the terminal interface so that when the application starts, the user can first choose **which platform(s) they want to search and download from**.

The application should present a clear interactive menu like:

```text
╔══════════════════════════════════════════════╗
║          NK TERMINAL DOWNLOADER              ║
║          Multi-Platform Media Tool            ║
╚══════════════════════════════════════════════╝

Select your download source:

  [1] YouTube
  [2] Telegram
  [3] Both YouTube & Telegram
  [4] Exit

Enter your choice:
```

### 1. Platform Selection

The user must select one of the available options:

* **1 — YouTube**
* **2 — Telegram**
* **3 — Both YouTube & Telegram**
* **4 — Exit**

The application should validate the input and re-display the menu if the user enters an invalid option.

---

### 2. YouTube Only

If the user selects:

```text
[1] YouTube
```

Proceed to the YouTube configuration flow.

Ask for the required information interactively:

```text
YouTube Configuration
────────────────────────────────────

Enter keyword:
> Apostle Babs Adewumi

Maximum number of results:
> 20

Download mode:
  [1] Video
  [2] Audio only
  [3] Both

Enter choice:
>
```

Then ask any other YouTube-specific options that are already supported by the existing application.

**Important:** Do not remove or change any existing YouTube functionality. The current YouTube downloader should continue working exactly as it does now.

---

### 3. Telegram Only

If the user selects:

```text
[2] Telegram
```

Proceed to the Telegram configuration flow.

Ask for the relevant Telegram-specific configuration, for example:

```text
Telegram Configuration
────────────────────────────────────

Enter keyword:
> Apostle Babs Adewumi

Maximum number of results:
> 20

Media type:
  [1] Video
  [2] Audio
  [3] Documents
  [4] All

Enter choice:
>
```

Then ask any additional Telegram-specific options required by the existing Telegram implementation.

The Telegram downloader should search for content related to the specified keyword and download matching media according to the selected options.

---

### 4. Both Platforms

If the user selects:

```text
[3] Both YouTube & Telegram
```

The application should allow the user to configure both platforms in a single session.

For example:

```text
╔══════════════════════════════════════════════╗
║        YOUTUBE + TELEGRAM MODE               ║
╚══════════════════════════════════════════════╝

YouTube Configuration
────────────────────────────────────

Enter keyword:
> Apostle Babs Adewumi

YouTube result limit:
> 20

Download mode:
  [1] Video
  [2] Audio only
  [3] Both

Enter choice:
>
```

Then:

```text
Telegram Configuration
────────────────────────────────────

Enter keyword:
> Apostle Babs Adewumi

Telegram result limit:
> 20

Media type:
  [1] Video
  [2] Audio
  [3] Documents
  [4] All

Enter choice:
>
```

However, **avoid asking for the same information twice when it can logically be shared.**

For example, if the keyword should be identical for both platforms, allow:

```text
Enter search keyword:
> Apostle Babs Adewumi

Search this keyword on:
  ✓ YouTube
  ✓ Telegram
```

Then ask only platform-specific settings separately.

---

### 5. Shared Configuration

Where appropriate, allow common settings to apply to both platforms.

For example:

```text
Search Configuration
────────────────────────────────────

Keyword:
> Apostle Babs Adewumi

Result limit:
> 20

Platforms:
  ✓ YouTube
  ✓ Telegram
```

Then:

```text
Platform-specific options

YouTube:
  Download type → Audio

Telegram:
  Media type → All
```

The goal is to make the workflow **fast and intuitive**, without unnecessarily asking the user for the same information multiple times.

---

### 6. Configuration Summary

Before starting the download/search process, display a final summary.

Example:

```text
╔══════════════════════════════════════════════╗
║              DOWNLOAD SUMMARY                ║
╚══════════════════════════════════════════════╝

Keyword       : Apostle Babs Adewumi
Platforms     : YouTube + Telegram
Result Limit  : 20

YouTube
  Mode        : Audio Only

Telegram
  Media       : All

────────────────────────────────────

[1] Start Download
[2] Edit Settings
[3] Cancel

Enter choice:
>
```

If the user selects **1**, begin the process.

If they select **2**, allow them to modify the configuration without restarting the entire application.

If they select **3**, cancel and return to the main menu.

---

### 7. Progress Display

When both platforms are selected, clearly separate the progress for each platform.

Example:

```text
╔══════════════════════════════════════════════╗
║              SEARCHING CONTENT               ║
╚══════════════════════════════════════════════╝

[YouTube]
Searching for: Apostle Babs Adewumi
Results found: 18

[Telegram]
Searching for: Apostle Babs Adewumi
Results found: 12
```

Then show download progress:

```text
YouTube Downloads
────────────────────────────────────
[██████████████████░░] 90%  18/20

Telegram Downloads
────────────────────────────────────
[████████████░░░░░░░░] 60%  12/20
```

Use the existing progress/download system wherever possible.

---

### 8. Important Implementation Requirements

**Do not rewrite the existing downloader functionality.**

Preserve:

* Existing YouTube search functionality
* `yt-dlp` integration
* Telegram functionality
* Metadata generation
* Manifest handling
* Duplicate detection
* Retry logic
* FFmpeg detection
* Audio-only mode
* Video mode
* Command-line arguments
* Existing output folder structure
* Existing file naming conventions
* Existing error handling
* Existing download logic

The primary change should be the **interactive platform-selection and configuration workflow**.

Structure the application so the platform selection acts as a router:

```text
START
  │
  ▼
Platform Selection
  │
  ├── 1 → YouTube Configuration → YouTube Downloader
  │
  ├── 2 → Telegram Configuration → Telegram Downloader
  │
  ├── 3 → Shared Configuration
  │         │
  │         ├── YouTube Configuration
  │         └── Telegram Configuration
  │                    │
  │                    ▼
  │            Run Both Downloaders
  │
  └── 4 → Exit
```

The interface should feel like a **premium, modern terminal application**, with clean sections, colors, icons/symbols where supported, clear prompts, validation, progress indicators, and helpful error messages.

Most importantly, **do not make the user pass command-line arguments just to choose a platform**. The platform selection should be available directly through the interactive terminal menu.
