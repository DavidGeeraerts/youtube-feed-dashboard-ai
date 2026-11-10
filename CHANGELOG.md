# Changelog

All notable changes to this project are documented in this file.

Version numbers follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Entries use these categories, and versions are ordered newest to oldest:

- `Added` for new features.
- `Changed` for changes in existing functionality.
- `Fixed` for any bug fixes.
- `Removed` for now removed features.
- `Security` in case of vulnerabilities.
- `Deprecated` for soon-to-be removed features.

## [0.1.5] - 2026-11-10

### Changed

- The dashboard update workflow runs every hour at minute 30 UTC (`30 * * * *`), instead of four times a day. Manual runs stay available. An overlapping run still waits in the `youtube-dashboard` group instead of cancelling the one that is already fetching or publishing.

## [0.1.4] - 2026-11-10

### Changed

- The channel list is read from the Quarto source `chapters/_07.1-youtube-xml-feeds.qmd` in DavidGeeraerts/AI (the raw GitHub URL), instead of scraping the rendered resources page. The file's markdown links are the list. The older HTML section is still accepted when that is what the URL returns.

## [0.1.3] - 2026-11-10

### Fixed

- YouTube feed fetches try a transient failure up to 5 times, including HTTP 404 and 5xx from the feeds endpoint, with exponential backoff and jitter. One bad response no longer marks that channel as failed for the run.
- A channel that errors (HTTP error, timeout, invalid XML, or an unexpected exception) is logged and skipped. The other channels are still fetched and saved, videos already stored for the failed channel are kept, and the run still publishes the data that succeeded.

## [0.1.2] - 2026-11-10

### Changed

- The Pages build uses this repo's Gemfile (`bundle exec jekyll build`) instead of `actions/jekyll-build-pages`, whose pinned `github-pages` 232 gem warned that it could not satisfy the Gemfile.
- Pages actions are the Node 24 releases: `actions/configure-pages` v6, `actions/upload-pages-artifact` v5 (which uploads with `actions/upload-artifact` v7), and `actions/deploy-pages` v5.

## [0.1.1] - 2026-11-09

### Changed

- Feed updates start from the latest branch tip, and the Jekyll build and Pages deploy use that commit (or the data commit just pushed) instead of the workflow's original SHA.
- `actions/checkout` and `actions/setup-python` now use the Node 24 releases, v7.

### Fixed

- Pushing feed data no longer fails with `fetch first` when `main` moves during a run. The push is rebased onto the latest branch and retried. If a day file conflicts, it is regenerated from the latest stored days plus a fresh fetch.

## [0.1.0] - 2026-11-09

### Added

- Daily dashboard of new YouTube videos from the channels in the Book of AI resources page, section Youtube Channels XML Feeds. The page opens on today in America/Los_Angeles, with yesterday and previous/next navigation over stored days.
- Each video shows a thumbnail, a title that links to YouTube, the channel name, and the publish time.
- Jekyll site using the Minimal Mistakes theme (4.28.1), with Catppuccin Latte for light and Catppuccin Mocha for dark.
- GitHub Actions workflow that fetches the feeds on a schedule and on manual run, commits per-day JSON, builds the site, and deploys it to GitHub Pages.
- Feed parser that reads the channel list at run time, dedupes videos by id, and keeps already stored days when a feed fails or returns nothing.
