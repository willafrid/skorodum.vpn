#!/usr/bin/env python3
"""Download two text sources, decode Base64 when needed, and combine them."""

from __future__ import annotations

import argparse
import base64
import binascii
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SOURCES = (
    "https://subrostunnel.vercel.app/gen.txt",
    "https://etoneya.best/whitelist",
)
DEFAULT_OUTPUT = Path("cron-base64/combined.txt")
USER_AGENT = "combined-text-sync/1.0"


class SyncError(RuntimeError):
    """Raised when an input cannot be downloaded or decoded."""


def download(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=30) as response:
            if response.status != 200:
                raise SyncError(f"{url}: HTTP {response.status}")
            return response.read()
    except HTTPError as error:
        raise SyncError(f"{url}: HTTP {error.code}") from error
    except URLError as error:
        raise SyncError(f"{url}: download failed ({error.reason})") from error


def decode_source_text(data: bytes, source: str) -> str:
    """Decode Base64 text when present; preserve an already plain-text source."""
    try:
        encoded = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise SyncError(f"{source}: response is not UTF-8 text") from error

    payload = re.sub(r"\s+", "", encoded)
    if not payload:
        raise SyncError(f"{source}: empty response")
    payload += "=" * (-len(payload) % 4)

    try:
        decoded = base64.b64decode(payload, altchars=b"-_", validate=True)
        return decoded.decode("utf-8-sig")
    except (ValueError, binascii.Error, UnicodeDecodeError):
        # Some sources publish the decoded text directly. It must remain intact.
        if encoded.lstrip().lower().startswith(("<!doctype", "<html")):
            raise SyncError(f"{source}: received an HTML page instead of text")
        return encoded


def write_if_changed(output: Path, content: str) -> bool:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() and output.read_text(encoding="utf-8") == content:
        return False

    temporary = output.with_suffix(f"{output.suffix}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(output)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args()

    try:
        parts = [decode_source_text(download(url), url).rstrip("\r\n") for url in SOURCES]
        combined = "\n\n".join(parts) + "\n"
        changed = write_if_changed(arguments.output, combined)
    except SyncError as error:
        print(f"sync failed: {error}", file=sys.stderr)
        return 1

    print(f"{'updated' if changed else 'unchanged'}: {arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
