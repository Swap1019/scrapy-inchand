# Inchand Scrapy Crawler

Crawler for `inchand.com` with two strategies:

1. Sitemap-based crawl: uses sitemap URLs as the source of truth.
2. Direct website crawl (non-sitemap): discovers URLs by crawling site pages.

## Project Structure

- `inchand/`: Scrapy project root (`scrapy.cfg`)
- `inchand/inchand/spiders/sitemap_spiders/`: sitemap-based spiders
- `inchand/inchand/spiders/non_sitemap_spiders/`: direct-crawl spiders
- `inchand/inchand/extensions.py`: crawl timing extension
- `inchand/inchand/log_store.py`: JSONL log writer
- `inchand/data/`: extracted outputs and logs

## Setup

From repository root:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Move into Scrapy project root:

```bash
cd inchand
```

List available spiders:

```bash
../.venv/bin/scrapy list
```

## Run With Script (Recommended)

Use the helper script from repository root:

```bash
./scripts/run_spiders.sh help
```

Common commands:

```bash
./scripts/run_spiders.sh list
./scripts/run_spiders.sh sitemap-all
./scripts/run_spiders.sh direct-all
./scripts/run_spiders.sh logs
```

Step-by-step commands:

```bash
./scripts/run_spiders.sh sitemap-index
./scripts/run_spiders.sh sitemap-urls
./scripts/run_spiders.sh sitemap-products
./scripts/run_spiders.sh direct-urls
./scripts/run_spiders.sh direct-products
```

## Run Commands

### Option A: Sitemap-Based Crawl

This mode reads URLs from sitemap XML files.

1. Extract sitemap index URLs:

```bash
../.venv/bin/scrapy crawl inchand_sitemap_index -O data/sitemap-extracted-data/sitemap_index.json
```

2. Extract page URLs (shop/category/vendor) from sitemap index:

```bash
../.venv/bin/scrapy crawl inchand_sitemap_urls \
  -a index_file=data/sitemap-extracted-data/sitemap_index.json \
  -a shop_output_file=data/sitemap-extracted-data/my_shop.json \
  -a category_output_file=data/sitemap-extracted-data/my_categories.json \
  -a vendor_output_file=data/sitemap-extracted-data/my_vendors.json
```

3. Scrape product data from the sitemap shop URL file:

```bash
../.venv/bin/scrapy crawl inchand_sitemap_products \
  -a urls_file=data/sitemap-extracted-data/my_shop.json \
  -O data/sitemap-extracted-data/my_products.json
```

### Option B: Direct Website Crawl (Non-Sitemap)

This mode discovers URLs directly from the website HTML (starting at `https://inchand.com`).

1. Discover shop/category/vendor URLs:

```bash
../.venv/bin/scrapy crawl inchand_urls
```

This writes:

- `data/non-sitemap-extracted-data/my_shops_no_sitemap.json`
- `data/non-sitemap-extracted-data/my_categories_no_sitemap.json`
- `data/non-sitemap-extracted-data/my_vendors_no_sitemap.json`

2. Scrape product data from discovered shop URLs:

```bash
../.venv/bin/scrapy crawl inchand_products \
  -a urls_file=data/non-sitemap-extracted-data/my_shops_no_sitemap.json \
  -O data/non-sitemap-extracted-data/my_products_no_sitemap.json
```

## Spider Flows

### Sitemap Flow

1. `inchand_sitemap_index`
- Reads sitemap index endpoints (`/sitemap.xml`).
- Exports sitemap file URLs to `data/sitemap-extracted-data/sitemap_index.json`.

2. `inchand_sitemap_urls`
- Reads `sitemap_index.json`.
- Opens each sitemap file and extracts page URLs.
- Splits and saves URLs into:
`my_shop.json`, `my_categories.json`, `my_vendors.json`.

3. `inchand_sitemap_products`
- Reads shop URLs from `my_shop.json`.
- Visits only product pages and extracts product data.
- Writes final product dataset (for example `my_products.json`).

### Direct (Non-Sitemap) Flow

1. `inchand_urls`
- Starts from `https://inchand.com`.
- Crawls links directly from HTML pages.
- Discovers and saves shop/category/vendor URLs into
`data/non-sitemap-extracted-data/*.json`.

2. `inchand_products`
- Reads shop URLs from `my_shops_no_sitemap.json`.
- Visits product pages and extracts product data.
- Writes final product dataset (for example `my_products_no_sitemap.json`).

## Crawl Time Extension

`CrawlTimingExtension` is enabled in `inchand/inchand/settings.py`:

```python
EXTENSIONS = {
    "inchand.extensions.CrawlTimingExtension": 500,
}
```

For each spider run, it logs:

- `spider`
- `reason`
- `duration_seconds`
- `requests`
- `responses`
- `items`

Output file:

- `data/logs/crawl_timings.jsonl`

## Log Files

All logs are JSON Lines (`.jsonl`) under `inchand/data/logs/`.

### `data/logs/spider_errors.jsonl`

Written by spiders when:

- HTTP response status is non-200 (`event: "http_error"`)
- request fails (`event: "request_error"`)

### `data/logs/crawl_timings.jsonl`

Written by the crawl timing extension when each spider closes.

### `data/logs/pipeline_events.jsonl`

Reserved for pipeline-level events. This is mainly useful if/when item pipelines are enabled.

## Useful Commands

Tail logs:

```bash
tail -f data/logs/spider_errors.jsonl
tail -f data/logs/crawl_timings.jsonl
```
