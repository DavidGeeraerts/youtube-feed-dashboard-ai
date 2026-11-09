#!/usr/bin/env python3
"""Fetch YouTube channel feeds and write per-day JSON for the dashboard.

The channel list is read at run time from the "Youtube Channels XML Feeds"
section of https://davidgeeraerts.github.io/AI/chapters/07-resources.html
Videos are grouped by the calendar date in America/Los_Angeles, deduped by
video id, and merged into assets/data/days/YYYY-MM-DD.json. A feed that
fails or returns nothing is recorded and does not remove videos already stored.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
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
    except TimeoutError as exc:
        raise FetchError("timeout") from exc
    if len(data) > 5_000_000:
        raise FetchError("response too large")
    if data[:2] == b"\x1f\x8b":
        import gzip

        try:
            data = gzip.decompress(data)
        except OSError as exc:
            raise FetchError("could not decompress response") from exc
    return data


def fetch_bytes_retry(url: str, attempts: int = 2, timeout: float = 20.0) -> bytes:
    last = "fetch failed"
    for attempt in range(attempts):
        try:
            return fetch_bytes(url, timeout=timeout)
        except FetchError as exc:
            last = str(exc)
            retry = last == "timeout" or last.startswith("connection error") or last.startswith("HTTP 5") or last == "HTTP 429"
            if not retry or attempt + 1 == attempts:
                break
            time.sleep(1.5)
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
        try:
            body = fetcher(channel["feed_url"])
            feed_name, videos = parse_feed(body)
        except (FetchError, FeedParseError) as exc:
            report["error"] = str(exc)
            reports.append(report)
            print(f"{channel['name']}: error ({exc})", file=sys.stderr)
            continue
        report["feed_name"] = feed_name or None
        report["videos"] = len(videos)
        if videos:
            report["status"] = "ok"
        else:
            report["status"] = "empty"
        reports.append(report)
        print(f"{channel['name']}: {report['status']} ({len(videos)} videos)")
        for video in videos:
            if video["id"] in seen_ids:
                continue
            seen_ids.add(video["id"])
            record = {
                "id": video["id"],
                "title": video["title"],
                "url": video["url"],
                "channel": channel["name"],
                "channel_id": channel["channel_id"],
                "published": video["published"].astimezone(timezone.utc).isoformat(timespec="seconds"),
                "thumbnail": video["thumbnail"],
                "day": la_date_of(video["published"]),
            }
            incoming.append(record)

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
    return 0


if __name__ == "__main__":
    sys.exit(main())
