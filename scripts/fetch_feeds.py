#!/usr/bin/env python3
"""Fetch YouTube channel feeds and write per-day JSON for the dashboard.

The channel list is read at run time from the "Youtube Channels XML Feeds"
section of https://davidgeeraerts.github.io/AI/chapters/07-resources.html
Videos are grouped by the calendar date in America/Los_Angeles, deduped by
video id, and merged into assets/data/days/YYYY-MM-DD.json.

YouTube's feeds endpoint sometimes returns 404 or 5xx for a valid channel
and then 200 a little later. Those responses, plus timeouts and connection
errors, are retried with exponential backoff and a little jitter. A channel
that still fails — HTTP error, timeout, invalid XML, or any other exception
— is logged and skipped. The other channels are saved, and videos already
stored for the failed channel are left in place. The process exits 0 in that
case so the workflow can publish the channels that succeeded. Only a missing
channel list is fatal, and that path does not touch stored days.
"""

from __future__ import annotations

import argparse
import http.client
import json
import random
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

SOURCE_URL = (
    "https://davidgeeraerts.github.io/AI/chapters/07-resources.html"
    "#youtube-channels-xml-feeds"
)
SECTION_ID = "youtube-channels-xml-feeds"
TIMEZONE = "America/Los_Angeles"
LA = ZoneInfo(TIMEZONE)
USER_AGENT = (
    "Mozilla/5.0 (compatible; YouTubeFeedDashboard/1.0; "
    "+https://github.com/DavidGeeraerts/youtube-feed-dashboard-ai)"
)
# Retry policy for HTTP fetches. These five numbers are the place to tune it.
#
# YouTube's /feeds/videos.xml endpoint intermittently returns 404 or 5xx for
# a channel that is fine a moment later. Each URL is tried FEED_FETCH_ATTEMPTS
# times (the first try plus retries). After failed try n (0-based) the wait is
# min(FEED_RETRY_BASE_DELAY * 2**n, FEED_RETRY_MAX_DELAY) plus up to
# FEED_RETRY_JITTER seconds.
#
# Defaults: 5 tries, waits of 2s, 4s, 8s, and 8s, jitter up to 0.5s, socket
# timeout 8s. For the 9 channels this dashboard follows:
# - every feed returns an immediate error: about 3.5 minutes of sleep, then
#   the run still saves whichever channels succeeded
# - every attempt hangs until the socket timeout and then backs off: about
#   10 minutes, inside the workflow's 20-minute job limit
FEED_FETCH_ATTEMPTS = 5
FEED_FETCH_TIMEOUT = 8.0
FEED_RETRY_BASE_DELAY = 2.0
FEED_RETRY_MAX_DELAY = 8.0
FEED_RETRY_JITTER = 0.5
# Retried for any URL, along with every 5xx. 404 is omitted on purpose:
# only a YouTube channel feed treats 404 as transient. See retryable_fetch_error.
_RETRYABLE_HTTP_STATUSES = frozenset({408, 425, 429})
ATOM = "http://www.w3.org/2005/Atom"
YT = "http://www.youtube.com/xml/schemas/2015"
MEDIA = "http://search.yahoo.com/mrss/"
VIDEO_FIELDS = ("id", "title", "url", "channel", "channel_id", "published", "thumbnail")


class FetchError(Exception):
    """A single HTTP fetch failed."""


class FeedParseError(Exception):
    """A feed body was not usable Atom XML."""


class FatalFetchError(Exception):
    """The channel list itself could not be read. Stored days are left untouched."""


def qname(namespace: str, tag: str) -> str:
    return f"{{{namespace}}}{tag}"


def page_url(source_url: str) -> str:
    return source_url.split("#", 1)[0]


