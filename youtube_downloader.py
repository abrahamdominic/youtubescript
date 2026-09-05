#!/usr/bin/env python3
"""Compatibility wrapper around ``media_finder.py``.

Keeps the legacy entry point:

    python youtube_downloader.py "Apostle Babs Adewumi"

working. All functionality now lives in ``media_finder.py``.
"""

from media_finder import main

if __name__ == "__main__":
    raise SystemExit(main())