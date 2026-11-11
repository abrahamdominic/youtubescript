"""Direct-link downloads for TikTok and Facebook (plus URL routing helpers).

This module isolates every social/direct-URL concern — platform detection,
URL validation, the TikTok/Facebook yt-dlp downloader, friendly error mapping
and per-platform metadata — from the YouTube/Telegram implementation in
``media_finder.py``.

Shared UI/path/JSON helpers are imported from ``media_finder`` at module load
time; ``media_finder`` imports the entry points lazily so the two modules never
form an import cycle (same pattern as ``src/telegram.py``).

Only publicly accessible content is downloaded. Authentication, paywalls,
private accounts, DRM and other access controls are never bypassed.
"""

from __future__ import annotations

import datetime
import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

# Shared helpers live in the main module (no duplication, no import cycle —
# media_finder imports this module lazily from inside main()).
import media_finder as _m

console = _m.console
sanitize_name = _m.sanitize_name
load_manifest = _m.load_manifest
write_json = _m.write_json
FileProgress = _m.FileProgress
ok_line = _m.ok_line
skip_line = _m.skip_line
show_error = _m.show_error
show_summary = _m.show_summary
show_final_screen = _m.show_final_screen
_require_ytdlp = _m._require_ytdlp
_trunc = _m._trunc
_safe_file_size = _m._safe_file_size
BRIGHT = _m.BRIGHT
CYAN = _m.CYAN
YELLOW = _m.YELLOW
RED = _m.RED
DIM = _m.DIM
MARK_FAIL = _m.MARK_FAIL
MANIFEST_NAME = _m.MANIFEST_NAME
COMBINED_METADATA = _m.COMBINED_METADATA
FAILED_DOWNLOADS = _m.FAILED_DOWNLOADS

try:
    import yt_dlp
except ImportError:
    yt_dlp = None  # type: ignore[assignment]


PLATFORM_LABELS = _m.PLATFORM_LABELS

_PLATFORM_DOMAINS: Dict[str, Tuple[str, ...]] = {
    "youtube": ("youtube.com", "youtu.be", "youtube-nocookie.com"),
    "telegram": ("t.me", "telegram.me", "telegram.dog"),
    "tiktok": ("tiktok.com", "musical.ly"),
    "facebook": ("facebook.com", "fb.watch", "fbwat.ch", "facebook.watch"),
}


# -------------------------------------------------------------------------
# URL detection / validation
# -------------------------------------------------------------------------


def detect_platform(url: str) -> Optional[str]:
    """Return the platform name for *url* (``youtube``/``telegram``/
    ``tiktok``/``facebook``) or None when the domain is unrecognized.

    Uses robust registrable-domain matching instead of fragile string checks,
    so short links such as ``vm.tiktok.com/...`` or ``fb.watch/...`` are
    detected correctly.
    """
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return None
    for prefix in ("www.", "m.", "web.", "mobile."):
        if host.startswith(prefix):
            host = host[len(prefix):]
            break
    if not host:
        return None
    for platform, suffixes in _PLATFORM_DOMAINS.items():
        for suffix in suffixes:
            if host == suffix or host.endswith("." + suffix):
                return platform
    return None


def validate_url(url: str, expected: Optional[str] = None) -> Optional[str]:
    """Validate ``url`` and (optionally) require it to match ``expected``.

    Returns None when the URL is usable, otherwise a short, user-facing error
    message. Never raises.
    """
    url = (url or "").strip()
    if not url:
        return "Please paste a URL."
    if not re.match(r"^https?://", url, re.IGNORECASE):
        return "The URL must start with http:// or https://."
    try:
        parsed = urlparse(url)
    except ValueError:
        return "That does not look like a valid URL."
    if not parsed.scheme or not parsed.netloc:
        return "That does not look like a valid URL."
    platform = detect_platform(url)
    if platform is None:
        return (
            "That URL is not supported.\n"
            "Paste a YouTube, TikTok, or Facebook video link."
        )
    if expected and platform != expected:
        return (
            f"That is a {PLATFORM_LABELS.get(platform, platform)} link, "
            f"not a {PLATFORM_LABELS.get(expected, expected)} link."
        )
    return None


