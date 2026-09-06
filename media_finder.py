#!/usr/bin/env python3
"""NK YouTube Keyword Downloader / media_finder.

Search YouTube and/or Telegram for media matching a keyword, download the
accessible matches (video or mp3) and save their metadata straight from
the terminal.

Examples:
    python media_finder.py "Apostle Babs Adewumi"
    python media_finder.py "Apostle Babs Adewumi" --source youtube
    python media_finder.py "Apostle Babs Adewumi" --source telegram --limit 20
    python media_finder.py "Apostle Babs Adewumi" --source telegram --type video
    python media_finder.py "Apostle Babs Adewumi" --source all
    python media_finder.py "Apostle Babs Adewumi" --mp3-only
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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

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
    from rich.prompt import Prompt
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

# Interactive video quality presets -> yt-dlp format selector suffix height.
VIDEO_QUALITIES = ["best", "2160", "1440", "1080", "720", "480", "360"]
# mp3 quality presets offered by the interactive menu (0 = best available).
MP3_QUALITIES = [0, 320, 256, 192, 128]


def build_video_format(quality: str, has_ffmpeg: bool) -> str:
    """Build a yt-dlp format selector for a chosen interactive video quality.

    ``quality`` is one of ``"best"`` / ``"2160"`` / ``"1440"`` / ``"1080"`` /
    ``"720"`` / ``"480"`` / ``"360"``. The returned selector prefers MP4 at the
    requested max height (merged with the best mp3 stream when FFmpeg is
    available) and degrades to a single combined MP4 otherwise. The default
    ``"1080"`` maps to the legacy default selectors verbatim.
    """
    if not quality:
        quality = "1080"
    if quality == "best":
        return "bv*+ba/b" if has_ffmpeg else "b"
    if quality == "1080":
        return DEFAULT_VIDEO_FORMAT if has_ffmpeg else NO_FFMPEG_VIDEO_FORMAT
    if has_ffmpeg:
        return f"bv*[height<={quality}][ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b"
    return f"b[height<={quality}][ext=mp4]/b[ext=mp4]/b"

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
    mp3_only: bool,
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
        yt_label = "All" if yt_limit == 0 else str(yt_limit)
        tg_label = "All" if tg_limit == 0 else str(tg_limit)
        limit_text = f"YouTube {yt_label}  /  Telegram {tg_label}"
    elif source == "youtube":
        limit_text = "All" if yt_limit == 0 else str(yt_limit)
    else:
        limit_text = "All" if tg_limit == 0 else str(tg_limit)
    table.add_row("Limit", limit_text)
    table.add_row("Mode", Text("mp3 only" if mp3_only else "Video", style=YELLOW if mp3_only else BRIGHT))
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
        "\u2022  Video/mp3 merging\n"
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
    size_bytes: int = 0,
) -> None:
    """Display the per-source download statistics (ab.md DOWNLOAD SUMMARY).

    Rendered as a compact box matching the layout in ab.md: two-space
    indent, right-aligned values, a per-stat mark, an optional downloaded
    size row, and the output folder at the bottom.
    """
    grid = Table.grid(padding=(0, 3))
    grid.add_column(style=DIM, justify="left")
    grid.add_column(style=BRIGHT, justify="right")
    grid.add_column(justify="left")
    grid.add_row("Total Found", str(total), "")
    grid.add_row("Downloaded", str(downloaded), Text(MARK_OK, style=GREEN))
    grid.add_row("Skipped", str(skipped), Text(MARK_SKIP, style=YELLOW))
    grid.add_row("Failed", str(failed), Text(MARK_FAIL, style=RED))
    if size_bytes > 0:
        grid.add_row(
            "Downloaded Size",
            _fmt_bytes(size_bytes),
            Text(MARK_OK, style=GREEN),
        )
    grid.add_row("", "", "")
    grid.add_row("Output Folder", "", "")
    grid.add_row(Text(str(output_dir), style=CYAN), "", "")
    console.print(
        Panel(
            grid,
            title=f"[bold cyan]{label} Download Summary[/]",
            border_style=CYAN,
            box=box.ROUNDED,
            width=54,
            padding=(1, 2),
        )
    )
    console.print()


def show_final_screen(
    processed: int,
    downloaded: int,
    skipped: int,
    failed: int,
    size_bytes: int = 0,
) -> None:
    """Show the final success (or warning) screen (ab.md SUCCESS SCREEN).

    Green success box with the check-marked heading and left-indented
    result lines (matching the ab.md layout); a yellow warning box with
    the failing count is used instead when any download failed. The total
    downloaded size (MB/GB) is included when known.
    """
    pad = "       "  # left indent matching the ab.md mock-up
    if size_bytes > 0:
        size_line = Text(f"{pad}{_fmt_bytes(size_bytes)} downloaded", style=CYAN)
    else:
        size_line = Text("")
    if failed:
        body: List[Text] = [
            Text(f"{pad}{MARK_FAIL} DOWNLOAD SESSION COMPLETED WITH ERRORS", style=RED),
            Text(""),
            Text(f"{pad}{processed} videos processed", style=BRIGHT),
            Text(f"{pad}{downloaded} successfully downloaded", style=GREEN),
        ]
        if skipped:
            body.append(Text(f"{pad}{skipped} already downloaded", style=YELLOW))
        body.append(Text(f"{pad}{failed} failed", style=RED))
        body.append(size_line)
        body.append(Text(""))
        console.print(
            Panel(
                Group(*body),
                title=f"[yellow]{MARK_FAIL} PROBLEMS DETECTED[/]",
                border_style="yellow",
                box=box.ROUNDED,
                width=54,
                padding=(1, 2),
            )
        )
    else:
        body = [
            Text(f"{pad}{MARK_OK} DOWNLOAD SESSION COMPLETE", style=GREEN),
            Text(""),
            Text(f"{pad}{processed} videos processed", style=BRIGHT),
            Text(f"{pad}{downloaded} successfully downloaded", style=GREEN),
        ]
        if skipped:
            body.append(Text(f"{pad}{skipped} already downloaded", style=YELLOW))
        body.append(size_line)
        body.append(Text(""))
        console.print(
            Panel(
                Group(*body),
                border_style="green",
                box=box.ROUNDED,
                width=54,
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
        "mp3": folder / "mp3",
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


def _safe_file_size(path: Optional[Union[str, Path]]) -> int:
    """Return the file size in bytes (0 when missing or unreadable)."""
    if not path:
        return 0
    try:
        return max(int(Path(path).stat().st_size), 0)
    except (OSError, TypeError, ValueError):
        return 0


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
    search_limit = limit
    if search_limit <= 0:
        search_limit = 1000  # fetch as many matching files as YouTube will return
    options: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,  # fast, list-only extraction for the search
        "ignoreerrors": True,  # one bad result must not kill the search
        "noplaylist": True,
        "playlistend": search_limit,
        "playlist_items": f"1-{search_limit}",
    }
    query = f"ytsearch{search_limit}:{keyword}"
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
    mp3_only: bool,
    merge_mp4: bool,
    use_mp3: bool,
    mp3_codec: str = "mp3",
    mp3_quality: str = "192",
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
        # Merge separate video/mp3 streams into a single MP4 container.
        options["merge_output_format"] = "mp4"
    if use_mp3:
        options["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": mp3_codec,
                "preferredquality": mp3_quality,
            }
        ]
    return options


def download_video(
    video: Dict[str, Any],
    videos_dir: Path,
    format_spec: str,
    mp3_only: bool,
    has_ffmpeg: bool,
    position: int,
    total: int,
    mp3_codec: str = "mp3",
    mp3_quality: str = "192",
) -> Dict[str, Any]:
    """Download one video. Returns the full yt-dlp info dict on success."""
    merge_mp4 = not mp3_only and has_ffmpeg and "+" in format_spec
    use_mp3 = mp3_only and has_ffmpeg and bool(mp3_codec)
    options = build_downloader_options(
        videos_dir,
        format_spec,
        mp3_only,
        merge_mp4,
        use_mp3,
        mp3_codec=mp3_codec,
        mp3_quality=mp3_quality,
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
    mp3_only: bool,
    has_ffmpeg: bool,
    position: int,
    total: int,
    mp3_codec: str = "mp3",
    mp3_quality: str = "192",
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
                    video,
                    videos_dir,
                    format_spec,
                    mp3_only,
                    has_ffmpeg,
                    position,
                    total,
                    mp3_codec=mp3_codec,
                    mp3_quality=mp3_quality,
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
    mp3_only: bool,
    has_ffmpeg: bool,
    skip_manifest: bool = False,
    preselected_results: Optional[List[Dict[str, Any]]] = None,
    video_quality: str = "1080",
    mp3_codec: str = "mp3",
    mp3_quality: str = "192",
) -> Dict[str, Any]:
    """Run the full YouTube source workflow. Returns result counts.

    When ``skip_manifest`` is True, previously-downloaded videos are processed
    again instead of being skipped. This is used internally by the interactive
    "Both" (video + mp3) mode so a second mp3 pass can download alongside videos
    that were just downloaded by the first pass.

    When ``preselected_results`` is provided, the search is skipped and that
    exact set of results is downloaded in order. This lets the interactive flow
    present a search once and reuse the user's selection across the video and
    mp3 passes of "Both" mode.

    ``video_quality`` is a preset height ("best"/"2160"/.../"360") used to build
    the video format selector. ``mp3_codec`` ("mp3"/"m4a") and ``mp3_quality``
    (a bitrate like "192"/"320" or "0" for best) control the mp3 postprocessor.
    """
    dirs = build_dirs(base_dir, keyword)

    if preselected_results is None:
        with console.status(f'[cyan]Searching YouTube for "{keyword}"...', spinner="dots"):
            results = search_youtube(keyword, limit)
        console.print()
        if results is None:
            show_error(
                "Could not reach YouTube.",
                "Check your internet connection and try again.",
            )
            return {"ok": False, "downloaded": 0, "skipped": 0, "failed": 0, "total": 0, "size_bytes": 0}
    else:
        results = list(preselected_results)

    total = len(results)
    if preselected_results is None:
        ok_line(f"Search completed - found {total} video{'' if total == 1 else 's'}")
        console.print()

    # Choose the effective yt-dlp format selector.
    if format_spec_arg:
        format_spec = format_spec_arg
        effective_mp3_codec = mp3_codec
    elif mp3_only:
        format_spec = "bestaudio/best"
        effective_mp3_codec = mp3_codec if has_ffmpeg else ""
    else:
        effective_mp3_codec = mp3_codec
        format_spec = build_video_format(video_quality, has_ffmpeg)

    manifest = load_manifest(dirs["manifest"])
    processed: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []
    downloaded_count = skipped_count = failed_count = 0
    size_bytes = 0

    for video in results:
        video_id = video["video_id"]
        position = video["search_position"]
        title = video["title"]

        if not skip_manifest and video_id in manifest:
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
            video,
            dirs["videos"],
            format_spec,
            mp3_only,
            has_ffmpeg,
            position,
            total,
            mp3_codec=effective_mp3_codec or "mp3",
            mp3_quality=mp3_quality,
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
                sanitize_name(title) + ".mp3" if mp3_only and has_ffmpeg else ""
            )
            if guessed:
                download_file = str(dirs["videos"] / guessed)
        size_bytes += _safe_file_size(download_file)

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
        "mp3_only": mp3_only,
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

    show_summary(
        "YouTube",
        total,
        downloaded_count,
        skipped_count,
        failed_count,
        dirs["base"],
        size_bytes=size_bytes,
    )
    return {
        "ok": True,
        "downloaded": downloaded_count,
        "skipped": skipped_count,
        "failed": failed_count,
        "total": total,
        "size_bytes": size_bytes,
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
            "  python media_finder.py                  # interactive platform selection menu\n"
            '  python media_finder.py "Apostle Babs Adewumi"\n'
            '  python media_finder.py "Apostle Babs Adewumi" --source telegram\n'
            '  python media_finder.py "Apostle Babs Adewumi" --source telegram --type video\n'
            '  python media_finder.py "Apostle Babs Adewumi" --source all --limit 20\n'
            '  python media_finder.py "Apostle Babs Adewumi" --mp3-only\n'
            '  python media_finder.py "Apostle Babs Adewumi" --output ./my-downloads'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "keyword",
        nargs="?",
        default=None,
        help=(
            "Search keyword. When omitted, the interactive platform-selection "
            "menu is shown (use --interactive to show it even with a keyword)."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=(
            "Maximum number of results to process. Use 0 to fetch ALL matching "
            f"files (default: YouTube {DEFAULT_YOUTUBE_LIMIT}, Telegram {DEFAULT_TELEGRAM_LIMIT})"
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
        choices=["video", "mp3", "document", "image", "all"],
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
        "--mp3-only",
        action="store_true",
        help="Download mp3 only for YouTube, converted to MP3 when FFmpeg is available",
    )
    parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Show the interactive platform-selection menu even when a keyword is given",
    )
    parser.add_argument(
        "--url",
        default=None,
        help="Download a single YouTube video by its URL without interactive prompts",
    )
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 0:
        parser.error("--limit must be 0 (all) or at least 1")
    return args


# -------------------------------------------------------------------------
# Interactive platform-selection (routing) mode
# -------------------------------------------------------------------------


@dataclass
class InteractiveConfig:
    """Configuration collected from the interactive platform-selection flow."""

    platforms: List[str] = field(default_factory=list)  # "youtube" | "telegram"
    keyword: str = ""
    limit: Optional[int] = None
    yt_mode: str = "video"       # "video" | "mp3" | "both"
    yt_video_quality: str = "1080"  # "best" | "2160" | "1440" | "1080" | "720" | "480" | "360"
    mp3_codec: str = "mp3"       # "" = keep original (no conversion)
    mp3_quality: str = "192"     # bitrate e.g. "192"/"320"; "0" = best available
    tg_media_type: str = "all"   # "video" | "mp3" | "document" | "all"
    output_dir: Optional[Path] = None
    format_spec: Optional[str] = None
    tg_auto: bool = True


def _require_terminal() -> bool:
    """Return True when the terminal can actually show interactive prompts."""
    if console.is_terminal and sys.stdin.isatty():
        return True
    show_error(
        "Interactive mode needs a real terminal.",
        "Launch the tool in an interactive terminal, or pass a keyword "
        'directly (e.g.  python media_finder.py "Apostle Babs Adewumi").',
    )
    return False


def _ask_text(message: str, default: str = "", allow_empty: bool = False) -> str:
    """Ask for free text, re-prompting until a value is given (unless empty is OK)."""
    while True:
        try:
            raw = Prompt.ask(
                message, default=default.strip() or None, console=console
            )
        except (EOFError, KeyboardInterrupt):
            raise
        raw = (raw or "").strip()
        if raw or allow_empty:
            return raw
        err_line("This value cannot be empty.")


def _ask_int(
    message: str,
    default: int,
    minimum: int = 1,
    maximum: int = 100_000,
) -> int:
    """Ask for a whole number in ``[minimum, maximum]``, re-prompting until valid."""
    while True:
        try:
            raw = Prompt.ask(message, default=str(default), console=console)
        except (EOFError, KeyboardInterrupt):
            raise
        raw = (raw or "").strip()
        try:
            value = int(raw)
        except (TypeError, ValueError):
            err_line(f"Please enter a whole number between {minimum} and {maximum}.")
            continue
        if minimum <= value <= maximum:
            return value
        err_line(f"Please enter a number between {minimum} and {maximum}.")


def _ask_choice(message: str, options: List[str]) -> int:
    """Print a numbered menu and return the chosen 1-based index."""
    for index, option in enumerate(options, start=1):
        row = Text()
        row.append("  [", style=DIM)
        row.append(str(index), style=CYAN)
        row.append("] ", style=DIM)
        row.append(option, style=BRIGHT)
        console.print(row)
    choice = _ask_int(message, 1, 1, len(options))
    console.print()
    return choice


def _prompt_mp3_options(cfg: InteractiveConfig) -> None:
    """Ask the mp3 format/codec and bitrate options."""
    console.print(Text("mp3 format:", style=BRIGHT))
    options = ["MP3", "M4A", "Original (no conversion)"]
    codec = {1: "mp3", 2: "m4a", 3: ""}[_ask_choice("Enter choice:", options)]
    cfg.mp3_codec = codec

    console.print(Text("mp3 quality:", style=BRIGHT))
    console.print(Text("  0 = best available", style=DIM))
    quality_choice = _ask_int(
        "Quality (0 for best, or 128/192/256/320 kbps)",
        0 if cfg.mp3_quality == "0" else int(cfg.mp3_quality or "192"),
        minimum=0,
        maximum=320,
    )
    if codec:
        cfg.mp3_quality = str(quality_choice) if quality_choice in (128, 192, 256, 320) else "0"
    else:
        cfg.mp3_quality = "0"


def _prompt_video_quality(cfg: InteractiveConfig) -> None:
    """Ask the YouTube video quality preset."""
    console.print(Text("Video quality:", style=BRIGHT))
    quality_labels = {
        "best": "Best available",
        "2160": "2160p / 4K",
        "1440": "1440p",
        "1080": "1080p",
        "720": "720p",
        "480": "480p",
        "360": "360p",
    }
    options = [quality_labels[q] for q in VIDEO_QUALITIES]
    chosen = _ask_choice("Enter choice:", options)
    cfg.yt_video_quality = VIDEO_QUALITIES[chosen - 1]


def _prompt_youtube_specific(cfg: InteractiveConfig) -> None:
    """Ask the YouTube-only options (download mode, quality, mp3 settings)."""
    console.print(Text("Download mode:", style=BRIGHT))
    options = ["Video", "mp3 only", "Both (video + mp3)"]
    cfg.yt_mode = {1: "video", 2: "mp3", 3: "both"}[
        _ask_choice("Enter choice:", options)
    ]
    if cfg.yt_mode in ("mp3", "both"):
        _prompt_mp3_options(cfg)
    if cfg.yt_mode in ("video", "both"):
        _prompt_video_quality(cfg)
    cfg.format_spec = (
        _ask_text(
            "yt-dlp format selector (Enter for automatic)",
            cfg.format_spec or "",
            allow_empty=True,
        )
        or None
    )


def _prompt_telegram_specific(cfg: InteractiveConfig) -> None:
    """Ask the Telegram-only options (existing media-type and --yes flags)."""
    console.print(Text("Media type:", style=BRIGHT))
    options = ["Video", "mp3", "Documents", "All"]
    cfg.tg_media_type = {1: "video", 2: "mp3", 3: "document", 4: "all"}[
        _ask_choice("Enter choice:", options)
    ]
    console.print(Text("Download confirmation:", style=BRIGHT))
    choice = _ask_choice(
        "Choose:",
        ["Auto-download everything found", "Ask before starting downloads"],
    )
    cfg.tg_auto = choice == 1


def _configure_youtube(cfg: InteractiveConfig) -> None:
    """Interactive YouTube configuration flow."""
    console.print(_heading("YouTube Configuration", CYAN))
    console.print()
    _prompt_keyword(cfg)
    cfg.limit = _ask_int(
        "Number of results (0 = fetch ALL matching files)",
        cfg.limit if cfg.limit else DEFAULT_YOUTUBE_LIMIT,
        minimum=0,
    )
    _prompt_youtube_specific(cfg)


def _configure_telegram(cfg: InteractiveConfig) -> None:
    """Interactive Telegram configuration flow."""
    console.print(_heading("Telegram Configuration", CYAN))
    console.print()
    _prompt_keyword(cfg)
    cfg.limit = _ask_int(
        "Number of results (0 = fetch ALL matching files)",
        cfg.limit if cfg.limit else DEFAULT_TELEGRAM_LIMIT,
        minimum=0,
    )
    _prompt_telegram_specific(cfg)


def _configure_both(cfg: InteractiveConfig) -> None:
    """Shared configuration flow used when both platforms are selected."""
    console.print(_heading("Search Configuration", CYAN))
    console.print()
    _prompt_keyword(cfg)
    cfg.limit = _ask_int(
        "Result limit (0 = fetch ALL matching files for each platform)",
        cfg.limit if cfg.limit else DEFAULT_TELEGRAM_LIMIT,
        minimum=0,
    )
    console.print(
        Text(
            f"Platforms:   {MARK_OK} YouTube    {MARK_OK} Telegram",
            style=GREEN,
        )
    )
    console.print()
    console.print(Text("Platform-specific options", style=CYAN))
    console.print()
    console.print(Text("YouTube", style=BRIGHT))
    _prompt_youtube_specific(cfg)
    console.print()
    console.print(Text("Telegram", style=BRIGHT))
    _prompt_telegram_specific(cfg)


def _prompt_keyword(cfg: InteractiveConfig) -> None:
    """Ask (or re-ask, pre-filled) for the search keyword."""
    cfg.keyword = _ask_text("Enter search keyword", cfg.keyword)


def _prompt_output_dir(cfg: InteractiveConfig) -> None:
    """Ask for the base output directory (default: downloads)."""
    default = str(cfg.output_dir or Path("downloads"))
    raw = _ask_text("Output directory (Enter for default)", default, allow_empty=True)
    cfg.output_dir = Path(raw.strip() or "downloads")


def _configure(cfg: InteractiveConfig) -> None:
    """Dispatch to the configuration flow matching the chosen platforms."""
    if cfg.platforms == ["youtube"]:
        _configure_youtube(cfg)
    elif cfg.platforms == ["telegram"]:
        _configure_telegram(cfg)
    else:
        _configure_both(cfg)
    _prompt_output_dir(cfg)


def show_platform_menu() -> str:
    """Render the platform-selection menu.

    Returns one of ``"youtube"``, ``"telegram"``, ``"all"``, ``"url"``
    or ``"exit"``.
    """
    console.print(_heading("Select Download Source", CYAN))
    console.print()
    console.print(
        Text(
            "Search and download from a platform, download by link, or combine platforms.",
            style=DIM,
        )
    )
    console.print()
    options = [
        "YouTube (search by keyword)",
        "Telegram",
        "Both YouTube & Telegram",
        "Download by YouTube Link",
        "Exit",
    ]
    choice = _ask_choice("Enter your choice:", options)
    return {
        1: "youtube",
        2: "telegram",
        3: "all",
        4: "url",
        5: "exit",
    }[choice]


def _platform_label(platform: str) -> str:
    return {"youtube": "YouTube", "telegram": "Telegram"}.get(platform, platform.title())


def show_download_summary(cfg: InteractiveConfig) -> int:
    """Show the final configuration summary; returns 1=start, 2=edit, 3=cancel."""
    yt_label = {"video": "Video", "mp3": "mp3 Only", "both": "Video + mp3"}[cfg.yt_mode]
    tg_label = {
        "video": "Video",
        "mp3": "mp3",
        "document": "Documents",
        "all": "All",
    }[cfg.tg_media_type]

    lines: List[Text] = []

    def add(label: str, value: str = "", indent: bool = False) -> None:
        pad = "  " if indent else ""
        if value:
            row = Text()
            row.append(pad + label.ljust(13), style=DIM)
            row.append(value, style=BRIGHT)
            lines.append(row)
        else:
            lines.append(Text(pad + label, style=CYAN))

    add("Keyword", cfg.keyword)
    add(
        "Platforms",
        "YouTube + Telegram"
        if len(cfg.platforms) == 2
        else _platform_label(cfg.platforms[0]),
    )
    limit_label = "All" if cfg.limit == 0 else str(cfg.limit)
    add("Result Limit", limit_label)
    lines.append(Text())
    if "youtube" in cfg.platforms:
        quality_label = {
            "best": "Best available",
            "2160": "2160p / 4K",
            "1440": "1440p",
            "1080": "1080p",
            "720": "720p",
            "480": "480p",
            "360": "360p",
        }.get(cfg.yt_video_quality, cfg.yt_video_quality)
        add("YouTube")
        add("Mode", yt_label, indent=True)
        if cfg.yt_mode in ("video", "both"):
            add("Quality", quality_label, indent=True)
        if cfg.yt_mode in ("mp3", "both"):
            mp3_label = {
                "mp3": "MP3",
                "m4a": "M4A",
                "": "Original",
            }.get(cfg.mp3_codec, cfg.mp3_codec)
            q = "Best" if cfg.mp3_quality == "0" else f"{cfg.mp3_quality} kbps"
            add("mp3", f"{mp3_label} / {q}", indent=True)
    if "telegram" in cfg.platforms:
        add("Telegram")
        add("Media", tg_label, indent=True)
    add("Output", str(cfg.output_dir or "downloads"))

    console.print()
    console.print(
        Panel(
            Group(*lines),
            title="[bold cyan]DOWNLOAD SUMMARY[/]",
            border_style=CYAN,
            box=box.DOUBLE,
            padding=(1, 2),
        )
    )
    console.print()
    console.print("  [1] Start Download")
    console.print("  [2] Edit Settings")
    console.print("  [3] Cancel")
    console.print()
    return _ask_int("Enter choice:", 1, 1, 3)


def _merge_counts(first: Dict[str, Any], second: Dict[str, Any]) -> Dict[str, Any]:
    """Combine counts from the two passes of YouTube 'Both' mode."""
    return {
        "ok": bool(first.get("ok", True) and second.get("ok", True)),
        "downloaded": int(first.get("downloaded", 0))
        + int(second.get("downloaded", 0)),
        "skipped": int(first.get("skipped", 0)),
        "failed": int(first.get("failed", 0)) + int(second.get("failed", 0)),
        "total": max(int(first.get("total", 0)), int(second.get("total", 0))),
        "size_bytes": int(first.get("size_bytes", 0))
        + int(second.get("size_bytes", 0)),
    }


def _show_yt_results_table(keyword: str, results: List[Dict[str, Any]]) -> None:
    """Render a numbered table of YouTube search results."""
    table = Table(
        title=f"[bold cyan]YouTube Search Results ({len(results)}) - {keyword}[/]",
        border_style=CYAN,
        box=box.ROUNDED,
        header_style=BLUE,
    )
    table.add_column("#", justify="right", style=DIM, no_wrap=True)
    table.add_column("Title", style=BRIGHT, max_width=46, overflow="fold")
    table.add_column("Channel", style=CYAN, max_width=26, overflow="fold")
    table.add_column("Duration", style=PURPLE)
    table.add_column("Views", justify="right", style=DIM)
    for index, item in enumerate(results, start=1):
        table.add_row(
            str(index),
            _trunc(item.get("title") or "Unknown", 46),
            _trunc(item.get("channel") or "Unknown", 26),
            simple_duration(item.get("duration")),
            simple_views(item.get("view_count")),
        )
    console.print()
    console.print(table)
    console.print()


def _parse_number_list(raw: str, maximum: int) -> List[int]:
    """Parse a user-supplied list like ``1,3,5-8`` into sorted, valid 1-indexed numbers."""
    selected: List[int] = []
    raw = re.sub(r"\s+", "", raw or "")
    if not raw:
        return selected
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            try:
                start_s, end_s = part.split("-", 1)
                start, end = int(start_s), int(end_s)
            except (TypeError, ValueError):
                continue
            if start > end:
                start, end = end, start
            selected.extend(range(max(1, start), min(end, maximum) + 1))
        else:
            try:
                value = int(part)
            except (TypeError, ValueError):
                continue
            if 1 <= value <= maximum:
                selected.append(value)
    return sorted(set(selected))


def _select_youtube_results(
    cfg: InteractiveConfig,
) -> Optional[List[Dict[str, Any]]]:
    """Search YouTube once and let the user pick which results to download.

    Returns the selected subset in search order, or ``None`` when there are no
    results (or the user chose to cancel). Raising on the Search Configuration
    being edited again is handled by the caller.
    """
    with console.status(
        f'[cyan]Searching YouTube for "{cfg.keyword}"...', spinner="dots"
    ):
        results = search_youtube(cfg.keyword, cfg.limit)
    console.print()
    if results is None:
        show_error(
            "Could not reach YouTube.",
            "Check your internet connection and try again.",
        )
        return None
    if not results:
        err_line("No matching videos were found on YouTube.")
        return None

    _show_yt_results_table(cfg.keyword, results)

    menu = _ask_choice(
        "How do you want to choose what to download?",
        ["Fetch ALL matching files", "Choose specific numbers", "Cancel"],
    )
    if menu == 1:
        return results
    if menu == 3:
        return None

    while True:
        raw = _ask_text("Enter result numbers (e.g. 1,3,5-8)", allow_empty=False)
        selected_indexes = _parse_number_list(raw, len(results))
        if selected_indexes:
            return [results[i - 1] for i in selected_indexes]
        err_line("No valid numbers entered. Please try again.")


def _run_youtube_interactive(
    cfg: InteractiveConfig,
    base_dir: Path,
    has_ffmpeg: bool,
) -> tuple[bool, Dict[str, Any]]:
    """Run the configured YouTube source, supporting the 'Both' mode.

    Returns ``(cancelled, counts)`` where ``cancelled`` is True when the user
    bailed out of the result selection.
    """
    console.print(_heading("YouTube Downloads", CYAN))
    selected = _select_youtube_results(cfg)
    if selected is None:
        skip_line("No videos selected to download.")
        return True, {"ok": True, "downloaded": 0, "skipped": 0, "failed": 0, "total": 0}
    if not selected:
        return True, {"ok": True, "downloaded": 0, "skipped": 0, "failed": 0, "total": 0}

    if cfg.yt_mode == "both":
        video_counts = run_youtube_source(
            cfg.keyword,
            cfg.limit,
            base_dir,
            cfg.format_spec,
            False,
            has_ffmpeg,
            preselected_results=selected,
            video_quality=cfg.yt_video_quality,
        )
        mp3_counts = run_youtube_source(
            cfg.keyword,
            cfg.limit,
            base_dir,
            cfg.format_spec,
            True,
            has_ffmpeg,
            skip_manifest=True,
            preselected_results=selected,
            mp3_codec=cfg.mp3_codec,
            mp3_quality=cfg.mp3_quality or "0",
        )
        return False, _merge_counts(video_counts, mp3_counts)
    return False, run_youtube_source(
        cfg.keyword,
        cfg.limit,
        base_dir,
        cfg.format_spec,
        cfg.yt_mode == "mp3",
        has_ffmpeg,
        preselected_results=selected,
        video_quality=cfg.yt_video_quality,
        mp3_codec=cfg.mp3_codec,
        mp3_quality=cfg.mp3_quality or "0",
    )


def run_configured_sources(
    cfg: InteractiveConfig,
    base_dir: Path,
    has_ffmpeg: bool,
) -> tuple[bool, bool]:
    """Run every configured source sequentially.

    Returns ``(interrupted, any_failed)``. Each platform gets its own clearly
    separated progress section, reusing the existing per-source downloaders.
    """
    interrupted = False
    any_failed = False
    cancelled = False
    totals = {"downloaded": 0, "skipped": 0, "failed": 0, "total": 0, "size_bytes": 0}
    effective_dir = cfg.output_dir or base_dir
    for platform in cfg.platforms:
        try:
            if platform == "youtube":
                cancelled_yt, counts = _run_youtube_interactive(cfg, effective_dir, has_ffmpeg)
                if cancelled_yt:
                    cancelled = True
                    break
            else:
                from src.telegram import run_telegram_source  # lazy, avoids import cycle

                console.print(_heading("Telegram Downloads", CYAN))
                tg_limit = cfg.limit if cfg.limit else DEFAULT_TELEGRAM_LIMIT
                counts = run_telegram_source(
                    cfg.keyword,
                    tg_limit,
                    cfg.tg_media_type,
                    effective_dir,
                    cfg.tg_auto,
                    has_ffmpeg,
                )
        except KeyboardInterrupt:
            interrupted = True
            break
        for key in totals:
            totals[key] += int(counts.get(key, 0))
        if not counts.get("ok", True):
            any_failed = True

    if totals["failed"] > 0:
        any_failed = True

    if not interrupted and not cancelled:
        show_final_screen(
            totals["total"],
            totals["downloaded"],
            totals["skipped"],
            totals["failed"],
            totals["size_bytes"],
        )
    return interrupted, any_failed


def _extract_url_video(url: str) -> Optional[Dict[str, Any]]:
    """Fetch basic info for a single YouTube video URL."""
    options: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    try:
        _require_ytdlp()
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception:
        return None
    if not info:
        return None
    thumbnails = info.get("thumbnails") or []
    return {
        "search_position": 1,
        "title": info.get("title") or "Download",
        "video_id": info.get("id") or "url",
        "url": url,
        "channel": info.get("channel"),
        "channel_url": info.get("channel_url"),
        "upload_date": info.get("upload_date"),
        "duration": info.get("duration"),
        "view_count": info.get("view_count"),
        "description": info.get("description"),
        "thumbnail": info.get("thumbnail")
        or (thumbnails[-1].get("url") if thumbnails else None),
    }


def run_url_download_flow(
    base_dir: Path,
    has_ffmpeg: bool,
    format_spec_arg: Optional[str],
    mp3_override: Optional[bool] = None,
    url: Optional[str] = None,
) -> int:
    """Interactive download-by-link flow. Allows pasting a YouTube URL directly.

    When ``mp3_override`` is given (True/False), the download-mode question is
    skipped and that mode is used directly. When ``url`` is given, the paste
    prompt is skipped too. Returns 0 on success, 1 on failure/cancel.
    """
    console.print(_heading("Download by YouTube Link", CYAN))
    console.print()
    if url:
        url = url.strip()
    else:
        url = _ask_text("Paste the YouTube video URL", allow_empty=False)

    if mp3_override is None:
        console.print(Text("Download mode:", style=BRIGHT))
        options = ["Video", "mp3 only"]
        mp3_only = {1: False, 2: True}[_ask_choice("Enter choice:", options)]
    else:
        mp3_only = bool(mp3_override)

    with console.status("Fetching video info...", spinner="dots"):
        video = _extract_url_video(url)
    console.print()
    if video is None:
        show_error(
            "Could not fetch that YouTube link.",
            "Check the URL and your internet connection, then try again.",
        )
        return 1

    if format_spec_arg:
        format_spec = format_spec_arg
    elif mp3_only:
        format_spec = "bestaudio/best"
    elif has_ffmpeg:
        format_spec = DEFAULT_VIDEO_FORMAT
    else:
        format_spec = NO_FFMPEG_VIDEO_FORMAT

    folder = base_dir / "by-link" / sanitize_name(video["title"])
    videos_dir = folder / "videos"
    metadata_dir = folder / "metadata"
    videos_dir.mkdir(parents=True, exist_ok=True)
    metadata_dir.mkdir(parents=True, exist_ok=True)

    ok_line(f"Downloading: {_trunc(video['title'], 60)}")
    console.print()
    info, error = attempt_download(
        video, videos_dir, format_spec, mp3_only, has_ffmpeg, 1, 1
    )
    if error is not None or not info:
        show_error(f"Download failed: {error or 'Unknown error'}")
        return 1

    download_file = None
    requested = info.get("requested_downloads") or []
    if requested and isinstance(requested[0], dict):
        download_file = requested[0].get("filepath")
    else:
        guessed = sanitize_name(video["title"]) + (
            ".mp3" if mp3_only and has_ffmpeg else ""
        )
        if guessed:
            download_file = str(videos_dir / guessed)

    meta = build_metadata(video, info, "downloaded", download_file=download_file)
    write_json(
        folder / "metadata.json",
        {
            "source": "url",
            "url": url,
            "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "format": format_spec,
            "mp3_only": mp3_only,
            "video": meta,
        },
    )
    write_per_video_metadata(metadata_dir, 1, meta)
    write_json(
        folder / "downloaded.json",
        {
            video["video_id"]: {
                "title": video["title"],
                "file": download_file,
                "search_position": 1,
            }
        },
    )
    write_json(folder / "failed_downloads.json", [])
    ok_line(f"Download completed: {_trunc(video['title'], 60)}")
    console.print()
    size_bytes = _safe_file_size(download_file)
    show_summary(
        "Link",
        1,
        1,
        0,
        0,
        folder,
        size_bytes=size_bytes,
    )
    show_final_screen(1, 1, 0, 0, size_bytes)
    return 0


def run_interactive_session(args: argparse.Namespace) -> int:
    """The interactive platform router: menu -> configure -> summary -> run."""
    base_dir = Path(args.output)
    has_ffmpeg = ffmpeg_available()

    show_startup_banner(has_ffmpeg, base_dir, "interactive")
    if not has_ffmpeg:
        show_ffmpeg_warning()

    if yt_dlp is None:
        try:
            _require_ytdlp()
        except RuntimeError as exc:
            show_error(str(exc))
            return 1

    exit_code = 0
    while True:
        platform = show_platform_menu()
        if platform == "exit":
            console.print(
                Panel(
                    Align.center(Text("Goodbye!  Come back soon.", style=DIM)),
                    border_style="bright_black",
                    box=box.ROUNDED,
                )
            )
            console.print()
            return exit_code

        if platform == "url":
            if run_url_download_flow(base_dir, has_ffmpeg, args.format_spec) != 0:
                exit_code = 1
            continue  # back to the platform selection menu

        cfg = InteractiveConfig(
            platforms=["youtube", "telegram"] if platform == "all" else [platform]
        )
        cfg.output_dir = base_dir
        if args.keyword:
            cfg.keyword = args.keyword
        if args.format_spec:
            cfg.format_spec = args.format_spec

        while True:
            _configure(cfg)
            choice = show_download_summary(cfg)
            if choice == 1:
                interrupted, any_failed = run_configured_sources(
                    cfg, base_dir, has_ffmpeg
                )
                if interrupted:
                    return 130
                if any_failed:
                    exit_code = 1
                break  # back to the platform selection menu
            if choice == 2:
                continue  # re-run the configuration flow with saved values
            break  # choice 3 -> cancel, back to the main menu
    return exit_code


# -------------------------------------------------------------------------
# Main workflow
# -------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    base_dir = Path(args.output)
    has_ffmpeg = ffmpeg_available()

    if args.url and not args.interactive:
        show_startup_banner(has_ffmpeg, base_dir, "url")
        if not has_ffmpeg:
            show_ffmpeg_warning()
        if yt_dlp is None:
            try:
                _require_ytdlp()
            except RuntimeError as exc:
                show_error(str(exc))
                return 1
        return run_url_download_flow(
            base_dir,
            has_ffmpeg,
            args.format_spec,
            mp3_override=args.mp3_only,
            url=args.url,
        )

    if args.interactive or args.keyword is None:
        if not _require_terminal():
            return 1
        try:
            return run_interactive_session(args)
        except (KeyboardInterrupt, EOFError):
            console.print()
            info_line("Session ended.")
            return 0
    keyword = args.keyword.strip()
    if not keyword:
        show_error("The search keyword cannot be empty.")
        return 1

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
        args.mp3_only,
        base_dir,
        has_ffmpeg,
    )

    total_downloaded = total_skipped = total_failed = total_processed = 0
    total_size_bytes = 0
    for source in sources:
        try:
            if source == "youtube":
                counts = run_youtube_source(
                    keyword, yt_limit, base_dir, args.format_spec, args.mp3_only, has_ffmpeg
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
        total_size_bytes += counts.get("size_bytes", 0)
        if not counts.get("ok", True):
            total_failed += 1

    show_final_screen(
        total_processed,
        total_downloaded,
        total_skipped,
        total_failed,
        total_size_bytes,
    )
    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())