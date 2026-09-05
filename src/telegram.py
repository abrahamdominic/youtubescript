"""Telegram source for the NK YouTube Keyword Downloader.

This module isolates every Telegram-specific concern (Telethon credentials,
authentication, search, media classification, downloads and metadata) from the
YouTube implementation in ``media_finder.py``.

Shared UI/path/JSON helpers are imported from ``media_finder`` at module load
time; ``media_finder`` in turn imports :func:`run_telegram_source` lazily so the
two modules never form an import cycle.

Only content the authenticated Telegram account is allowed to access is
searched or downloaded. Private/restricted channels and Telegram security
mechanisms are never bypassed, and flood-wait (rate limit) delays are always
respected.
"""

from __future__ import annotations

import asyncio
import datetime
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich import box
from rich.console import Group
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

# Shared helpers live in the main module (no duplication, no import cycle —
# media_finder imports this module only lazily from inside main()).
import media_finder as _m


console = _m.console
sanitize_name = _m.sanitize_name
build_telegram_dirs = _m.build_telegram_dirs
read_json = _m.read_json
write_json = _m.write_json
load_manifest = _m.load_manifest
FileProgress = _m.FileProgress
ok_line = _m.ok_line
skip_line = _m.skip_line
show_error = _m.show_error
show_download_card = _m.show_download_card
show_results_table = _m.show_results_table
show_summary = _m.show_summary
_trunc = _m._trunc
_fmt_bytes = _m._fmt_bytes
BRIGHT = _m.BRIGHT
CYAN = _m.CYAN
YELLOW = _m.YELLOW
RED = _m.RED
DIM = _m.DIM
MARK_FAIL = _m.MARK_FAIL

try:
    from telethon import TelegramClient, errors as tg_errors
except ImportError:
    TelegramClient = None  # type: ignore[assignment]
    tg_errors = None  # type: ignore[assignment]

try:
    from dotenv import load_dotenv
except ImportError:

    def load_dotenv(*_args: Any, **_kwargs: Any) -> bool:  # type: ignore[no-redef]
        return False


TELEGRAM_ENV = {
    "api_id": "TELEGRAM_API_ID",
    "api_hash": "TELEGRAM_API_HASH",
    "session_name": "TELEGRAM_SESSION_NAME",
}


# -------------------------------------------------------------------------
# Credentials / environment
# -------------------------------------------------------------------------


def _load_telegram_env() -> Dict[str, str]:
    """Return Telegram credentials from the environment / .env file."""
    load_dotenv()
    api_id = (os.getenv(TELEGRAM_ENV["api_id"]) or "").strip()
    api_hash = (os.getenv(TELEGRAM_ENV["api_hash"]) or "").strip()
    session = (os.getenv(TELEGRAM_ENV["session_name"]) or "media_finder").strip()
    return {"api_id": api_id, "api_hash": api_hash, "session_name": session}


# -------------------------------------------------------------------------
# Media classification / matching
# -------------------------------------------------------------------------


def _media_type_of(message: Any) -> str:
    """Classify a Telegram message's media into a simple media type."""
    if getattr(message, "photo", None):
        return "image"
    if getattr(message, "video", None):
        return "video"
    if getattr(message, "voice", None):
        return "audio"
    if getattr(message, "audio", None):
        return "audio"
    if getattr(message, "document", None):
        mime = (
            getattr(getattr(message, "file", None), "mime_type", "") or ""
        ).lower()
        if mime.startswith("video"):
            return "video"
        if mime.startswith("audio") or mime.startswith("application/ogg"):
            return "audio"
        return "document"
    return "document"


def _guess_extension(message: Any) -> str:
    name = getattr(getattr(message, "file", None), "name", "") or ""
    if "." in name:
        ext = "." + name.rsplit(".", 1)[1].lower()
        if len(ext) <= 6:
            return re.sub(r"[^a-z0-9.]", "", ext)
    ext_map = {
        "video": ".mp4",
        "audio": ".mp3",
        "document": ".pdf",
        "image": ".jpg",
    }
    return ext_map.get(_media_type_of(message), ".bin")


def _matches_keyword(message: Any, keyword: str) -> bool:
    name = (getattr(getattr(message, "file", None), "name", "") or "").lower()
    return keyword.lower() in name


# -------------------------------------------------------------------------
# Search
# -------------------------------------------------------------------------


def _print_rate_limit(wait_seconds: int) -> None:
    """Show a single clear panel when Telegram asks us to wait."""
    console.print(
        Panel(
            Text(
                f"Telegram rate limit reached - waiting {wait_seconds}s "
                "as requested by Telegram.",
                style=YELLOW,
            ),
            title="[yellow]\u26a0 Telegram Rate Limit[/]",
            border_style="yellow",
            box=box.ROUNDED,
        )
    )


