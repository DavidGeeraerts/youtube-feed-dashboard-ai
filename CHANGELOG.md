# Changelog

All notable changes to this project are documented in this file.

Version numbers follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Entries use these categories: Added, Changed, Fixed, Removed, Security, Deprecated.

## [0.1.0] - 2026-11-09

### Added

- Daily dashboard of new YouTube videos from the channels in the Book of AI resources page, section Youtube Channels XML Feeds. The page opens on today in America/Los_Angeles, with yesterday and previous/next navigation over stored days.
- Each video shows a thumbnail, a title that links to YouTube, the channel name, and the publish time.
- Jekyll site using the Minimal Mistakes theme (4.28.1), with Catppuccin Latte for light and Catppuccin Mocha for dark.
- GitHub Actions workflow that fetches the feeds on a schedule and on manual run, commits per-day JSON, builds the site, and deploys it to GitHub Pages.
- Feed parser that reads the channel list at run time, dedupes videos by id, and keeps already stored days when a feed fails or returns nothing.