# -------------------------------------------------------------------------
# Error handling
# -------------------------------------------------------------------------


def friendly_download_error(error: str) -> str:
    """Map a raw downloader error string to a concise, user-facing message.

    Returns the original message when no known pattern matches.
    """
    low = (error or "").lower()
    if not low:
        return "Unknown error"
    if "ffmpeg" in low:
        return (
            "FFmpeg is required to merge this video and audio.\n"
            "Please install FFmpeg and try again."
        )
    if "private" in low:
        return (
            "The video is private or requires authentication.\n"
            "Please provide a publicly accessible URL."
        )
    if any(
        phrase in low
        for phrase in (
            "sign in to confirm you're not a bot",
            "sign in to confirm you’re not a bot",
            "confirm you're not a bot",
            "confirm you’re not a bot",
            "bot verification",
            "use --cookies-from-browser",
            "use --cookies",
        )
    ):
        return (
            "Bot verification required by the platform.\n"
            "Use --cookies cookies.txt or --cookies-from-browser <browser> to authenticate."
        )
    if any(
        word in low
        for word in ("login", "sign in", "authorization",
                     "authentication", "credentials", "log in")
    ):
        return (
            "Login or authentication is required.\n"
            "Please provide a publicly accessible URL or authenticate with cookies."
        )
    if any(
        word in low
        for word in ("geo-restricted", "not available in your country",
                     "unavailable in your country", "your country", "region")
    ):
        return "The video is not available in your region."
    if any(
        word in low
        for word in ("deleted", "removed", "does not exist", "no longer exists",
                     "not found")
    ):
        return "The video was deleted, removed, or is no longer available."
    if "too many requests" in low or "rate limit" in low:
        return "Rate limiting reached. Wait a moment and try again."
    if any(
        word in low
        for word in ("unsupported", "not supported", "no video", "no media",
                     "no supported")
    ):
        return "No downloadable video was found on that page."
    if "unexpected response" in low or "unable to download webpage" in low:
        return (
            "The platform blocked the download request.\n"
            "Update yt-dlp and retry:  pip install -U yt-dlp"
        )
    if "ip address is blocked" in low or "blocked from accessing" in low:
        return (
            "The platform is blocking requests from this network/IP for "
            "this post.\nTry a different network or a publicly accessible video."
        )
    if "cannot parse data" in low or "could not parse" in low:
        return (
            "The page could not be read. The video may be restricted, or\n"
            "the platform requires an updated yt-dlp (pip install -U yt-dlp)."
        )
    return (error or "Unknown error").strip()


# -------------------------------------------------------------------------
# Info extraction
# -------------------------------------------------------------------------


def _impersonation_available() -> bool:
    """Return True when yt-dlp can impersonate a real browser (curl_cffi).

    TikTok (and Facebook) challenge plain browser-less requests with a JS
    verification page. yt-dlp needs ``curl_cffi`` to impersonate a real
    Chrome TLS fingerprint; without it extraction fails with an
    "Unexpected response" error instead of a useful message.
    """
    try:
        import curl_cffi  # noqa: F401
        return True
    except ImportError:
        return False


def _warn_if_impersonation_missing(platform: str) -> None:
    """Give a clear, proactive tip when TikTok/Facebook need curl_cffi."""
    if platform in ("tiktok", "facebook") and not _impersonation_available():
        _m.show_error(
            f"{PLATFORM_LABELS.get(platform, platform.title())} requires "
            "curl_cffi so yt-dlp can mimic a real browser.",
            "Install it with:  pip install -r requirements.txt\n"
            "or:              pip install -U yt-dlp curl_cffi",
        )
        console.print()