async def _tg_search(
    client: Any,
    keyword: str,
    limit: int,
    media_type: str,
) -> List[Dict[str, Any]]:
    """Search accessible dialogs for messages matching the keyword."""
    results: List[Dict[str, Any]] = []
    seen: set = set()
    found_wait = False

    def add_item(message: Any, dialog_title: str) -> None:
        key = f"{getattr(message, 'chat_id', '')}:{getattr(message, 'id', '')}"
        if key in seen or not message.id:
            return
        seen.add(key)
        media = getattr(message, "file", None)
        if media is None:
            return
        detected = _media_type_of(message)
        if media_type != "all" and detected != media_type:
            return
        name = (getattr(media, "name", "") or "").strip()
        if (message.text or "").strip():
            title = (message.text or "").strip().splitlines()[0][:140]
        else:
            title = name or f"Message {message.id}"
        results.append(
            {
                "message": message,
                "message_id": message.id,
                "chat_id": message.chat_id,
                "channel": dialog_title or "Unknown",
                "title": title,
                "media_type": detected,
                "filename": name or None,
                "size": getattr(media, "size", None) or None,
                "size_display": _fmt_bytes(getattr(media, "size", None)),
                "date": message.date,
            }
        )

    per_dialog_text = max(10, min(60, limit * 3))
    scan_window = max(5, min(40, limit * 2))

    try:
        async for dialog in client.iter_dialogs():
            if len(results) >= limit:
                break
            dialog_title = getattr(dialog, "title", None) or "Unknown"

            # Text / caption match.
            try:
                async for message in client.iter_messages(
                    dialog.id, search=keyword, limit=per_dialog_text
                ):
                    if len(results) >= limit:
                        break
                    if not getattr(message, "file", None):
                        continue
                    add_item(message, dialog_title)
            except tg_errors.FloodWaitError as exc:
                if not found_wait:
                    _print_rate_limit(exc.seconds)
                    found_wait = True
                await asyncio.sleep(exc.seconds)
                continue
            except Exception:
                continue

            # Filename / media-info match on recent messages.
            try:
                async for message in client.iter_messages(
                    dialog.id, limit=scan_window
                ):
                    if len(results) >= limit:
                        break
                    if not getattr(message, "file", None):
                        continue
                    if not _matches_keyword(message, keyword):
                        continue
                    add_item(message, dialog_title)
            except tg_errors.FloodWaitError as exc:
                if not found_wait:
                    _print_rate_limit(exc.seconds)
                    found_wait = True
                await asyncio.sleep(exc.seconds)
            except Exception:
                continue
    except Exception:
        pass

    return results[:limit]


# -------------------------------------------------------------------------
# Authentication
# -------------------------------------------------------------------------


async def _tg_auth_client(api_id: str, api_hash: str, session_name: str) -> Any:
    """Connect and authenticate (first run only) a Telethon client."""
    client = TelegramClient(session_name, int(api_id), api_hash)
    await client.connect()
    if not await client.is_user_authorized():
        if not (console.is_terminal and sys.stdin.isatty()):
            raise RuntimeError(
                "No Telegram session found and the terminal is not interactive.\n"
                "Please run the command in an interactive terminal once to log in, "
                "or re-use an existing session file."
            )
        console.print(
            Panel(
                Text(
                    "No Telegram session found.\n\n"
                    "Enter your Telegram credentials to authenticate. "
                    "Your session will be saved locally for future runs.",
                    style=BRIGHT,
                ),
                title="[cyan]Telegram Authentication[/]",
                border_style=CYAN,
                box=box.ROUNDED,
            )
        )
        console.print()
        phone = Prompt.ask("[cyan]Enter your phone number[/]", console=console)
        code_sent = False
        try:
            await client.send_code_request(phone)
            code_sent = True
        except tg_errors.FloodWaitError as exc:
            _print_rate_limit(exc.seconds)
            await asyncio.sleep(exc.seconds)
            await client.send_code_request(phone)
            code_sent = True
        except tg_errors.rpcerrorlist.ApiIdInvalidError:
            if await client.is_connected():
                await client.disconnect()
            raise RuntimeError(
                "Invalid API ID/hash. Check TELEGRAM_API_ID and "
                "TELEGRAM_API_HASH in your .env file."
            )

        if code_sent:
            code = Prompt.ask("[cyan]Enter the verification code[/]", console=console)
            try:
                await client.sign_in(phone, code)
            except tg_errors.SessionPasswordNeededError:
                password = Prompt.ask(
                    "[cyan]Enter your 2FA password[/]",
                    password=True,
                    console=console,
                )
                await client.sign_in(password=password)
            except tg_errors.rpcerrorlist.PhoneCodeInvalidError:
                if await client.is_connected():
                    await client.disconnect()
                raise RuntimeError(
                    "Invalid verification code. Please try again."
                )
    return client


