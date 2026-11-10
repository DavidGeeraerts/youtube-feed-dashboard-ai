# Changelog

All notable changes to this project are documented in this file.

Version numbers follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Entries use these categories:

## Features Heading
- `Added` for new features.
- `Changed` for changes in existing functionality.
- `Fixed` for any bug fixes.
- `Removed` for now removed features.
- `Security` in case of vulnerabilities.
- `Deprecated` for soon-to-be removed features.



## [0.1.0] - 2026-11-09

### Added

- Daily dashboard of new YouTube videos from the channels in the Book of AI resources page, section Youtube Channels XML Feeds. The page opens on today in America/Los_Angeles, with yesterday and previous/next navigation over stored days.
- Each video shows a thumbnail, a title that links to YouTube, the channel name, and the publish time.
- Jekyll site using the Minimal Mistakes theme (4.28.1), with Catppuccin Latte for light and Catppuccin Mocha for dark.
- GitHub Actions workflow that fetches the feeds on a schedule and on manual run, commits per-day JSON, builds the site, and deploys it to GitHub Pages.
- Feed parser that reads the channel list at run time, dedupes videos by id, and keeps already stored days when a feed fails or returns nothing.

## [0.1.1] - 2026-11-09

### Changed

- Feed updates start from the latest branch tip, and the Jekyll build and Pages deploy use that commit (or the data commit just pushed) instead of the workflow's original SHA.
- `actions/checkout` and `actions/setup-python` now use the Node 24 releases, v7.

### Fixed

- Pushing feed data no longer fails with `fetch first` when `main` moves during a run. The push is rebased onto the latest branch and retried. If a day file conflicts, it is regenerated from the latest stored days plus a fresh fetch.