def _fetch_social_info(
    url: str,
    cookie_opts: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Fetch basic yt-dlp info for a TikTok/Facebook URL.

    Returns ``(info_dict, None)`` on success or ``(None, error_message)``.
    """
    options: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    _m.apply_ytdlp_base_options(options, cookie_opts)
    try:
        _require_ytdlp()
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"
    return (info or {}), None


def _build_social_video(info: Dict[str, Any], url: str) -> Dict[str, Any]:
    """Normalize yt-dlp info into the item shape the download engine expects."""
    return {
        "search_position": 1,
        "title": info.get("title") or "Download",
        "video_id": info.get("id") or info.get("webpage_url") or url,
        "url": url,
        "channel": info.get("uploader") or info.get("channel") or info.get("creator"),
        "channel_url": info.get("uploader_url") or info.get("channel_url"),
        "upload_date": info.get("upload_date"),
        "duration": info.get("duration"),
        "view_count": info.get("view_count"),
        "description": info.get("description"),
        "thumbnail": info.get("thumbnail"),
    }


def _locate_download_file(info: Dict[str, Any], title: str, videos_dir: Path) -> Optional[str]:
    """Best-effort path of the file actually saved by the download engine."""
    requested = info.get("requested_downloads") or []
    if requested and isinstance(requested[0], dict):
        candidate = requested[0].get("filepath")
        if candidate and Path(candidate).exists():
            return str(candidate)
    stem = sanitize_name(title)
    matches = sorted(videos_dir.glob(f"{stem}*"))
    if matches:
        return str(matches[-1])
    return None


# -------------------------------------------------------------------------
# TikTok / Facebook download
# -------------------------------------------------------------------------


def download_social_url(
    platform: str,
    url: str,
    base_dir: Path,
    has_ffmpeg: bool,
    mp3_only: bool = False,
    format_spec_arg: Optional[str] = None,
    cookie_opts: Optional[Dict[str, Any]] = None,
) -> int:
    """Download one TikTok/Facebook URL into ``base_dir/<platform>/<title>/``.

    Reuses the existing yt-dlp download engine, progress UI, JSON manifest
    duplicate protection, FFmpeg detection and summary screens. Returns 0 on
    success, 1 on failure/cancel.
    """
    label = PLATFORM_LABELS.get(platform, platform.title())
    _warn_if_impersonation_missing(platform)

    info, fetch_error = _fetch_social_info(url, cookie_opts=cookie_opts)
    if fetch_error is not None or not info:
        show_error(
            friendly_download_error(fetch_error or "Unknown error"),
            hint="Please provide a publicly accessible video URL.",
        )
        return 1

    video = _build_social_video(info, url)
    video_id = video["video_id"]
    title = video["title"]

    # Duplicate protection: the same JSON manifest mechanism used by YouTube
    # and Telegram, kept per platform so an already-saved video is never
    # downloaded again.
    platform_dir = base_dir / platform
    platform_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = platform_dir / MANIFEST_NAME
    manifest = load_manifest(manifest_path)
    prior = manifest.get(video_id)
    if prior and isinstance(prior, dict):
        prior_file = prior.get("file")
        prior_folder = Path(prior.get("folder") or (Path(prior_file).parent if prior_file else ""))
        if prior_file and Path(prior_file).exists():
            skip_line(f"Already downloaded: {_trunc(title, 60)}")
            console.print()
            show_summary(label, 1, 0, 1, 0, prior_folder if prior_folder != Path("") else platform_dir)
            return 0

    folder = platform_dir / sanitize_name(title)
    videos_dir = folder / "videos"
    metadata_dir = folder / "metadata"
    videos_dir.mkdir(parents=True, exist_ok=True)
    metadata_dir.mkdir(parents=True, exist_ok=True)

    if format_spec_arg:
        format_spec = format_spec_arg
    elif mp3_only:
        format_spec = "bestaudio/best"
    else:
        format_spec = _m.build_video_format("best", has_ffmpeg)

    quality_text = "mp3 only" if mp3_only else "Best Available"
    ok_line(f"Downloading: {_trunc(title, 60)}")
    console.print()

    info_dict, error = _m.attempt_download(
        video,
        videos_dir,
        format_spec,
        mp3_only,
        has_ffmpeg,
        1,
        1,
        progress_label=f"{label} | {quality_text}",
        cookie_opts=cookie_opts,
    )
    if error is not None or not info_dict:
        reason = friendly_download_error(error or "Unknown error")
        write_json(folder / FAILED_DOWNLOADS, [{"title": title, "url": url, "video_id": video_id, "error": reason}])
        show_error(f"Download failed: {reason}", hint="Please provide a publicly accessible video URL.")
        show_summary(label, 1, 0, 0, 1, folder)
        return 1

    download_file = _locate_download_file(info_dict, title, videos_dir)
    if not download_file and mp3_only and has_ffmpeg:
        download_file = str(videos_dir / f"{sanitize_name(title)}.mp3")
    size_bytes = _safe_file_size(download_file)
    source_url = info_dict.get("webpage_url") or info_dict.get("original_url") or url
    timestamp = datetime.datetime.now().isoformat(timespec="seconds")

    meta: Dict[str, Any] = {
        "source": platform,
        "platform": platform,
        "url": source_url,
        "title": info_dict.get("title") or title,
        "video_id": video_id,
        "uploader": info_dict.get("uploader") or info_dict.get("channel") or info_dict.get("creator"),
        "uploader_url": info_dict.get("uploader_url") or info_dict.get("channel_url"),
        "upload_date": info_dict.get("upload_date"),
        "duration": info_dict.get("duration"),
        "duration_formatted": _m.simple_duration(info_dict.get("duration")),
        "view_count": info_dict.get("view_count"),
        "description": _trunc(info_dict.get("description") or "", 200),
        "thumbnail": info_dict.get("thumbnail"),
        "file": download_file,
        "file_size": size_bytes,
        "download_timestamp": timestamp,
        "quality": quality_text,
        "status": "downloaded",
        "error": None,
    }

    write_json(
        folder / COMBINED_METADATA,
        {
            "source": platform,
            "platform": platform,
            "url": url,
            "generated_at": timestamp,
            "format": format_spec,
            "mp3_only": mp3_only,
            "total": 1,
            "downloaded": 1,
            "skipped": 0,
            "failed": 0,
            "videos": [meta],
        },
    )
    _m.write_per_video_metadata(metadata_dir, 1, meta)
    write_json(
        folder / MANIFEST_NAME,
        {video_id: {"title": title, "file": download_file, "search_position": 1, "folder": str(folder)}},
    )
    write_json(folder / FAILED_DOWNLOADS, [])

    manifest[video_id] = {
        "title": title,
        "url": source_url,
        "file": download_file,
        "folder": str(folder),
        "platform": platform,
        "status": "downloaded",
    }
    write_json(manifest_path, manifest)

    ok_line(f"Download completed: {_trunc(title, 60)}")
    console.print()
    show_summary(label, 1, 1, 0, 0, folder, size_bytes=size_bytes)
    show_final_screen(1, 1, 0, 0, size_bytes)
    return 0


def download_tiktok(
    url: str,
    base_dir: Path,
    has_ffmpeg: bool,
    mp3_only: bool = False,
    format_spec_arg: Optional[str] = None,
) -> int:
    """Download a TikTok video by URL. Returns 0 on success, 1 on failure."""
    return download_social_url("tiktok", url, base_dir, has_ffmpeg, mp3_only, format_spec_arg)


def download_facebook(
    url: str,
    base_dir: Path,
    has_ffmpeg: bool,
    mp3_only: bool = False,
    format_spec_arg: Optional[str] = None,
) -> int:
    """Download a Facebook video by URL. Returns 0 on success, 1 on failure."""
    return download_social_url("facebook", url, base_dir, has_ffmpeg, mp3_only, format_spec_arg)