# -------------------------------------------------------------------------
# Download
# -------------------------------------------------------------------------


async def _tg_download_item(
    client: Any,
    item: Dict[str, Any],
    tg_dirs: Dict[str, Path],
) -> tuple[Optional[str], Optional[str]]:
    """Download one Telegram item into the correct media subfolder.

    Returns ``(final_path, None)`` on success or ``(None, error_message)``.
    """
    media_dir = tg_dirs.get(item["media_type"]) or tg_dirs["documents"]
    media_dir.mkdir(parents=True, exist_ok=True)
    if item.get("filename"):
        stem = sanitize_name(Path(item["filename"]).stem)
    else:
        stem = sanitize_name(
            f"{item['channel']}_{item['message_id']}_{item['title'][:40]}"
        )
    ext = _guess_extension(item["message"]) if not item.get("filename") else ""
    base = f"{stem}{ext}"
    matches = list(media_dir.glob(f"{Path(base).stem}*"))
    if matches:
        return str(matches[0]), None

    pbar = FileProgress(console, f"[cyan]{_trunc(base, 40)}[/]")
    pbar.start()
    dest = media_dir / stem
    try:
        saved = await client.download_media(
            message=item["message"],
            file=str(dest),
            progress_callback=pbar.telethon_callback(),
        )
    except tg_errors.FloodWaitError as exc:
        _print_rate_limit(exc.seconds)
        await asyncio.sleep(exc.seconds)
        try:
            saved = await client.download_media(
                message=item["message"],
                file=str(dest),
                progress_callback=pbar.telethon_callback(),
            )
        except Exception as exc2:
            pbar.stop()
            return None, f"{type(exc2).__name__}: {exc2}"
    except Exception as exc:
        pbar.stop()
        return None, f"{type(exc).__name__}: {exc}"
    finally:
        pbar.stop()

    if not saved:
        return None, "Media unavailable"

    saved_path = Path(str(saved))
    if saved_path.is_dir():
        same_kind = list(saved_path.glob(f"{stem}*"))
        if not same_kind:
            return None, "Media unavailable"
        saved_path = sorted(same_kind, key=lambda p: p.stat().st_mtime)[-1]
    return str(saved_path), None


# -------------------------------------------------------------------------
# Full Telegram workflow
# -------------------------------------------------------------------------


