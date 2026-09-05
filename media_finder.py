#!/usr/bin/env python3
"""NK YouTube Keyword Downloader / media_finder.

Search YouTube and/or Telegram for media matching a keyword, download the
accessible matches (video or audio) and save their metadata straight from
the terminal.

Examples:
    python media_finder.py "Apostle Babs Adewumi"
    python media_finder.py "Apostle Babs Adewumi" --source youtube
    python media_finder.py "Apostle Babs Adewumi" --source telegram --limit 20
    python media_finder.py "Apostle Babs Adewumi" --source telegram --type video
    python media_finder.py "Apostle Babs Adewumi" --source all
    python media_finder.py "Apostle Babs Adewumi" --audio-only
    python media_finder.py "Apostle Babs Adewumi" --output ./my-downloads
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# --- Required dependency: Rich -------------------------------------------------
try:
    from rich import box
    from rich.align import Align
    from rich.console import Console, Group
    from rich.panel import Panel
    from rich.progress import (
        BarColumn,
        Progress,
        TextColumn,
        TimeElapsedColumn,
    )
    from rich.table import Table
    from rich.text import Text
except ImportError:

    def _require_rich() -> None:  # pragma: no cover - runs only without rich
        print(
            "Rich is not installed.\n\n"
            "Install it with:\n\n    pip install rich\n\n"
            "or run:\n    pip install -r requirements.txt",
            file=sys.stderr,
        )
        sys.exit(1)

    _require_rich()

# --- Optional dependency --------------------------------------------------------
try:
    import yt_dlp
except ImportError:
    yt_dlp = None  # type: ignore[assignment]


def _require_ytdlp() -> None:
    """Raise a clear error when the yt-dlp dependency is missing."""
    if yt_dlp is None:
        raise RuntimeError(
            "yt-dlp is not installed.\n"
            "Install it with:  pip install -U yt-dlp\n"
            "or run:          pip install -r requirements.txt"
        )


# -------------------------------------------------------------------------
# Constants
# -------------------------------------------------------------------------

DEFAULT_YOUTUBE_LIMIT = 50
DEFAULT_TELEGRAM_LIMIT = 20

# Prefer MP4 at max 1080p, fall back to a single combined MP4, then anything.
DEFAULT_VIDEO_FORMAT = "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b"
# Combined MP4 only -- used when FFmpeg is unavailable (no merging possible).
NO_FFMPEG_VIDEO_FORMAT = "b[ext=mp4]/b"

MANIFEST_NAME = "downloaded.json"
COMBINED_METADATA = "metadata.json"
FAILED_DOWNLOADS = "failed_downloads.json"
FOLDER_README = "README.txt"

MARK_OK = "\u2713"     # ✓
MARK_FAIL = "\u2717"    # ✗
MARK_SKIP = "\u2192"    # →

console = Console(emoji=False, highlight=False)

CYAN = "bold cyan"
BLUE = "bold bright_blue"
PURPLE = "bold magenta"
GREEN = "bold green"
YELLOW = "bold yellow"
RED = "bold red"
DIM = "dim white"
BRIGHT = "bright_white"


# -------------------------------------------------------------------------
# Rich / UI helpers
# -------------------------------------------------------------------------


def _trunc(text: str, length: int = 72) -> str:
    text = str(text).replace("\n", " ").strip()
    return text if len(text) <= length else text[: length - 1] + "\u2026"


def _heading(title: str, style: str = CYAN) -> Panel:
    return Panel(
        Text(title.upper(), style=style, justify="center"),
        border_style=style,
        box=box.ROUNDED,
    )


def ok_line(msg: str) -> None:
    console.print(f"{MARK_OK} {msg}", style=GREEN)


def skip_line(msg: str) -> None:
    console.print(f"{MARK_SKIP} {msg}", style=YELLOW)


def err_line(msg: str) -> None:
    console.print(f"{MARK_FAIL} {msg}", style=RED)


def info_line(msg: str) -> None:
    console.print(msg, style=BRIGHT)


def dim_line(msg: str) -> None:
    console.print(msg, style=DIM)


_ART_SMALL = [
    " _  _ _  __  _____ ___ ___ __  __ ___ _  _   _   _      _____ ___   ___  _",
    "| \\| | |/ / |_   _| __| _ \\  \\/  |_ _| \\| | /_\\ | |    |_   _/ _ \\ / _ \\| |",
    "| .` | ' <    | | | _||   / |\\/| || || .` |/ _ \\| |__    | || (_) | (_) | |__",
    "|_|\\_|_|\\_\\   |_| |___|_|_\\_|  |_|___|_|\\_/_/ \\_\\____|   |_| \\___/ \\___/|____|",
]
_ART_MINI = [
    "       ____ _     ___           ____  _",
    "|\\ ||/  ||_|_)|\\/| | |\\ | /\\ |   |/ \\/ \\|",
    "| \\||\\  ||_| \\|  |_|_| \\|/--\\|_  |\\_/\\_/|_",
]


def show_startup_banner(ffmpeg_ok: bool, output_dir: Path, source: str) -> None:
    """Render the branded startup banner with a small status section."""
    art_lines = _ART_SMALL if (console.width or 80) >= 94 else _ART_MINI
    styles = [CYAN, BLUE, PURPLE, CYAN][: len(art_lines)]
    art = Text()
    for idx, (line, style) in enumerate(zip(art_lines, styles)):
        art.append(line.rstrip(), style=style)
        if idx < len(art_lines) - 1:
            art.append("\n")

    title = Text("YouTube Media Downloader", style=BRIGHT)
    tagline = Text("Search  \u2022  Download  \u2022  Organize  \u2022  Archive", style=DIM)

    status = Table.grid(padding=(0, 2))
    status.add_column(style=DIM, justify="left")
    status.add_column(justify="left")
    status.add_row("YT-DLP", Text(f"{MARK_OK} Ready", style=GREEN) if yt_dlp else Text(MARK_FAIL + " Missing", style=RED))
    if ffmpeg_ok:
        status.add_row("FFmpeg", Text(f"{MARK_OK} Available", style=GREEN))
    else:
        status.add_row("FFmpeg", Text("Warning - Not found", style=YELLOW))
    status.add_row("Source", Text(source.upper(), style=CYAN))
    status.add_row("Output", Text(str(output_dir), style=CYAN))

    body = Group(
        Align.center(art),
        Text(),
        Align.center(title),
        Align.center(tagline),
        Text(),
        Align.center(Panel(status, border_style="bright_black", padding=(0, 1))),
    )
    console.print(
        Panel(
            body,
            title=f"[{CYAN}]NK Terminal Tool[/]",
            subtitle=f"[{DIM}]NK YouTube Keyword Downloader[/]",
            border_style=BLUE,
            padding=(1, 2),
            box=box.ROUNDED,
        )
    )
    console.print()


def show_search_config(
    keyword: str,
    yt_limit: int,
    tg_limit: int,
    source: str,
    audio_only: bool,
    output_dir: Path,
    ffmpeg_ok: bool,
) -> None:
    """Display the search configuration panel before any searching."""
    table = Table.grid(padding=(0, 2))
    table.add_column(style=DIM, justify="left")
    table.add_column(style=CYAN)
    table.add_row("Keyword", keyword)
    table.add_row("Source", "YouTube" if source == "youtube" else "Telegram" if source == "telegram" else "YouTube + Telegram")

    limit_text = ""
    if source == "all":
        limit_text = f"YouTube {yt_limit}  /  Telegram {tg_limit}"
    elif source == "youtube":
        limit_text = str(yt_limit)
    else:
        limit_text = str(tg_limit)
    table.add_row("Limit", limit_text)
    table.add_row("Mode", Text("Audio only" if audio_only else "Video", style=YELLOW if audio_only else BRIGHT))
    out_text = str(output_dir)
    if source == "telegram":
        out_text += "/<keyword>/telegram"
    elif source == "all":
        out_text += "/<keyword>  (youtube + telegram)"
    table.add_row("Output", out_text)
    status_text = (
        Text(f"{MARK_OK} Available", style=GREEN)
        if ffmpeg_ok
        else Text("Limited", style=YELLOW)
    )
    table.add_row("FFmpeg", status_text)
    console.print(
        Panel(
            table,
            title="[bold cyan]Search Configuration[/]",
            border_style=CYAN,
            box=box.ROUNDED,
        )
    )
    console.print()


def show_ffmpeg_warning() -> None:
    """Show the FFmpeg availability warning panel."""
    body = (
        "Some features will be limited:\n\n"
        "\u2022  Video/audio merging\n"
        "\u2022  MP4 conversion\n"
        "\u2022  MP3 extraction\n\n"
        "Install FFmpeg and make sure it is available on your PATH."
    )
    console.print(
        Panel(
            Text(body, style=YELLOW),
            title="[yellow]\u26a0 FFmpeg Not Found[/]",
            border_style="yellow",
            box=box.ROUNDED,
        )
    )
    console.print()


def show_error(message: str, hint: Optional[str] = None) -> None:
    """Show a clear, readable Rich error panel without raw tracebacks."""
    body = Text(message, style=BRIGHT)
    if hint:
        body.append("\n\n" + hint, style=DIM)
    console.print(
        Panel(
            body,
            title=f"[{RED}]{MARK_FAIL} ERROR[/]",
            border_style="red",
            box=box.ROUNDED,
        )
    )


def show_download_card(position: int, total: int, title: str, subtitle: str, status: str) -> None:
    """Render a per-download information card."""
    table = Table.grid(padding=(0, 1))
    table.add_column(style=DIM, justify="right")
    table.add_column(style=BRIGHT)
    table.add_row("Title", _trunc(title, 66))
    if subtitle:
        table.add_row("", _trunc(subtitle, 66))

    panel_title = f"[{CYAN}][{position:02d}/{total:02d}] {status}[/]"
    border_style = "cyan"
    if status == "Skipped":
        border_style = "yellow"
    elif status == "Failed":
        border_style = "red"
    console.print(Panel(table, title=panel_title, border_style=border_style, box=box.ROUNDED))


def show_results_table(plugin: str, items: List[Dict[str, Any]]) -> None:
    """Display discovered Telegram (or other) results before downloading."""
    table = Table(
        title=f"[bold cyan]{plugin} Search Results[/]",
        border_style=CYAN,
        box=box.ROUNDED,
        header_style=BLUE,
    )
    table.add_column("#", justify="right", style=DIM, no_wrap=True)
    table.add_column("Title", style=BRIGHT, max_width=48, overflow="fold")
    table.add_column("Channel", style=CYAN, max_width=28, overflow="fold")
    table.add_column("Type", style=PURPLE)
    table.add_column("Size", justify="right", style=DIM)
    for index, item in enumerate(items, start=1):
        table.add_row(
            str(index),
            _trunc(item.get("title") or "Unknown", 48),
            _trunc(item.get("channel") or "Unknown", 28),
            (item.get("media_type") or "document").title(),
            item.get("size_display") or "",
        )
    console.print()
    console.print(table)
    console.print()


def show_summary(
    label: str,
    total: int,
    downloaded: int,
    skipped: int,
    failed: int,
    output_dir: Path,
) -> None:
    """Display the per-source download summary panel."""
    table = Table.grid(padding=(0, 4))
    table.add_column(style=DIM, justify="left")
    table.add_column(style=BRIGHT, justify="right")
    table.add_column(justify="left")
    table.add_row("Total Found", str(total), "")
    table.add_row("Downloaded", str(downloaded), Text(MARK_OK, style=GREEN))
    table.add_row("Skipped", str(skipped), Text(MARK_SKIP, style=YELLOW))
    table.add_row("Failed", str(failed), Text(MARK_FAIL, style=RED))
    table.add_row("", "", "")
    table.add_row("Output Folder", "", "")
    table.add_row(Text(str(output_dir), style=CYAN), "", "")
    console.print(
        Panel(
            table,
            title=f"[{CYAN}]{label} Download Summary[/]",
            border_style=CYAN,
            box=box.ROUNDED,
        )
    )
    console.print()


def show_final_screen(processed: int, downloaded: int, skipped: int, failed: int) -> None:
    """Show the final success (or warning) screen."""
    lines = [
        Align.center(Text(f"{processed} videos processed", style=BRIGHT)),
        Align.center(Text(f"{downloaded} successfully downloaded", style=GREEN)),
    ]
    if skipped:
        lines.append(Align.center(Text(f"{skipped} already downloaded", style=YELLOW)))
    if failed:
        lines.append(Align.center(Text(f"{failed} failed", style=RED)))
    if failed:
        console.print(
            Panel(
                Group(*lines),
                title="[yellow]\u26a0 DOWNLOAD SESSION COMPLETED WITH ERRORS[/]",
                subtitle=f"[{DIM}]See the summary above and the failed_downloads.json files[/]",
                border_style="yellow",
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )
    else:
        console.print(
            Panel(
                Group(
                    Align.center(Text(f"{MARK_OK} DOWNLOAD SESSION COMPLETE", style=GREEN, justify="center")),
                    Text(),
                    *lines,
                ),
                border_style="green",
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )
    console.print()


# -------------------------------------------------------------------------
# Path / filename helpers
# -------------------------------------------------------------------------


def sanitize_name(name: str, fallback: str = "download") -> str:
    """Return a filesystem-safe version of *name*.

    Removes characters that are illegal on common filesystems and collapses
    whitespace so the result can be used as a folder or file name.
    """
    name = unicodedata.normalize("NFKD", name)
    name = name.encode("ascii", "ignore").decode("ascii")
    name = re.sub(r'[\\/:*?"<>|#%&{}\[\]$!\'@+`=]', "", name)
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)
    name = re.sub(r"\s+", " ", name).strip().rstrip(". ")
    # Keep names at a sane length for path limits on Windows.
    name = name[:150].rstrip(". ")
    return name or fallback


def build_dirs(base_dir: Path, keyword: str) -> Dict[str, Path]:
    """Create and return the keyword-based YouTube output structure."""
    folder = base_dir / sanitize_name(keyword)
    videos = folder / "videos"
    metadata = folder / "metadata"
    videos.mkdir(parents=True, exist_ok=True)
    metadata.mkdir(parents=True, exist_ok=True)
    return {
        "base": folder,
        "videos": videos,
        "metadata": metadata,
        "manifest": folder / MANIFEST_NAME,
        "combined_metadata": folder / COMBINED_METADATA,
        "failed": folder / FAILED_DOWNLOADS,
        "readme": folder / FOLDER_README,
    }


def build_telegram_dirs(base_dir: Path, keyword: str) -> Dict[str, Path]:
    """Create and return the keyword-based Telegram output structure."""
    folder = base_dir / sanitize_name(keyword) / "telegram"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "metadata").mkdir(parents=True, exist_ok=True)
    return {
        "base": folder,
        "videos": folder / "videos",
        "audio": folder / "audio",
        "documents": folder / "documents",
        "images": folder / "images",
        "metadata": folder / "metadata",
        "manifest": folder / MANIFEST_NAME,
        "combined_metadata": folder / COMBINED_METADATA,
        "failed": folder / FAILED_DOWNLOADS,
    }


# -------------------------------------------------------------------------
# JSON helpers
# -------------------------------------------------------------------------


def read_json(path: Path, default: Any) -> Any:
    """Load JSON from ``path``, returning ``default`` if missing/invalid."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def write_json(path: Path, data: Any) -> None:
    """Atomically write JSON to ``path`` (write-then-rename)."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def load_manifest(path: Path) -> Dict[str, Dict[str, Any]]:
    """Load a map of already-downloaded items."""
    data = read_json(path, {})
    return data if isinstance(data, dict) else {}


# -------------------------------------------------------------------------
# Shared formatting helpers
# -------------------------------------------------------------------------


def simple_duration(seconds: Optional[int]) -> str:
    """Format a duration in seconds as ``HH:MM:SS`` (or ``MM:SS``)."""
    if not seconds:
        return "N/A"
    seconds = int(seconds)
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def simple_views(count: Optional[int]) -> str:
    """Format a view count in a compact, human-readable form."""
    if count is None:
        return "N/A"
    try:
        count = int(count)
    except (TypeError, ValueError):
        return "N/A"
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.1f}K"
    return str(count)


def _fmt_bytes(n: Optional[float]) -> str:
    if n is None:
        return ""
    try:
        n = float(n)
    except (TypeError, ValueError):
        return ""
    if n < 0:
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{int(n)}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return ""


def _fmt_duration(sec: Optional[float]) -> str:
    if not sec or sec < 0:
        return ""
    sec = int(sec)
    hours, rem = divmod(sec, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{minutes:02d}:{secs:02d}" if not hours else f"{hours}:{minutes:02d}:{secs:02d}"


def _fmt_speed(bps: Optional[float]) -> str:
    value = _fmt_bytes(bps)
    return f"{value}/s" if value else ""


class FileProgress:
    """A transient Rich progress bar fed by download progress callbacks."""

    def __init__(self, console: Console, description: str) -> None:
        self._console = console
        self._started = False
        self._finished = False
        self._progress = Progress(
            TextColumn("[bold cyan]{task.description}", justify="left"),
            BarColumn(bar_width=26),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("[dim]{task.fields[size]}", justify="right"),
            TextColumn("[green]{task.fields[speed]}"),
            TextColumn("[magenta]{task.fields[eta]}"),
            TimeElapsedColumn(),
            console=console,
            transient=True,
            expand=True,
        )
        self._task_id = self._progress.add_task(
            _trunc(description, 46), total=None, size="", speed="", eta=""
        )

    def start(self) -> None:
        if not self._started:
            self._progress.start()
            self._started = True

    def stop(self) -> None:
        if self._started and not self._finished:
            self._finished = True
            self._progress.stop()

    def update(self, downloaded: float, total: Optional[float], speed: Optional[float] = None, eta: Optional[float] = None) -> None:
        if not self._started or self._finished:
            return
        size = _fmt_bytes(downloaded)
        if total:
            size = f"{_fmt_bytes(downloaded)} / {_fmt_bytes(total)}"
        self._progress.update(
            self._task_id,
            total=total if total else None,
            completed=min(downloaded, total) if total else downloaded,
            size=size,
            speed=_fmt_speed(speed),
            eta=_fmt_duration(eta),
            refresh=True,
        )

    def ytdlp_hook(self, data: Dict[str, Any]) -> None:
        status = data.get("status")
        if status == "downloading":
            total = data.get("total_bytes") or data.get("total_bytes_estimate")
            self.update(
                data.get("downloaded_bytes") or 0,
                total,
                data.get("speed"),
                data.get("eta"),
            )
        elif status == "finished":
            total = data.get("total_bytes") or data.get("total_bytes_estimate")
            if total:
                self.update(total, total)
            self.stop()
        elif status == "error":
            self.stop()

    def telethon_callback(self) -> Callable[[int, int], None]:
        start_time = time.monotonic()
        last_time = start_time
        last_bytes = 0

        def callback(received: int, total: int) -> None:
            nonlocal last_time, last_bytes
            now = time.monotonic()
            dt = now - last_time
            speed = (received - last_bytes) / dt if dt > 0 else 0
            eta = (total - received) / speed if total and speed > 0 else None
            last_time = now
            last_bytes = received
            self.update(received, total, speed, eta)
            if total and received >= total:
                self.stop()

        return callback


# -------------------------------------------------------------------------
# YouTube search
# -------------------------------------------------------------------------


def ffmpeg_available() -> bool:
    """Return True when an ffmpeg binary can be found on PATH."""
    return shutil.which("ffmpeg") is not None


def search_youtube(keyword: str, limit: int) -> Optional[List[Dict[str, Any]]]:
    """Search YouTube and return a list of search results with basic info."""
    options: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,  # fast, list-only extraction for the search
        "ignoreerrors": True,  # one bad result must not kill the search
        "noplaylist": True,
        "playlistend": limit,
    }
    query = f"ytsearch{limit}:{keyword}"
    try:
        _require_ytdlp()
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(query, download=False)
    except Exception:
        return None  # caller decides how to report

    entries = (info.get("entries") or []) if info else []
    results: List[Dict[str, Any]] = []
    for position, entry in enumerate(entries, start=1):
        if not entry:
            continue
        video_id = entry.get("id")
        if not video_id:
            continue
        thumbnails = entry.get("thumbnails") or []
        results.append(
            {
                "search_position": position,
                "title": entry.get("title") or f"Video {position}",
                "video_id": video_id,
                "url": entry.get("url")
                or f"https://www.youtube.com/watch?v={video_id}",
                "channel": entry.get("channel"),
                "channel_url": entry.get("channel_url"),
                "upload_date": entry.get("upload_date"),
                "duration": entry.get("duration"),
                "view_count": entry.get("view_count"),
                "description": entry.get("description"),
                "thumbnail": entry.get("thumbnail")
                or (thumbnails[-1].get("url") if thumbnails else None),
            }
        )
    return results


def build_downloader_options(
    videos_dir: Path,
    format_spec: str,
    audio_only: bool,
    merge_mp4: bool,
    use_mp3: bool,
) -> Dict[str, Any]:
    """Build the yt-dlp option dict used for a single video download."""
    options: Dict[str, Any] = {
        "outtmpl": str(videos_dir / "%(title)s.%(ext)s"),
        "format": format_spec,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "updatetime": False,
        "retries": 3,
        "fragment_retries": 3,
    }
    if merge_mp4:
        # Merge separate video/audio streams into a single MP4 container.
        options["merge_output_format"] = "mp4"
    if use_mp3:
        options["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ]
    return options


def download_video(
    video: Dict[str, Any],
    videos_dir: Path,
    format_spec: str,
    audio_only: bool,
    has_ffmpeg: bool,
    position: int,
    total: int,
) -> Dict[str, Any]:
    """Download one video. Returns the full yt-dlp info dict on success."""
    merge_mp4 = not audio_only and has_ffmpeg and "+" in format_spec
    use_mp3 = audio_only and has_ffmpeg
    options = build_downloader_options(
        videos_dir, format_spec, audio_only, merge_mp4, use_mp3
    )
    pbar = FileProgress(console, f"[{position:02d}/{total:02d}] Downloading")
    options["progress_hooks"] = [pbar.ytdlp_hook]
    _require_ytdlp()
    pbar.start()
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(video["url"], download=True)
    finally:
        pbar.stop()
    return info or {}


def attempt_download(
    video: Dict[str, Any],
    videos_dir: Path,
    format_spec: str,
    audio_only: bool,
    has_ffmpeg: bool,
    position: int,
    total: int,
) -> tuple[Dict[str, Any] | None, str | None]:
    """Try to download ``video`` once, then retry once more on failure.

    Returns ``(info_dict, None)`` on success or ``(None, error_message)``.
    """
    attempts = 2
    last_error: Optional[str] = None
    for attempt in range(attempts):
        try:
            return (
                download_video(
                    video, videos_dir, format_spec, audio_only, has_ffmpeg, position, total
                ),
                None,
            )
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt + 1 < attempts:
                time.sleep(2)
    return None, last_error


# -------------------------------------------------------------------------
# YouTube metadata
# -------------------------------------------------------------------------


def build_metadata(
    video: Dict[str, Any],
    info: Optional[Dict[str, Any]],
    status: str,
    error: Optional[str] = None,
    download_file: Optional[str] = None,
) -> Dict[str, Any]:
    """Combine search-level info with the full per-video info dict."""
    source = info if info else video
    thumbnail = source.get("thumbnail")
    if not thumbnail:
        thumbnails = source.get("thumbnails") or []
        thumbnail = thumbnails[-1].get("url") if thumbnails else None
    return {
        "search_position": video.get("search_position"),
        "title": source.get("title") or video.get("title"),
        "url": source.get("webpage_url") or video.get("url"),
        "video_id": source.get("id") or video.get("video_id"),
        "channel": source.get("channel") or video.get("channel"),
        "channel_url": source.get("channel_url") or video.get("channel_url"),
        "upload_date": source.get("upload_date") or video.get("upload_date"),
        "duration": source.get("duration") or video.get("duration"),
        "duration_formatted": simple_duration(source.get("duration")),
        "view_count": source.get("view_count") or video.get("view_count"),
        "views_formatted": simple_views(source.get("view_count")),
        "description": source.get("description") or video.get("description"),
        "thumbnail": thumbnail or video.get("thumbnail"),
        "status": status,
        "error": error,
        "file": download_file,
    }


def write_per_video_metadata(metadata_dir: Path, position: int, data: Dict[str, Any]) -> None:
    """Save one JSON metadata file per search result, preserving order."""
    path = metadata_dir / f"video_{position:03d}.json"
    write_json(path, data)


def write_folder_readme(path: Path, keyword: str, summary: Dict[str, Any]) -> None:
    """Write a small human-readable readme inside the keyword folder."""
    lines = [
        "NK YouTube Keyword Downloader",
        "============================",
        "",
        f"Keyword:      {keyword}",
        f"Date:         {datetime.datetime.now().isoformat(timespec='seconds')}",
        f"Total found:  {summary['total']}",
        f"Downloaded:   {summary['downloaded']}",
        f"Skipped:      {summary['skipped']}",
        f"Failed:       {summary['failed']}",
        "",
        "Contents:",
        "  videos/            downloaded media files",
        "  metadata/          one JSON file per search result",
        "  metadata.json      combined metadata for every processed video",
        "  failed_downloads.json   details about videos that could not be saved",
        "  downloaded.json    manifest used to skip duplicates on re-runs",
        "",
        "Only download content you are authorized to download. Respect YouTube's",
        "Terms of Service and applicable copyright laws.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


# -------------------------------------------------------------------------
# YouTube workflow
# -------------------------------------------------------------------------


def run_youtube_source(
    keyword: str,
    limit: int,
    base_dir: Path,
    format_spec_arg: Optional[str],
    audio_only: bool,
    has_ffmpeg: bool,
) -> Dict[str, Any]:
    """Run the full YouTube source workflow. Returns result counts."""
    dirs = build_dirs(base_dir, keyword)

    with console.status(f'[cyan]Searching YouTube for "{keyword}"...', spinner="dots"):
        results = search_youtube(keyword, limit)
    console.print()
    if results is None:
        show_error(
            "Could not reach YouTube.",
            "Check your internet connection and try again.",
        )
        return {"ok": False, "downloaded": 0, "skipped": 0, "failed": 0, "total": 0}
    total = len(results)
    ok_line(f"Search completed - found {total} video{'' if total == 1 else 's'}")
    console.print()

    # Choose the effective yt-dlp format selector.
    if format_spec_arg:
        format_spec = format_spec_arg
    elif audio_only:
        format_spec = "bestaudio/best"
    elif has_ffmpeg:
        format_spec = DEFAULT_VIDEO_FORMAT
    else:
        format_spec = NO_FFMPEG_VIDEO_FORMAT

    manifest = load_manifest(dirs["manifest"])
    processed: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []
    downloaded_count = skipped_count = failed_count = 0

    for video in results:
        video_id = video["video_id"]
        position = video["search_position"]
        title = video["title"]

        if video_id in manifest:
            skipped_count += 1
            base_meta = build_metadata(video, None, "skipped")
            processed.append(base_meta)
            write_per_video_metadata(dirs["metadata"], position, base_meta)
            show_download_card(position, total, title, video.get("channel") or "", "Skipped")
            skip_line(f"Already downloaded: {_trunc(title, 60)}")
            console.print()
            continue

        show_download_card(position, total, title, video.get("channel") or "", "Downloading")

        info, error = attempt_download(
            video, dirs["videos"], format_spec, audio_only, has_ffmpeg, position, total
        )
        if error is not None or not info:
            failed_count += 1
            reason = error or "Unknown error"
            failed.append(
                {
                    "title": title,
                    "url": video["url"],
                    "video_id": video_id,
                    "error": reason,
                }
            )
            meta = build_metadata(video, info, "failed", error=reason)
            processed.append(meta)
            write_per_video_metadata(dirs["metadata"], position, meta)
            console.print(
                Panel(
                    Group(
                        Text(f"{MARK_FAIL} Download failed", style=RED),
                        Text(f"Reason: {reason}", style=DIM),
                    ),
                    border_style="red",
                    box=box.ROUNDED,
                    padding=(0, 1),
                    expand=False,
                )
            )
            console.print()
            continue

        downloaded_count += 1
        download_file = None
        requested = info.get("requested_downloads") or []
        if requested and isinstance(requested[0], dict):
            download_file = requested[0].get("filepath")
        else:
            guessed = (
                sanitize_name(title) + ".mp3" if audio_only and has_ffmpeg else ""
            )
            if guessed:
                download_file = str(dirs["videos"] / guessed)

        meta = build_metadata(video, info, "downloaded", download_file=download_file)
        processed.append(meta)
        write_per_video_metadata(dirs["metadata"], position, meta)
        manifest[video_id] = {
            "title": title,
            "file": download_file,
            "search_position": position,
        }
        write_json(dirs["manifest"], manifest)
        ok_line(f"Download completed: {_trunc(title, 60)}")
        console.print()

    combined = {
        "source": "youtube",
        "keyword": keyword,
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "format": format_spec,
        "audio_only": audio_only,
        "total": total,
        "downloaded": downloaded_count,
        "skipped": skipped_count,
        "failed": failed_count,
        "videos": processed,
    }
    write_json(dirs["combined_metadata"], combined)
    write_json(dirs["failed"], failed)
    write_folder_readme(
        dirs["readme"],
        keyword,
        {
            "total": total,
            "downloaded": downloaded_count,
            "skipped": skipped_count,
            "failed": failed_count,
        },
    )

    show_summary("YouTube", total, downloaded_count, skipped_count, failed_count, dirs["base"])
    return {
        "ok": True,
        "downloaded": downloaded_count,
        "skipped": skipped_count,
        "failed": failed_count,
        "total": total,
    }


# -------------------------------------------------------------------------
# Argument parsing
# -------------------------------------------------------------------------


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="media_finder.py",
        description=(
            "NK Terminal Tool\n"
            "YouTube Media Downloader\n"
            "\n"
            "Search YouTube and/or Telegram for a keyword and download\n"
            "the accessible matching media with full metadata."
        ),
        epilog=(
            "Examples:\n"
            '  python media_finder.py "Apostle Babs Adewumi"\n'
            '  python media_finder.py "Apostle Babs Adewumi" --source telegram\n'
            '  python media_finder.py "Apostle Babs Adewumi" --source telegram --type video\n'
            '  python media_finder.py "Apostle Babs Adewumi" --source all --limit 20\n'
            '  python media_finder.py "Apostle Babs Adewumi" --audio-only\n'
            '  python media_finder.py "Apostle Babs Adewumi" --output ./my-downloads'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("keyword", help="Search keyword")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=(
            "Maximum number of results to process "
            f"(default: YouTube {DEFAULT_YOUTUBE_LIMIT}, Telegram {DEFAULT_TELEGRAM_LIMIT})"
        ),
    )
    parser.add_argument(
        "--output",
        default="downloads",
        help="Base output directory (default: downloads)",
    )
    parser.add_argument(
        "--source",
        choices=["youtube", "telegram", "all"],
        default="youtube",
        help="Which source to search (default: youtube)",
    )
    parser.add_argument(
        "--type",
        dest="media_type",
        choices=["video", "audio", "document", "image", "all"],
        default="all",
        help="Telegram media type filter (default: all)",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Auto-download all Telegram results without asking for confirmation",
    )
    parser.add_argument(
        "--format",
        dest="format_spec",
        default=None,
        help="yt-dlp format selector for YouTube (overrides the automatic selection)",
    )
    parser.add_argument(
        "--audio-only",
        action="store_true",
        help="Download audio only for YouTube, converted to MP3 when FFmpeg is available",
    )
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    return args


# -------------------------------------------------------------------------
# Main workflow
# -------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    keyword = args.keyword.strip()
    if not keyword:
        show_error("The search keyword cannot be empty.")
        return 1

    base_dir = Path(args.output)
    has_ffmpeg = ffmpeg_available()

    show_startup_banner(has_ffmpeg, base_dir, args.source)
    if not has_ffmpeg:
        show_ffmpeg_warning()

    if yt_dlp is None and args.source in ("youtube", "all"):
        try:
            _require_ytdlp()
        except RuntimeError as exc:
            show_error(str(exc))
            return 1

    sources = ["youtube", "telegram"] if args.source == "all" else [args.source]
    yt_limit = args.limit if args.limit is not None else DEFAULT_YOUTUBE_LIMIT
    tg_limit = args.limit if args.limit is not None else DEFAULT_TELEGRAM_LIMIT

    show_search_config(
        keyword,
        yt_limit,
        tg_limit,
        args.source,
        args.audio_only,
        base_dir,
        has_ffmpeg,
    )

    total_downloaded = total_skipped = total_failed = total_processed = 0
    for source in sources:
        try:
            if source == "youtube":
                counts = run_youtube_source(
                    keyword, yt_limit, base_dir, args.format_spec, args.audio_only, has_ffmpeg
                )
            else:
                from src.telegram import run_telegram_source  # lazy, avoids import cycle

                counts = run_telegram_source(
                    keyword, tg_limit, args.media_type, base_dir, args.yes, has_ffmpeg
                )
        except KeyboardInterrupt:
            console.print()
            console.print(
                Panel(
                    Align.center(
                        Text(
                            "Download session interrupted. Already downloaded files "
                            "will be resumed on the next run.",
                            style=YELLOW,
                            justify="center",
                        )
                    ),
                    border_style="yellow",
                    box=box.ROUNDED,
                )
            )
            return 130

        total_downloaded += counts.get("downloaded", 0)
        total_skipped += counts.get("skipped", 0)
        total_failed += counts.get("failed", 0)
        total_processed += counts.get("total", 0)
        if not counts.get("ok", True):
            total_failed += 1

    show_final_screen(
        total_processed,
        total_downloaded,
        total_skipped,
        total_failed,
    )
    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())