"""Streaming playback support for the NK Media Finder.

Playback never writes media into the downloads folder. mpv gets a resolved
direct URL (plus a separate audio URL when the site has no combined stream).
ffplay/VLC receive a yt-dlp stdout pipe, which avoids expired URLs, custom
header issues and missing audio. Telegram media is piped straight from the
authenticated Telethon session into the player's stdin.

Shared UI/yt-dlp helpers are imported from ``media_finder``. ``media_finder``
imports this module lazily, so there is no import cycle.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import media_finder as _m

console = _m.console
ok_line = _m.ok_line
err_line = _m.err_line
dim_line = _m.dim_line

# A single combined stream is playable by every player without FFmpeg merging.
# Downloads still use the higher-quality adaptive selectors.
PROGRESSIVE_VIDEO_FORMAT = (
    "best[vcodec!=none][acodec!=none][ext=mp4]/"
    "best[vcodec!=none][acodec!=none]/b[ext=mp4]/b"
)
AUDIO_FORMAT = "bestaudio/best"

PLAYER_ENV_VARS = ("MEDIA_PLAYER", "PLAYER")
PLAYER_CANDIDATES = ("mpv", "vlc", "cvlc", "ffplay")

# ffplay needs a longer probe and bigger buffer for network/piped streams;
# without these, short or slow sources can start muted or stutter.
FFPLAY_FLAGS = [
    "-hide_banner",
    "-loglevel",
    "error",
    "-autoexit",
    "-infbuf",
    "-fflags",
    "+genpts+discardcorrupt",
    "-probesize",
    "32M",
    "-analyzeduration",
    "5000000",
]

MPV_FLAGS = [
    "--force-window=yes",
    "--cache=yes",
    "--demuxer-max-bytes=32MiB",
    "--demuxer-readahead-secs=10",
]


@dataclass
class Player:
    """A discovered external player and its command line."""

    argv: List[str]
    kind: str  # "mpv" | "vlc" | "ffplay"

    @property
    def name(self) -> str:
        return os.path.basename(self.argv[0])

    @property
    def stdin_argument(self) -> str:
        """Input target to use when feeding media through stdin."""
        if self.kind == "ffplay":
            return "-"
        return "fd://0"  # mpv and VLC both understand this.


@dataclass
class Stream:
    """A resolved direct media URL plus the headers needed to fetch it."""

    url: str
    headers: Dict[str, str]
    title: str
    format_id: str = ""
    audio_url: Optional[str] = None
    audio_headers: Dict[str, str] = field(default_factory=dict)


def _player_kind(executable: str) -> str:
    name = os.path.basename(executable).lower()
    if name.startswith("mpv"):
        return "mpv"
    if name.startswith("vlc") or name == "cvlc":
        return "vlc"
    return "ffplay"


def find_player() -> Optional[Player]:
    """Find an external player, honouring MEDIA_PLAYER / PLAYER overrides."""
    for var in PLAYER_ENV_VARS:
        raw = (os.getenv(var) or "").strip()
        if not raw:
            continue
        try:
            argv = shlex.split(raw)
        except ValueError:
            argv = []
        if argv and shutil.which(argv[0]):
            return Player(argv, _player_kind(argv[0]))
        _m.show_error(
            f"{var} is set but the player could not be found: {raw}",
            "Set it to an installed player, e.g.  MEDIA_PLAYER=mpv  or  "
            "MEDIA_PLAYER=ffplay",
        )
        return None

    for name in PLAYER_CANDIDATES:
        path = shutil.which(name)
        if path:
            return Player([path], _player_kind(name))
    return None


def player_available() -> bool:
    """Return True when at least one supported player is installed."""
    return find_player() is not None


def _show_missing_player() -> None:
    _m.show_error(
        "No media player found for streaming.",
        "Install mpv (recommended):  sudo apt install mpv\n"
        "or use ffplay from FFmpeg:  sudo apt install ffmpeg\n"
        "You can also set MEDIA_PLAYER=/path/to/player.",
    )


def _normalise_selector(
    format_spec: Optional[str], mp3_only: bool
) -> tuple[str, Optional[str]]:
    """Return a selector a plain player can consume, plus an optional note."""
    if mp3_only:
        if format_spec and "+" not in format_spec:
            return format_spec, None
        return AUDIO_FORMAT, None
    if not format_spec:
        return PROGRESSIVE_VIDEO_FORMAT, None
    if "+" in format_spec or format_spec.startswith(("bv", "ba")):
        return (
            PROGRESSIVE_VIDEO_FORMAT,
            "Streaming uses one combined stream with audio; downloaded quality "
            "is unchanged.",
        )
    return format_spec, None


def _cookie_args(cookie_opts: Optional[Dict[str, Any]]) -> List[str]:
    """Translate the app's cookie options into yt-dlp CLI flags."""
    args: List[str] = []
    if not cookie_opts:
        return args
    if cookie_opts.get("cookiefile"):
        args.extend(["--cookies", str(cookie_opts["cookiefile"])])
    if cookie_opts.get("cookiesfrombrowser"):
        args.extend(
            ["--cookies-from-browser", str(cookie_opts["cookiesfrombrowser"])]
        )
    return args