async def _tg_worker(
    keyword: str,
    limit: int,
    media_type: str,
    tg_dirs: Dict[str, Path],
    auto_yes: bool,
) -> Dict[str, Any]:
    """Full async Telegram workflow: auth, search, confirm, download, write outputs."""
    env = _load_telegram_env()
    if not env["api_id"] or not env["api_hash"]:
        raise RuntimeError(
            "Telegram credentials are missing.\n"
            "Create a .env file with TELEGRAM_API_ID and TELEGRAM_API_HASH.\n"
            "See .env.example and the README for instructions."
        )

    client = await _tg_auth_client(env["api_id"], env["api_hash"], env["session_name"])
    try:
        with console.status(
            f'[cyan]Searching Telegram for "{keyword}"...', spinner="dots"
        ):
            items = await _tg_search(client, keyword, limit, media_type)
        console.print()
        total = len(items)
        ok_line(
            f"Search completed - found {total} matching "
            f"message{'' if total == 1 else 's'}"
        )
        console.print()

        if total == 0:
            return {"ok": True, "downloaded": 0, "skipped": 0, "failed": 0, "total": 0}

        show_telegram_search_results(keyword, items)

        if not auto_yes:
            answer = Prompt.ask(
                "[cyan]Download all results? [Y/n][/]",
                default="Y",
                choices=["Y", "y", "n", "N"],
                console=console,
            )
            console.print()
            if answer.strip().lower() != "y":
                skip_line("Download cancelled by user")
                console.print()
                show_summary("Telegram", total, 0, 0, 0, tg_dirs["base"])
                return {
                    "ok": True,
                    "downloaded": 0,
                    "skipped": 0,
                    "failed": 0,
                    "total": total,
                }

        manifest = load_manifest(tg_dirs["manifest"])
        processed: List[Dict[str, Any]] = []
        failed: List[Dict[str, Any]] = []
        downloaded_count = skipped_count = failed_count = 0

        for index, item in enumerate(items, start=1):
            key = f"{item['chat_id']}:{item['message_id']}"
            title = _trunc(item["title"], 60)
            show_download_card(index, total, title, item["channel"], "Downloading")

            meta_base = {
                "source": "telegram",
                "keyword": keyword,
                "message_id": item["message_id"],
                "chat_id": item["chat_id"],
                "channel_name": item["channel"],
                "date": item["date"].isoformat() if item["date"] else None,
                "message_text": (item["message"].text or "")[:2000],
                "media_type": item["media_type"],
                "filename": item["filename"],
                "file_size": item["size"],
                "status": "downloaded",
                "error": None,
            }

            if key in manifest:
                skipped_count += 1
                meta = dict(meta_base, status="skipped")
                processed.append(meta)
                skip_line(f"Already downloaded (message {item['message_id']})")
                console.print()
                continue

            saved_path, error = await _tg_download_item(client, item, tg_dirs)
            if error is not None or not saved_path:
                failed_count += 1
                failed.append(
                    {
                        "title": item["title"],
                        "channel": item["channel"],
                        "message_id": item["message_id"],
                        "chat_id": item["chat_id"],
                        "error": error or "Media unavailable",
                    }
                )
                meta = dict(meta_base, status="failed", error=error)
                processed.append(meta)
                console.print(
                    Panel(
                        Group(
                            Text(f"{MARK_FAIL} Download failed", style=RED),
                            Text(
                                f"Reason: {error or 'Media unavailable'}",
                                style=DIM,
                            ),
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
            meta = dict(
                meta_base, status="downloaded", filename=Path(saved_path).name
            )
            processed.append(meta)

            manifest[key] = {
                "message_id": item["message_id"],
                "channel": item["channel"],
                "file": saved_path,
                "title": item["title"],
            }
            write_json(tg_dirs["manifest"], manifest)
            ok_line(f"Download completed: {title}")
            console.print()

        metadb = tg_dirs["metadata"]
        for meta in processed:
            mid = meta["message_id"]
            meta_path = metadb / f"{mid}.json"
            if meta_path.exists():
                meta_path = metadb / f"{meta['chat_id']}_{mid}.json"
            write_json(meta_path, meta)

        combined = {
            "source": "telegram",
            "keyword": keyword,
            "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "search_type": media_type,
            "total": total,
            "downloaded": downloaded_count,
            "skipped": skipped_count,
            "failed": failed_count,
            "results": processed,
        }
        write_json(tg_dirs["combined_metadata"], combined)
        write_json(tg_dirs["failed"], failed)

        show_summary(
            "Telegram",
            total,
            downloaded_count,
            skipped_count,
            failed_count,
            tg_dirs["base"],
        )
        return {
            "ok": True,
            "downloaded": downloaded_count,
            "skipped": skipped_count,
            "failed": failed_count,
            "total": total,
        }
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


def show_telegram_search_results(keyword: str, items: List[Dict[str, Any]]) -> None:
    """Display the keyword heading panel and the discovered result table."""
    info = Table.grid(padding=(0, 2))
    info.add_column(style=DIM, justify="left")
    info.add_column(style=CYAN)
    info.add_row("Keyword", keyword)
    info.add_row(
        "Found", f"{len(items)} matching message{'' if len(items) == 1 else 's'}"
    )
    console.print(
        Panel(
            info,
            title="[bold cyan]Telegram Search[/]",
            border_style=CYAN,
            box=box.ROUNDED,
        )
    )
    console.print()
    show_results_table("Telegram", items)


def run_telegram_source(
    keyword: str,
    limit: int,
    media_type: str,
    base_dir: Path,
    auto_yes: bool,
    has_ffmpeg: bool,
) -> Dict[str, Any]:
    """Run the full Telegram source workflow. Returns result counts."""
    del has_ffmpeg
    if TelegramClient is None:
        show_error(
            "Telethon is not installed. Telegram searches are unavailable.",
            "Install it with:  pip install -r requirements.txt",
        )
        return {"ok": False, "downloaded": 0, "skipped": 0, "failed": 0, "total": 0}

    tg_dirs = build_telegram_dirs(base_dir, keyword)
    try:
        return asyncio.run(_tg_worker(keyword, limit, media_type, tg_dirs, auto_yes))
    except RuntimeError as exc:
        show_error(str(exc))
        return {"ok": False, "downloaded": 0, "skipped": 0, "failed": 0, "total": 0}
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        show_error(
            "Telegram search failed.",
            f"{type(exc).__name__}: {exc}\n"
            "Check your credentials and connection and try again.",
        )
        return {"ok": False, "downloaded": 0, "skipped": 0, "failed": 0, "total": 0}