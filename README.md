<div align="center">
<img src="/assets/images/Project-youtube-feed-dashboard-ai-banner-.jpg" alt="Banner"/>
</div>

[![Update dashboard](https://github.com/DavidGeeraerts/youtube-feed-dashboard-ai/actions/workflows/update-dashboard.yml/badge.svg)](https://github.com/DavidGeeraerts/youtube-feed-dashboard-ai/actions/workflows/update-dashboard.yml)

# YouTube feed dashboard

Daily dashboard of new videos from the YouTube channels listed in [Youtube Channels XML Feeds](https://github.com/DavidGeeraerts/AI/blob/main/chapters/_07.1-youtube-xml-feeds.qmd) (`chapters/_07.1-youtube-xml-feeds.qmd` in the Book of AI).

Dates and publish times use **America/Los_Angeles**. The page opens on today in that time zone. **Yesterday** is one step back, and earlier days that have been stored can be opened with Previous day or the day menu.

The site is a [Jekyll](https://jekyllrb.com/) site deployed to GitHub Pages:

**https://davidgeeraerts.github.io/youtube-feed-dashboard-ai/**

## Theme

The theme is [Minimal Mistakes](https://github.com/mmistakes/minimal-mistakes) 4.28.1, loaded with `remote_theme` so it stays compatible with GitHub Pages.

It fits this dashboard for three reasons:

- GitHub Pages can build it. `jekyll-remote-theme` and `jekyll-include-cache` are part of the Pages gem, and the Actions workflow builds with that gem through Bundler, then deploys the result.
- It is built for cards and thumbnails. Archive pages have a grid layout (`entries_layout: grid`) and posts can use a gallery of images. The video board uses that card idea, with a 16:9 frame instead of the theme's short blog-teaser crop, so YouTube thumbnails stay intact.
- Light and dark are both readable. The light skin is **Catppuccin Latte** and the dark skin is **Catppuccin Mocha**, a matched pair shipped with the theme. The page follows the system setting and has System / Light / Dark controls.

## How it works

1. `.github/workflows/update-dashboard.yml` runs every hour at minute 30 UTC, and whenever someone starts it with **Run workflow**.
2. `scripts/fetch_feeds.py` downloads the raw Quarto file [`chapters/_07.1-youtube-xml-feeds.qmd`](https://raw.githubusercontent.com/DavidGeeraerts/AI/main/chapters/_07.1-youtube-xml-feeds.qmd) and reads its markdown links. Each link is a channel feed (`https://www.youtube.com/feeds/videos.xml?channel_id=...`). Channels added in that file are picked up on the next run. Nothing in this repo has to be edited to follow a new channel. If the document is the older rendered resources page instead, the script still reads `#youtube-channels-xml-feeds`, or every feed link on the page when that section is missing.
3. Each feed is fetched with the Python standard library. A transient failure — timeout, connection error, HTTP 429, HTTP 5xx, or a 404 from YouTube's feeds endpoint — is tried up to 5 times with exponential backoff and a little jitter between tries (about 2s, 4s, 8s, and 8s). A channel that still fails, times out, returns invalid XML, or raises an unexpected error is logged and skipped. The other channels are saved, videos already stored for the failed channel stay, and the script still exits successfully so the workflow can publish the data that succeeded. If the channel list itself cannot be read, the script exits with an error and leaves the stored days alone.
4. Videos are deduped by YouTube video id. The publish time is converted to America/Los_Angeles, and the video is stored under that calendar date. A video that is already stored stays on its original day.
5. The workflow commits `assets/data/index.json` and `assets/data/days/YYYY-MM-DD.json` so a video remains available after it falls off YouTube's 15-item feed. It commits on top of the latest branch tip. If that push is rejected, it rebases and retries. A conflicting day file is regenerated from the stored days on that tip plus a fresh fetch.
6. The same workflow builds the Jekyll site and deploys it to GitHub Pages. The page loads today's JSON in the browser, so "today" stays correct in America/Los_Angeles even if the last build was yesterday.

## Enable GitHub Pages

Scheduled runs only happen after this workflow is on the default branch (`main`).

1. Merge the dashboard pull request.
2. In the repo: **Settings → Pages → Build and deployment → Source: GitHub Actions**.
3. If the workflow cannot push the data commit: **Settings → Actions → General → Workflow permissions → Read and write permissions**. The workflow asks for `contents: write`, which is what allows that commit.
4. Open **Actions → Update dashboard → Run workflow** once, to confirm the fetch and the Pages deploy. The first scheduled run can also be delayed; GitHub does not guarantee the exact minute.

The dashboard URL is [https://davidgeeraerts.github.io/youtube-feed-dashboard-ai/](https://davidgeeraerts.github.io/youtube-feed-dashboard-ai/).

## Change the schedule

Edit the `cron` line in `.github/workflows/update-dashboard.yml`. GitHub cron is UTC, and a run can start later than the time you write.

The current schedule is `30 * * * *` (minute 30 of every hour, UTC). The half hour avoids the top-of-hour rush on GitHub's scheduled runners. A run can still start later than :30. In Pacific time that is about 30 minutes past each hour during Pacific Standard Time, or one hour later during Pacific Daylight Time.

If a run is still going when the next hour starts, it is left to finish. The next run waits in the `youtube-dashboard` concurrency group, so two runs cannot push feed data at the same time. A run that is already waiting is replaced by the newer one, so delayed hours do not stack up.

`workflow_dispatch` is listed next to the schedule, so **Run workflow** stays available no matter what the cron says.

## Local commands

```bash
python3 -m unittest discover -s tests -v
python3 scripts/fetch_feeds.py
bundle config set --local path vendor/bundle
bundle install
bundle exec jekyll build
```

On Ruby 3, `jekyll serve` also needs the `webrick` gem (`bundle add webrick`). `bundle install` uses the `github-pages` gem so the local build tracks GitHub Pages. The theme is downloaded from GitHub during the build. The configured base URL is `/youtube-feed-dashboard-ai`.

Fetcher tests do not call YouTube. `scripts/fetch_feeds.py` does.

## Data files

`assets/data/index.json` lists the channels, whether each feed succeeded, and which days are stored.

`assets/data/days/YYYY-MM-DD.json` holds that day's videos: id, title, YouTube URL, channel name, channel id, UTC publish time, and thumbnail.

## License

[GNU Affero General Public License v3.0](LICENSE).