def build_ytdlp_command(
    url: str,
    selector: str,
    cookie_opts: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Build a yt-dlp command that writes one playable stream to stdout."""
    command = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--ignore-config",
        "--quiet",
        "--no-warnings",
        "--no-playlist",
        "--ignore-errors",
        "--retries",
        "3",
        "--fragment-retries",
        "3",
        "--socket-timeout",
        "20",
        "--format",
        selector,
        "--output",
        "-",
    ]
    if "youtube.com" in url or "youtu.be" in url:
        command.extend(
            [
                "--extractor-args",
                "youtube:player_client=android,ios,web",
            ]
        )
    command.extend(_cookie_args(cookie_opts))
    command.append(url)
    return command


def _has_audio(fmt: Dict[str, Any]) -> bool:
    return fmt.get("acodec") not in (None, "", "none")


def _pick_audio_format(info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Pick the best standalone audio format from an yt-dlp info dict."""
    formats = info.get("formats") or []
    candidates = [
        fmt
        for fmt in formats
        if isinstance(fmt, dict)
        and _has_audio(fmt)
        and fmt.get("vcodec") in (None, "", "none")
        and fmt.get("url")
    ]
    if not candidates:
        return None

    def quality(fmt: Dict[str, Any]) -> float:
        try:
            return float(fmt.get("tbr") or fmt.get("abr") or 0)
        except (TypeError, ValueError):
            return 0.0

    return max(candidates, key=quality)


def _select_formats(
    info: Dict[str, Any],
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """Return the main format and, when needed, a separate audio format."""
    requested = info.get("requested_formats") or []
    if requested and isinstance(requested[0], dict):
        main = requested[0]
        audio = next(
            (
                fmt
                for fmt in requested[1:]
                if isinstance(fmt, dict) and _has_audio(fmt) and fmt.get("url")
            ),
            None,
        )
    else:
        main = info
        audio = None
    if not _has_audio(main) and main.get("vcodec") not in (None, "", "none"):
        audio = audio or _pick_audio_format(info)
    return main, audio


def resolve_stream(
    url: str,
    title: str,
    cookie_opts: Optional[Dict[str, Any]] = None,
    mp3_only: bool = False,
    format_spec: Optional[str] = None,
) -> Optional[Stream]:
    """Resolve a page URL into a direct stream URL using yt-dlp."""
    try:
        _m._require_ytdlp()
        import yt_dlp  # noqa: WPS433 - optional dependency, checked above
    except (ImportError, RuntimeError) as exc:
        _m.show_error(str(exc))
        return None

    selector, note = _normalise_selector(format_spec, mp3_only)
    if note:
        dim_line(note)

    options: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
    }
    _m.apply_ytdlp_base_options(options, cookie_opts)

    # Fall back to a guaranteed combined format if a custom selector produces
    # a video-only stream, which would otherwise play without audio.
    selectors = [selector]
    if selector not in (PROGRESSIVE_VIDEO_FORMAT, AUDIO_FORMAT, "b", "best"):
        selectors.append(PROGRESSIVE_VIDEO_FORMAT)

    info: Optional[Dict[str, Any]] = None
    chosen: Dict[str, Any] = {}
    audio_fmt: Optional[Dict[str, Any]] = None
    last_error: Optional[Exception] = None
    for candidate in selectors:
        attempt = dict(options, format=candidate)
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                with yt_dlp.YoutubeDL(attempt) as ydl:
                    info = ydl.extract_info(url, download=False)
        except Exception as exc:  # yt-dlp raises many extractor-specific errors.
            last_error = exc
            info = None
        if not info:
            continue
        chosen, audio_fmt = _select_formats(info)
        if mp3_only or _has_audio(chosen) or audio_fmt:
            break
        # Selected a video-only stream with no audio alternative; retry.
        info = None

    if not info:
        clean = _m.strip_ansi(str(last_error) if last_error else "")
        hint = "Check the URL and your internet connection."
        if _m.is_bot_challenge_error(clean):
            hint = (
                "Bot verification detected. Use --cookies cookies.txt or "
                "--cookies-from-browser chrome to authenticate."
            )
        elif not clean or "no video formats" in clean.lower():
            clean = "No playable stream was found for this link."
            hint = "Try another URL, or provide cookies if the site requires sign-in."
        _m.show_error(f"Could not start playback: {clean}", hint=hint)
        return None

    stream_url = chosen.get("url") or info.get("url")
    if not stream_url:
        _m.show_error(
            "Playback failed.",
            "No direct stream URL was available for this format. Try another "
            "link or a different format.",
        )
        return None

    return Stream(
        url=stream_url,
        headers=dict(chosen.get("http_headers") or info.get("http_headers") or {}),
        title=title or info.get("title") or "Playing",
        format_id=str(chosen.get("format_id") or ""),
        audio_url=(audio_fmt or {}).get("url"),
        audio_headers=dict((audio_fmt or {}).get("http_headers") or {}),
    )


def _header_args(player: Player, headers: Dict[str, str]) -> List[str]:
    """Translate yt-dlp headers into player-specific command line flags."""
    if not headers:
        return []
    if player.kind == "mpv":
        return [f"--http-header-fields={k}: {v}" for k, v in headers.items()]
    if player.kind == "ffplay":
        return ["-headers", "".join(f"{k}: {v}\r\n" for k, v in headers.items())]
    return [f"--http-headers={k}={v}" for k, v in headers.items()]


def build_command(
    player: Player,
    stream: Stream,
    cookie_opts: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Build the command line for playing a resolved direct URL."""
    argv = list(player.argv)
    title = _m._trunc(stream.title, 100)
    argv.extend(_header_args(player, stream.headers))

    if player.kind == "mpv":
        argv.extend(MPV_FLAGS)
        argv.append(f"--title={title}")
        if stream.audio_url:
            argv.append(f"--audio-file={stream.audio_url}")
        if cookie_opts and cookie_opts.get("cookiefile"):
            argv.append(f"--cookies-file={cookie_opts['cookiefile']}")
        argv.append(stream.url)
    elif player.kind == "ffplay":
        argv.extend(FFPLAY_FLAGS)
        argv.extend(["-reconnect", "1", "-reconnect_streamed", "1", stream.url])
    else:  # VLC / cvlc
        argv.extend(["--play-and-exit", f"--meta-title={title}", stream.url])
        argv.append("vlc://quit")
    return argv


def build_stdin_command(player: Player, title: str) -> List[str]:
    """Build the command line for playing media piped through stdin."""
    argv = list(player.argv)
    safe_title = _m._trunc(title or "Playing", 100)
    if player.kind == "mpv":
        argv.extend(MPV_FLAGS)
        argv.extend([f"--title={safe_title}", player.stdin_argument])
    elif player.kind == "ffplay":
        argv.extend(FFPLAY_FLAGS)
        argv.extend(["-i", player.stdin_argument])
    else:  # VLC / cvlc
        argv.extend(
            ["--play-and-exit", f"--meta-title={safe_title}", player.stdin_argument]
        )
    return argv


def _run_piped_player(
    player: Player,
    producer: List[str],
    title: str,
    producer_env: Optional[Dict[str, str]] = None,
) -> bool:
    """Run a producer process whose stdout feeds the player's stdin."""
    ok_line(f"Playing: {_m._trunc(title, 70)}")
    dim_line(f"Player: {player.name}  -  press q (or close the window) to stop.")

    producer_env_dict = os.environ.copy()
    if producer_env:
        producer_env_dict.update(producer_env)
    source = subprocess.Popen(producer, stdout=subprocess.PIPE, env=producer_env_dict)
    player_proc: Optional[subprocess.Popen] = None
    try:
        assert source.stdout is not None
        player_proc = subprocess.Popen(
            build_stdin_command(player, title), stdin=source.stdout
        )
        source.stdout.close()  # source gets SIGPIPE when the player quits early
        code = player_proc.wait()
    except KeyboardInterrupt:
        dim_line("Playback stopped.")
        code = 0
    finally:
        if player_proc is not None and player_proc.poll() is None:
            player_proc.terminate()
            player_proc.wait()
        if source.poll() is None:
            source.terminate()
        source.wait()

    if source.returncode not in (0, None):
        err_line(f"Stream source exited with code {source.returncode}.")
        return False
    if code == 0:
        dim_line("Playback finished.")
        return True
    err_line(f"Player exited with code {code}.")
    return False


def play_url(
    url: str,
    title: str,
    cookie_opts: Optional[Dict[str, Any]] = None,
    mp3_only: bool = False,
    format_spec: Optional[str] = None,
) -> bool:
    """Play a YouTube/TikTok/Facebook URL without saving it to disk."""
    player = find_player()
    if not player:
        _show_missing_player()
        return False

    selector, note = _normalise_selector(format_spec, mp3_only)
    if note:
        dim_line(note)
    display_title = title or "Playing"

    if player.kind == "mpv":
        # mpv can seek a direct URL and mix a separate audio track itself.
        stream = resolve_stream(url, display_title, cookie_opts, mp3_only, format_spec)
        if not stream:
            return False
        ok_line(f"Playing: {_m._trunc(stream.title, 70)}")
        dim_line(f"Player: {player.name}  -  press q (or close the window) to stop.")
        try:
            result = subprocess.run(
                build_command(player, stream, cookie_opts), check=False
            )
        except KeyboardInterrupt:
            dim_line("Playback stopped.")
            return True
        except FileNotFoundError:
            _show_missing_player()
            return False
        if result.returncode == 0:
            dim_line("Playback finished.")
            return True
        err_line(f"Player exited with code {result.returncode}.")
        return False

    # ffplay/VLC get a yt-dlp stdout pipe: no expired URLs, no header mismatch,
    # and the selector always contains audio.
    return _run_piped_player(
        player,
        build_ytdlp_command(url, selector, cookie_opts),
        display_title,
    )


async def play_telegram_item(client: Any, item: Dict[str, Any]) -> bool:
    """Stream a Telegram message's media into the player, with no temp file."""
    player = find_player()
    if not player:
        _show_missing_player()
        return False

    message = item.get("message")
    media = getattr(message, "media", None) if message is not None else None
    if media is None:
        _m.show_error(
            "This Telegram message has no playable media.",
            "Choose a video, audio or image result.",
        )
        return False

    title = item.get("title") or "Telegram media"
    ok_line(f"Playing: {_m._trunc(title, 70)}")
    dim_line(f"Player: {player.name}  -  press q (or close the window) to stop.")
    command = build_stdin_command(player, title)

    process: Optional[subprocess.Popen] = None
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE)
        assert process.stdin is not None

        async def pump() -> None:
            try:
                async for chunk in client.iter_download(media):
                    if not chunk:
                        continue
                    await asyncio.to_thread(process.stdin.write, chunk)
                    await asyncio.to_thread(process.stdin.flush)
            except (BrokenPipeError, OSError):
                # The player was closed early; that is a normal stop.
                pass
            finally:
                try:
                    process.stdin.close()
                except OSError:
                    pass

        await pump()
        code = await asyncio.to_thread(process.wait)
        if code == 0:
            dim_line("Playback finished.")
            return True
        err_line(f"Player exited with code {code}.")
        return False
    except KeyboardInterrupt:
        dim_line("Playback stopped.")
        return True
    except Exception as exc:  # Telethon/network errors must not kill the session.
        _m.show_error(f"Could not stream this Telegram file: {exc}")
        return False
    finally:
        if process is not None:
            if process.stdin is not None and not process.stdin.closed:
                try:
                    process.stdin.close()
                except OSError:
                    pass
            if process.poll() is None:
                process.terminate()
                try:
                    await asyncio.to_thread(process.wait, 5)
                except asyncio.TimeoutError:
                    process.kill()
