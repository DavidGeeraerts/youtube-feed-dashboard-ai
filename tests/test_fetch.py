import json
import tempfile
import unittest
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import fetch_feeds


REAL_SECTION = """
<section id="other">
  <a href="https://www.youtube.com/feeds/videos.xml?channel_id=SHOULD_NOT">Nope</a>
</section>
<section id="youtube-channels-xml-feeds" class="level2" data-number="7.4">
<h2 data-number="7.4" class="anchored" data-anchor-id="youtube-channels-xml-feeds"><span class="header-section-number">7.4</span> Youtube Channels XML Feeds</h2>
<ul>
<li><a href="https://www.youtube.com/feeds/videos.xml?channel_id=UCeNLqAes-kUMjWksPA6d-BA">0xSero</a></li>
<li><a href="https://www.youtube.com/feeds/videos.xml?channel_id=UCm4Sy7W36u_ZFOZWX9cd07w">Agent Zero</a></li>
<li><a href="https://www.youtube.com/feeds/videos.xml?channel_id=UCgkApalw5crKXOtr_mqtPQg">Agentic AI Foundation</a></li>
<li><a href="https://www.youtube.com/feeds/videos.xml?channel_id=UCLKPca3kwwd-B59HNr-_lvA">AI Engineer</a></li>
<li><a href="https://www.youtube.com/feeds/videos.xml?channel_id=UCXUPKJO5MZQN11PqgIvyuvQ">Andrej Karpathy</a></li>
<li><a href="https://www.youtube.com/feeds/videos.xml?channel_id=UC-mexo-76-J1MlQM8NkWCYw">Armin Ronacher</a></li>
<li><a href="https://www.youtube.com/feeds/videos.xml?channel_id=UCKWaEZ-_VweaEx1j62do_vQ">IBM Technology</a></li>
<li><a href="https://www.youtube.com/feeds/videos.xml?channel_id=UCgUfJoPtkt7-RiiuYh4vmGA">Kai</a></li>
<li><a href="https://www.youtube.com/feeds/videos.xml?channel_id=UCPbwhExawYrn9xxI21TFfyw">The Pragmatic Engineer</a></li>
<li><a href="https://www.youtube.com/feeds/videos.xml?channel_id=UCgUfJoPtkt7-RiiuYh4vmGA">Kai again</a></li>
</ul>
</section>
<section id="youtube-videos">
  <a href="https://www.youtube.com/feeds/videos.xml?channel_id=UCAFTER">After</a>
</section>
"""

KAI_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns:media="http://search.yahoo.com/mrss/" xmlns="http://www.w3.org/2005/Atom">
  <title>Kai</title>
  <entry>
    <id>yt:video:PWoc_SfcsAQ</id>
    <yt:videoId>PWoc_SfcsAQ</yt:videoId>
    <title>Is This the End of NVIDIA's Memory Chip (NCM)</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=PWoc_SfcsAQ"/>
    <published>2026-11-09T15:30:26+00:00</published>
    <media:group>
      <media:thumbnail url="https://i1.ytimg.com/vi/PWoc_SfcsAQ/hqdefault.jpg"/>
    </media:group>
  </entry>
  <entry>
    <id>yt:video:PWoc_SfcsAQ</id>
    <yt:videoId>PWoc_SfcsAQ</yt:videoId>
    <title>Duplicate</title>
    <published>2026-11-09T15:30:26+00:00</published>
  </entry>
  <entry>
    <id>yt:video:lateone</id>
    <title>Just before midnight PT</title>
    <published>2026-11-09T07:30:00Z</published>
  </entry>
