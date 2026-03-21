# VNM Simulation Metadata

This repository contains firmware information and an automated synchronization pipeline for Discord Forum profiles.

## Profile Database (Static API)

The profiles are synchronized from Discord and served as a sharded JSON database via GitHub Pages.

### How to use in Desktop App

1.  **Fetch Manifest**: Start by fetching the `db/manifest.json`. This contains the total number of records and pages.
    - URL: `https://files.vnmsimulation.com/db/manifest.json`

2.  **Fetch Shards**: Load profiles in pages (100 records per page) from `db/page_N.json`.
    - URL Example: `https://files.vnmsimulation.com/db/page_1.json`

3.  **Search**: Use `db/search_index.json` for fast local keyword searching (Author + Thread Name).
    - URL: `https://files.vnmsimulation.com/db/search_index.json`

4.  **Download Profiles**: Use the `github_raw_url` field in the record to download the `.vnmprofile` file.

### Sync Workflow
The synchronization runs every hour via GitHub Actions. You can check the status in the [Actions tab](../../actions).