def parse_datetime(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def la_date_of(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(LA).date().isoformat()


def https_url(url: str) -> str:
    text = url.strip()
    if text.startswith("//"):
        text = "https:" + text
    parsed = urllib.parse.urlparse(text)
    if parsed.scheme != "https" or not parsed.netloc:
        return ""
    return text


def channel_feed(url: str) -> dict | None:
    text = url.strip()
    if text.startswith("//"):
        text = "https:" + text
    parsed = urllib.parse.urlparse(text)
    host = parsed.netloc.lower().removeprefix("www.")
    if parsed.scheme not in {"http", "https"} or host != "youtube.com":
        return None
    if not parsed.path.rstrip("/").endswith("/feeds/videos.xml"):
        return None
    channel_ids = urllib.parse.parse_qs(parsed.query).get("channel_id") or []
    channel_id = channel_ids[0].strip() if channel_ids else ""
    if not channel_id:
        return None
    return {
        "channel_id": channel_id,
        "feed_url": f"https://www.youtube.com/feeds/videos.xml?channel_id={urllib.parse.quote(channel_id)}",
    }


@dataclass
class ChannelList:
    section_found: bool
    channels: list[dict]


class _ChannelParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.section_found = False
        self._in_section = False
        self._depth = 0
        self._capture = False
        self._href = ""
        self._parts: list[str] = []
        self.section_links: list[dict] = []
        self.page_links: list[dict] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value or "" for key, value in attrs}
        if tag == "section" and attr.get("id") == SECTION_ID and not self._in_section:
            self.section_found = True
            self._in_section = True
            self._depth = 1
        elif tag == "section" and self._in_section:
            self._depth += 1
        if tag == "a":
            href = attr.get("href", "").strip()
            if channel_feed(href):
                self._capture = True
                self._href = href
                self._parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._capture:
            name = " ".join("".join(self._parts).split())
            self._add(name, self._href)
            self._capture = False
            self._href = ""
            self._parts = []
        if tag == "section" and self._in_section:
            self._depth -= 1
            if self._depth <= 0:
                self._in_section = False

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._parts.append(data)

    def _add(self, name: str, href: str) -> None:
        feed = channel_feed(href)
        if not feed:
            return
        record = {
            "name": name or feed["channel_id"],
            "channel_id": feed["channel_id"],
            "feed_url": feed["feed_url"],
        }
        self.page_links.append(record)
        if self._in_section:
            self.section_links.append(record)


def dedupe_channels(channels: list[dict]) -> list[dict]:
    seen: set[str] = set()
    unique: list[dict] = []
    for channel in channels:
        if channel["channel_id"] in seen:
            continue
        seen.add(channel["channel_id"])
        unique.append(channel)
    return unique


def parse_channel_list(html: str) -> ChannelList:
    parser = _ChannelParser()
    parser.feed(html)
    parser.close()
    chosen = parser.section_links if parser.section_found else parser.page_links
    return ChannelList(section_found=parser.section_found, channels=dedupe_channels(chosen))


def _text(node: ET.Element | None) -> str:
    if node is None or node.text is None:
        return ""
    return node.text.strip()


def _video_id(entry: ET.Element) -> str:
    explicit = _text(entry.find(qname(YT, "videoId")))
    if explicit:
        return explicit
    raw = _text(entry.find(qname(ATOM, "id")))
    prefix = "yt:video:"
    if raw.startswith(prefix):
        return raw[len(prefix) :]
    return ""


def _alternate_link(entry: ET.Element) -> str:
    for link in entry.findall(qname(ATOM, "link")):
        rel = link.attrib.get("rel", "alternate")
        href = link.attrib.get("href", "")
        if rel == "alternate" and href:
            return href
    return ""


def _thumbnail(entry: ET.Element, video_id: str) -> str:
    for thumb in entry.iter(qname(MEDIA, "thumbnail")):
        url = https_url(thumb.attrib.get("url", ""))
        if url:
            return url
    return f"https://i.ytimg.com/vi/{urllib.parse.quote(video_id)}/hqdefault.jpg"


def parse_feed(xml_bytes: bytes) -> tuple[str, list[dict]]:
    if xml_bytes.startswith(b"\xef\xbb\xbf"):
        xml_bytes = xml_bytes[3:]
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise FeedParseError(f"invalid XML: {exc}") from exc
    if root.tag != qname(ATOM, "feed"):
        raise FeedParseError("response is not an Atom feed")
    feed_name = _text(root.find(qname(ATOM, "title")))
    videos: list[dict] = []
    seen: set[str] = set()
    for entry in root.findall(qname(ATOM, "entry")):
        video_id = _video_id(entry)
        published_raw = _text(entry.find(qname(ATOM, "published")))
        if not video_id or not published_raw:
            continue
        try:
            published = parse_datetime(published_raw)
        except ValueError:
            continue
        if video_id in seen:
            continue
        seen.add(video_id)
        watch = https_url(_alternate_link(entry)) or f"https://www.youtube.com/watch?v={urllib.parse.quote(video_id)}"
        title = _text(entry.find(qname(ATOM, "title"))) or "(untitled)"
        videos.append(
            {
                "id": video_id,
                "title": title,
                "url": watch,
                "published": published,
                "thumbnail": _thumbnail(entry, video_id),
            }
        )
    return feed_name, videos


def normalize_video(video: dict) -> dict | None:
    video_id = str(video.get("id") or "").strip()
    if not video_id:
        return None
    published = str(video.get("published") or "")
    return {
        "id": video_id,
        "title": str(video.get("title") or "(untitled)"),
        "url": str(video.get("url") or f"https://www.youtube.com/watch?v={video_id}"),
        "channel": str(video.get("channel") or ""),
        "channel_id": str(video.get("channel_id") or ""),
        "published": published,
        "thumbnail": str(video.get("thumbnail") or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"),
    }


def load_days(data_dir: Path) -> dict[str, list[dict]]:
    days_dir = data_dir / "days"
    loaded: dict[str, list[dict]] = {}
    if not days_dir.is_dir():
        return loaded
    for path in sorted(days_dir.glob("*.json")):
        if len(path.stem) != 10 or path.stem[4] != "-" or path.stem[7] != "-":
            continue
        try:
            datetime.strptime(path.stem, "%Y-%m-%d")
        except ValueError:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        raw_videos = payload.get("videos") if isinstance(payload, dict) else None
        if not isinstance(raw_videos, list):
            continue
        videos: list[dict] = []
        for item in raw_videos:
            if isinstance(item, dict):
                normalized = normalize_video(item)
                if normalized:
                    videos.append(normalized)
        loaded[path.stem] = videos
    return loaded


def merge_days(existing: dict[str, list[dict]], incoming: list[dict]) -> dict[str, list[dict]]:
    """Add new videos. A video id already stored stays on its original day."""
    merged = {day: [dict(video) for video in videos] for day, videos in existing.items()}
    located = {video["id"]: day for day, videos in merged.items() for video in videos}
    for video in incoming:
        day = video["day"]
        stored = {field: video[field] for field in VIDEO_FIELDS}
        previous = located.get(stored["id"])
        if previous:
            for index, old in enumerate(merged[previous]):
                if old["id"] != stored["id"]:
                    continue
                updated = dict(old)
                for field in ("title", "url", "thumbnail", "channel", "channel_id"):
                    if stored.get(field):
                        updated[field] = stored[field]
                merged[previous][index] = updated
                break
            continue
        merged.setdefault(day, []).append(stored)
        located[stored["id"]] = day
    return merged


def published_sort_key(video: dict) -> tuple:
    raw = video.get("published") or ""
    try:
        moment = parse_datetime(raw)
    except ValueError:
        moment = datetime.min.replace(tzinfo=timezone.utc)
    return (moment, video.get("id") or "")


def write_json(path: Path, payload: dict) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)
    return True


def _http_status(message: str) -> int | None:
    parts = message.split()
    if len(parts) < 2 or parts[0] != "HTTP":
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


def retryable_fetch_error(message: str, url: str) -> bool:
    """True when this failure is worth another try.

    A 404 is retried only for a YouTube channel feed. That endpoint returns
    404 for valid channels during short outages. A 404 on the channel list
    page is treated as final.
    """
    if message == "timeout" or message.startswith("connection error"):
        return True
    status = _http_status(message)
    if status is None:
        return False
    if status in _RETRYABLE_HTTP_STATUSES or 500 <= status <= 599:
        return True
    return status == 404 and channel_feed(url) is not None


def retry_delay(failed_attempt: int, random_fn=None) -> float:
    """Seconds to wait after failed attempt ``failed_attempt`` (0-based)."""
    if failed_attempt < 0:
        raise ValueError("failed_attempt must be >= 0")
    if random_fn is None:
        random_fn = random.random
    delay = min(FEED_RETRY_BASE_DELAY * (2 ** failed_attempt), FEED_RETRY_MAX_DELAY)
    jitter = FEED_RETRY_JITTER
    if jitter:
        delay += jitter * float(random_fn())
    return delay


def failure_message(exc: Exception) -> str:
    if isinstance(exc, (FetchError, FeedParseError)):
        return str(exc)
    return f"unexpected error: {type(exc).__name__}: {exc}"


def fetch_bytes(url: str, timeout: float = 20.0) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/atom+xml, application/xml, text/xml, text/html;q=0.9, */*;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read(5_000_001)
    except urllib.error.HTTPError as exc:
        raise FetchError(f"HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise FetchError(f"connection error: {reason}") from exc
    except (TimeoutError, ConnectionError, http.client.HTTPException) as exc:
        raise FetchError(f"connection error: {exc}") from exc
    if len(data) > 5_000_000:
        raise FetchError("response too large")
    if data[:2] == b"\x1f\x8b":
        import gzip

        try:
            data = gzip.decompress(data)
        except OSError as exc:
            raise FetchError("could not decompress response") from exc
    return data


def fetch_bytes_retry(
    url: str,
    attempts: int | None = None,
    timeout: float | None = None,
    *,
    sleeper=None,
    fetch=None,
    random_fn=None,
) -> bytes:
    """Fetch ``url``, retrying transient failures with exponential backoff.

    ``attempts`` includes the first try. Pass ``sleeper``, ``fetch``, and
    ``random_fn`` in tests so nothing sleeps or touches the network.
    """
    if attempts is None:
        attempts = FEED_FETCH_ATTEMPTS
    if timeout is None:
        timeout = FEED_FETCH_TIMEOUT
    if sleeper is None:
        sleeper = time.sleep
    if fetch is None:
        fetch = fetch_bytes
    if random_fn is None:
        random_fn = random.random
    if attempts < 1:
        raise ValueError("attempts must be at least 1")

    last = "fetch failed"
    tries = 0
    while tries < attempts:
        tries += 1
        try:
            return fetch(url, timeout=timeout)
        except FetchError as exc:
            last = str(exc)
            if tries >= attempts or not retryable_fetch_error(last, url):
                break
            delay = retry_delay(tries - 1, random_fn=random_fn)
            print(
                f"retrying fetch after {last} "
                f"(failed attempt {tries} of {attempts}, waiting {delay:.1f}s): {url}",
                file=sys.stderr,
            )
            sleeper(delay)
    if tries > 1 and retryable_fetch_error(last, url):
        raise FetchError(f"{last} after {tries} attempts")
    raise FetchError(last)


def update_dashboard(
    data_dir: Path,
    source_url: str = SOURCE_URL,
    *,
    fetcher=fetch_bytes_retry,
    now: datetime | None = None,
    pause: float = 0.25,
) -> dict:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    try:
        page = fetcher(page_url(source_url))
    except FetchError as exc:
        raise FatalFetchError(f"Could not download the channel list: {exc}") from exc
    html = page.decode("utf-8", errors="replace")
    parsed = parse_channel_list(html)
    if not parsed.section_found:
        print(
            f"warning: section #{SECTION_ID} was not found; using every channel feed link on the page",
            file=sys.stderr,
        )
    if not parsed.channels:
        raise FatalFetchError(
            "No YouTube channel XML feeds found on the resources page "
            f"({source_url}). Expected a list inside section id '{SECTION_ID}'."
        )

    incoming: list[dict] = []
    reports: list[dict] = []
    seen_ids: set[str] = set()
    for index, channel in enumerate(parsed.channels):
        if pause and index:
            time.sleep(pause)
        report = {
            "name": channel["name"],
            "channel_id": channel["channel_id"],
            "feed_url": channel["feed_url"],
            "feed_name": None,
            "status": "error",
            "videos": 0,
            "error": None,
        }
        # Build this channel's records locally. A failure here must not
        # discard videos already accepted from earlier channels, and must
        # not publish a partial list from this channel.
        channel_records: list[dict] = []
        try:
            body = fetcher(channel["feed_url"])
            feed_name, videos = parse_feed(body)
            report["feed_name"] = feed_name or None
            report["videos"] = len(videos)
            report["status"] = "ok" if videos else "empty"
            for video in videos:
                if video["id"] in seen_ids:
                    continue
                channel_records.append(
                    {
                        "id": video["id"],
                        "title": video["title"],
                        "url": video["url"],
                        "channel": channel["name"],
                        "channel_id": channel["channel_id"],
                        "published": video["published"].astimezone(timezone.utc).isoformat(timespec="seconds"),
                        "thumbnail": video["thumbnail"],
                        "day": la_date_of(video["published"]),
                    }
                )
        except Exception as exc:
            report["status"] = "error"
            report["videos"] = 0
            report["feed_name"] = None
            report["error"] = failure_message(exc)
            reports.append(report)
            print(f"{channel['name']}: error ({report['error']})", file=sys.stderr)
            if not isinstance(exc, (FetchError, FeedParseError)):
                traceback.print_exc()
            continue
        for record in channel_records:
            seen_ids.add(record["id"])
            incoming.append(record)
        reports.append(report)
        print(f"{channel['name']}: {report['status']} ({report['videos']} videos)")

    merged = merge_days(load_days(data_dir), incoming)
    days_written = []
    video_count = 0
    for day in sorted(merged):
        videos = sorted(merged[day], key=published_sort_key, reverse=True)
        video_count += len(videos)
        changed = write_json(
            data_dir / "days" / f"{day}.json",
            {"date": day, "timezone": TIMEZONE, "videos": videos},
        )
        if changed:
            days_written.append(day)
    day_names = sorted(merged, reverse=True)
    today = la_date_of(moment)
    index_payload = {
        "timezone": TIMEZONE,
        "generated_at": moment.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "today": today,
        "source": source_url,
        "section_found": parsed.section_found,
        "channels": reports,
        "days": day_names,
    }
    write_json(data_dir / "index.json", index_payload)
    today_count = len(merged.get(today, []))
    errors = sum(1 for report in reports if report["status"] == "error")
    return {
        "channels": reports,
        "days": day_names,
        "days_written": days_written,
        "video_count": video_count,
        "today": today,
        "today_count": today_count,
        "errors": errors,
        "section_found": parsed.section_found,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="assets/data", help="Directory for index.json and days/")
    parser.add_argument("--source-url", default=SOURCE_URL, help="Resources page, with or without the section hash")
    args = parser.parse_args(argv)
    try:
        summary = update_dashboard(Path(args.data_dir), args.source_url)
    except FatalFetchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(
        f"today {summary['today']}: {summary['today_count']} videos; "
        f"{summary['video_count']} stored across {len(summary['days'])} days; "
        f"{summary['errors']} feed errors"
    )
    failed = [channel for channel in summary["channels"] if channel["status"] == "error"]
    if failed:
        print(
            "Failed channels (stored videos kept; other channels still saved):",
            file=sys.stderr,
        )
        for channel in failed:
            print(f"  - {channel['name']}: {channel['error']}", file=sys.stderr)
    # Exit 0 even when every channel feed failed. The day files already on
    # disk are still valid, and index.json now records which feeds failed,
    # so the workflow can publish that instead of leaving the site stale.
    return 0


if __name__ == "__main__":
    sys.exit(main())
