import json
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