</feed>
"""


class ParseTests(unittest.TestCase):
    def test_real_section_lists_nine_channels_in_order(self):
        parsed = fetch_feeds.parse_channel_list(REAL_SECTION)
        self.assertTrue(parsed.section_found)
        names = [channel["name"] for channel in parsed.channels]
        self.assertEqual(
            names,
            [
                "0xSero",
                "Agent Zero",
                "Agentic AI Foundation",
                "AI Engineer",
                "Andrej Karpathy",
                "Armin Ronacher",
                "IBM Technology",
                "Kai",
                "The Pragmatic Engineer",
            ],
        )
        armin = parsed.channels[5]
        self.assertEqual(armin["channel_id"], "UC-mexo-76-J1MlQM8NkWCYw")
        self.assertTrue(armin["feed_url"].startswith("https://www.youtube.com/feeds/videos.xml?channel_id="))

    def test_normalizes_http_and_ignores_non_feeds(self):
        html = """
        <section id="youtube-channels-xml-feeds">
          <a href="http://youtube.com/feeds/videos.xml?channel_id=UCabc&extra=1">Example</a>
          <a href="https://example.com/feeds/videos.xml?channel_id=UCnope">Other</a>
          <a href="//www.youtube.com/feeds/videos.xml?channel_id=UCdef">Relative</a>
        </section>
        """
        parsed = fetch_feeds.parse_channel_list(html)
        self.assertEqual(
            [channel["feed_url"] for channel in parsed.channels],
            [
                "https://www.youtube.com/feeds/videos.xml?channel_id=UCabc",
                "https://www.youtube.com/feeds/videos.xml?channel_id=UCdef",
            ],
        )

    def test_fallback_when_section_missing(self):
        html = '<a href="https://www.youtube.com/feeds/videos.xml?channel_id=UConly">Only</a>'
        parsed = fetch_feeds.parse_channel_list(html)
        self.assertFalse(parsed.section_found)
        self.assertEqual(parsed.channels[0]["name"], "Only")

    def test_feed_buckets_pacific_time_and_dedupes(self):
        feed_name, videos = fetch_feeds.parse_feed(KAI_FEED)
        self.assertEqual(feed_name, "Kai")
        self.assertEqual([video["id"] for video in videos], ["PWoc_SfcsAQ", "lateone"])
        self.assertEqual(videos[0]["thumbnail"], "https://i1.ytimg.com/vi/PWoc_SfcsAQ/hqdefault.jpg")
        self.assertEqual(videos[1]["url"], "https://www.youtube.com/watch?v=lateone")
        self.assertTrue(videos[1]["thumbnail"].endswith("/hqdefault.jpg"))
        # 2026-11-09 is PST (UTC-8): 07:30Z is still November 8 locally, 15:30Z is November 9.
        self.assertEqual(fetch_feeds.la_date_of(videos[0]["published"]), "2026-11-09")
        self.assertEqual(fetch_feeds.la_date_of(videos[1]["published"]), "2026-11-08")

    def test_daylight_saving_boundary(self):
        # July 2026 is PDT (UTC-7).
        before = fetch_feeds.parse_datetime("2026-07-15T06:59:00+00:00")
        after = fetch_feeds.parse_datetime("2026-07-15T07:00:00+00:00")
        self.assertEqual(fetch_feeds.la_date_of(before), "2026-07-14")
        self.assertEqual(fetch_feeds.la_date_of(after), "2026-07-15")

    def test_invalid_xml_raises(self):
        with self.assertRaises(fetch_feeds.FeedParseError):
            fetch_feeds.parse_feed(b"<html>nope</html>")
        with self.assertRaises(fetch_feeds.FeedParseError):
            fetch_feeds.parse_feed(b"<feed><title>unclosed")

    def test_empty_feed(self):
        name, videos = fetch_feeds.parse_feed(
            b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>Empty</title></feed>'
        )
        self.assertEqual(name, "Empty")
        self.assertEqual(videos, [])


class UpdateTests(unittest.TestCase):
    def test_merge_keeps_history_and_does_not_move_days(self):
        existing = {
            "2026-11-01": [
                {
                    "id": "oldvid",
                    "title": "Old title",
                    "url": "https://www.youtube.com/watch?v=oldvid",
                    "channel": "Kai",
                    "channel_id": "UCgUfJoPtkt7-RiiuYh4vmGA",
                    "published": "2026-11-01T18:00:00+00:00",
                    "thumbnail": "https://i.ytimg.com/vi/oldvid/hqdefault.jpg",
                }
            ]
        }
        incoming = [
            {
                "id": "oldvid",
                "title": "Updated title",
                "url": "https://www.youtube.com/watch?v=oldvid",
                "channel": "Kai",
                "channel_id": "UCgUfJoPtkt7-RiiuYh4vmGA",
                "published": "2026-11-09T18:00:00+00:00",
                "thumbnail": "https://i.ytimg.com/vi/oldvid/hqdefault.jpg",
                "day": "2026-11-09",
            },
            {
                "id": "newvid",
                "title": "New",
                "url": "https://www.youtube.com/watch?v=newvid",
                "channel": "Kai",
                "channel_id": "UCgUfJoPtkt7-RiiuYh4vmGA",
                "published": "2026-11-09T20:00:00+00:00",
                "thumbnail": "https://i.ytimg.com/vi/newvid/hqdefault.jpg",
                "day": "2026-11-09",
            },
        ]
        merged = fetch_feeds.merge_days(existing, incoming)
        self.assertEqual([video["id"] for video in merged["2026-11-01"]], ["oldvid"])
        self.assertEqual(merged["2026-11-01"][0]["title"], "Updated title")
        self.assertEqual([video["id"] for video in merged["2026-11-09"]], ["newvid"])

    def test_failed_feed_keeps_stored_videos(self):
        html = """
        <section id="youtube-channels-xml-feeds">
          <a href="https://www.youtube.com/feeds/videos.xml?channel_id=UCgUfJoPtkt7-RiiuYh4vmGA">Kai</a>
          <a href="https://www.youtube.com/feeds/videos.xml?channel_id=UCbroken">Broken</a>
        </section>
        """

        def fetcher(url: str) -> bytes:
            if url.endswith("07-resources.html"):
                return html.encode()
            if "UCbroken" in url:
                raise fetch_feeds.FetchError("HTTP 503")
            if "UCgUfJoPtkt7-RiiuYh4vmGA" in url:
                return KAI_FEED
            raise AssertionError(url)

        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            (data / "days").mkdir()
            (data / "days" / "2026-10-01.json").write_text(
                json.dumps(
                    {
                        "date": "2026-10-01",
                        "timezone": "America/Los_Angeles",
                        "videos": [
                            {
                                "id": "kept",
                                "title": "Kept",
                                "url": "https://www.youtube.com/watch?v=kept",
                                "channel": "Broken",
                                "channel_id": "UCbroken",
                                "published": "2026-10-01T18:00:00+00:00",
                                "thumbnail": "https://i.ytimg.com/vi/kept/hqdefault.jpg",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            summary = fetch_feeds.update_dashboard(
                data,
                fetcher=fetcher,
                now=datetime(2026, 11, 9, 18, 0, tzinfo=timezone.utc),
                pause=0,
            )
            self.assertEqual(summary["errors"], 1)
            self.assertEqual(summary["today"], "2026-11-09")
            self.assertGreaterEqual(summary["today_count"], 1)
            kept = json.loads((data / "days" / "2026-10-01.json").read_text(encoding="utf-8"))
            self.assertEqual(kept["videos"][0]["id"], "kept")
            fresh = json.loads((data / "days" / "2026-11-09.json").read_text(encoding="utf-8"))
            self.assertEqual(fresh["videos"][0]["channel"], "Kai")
            index = json.loads((data / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(index["timezone"], "America/Los_Angeles")
            broken = [channel for channel in index["channels"] if channel["name"] == "Broken"][0]
            self.assertEqual(broken["status"], "error")
            self.assertIn("2026-10-01", index["days"])

    def test_missing_channel_list_does_not_wipe_days(self):
        def fetcher(url: str) -> bytes:
            raise fetch_feeds.FetchError("HTTP 500")

        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            day = data / "days"
            day.mkdir(parents=True)
            target = day / "2026-11-09.json"
            target.write_text("{}\n", encoding="utf-8")
            with self.assertRaises(fetch_feeds.FatalFetchError):
                fetch_feeds.update_dashboard(data, fetcher=fetcher, pause=0)
            self.assertTrue(target.exists())
            self.assertFalse((data / "index.json").exists())


TWO_CHANNEL_PAGE = """
<section id="youtube-channels-xml-feeds">
  <a href="https://www.youtube.com/feeds/videos.xml?channel_id=UCbroken">Broken</a>
  <a href="https://www.youtube.com/feeds/videos.xml?channel_id=UCgUfJoPtkt7-RiiuYh4vmGA">Kai</a>
