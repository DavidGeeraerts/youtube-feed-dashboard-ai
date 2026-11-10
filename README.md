<div align="center">
<img src="/assets/images/Project-youtube-feed-dashboard-ai-banner-.jpg" alt="Banner"/>
</div>

# YouTube feed dashboard

Daily dashboard of new videos from the YouTube channels listed in [The Book of AI, chapter 7](https://davidgeeraerts.github.io/AI/chapters/07-resources.html#youtube-channels-xml-feeds) (section **Youtube Channels XML Feeds**).

Dates and publish times use **America/Los_Angeles**. The page opens on today in that time zone. **Yesterday** is one step back, and earlier days that have been stored can be opened with Previous day or the day menu.

The site is a [Jekyll](https://jekyllrb.com/) site deployed to GitHub Pages:

**https://davidgeeraerts.github.io/youtube-feed-dashboard-ai/**

## Theme

The theme is [Minimal Mistakes](https://github.com/mmistakes/minimal-mistakes) 4.28.1, loaded with `remote_theme` so it stays compatible with GitHub Pages.

It fits this dashboard for three reasons:

- GitHub Pages can build it. `jekyll-remote-theme` and `jekyll-include-cache` are part of the Pages gem, and the Actions workflow builds with `actions/jekyll-build-pages` (the same Jekyll Pages uses) and deploys the result.
- It is built for cards and thumbnails. Archive pages have a grid layout (`entries_layout: grid`) and posts can use a gallery of images. The video board uses that card idea, with a 16:9 frame instead of the theme's short blog-teaser crop, so YouTube thumbnails stay intact.
- Light and dark are both readable. The light skin is **Catppuccin Latte** and the dark skin is **Catppuccin Mocha**, a matched pair shipped with the theme. The page follows the system setting and has System / Light / Dark controls.

## How it works

1. `.github/workflows/update-dashboard.yml` runs four times a day, and whenever someone starts it with **Run workflow**.
2. `scripts/fetch_feeds.py` downloads the resources page and reads the links in `#youtube-channels-xml-feeds`. Each link is a channel feed (`https://www.youtube.com/feeds/videos.xml?channel_id=...`). Channels added on that page are picked up on the next run. Nothing in this repo has to be edited to follow a new channel.
3. Each feed is fetched with the Python standard library. A feed that fails or returns no videos is recorded in `assets/data/index.json` and does not erase days already stored. If the resources page itself cannot be read, the script exits and leaves the stored days alone.
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

The current schedule is `30 3,15,19,23 * * *` (03:30, 15:30, 19:30, and 23:30 UTC), which is about 7:30am, 11:30am, 3:30pm, and 7:30pm Pacific Standard Time, or one hour later during Pacific Daylight Time.

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
