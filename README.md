# Inchand Scrapy Crawler

Crawler for `inchand.com` using sitemap-based spiders.

## Project Structure

- `inchand/`: Scrapy project root (`scrapy.cfg`)
- `inchand/inchand/spiders/sitemap_spiders/`: sitemap-based spiders
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
./scripts/run_spiders.sh logs
```

Primary storage mode:

- Default mode uses Elasticsearch as the main product store and Redis as the updater cache.
- JSON storage is optional and enabled only with `USE_JSON_STORAGE=true`.

Step-by-step commands:

```bash
./scripts/run_spiders.sh sitemap-urls
./scripts/run_spiders.sh sitemap-products
./scripts/run_spiders.sh sitemap-update
```

### Storage Modes (`run_spiders.sh`)

Default mode:

- `inchand_sitemap_products` upserts products into Elasticsearch.
- `inchand_sitemap_products_update` loads existing products from Elasticsearch, caches them in Redis, compares fetched data against the Redis copy, then upserts changed records back into Elasticsearch.
- If `USE_REDIS_SCHEDULER=true`, Scrapy uses `scrapy-redis`'s priority queue scheduler and still respects `Request.priority`.

Optional JSON mode:

- Set `USE_JSON_STORAGE=true` to keep writing and updating `my_products.jsonl`.
- JSON mode can run alongside Elasticsearch/Redis; it is a side output, not the primary store.

### Resume Mode Design (`run_spiders.sh`)

`sitemap-products` defaults to `SITEMAP_OUTPUT_MODE=resume`.

When `USE_JSON_STORAGE=true`, primary JSON output is JSONL (`my_products.jsonl`), and resume mode appends directly:

1. Spider loads already-seen URLs from `products_file`.
2. Feed export appends new items to the same `.jsonl` file with `-o`.

Why this choice:

- JSONL is append-friendly and robust for long crawls/restarts.
- New data is persisted incrementally during crawl.
- No end-of-run merge step is required.

## Run Commands

### Sitemap-Based Crawl

This mode reads URLs from sitemap XML files.

1. Extract page URLs (shop/category) directly from sitemap endpoints:

```bash
../.venv/bin/scrapy crawl inchand_sitemap_urls \
  -a shop_output_file=data/sitemap-extracted-data/my_shop.json \
  -a category_output_file=data/sitemap-extracted-data/my_categories.json
```

2. Scrape product data from the sitemap shop URL file:

```bash
../.venv/bin/scrapy crawl inchand_sitemap_products \
  -a urls_file=data/sitemap-extracted-data/my_shop.json
```

3. Update existing product records by checking field changes:

```bash
../.venv/bin/scrapy crawl inchand_sitemap_products_update
```

JSON-enabled equivalents:

```bash
USE_JSON_STORAGE=true ../.venv/bin/scrapy crawl inchand_sitemap_products \
  -a urls_file=data/sitemap-extracted-data/my_shop.json \
  -a products_file=data/sitemap-extracted-data/my_products.jsonl \
  -o data/sitemap-extracted-data/my_products.jsonl

USE_JSON_STORAGE=true ../.venv/bin/scrapy crawl inchand_sitemap_products_update \
  -a products_file=data/sitemap-extracted-data/my_products.jsonl
```

## Spider Flows

### Sitemap Flow

1. `inchand_sitemap_urls`
- Starts from sitemap endpoints (`/sitemap.xml`).
- Follows sitemap index entries internally.
- Extracts and saves page URLs into:
`my_shop.json`, `my_categories.json`.

2. `inchand_sitemap_products`
- Reads shop URLs from `my_shop.json`.
- Visits only product pages and extracts product data.
- Upserts product documents into Elasticsearch through the pipeline.
- Optionally writes product dataset to `my_products.jsonl` when `USE_JSON_STORAGE=true`.

3. `inchand_sitemap_products_update`
- Reads existing products from Elasticsearch by default.
- Caches those products in Redis and uses the cached copy for comparison.
- Re-fetches each product page and compares tracked fields.
- Upserts only changed records back into Elasticsearch and refreshes the Redis cache.
- Rewrites `my_products.jsonl` atomically only when `USE_JSON_STORAGE=true`.

### Updater Spider Rules

Spider: `inchand_sitemap_products_update`

Run:

```bash
./scripts/run_spiders.sh sitemap-update
```

Update prioritization:

- Products with discount first (`discount_percent > 0`)
- Higher discount percent first
- Then products without discount
- Lower `number_of_inactivity` first

Immutable fields (not updated by updater):

- `dbid`
- `uuid`
- `brand`
- `website`
- `url`
- `user_like`
- `user_dislike`
- `created_date`
- `admin_marked_fake`
- `scam_score`
- `is_vectorized`

Activity/inactivity behavior:

- If `selling_price` is empty:
  - `is_active = false`
  - `number_of_inactivity = previous + 1`
- If `selling_price` exists:
  - `is_active = true`
  - `number_of_inactivity = 0`

File behavior:

- Default source of truth is Elasticsearch
- Redis stores cached product records for updater comparison
- Optional JSON input/output is `data/sitemap-extracted-data/my_products.jsonl`
- JSONL rewrite is atomic (`.tmp` + replace) when `USE_JSON_STORAGE=true` and there are changes

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

Written by the active pipelines when:

- Elasticsearch upserts happen
- Redis cache entries are refreshed
- pipeline-level skip/error events occur

## Useful Commands

Tail logs:

```bash
tail -f data/logs/spider_errors.jsonl
tail -f data/logs/crawl_timings.jsonl
```