</section>
"""

YOUTUBE_FEED = "https://www.youtube.com/feeds/videos.xml?channel_id=UCok"
CHANNEL_LIST_URL = "https://davidgeeraerts.github.io/AI/chapters/07-resources.html"


class NoNetworkTestCase(unittest.TestCase):
    """Fail if a test sleeps or opens a real socket."""

    def setUp(self):
        original_sleep = fetch_feeds.time.sleep
        original_open = urllib.request.urlopen

        def forbid_sleep(seconds):
            raise AssertionError(f"real sleep of {seconds}s")

        def forbid_urlopen(*args, **kwargs):
            raise AssertionError(f"real network call: {args!r} {kwargs!r}")

        fetch_feeds.time.sleep = forbid_sleep
        urllib.request.urlopen = forbid_urlopen
        self.addCleanup(lambda: setattr(fetch_feeds.time, "sleep", original_sleep))
        self.addCleanup(lambda: setattr(urllib.request, "urlopen", original_open))


def retrying_fetcher(fetch, sleeps, random_value=0.0):
    def fetcher(url: str) -> bytes:
        return fetch_feeds.fetch_bytes_retry(
            url,
            fetch=fetch,
            sleeper=sleeps.append,
            random_fn=lambda: random_value,
        )

    return fetcher


def write_kept_day(data: Path) -> None:
    day = data / "days"
    day.mkdir(parents=True, exist_ok=True)
    (day / "2026-10-01.json").write_text(
        json.dumps(
            {
                "date": "2026-10-01",
                "timezone": "America/Los_Angeles",
                "videos": [
                    {
                        "id": "kept",
                        "title": "Kept",
                        "url": "https://www.youtube.com/watch?v=kept",
                        "channel": "Broken",
                        "channel_id": "UCbroken",
                        "published": "2026-10-01T18:00:00+00:00",
                        "thumbnail": "https://i.ytimg.com/vi/kept/hqdefault.jpg",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


class RetryTests(NoNetworkTestCase):
    def test_shipped_retry_policy_stays_within_a_few_minutes(self):
        self.assertEqual(fetch_feeds.FEED_FETCH_ATTEMPTS, 5)
        self.assertEqual(fetch_feeds.FEED_FETCH_TIMEOUT, 8.0)
        self.assertEqual(fetch_feeds.FEED_RETRY_BASE_DELAY, 2.0)
        self.assertEqual(fetch_feeds.FEED_RETRY_MAX_DELAY, 8.0)
        self.assertEqual(fetch_feeds.FEED_RETRY_JITTER, 0.5)
        plain = [fetch_feeds.retry_delay(i, random_fn=lambda: 0) for i in range(4)]
        self.assertEqual(plain, [2.0, 4.0, 8.0, 8.0])
        jittered = [fetch_feeds.retry_delay(i, random_fn=lambda: 1) for i in range(4)]
        self.assertEqual(jittered, [2.5, 4.5, 8.5, 8.5])
        # Nine channels, every attempt an immediate HTTP error.
        self.assertLessEqual(9 * sum(jittered), 4 * 60)
        # Nine channels, every attempt hangs for the full socket timeout, then backs off.
        hung = 9 * (fetch_feeds.FEED_FETCH_ATTEMPTS * fetch_feeds.FEED_FETCH_TIMEOUT + sum(jittered))
        self.assertLess(hung, 12 * 60)

    def test_404_then_200_recovers(self):
        calls = []
        sleeps = []
        body = b"<feed>ok</feed>"

        def fetch(url, timeout=0.0):
            calls.append((url, timeout))
            if len(calls) == 1:
                raise fetch_feeds.FetchError("HTTP 404")
            return body

        got = fetch_feeds.fetch_bytes_retry(
            YOUTUBE_FEED,
            fetch=fetch,
            sleeper=sleeps.append,
            random_fn=lambda: 0.25,
        )
        self.assertEqual(got, body)
        self.assertEqual([url for url, _timeout in calls], [YOUTUBE_FEED, YOUTUBE_FEED])
        self.assertEqual({timeout for _url, timeout in calls}, {fetch_feeds.FEED_FETCH_TIMEOUT})
        self.assertEqual(sleeps, [fetch_feeds.retry_delay(0, random_fn=lambda: 0.25)])
        self.assertEqual(sleeps[0], 2.125)

    def test_persistent_failure_stops_at_retry_limit(self):
        calls = []
        sleeps = []

        def fetch(url, timeout=0.0):
            calls.append(url)
            raise fetch_feeds.FetchError("HTTP 500")

        with self.assertRaises(fetch_feeds.FetchError) as caught:
            fetch_feeds.fetch_bytes_retry(
                YOUTUBE_FEED,
                fetch=fetch,
                sleeper=sleeps.append,
                random_fn=lambda: 1.0,
            )
        self.assertEqual(
            str(caught.exception),
            f"HTTP 500 after {fetch_feeds.FEED_FETCH_ATTEMPTS} attempts",
        )
        self.assertEqual(len(calls), fetch_feeds.FEED_FETCH_ATTEMPTS)
        self.assertEqual(
            sleeps,
            [fetch_feeds.retry_delay(i, random_fn=lambda: 1.0) for i in range(fetch_feeds.FEED_FETCH_ATTEMPTS - 1)],
        )
        self.assertGreater(sleeps[-1], sleeps[0])

    def test_youtube_404_gives_up_after_the_same_limit(self):
        calls = []

        def fetch(url, timeout=0.0):
            calls.append(url)
            raise fetch_feeds.FetchError("HTTP 404")

        with self.assertRaises(fetch_feeds.FetchError) as caught:
            fetch_feeds.fetch_bytes_retry(
                YOUTUBE_FEED,
                fetch=fetch,
                sleeper=lambda _delay: None,
                random_fn=lambda: 0.0,
            )
        self.assertEqual(str(caught.exception), f"HTTP 404 after {fetch_feeds.FEED_FETCH_ATTEMPTS} attempts")
        self.assertEqual(len(calls), fetch_feeds.FEED_FETCH_ATTEMPTS)

    def test_non_feed_404_and_other_client_errors_are_not_retried(self):
        cases = [
            (CHANNEL_LIST_URL, "HTTP 404"),
            (YOUTUBE_FEED, "HTTP 403"),
            (YOUTUBE_FEED, "HTTP 400"),
            (YOUTUBE_FEED, "response too large"),
        ]
        for url, message in cases:
            with self.subTest(url=url, message=message):
                calls = []
                sleeps = []

                def fetch(target, timeout=0.0, message=message):
                    calls.append(target)
                    raise fetch_feeds.FetchError(message)

                with self.assertRaises(fetch_feeds.FetchError) as caught:
                    fetch_feeds.fetch_bytes_retry(
                        url,
                        fetch=fetch,
                        sleeper=sleeps.append,
                        random_fn=lambda: 0.0,
                    )
                self.assertEqual(str(caught.exception), message)
                self.assertEqual(calls, [url])
                self.assertEqual(sleeps, [])

    def test_timeout_connection_and_5xx_are_retried_for_any_url(self):
        for message in ("timeout", "connection error: timed out", "HTTP 599"):
            with self.subTest(message=message):
                calls = []

                def fetch(url, timeout=0.0, message=message):
                    calls.append(url)
                    if len(calls) == 1:
                        raise fetch_feeds.FetchError(message)
                    return b"ok"

                got = fetch_feeds.fetch_bytes_retry(
                    CHANNEL_LIST_URL,
                    fetch=fetch,
                    sleeper=lambda _delay: None,
                    random_fn=lambda: 0.0,
                )
                self.assertEqual(got, b"ok")
                self.assertEqual(len(calls), 2)


class IsolationTests(NoNetworkTestCase):
    def _run(self, fetch, sleeps):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            write_kept_day(data)
            summary = fetch_feeds.update_dashboard(
                data,
                fetcher=retrying_fetcher(fetch, sleeps),
                now=datetime(2026, 11, 9, 18, 0, tzinfo=timezone.utc),
                pause=0,
            )
            kept = json.loads((data / "days" / "2026-10-01.json").read_text(encoding="utf-8"))
            index = json.loads((data / "index.json").read_text(encoding="utf-8"))
            kai_path = data / "days" / "2026-11-09.json"
            kai_day = json.loads(kai_path.read_text(encoding="utf-8")) if kai_path.exists() else None
            return summary, kept, index, kai_day

    def test_one_channel_failing_does_not_affect_others(self):
        calls = []
        sleeps = []

        def fetch(url, timeout=0.0):
            calls.append(url)
            if url.endswith("07-resources.html"):
                return TWO_CHANNEL_PAGE.encode()
            if "UCbroken" in url:
                raise fetch_feeds.FetchError("HTTP 404")
            if "UCgUfJoPtkt7-RiiuYh4vmGA" in url:
                return KAI_FEED
            raise AssertionError(url)

        summary, kept, index, kai_day = self._run(fetch, sleeps)
        self.assertEqual(summary["errors"], 1)
        self.assertEqual(kept["videos"][0]["id"], "kept")
        self.assertIsNotNone(kai_day)
        self.assertEqual(kai_day["videos"][0]["id"], "PWoc_SfcsAQ")
        self.assertEqual(kai_day["videos"][0]["channel"], "Kai")
        self.assertIn("2026-10-01", index["days"])
        self.assertIn("2026-11-09", index["days"])
        by_name = {channel["name"]: channel for channel in index["channels"]}
        self.assertEqual(by_name["Broken"]["status"], "error")
        self.assertEqual(by_name["Broken"]["error"], f"HTTP 404 after {fetch_feeds.FEED_FETCH_ATTEMPTS} attempts")
        self.assertEqual(by_name["Kai"]["status"], "ok")
        self.assertEqual(sum(1 for url in calls if "UCbroken" in url), fetch_feeds.FEED_FETCH_ATTEMPTS)
        self.assertEqual(sum(1 for url in calls if "UCgUfJoPtkt7-RiiuYh4vmGA" in url), 1)
        self.assertEqual(len(sleeps), fetch_feeds.FEED_FETCH_ATTEMPTS - 1)

    def test_malformed_xml_on_one_channel_is_isolated(self):
        calls = []
        sleeps = []

        def fetch(url, timeout=0.0):
            calls.append(url)
            if url.endswith("07-resources.html"):
                return TWO_CHANNEL_PAGE.encode()
            if "UCbroken" in url:
                return b"<feed><title>unclosed"
            if "UCgUfJoPtkt7-RiiuYh4vmGA" in url:
                return KAI_FEED
            raise AssertionError(url)

        summary, kept, index, kai_day = self._run(fetch, sleeps)
        self.assertEqual(summary["errors"], 1)
        self.assertEqual(kept["videos"][0]["id"], "kept")
        self.assertEqual(kept["videos"][0]["channel"], "Broken")
        self.assertIsNotNone(kai_day)
        self.assertEqual([video["channel"] for video in kai_day["videos"]], ["Kai"])
        by_name = {channel["name"]: channel for channel in index["channels"]}
        self.assertEqual(by_name["Broken"]["status"], "error")
        self.assertIn("invalid XML", by_name["Broken"]["error"])
        self.assertEqual(by_name["Kai"]["status"], "ok")
        self.assertGreater(by_name["Kai"]["videos"], 0)
        self.assertEqual(sum(1 for url in calls if "UCbroken" in url), 1)
        self.assertEqual(sleeps, [])

    def test_unexpected_exception_on_one_channel_is_isolated(self):
        calls = []

        def fetch(url, timeout=0.0):
            calls.append(url)
            if url.endswith("07-resources.html"):
                return TWO_CHANNEL_PAGE.encode()
            if "UCbroken" in url:
                raise RuntimeError("boom")
            if "UCgUfJoPtkt7-RiiuYh4vmGA" in url:
                return KAI_FEED
            raise AssertionError(url)

        summary, kept, index, kai_day = self._run(fetch, [])
        self.assertEqual(summary["errors"], 1)
        self.assertEqual(kept["videos"][0]["id"], "kept")
        self.assertEqual(kai_day["videos"][0]["channel"], "Kai")
        broken = [channel for channel in index["channels"] if channel["name"] == "Broken"][0]
        self.assertEqual(broken["error"], "unexpected error: RuntimeError: boom")
        self.assertEqual(sum(1 for url in calls if "UCbroken" in url), 1)
        self.assertEqual(sum(1 for url in calls if "UCgUfJoPtkt7-RiiuYh4vmGA" in url), 1)

    def test_every_feed_failing_still_keeps_stored_days_and_writes_index(self):
        def fetch(url, timeout=0.0):
            if url.endswith("07-resources.html"):
                return TWO_CHANNEL_PAGE.encode()
            raise fetch_feeds.FetchError("HTTP 404")

        summary, kept, index, kai_day = self._run(fetch, [])
        self.assertEqual(summary["errors"], 2)
        self.assertIsNone(kai_day)
        self.assertEqual(kept["videos"][0]["id"], "kept")
        self.assertEqual([channel["status"] for channel in index["channels"]], ["error", "error"])
        self.assertEqual(index["days"], ["2026-10-01"])

    def test_main_exits_zero_when_feeds_fail_and_one_when_the_list_is_missing(self):
        original = fetch_feeds.update_dashboard

        def succeed(data_dir, source_url):
            return {
                "today": "2026-11-10",
                "today_count": 1,
                "video_count": 4,
                "days": ["2026-11-10", "2026-10-01"],
                "errors": 1,
                "channels": [
                    {
                        "name": "Broken",
                        "channel_id": "UCbroken",
                        "status": "error",
                        "error": "HTTP 404 after 5 attempts",
                    },
                    {"name": "Kai", "channel_id": "UCkai", "status": "ok", "error": None},
                ],
            }

        def missing_list(data_dir, source_url):
            raise fetch_feeds.FatalFetchError("Could not download the channel list: HTTP 404")

        self.addCleanup(lambda: setattr(fetch_feeds, "update_dashboard", original))
        fetch_feeds.update_dashboard = succeed
        self.assertEqual(fetch_feeds.main(["--data-dir", "unused"]), 0)
        fetch_feeds.update_dashboard = missing_list
        self.assertEqual(fetch_feeds.main(["--data-dir", "unused"]), 1)


if __name__ == "__main__":
    unittest.main()
