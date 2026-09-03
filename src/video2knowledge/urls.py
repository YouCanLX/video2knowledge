from __future__ import annotations

import re
from urllib.parse import urlparse


def extract_bilibili_bvid(url: str) -> str:
    parsed = urlparse(url.strip())
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not (
        hostname == "bilibili.com" or hostname.endswith(".bilibili.com")
    ):
        raise ValueError("Enter a valid bilibili.com video URL")
    match = re.search(r"(?<![0-9A-Za-z])(BV[0-9A-Za-z]{10})(?![0-9A-Za-z])", parsed.path)
    if not match:
        raise ValueError("The Bilibili URL does not contain a valid BV video ID")
    return match.group(1)


def extract_bilibili_creator_id(url: str) -> int:
    parsed = urlparse(url.strip())
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not (
        hostname == "bilibili.com" or hostname.endswith(".bilibili.com")
    ):
        raise ValueError("Enter a valid bilibili.com creator URL")
    match = re.fullmatch(r"/(\d+)(?:/(?:lists|upload/video))?/?", parsed.path)
    if not match or int(match.group(1)) <= 0:
        raise ValueError("The Bilibili URL does not contain a valid creator ID")
    return int(match.group(1))
