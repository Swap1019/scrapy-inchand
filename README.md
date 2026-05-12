# Inchand Scrapy Crawler

Scrapy + Redis crawler for `inchand.com` with two spiders:

- `inchand_urls`: discovers shop/category URLs and pushes them into Redis queues with deduplication.
- `inchand_products`: consumes product URLs from Redis, scrapes product details, and upserts products in Redis.

## Project Structure

- `inchand/`: Scrapy project root (`scrapy.cfg` lives here)
- `inchand/inchand/spiders/inchand_urls_spider.py`: URL discovery spider
- `inchand/inchand/spiders/inchand_products_spider.py`: product detail spider
- `inchand/inchand/pipelines.py`: Redis upsert pipeline + pipeline event logs
- `inchand/inchand/log_store.py`: JSONL log writer utility
- `inchand/inchand/settings.py`: Scrapy, Redis, and logging settings

## Requirements

- Python 3.13+
- Redis running locally on `localhost:6379`
- Dependencies from `requirements.txt`

## Setup

From repository root:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Start Redis (if not already running):

```bash
redis-server
```

## How It Works

1. Seed initial URL(s) into Redis key `inchand:start_urls`.
2. Run `inchand_urls` to discover and enqueue product-related URLs.
3. Run `inchand_products` to consume `shop_urls` and store normalized products in Redis.

### Spider Flow

- `inchand_urls` (`RedisSpider`, key: `inchand:start_urls`)
  - Extracts links from pages.
  - Filters non-http/static/js anchors.
  - Deduplicates discovered URLs with:
    - `shop_urls:seen` and `category_urls:seen` (`SADD`)
    - pushes only new URLs to `shop_urls` and `category_urls` (`LPUSH`)
  - Yields `{"type": "shop", "url": ...}` for new shop URLs.

- `inchand_products` (`RedisSpider`, key: `shop_urls`)
  - Scrapes product fields:
    - `url`, `persian_title`, `english_title`
    - `original_price`, `discounted_price`, `discounted_percentage`
    - `description`, `thumbnail_image`, `images`, `specs`
  - Sends item to Redis pipeline.

### Pipeline Behavior

`RedisStorePipeline` writes products as:

- key: `product:<product_url>`
- value: JSON object (UTF-8, `ensure_ascii=False`)

Pipeline logic:

- Normalizes item shape and values.
- Stores all product fields; missing values become `null`.
- Creates key if missing.
- Updates key only if data changed.
- Skips writing if unchanged.

## Running the Crawlers

Use Scrapy project directory:

```bash
cd inchand
```

Seed start URL:

```bash
redis-cli LPUSH inchand:start_urls https://inchand.com
```

Run URL crawler:

```bash
../.venv/bin/scrapy crawl inchand_urls
```

Run product crawler:

```bash
../.venv/bin/scrapy crawl inchand_products
```

List spiders:

```bash
../.venv/bin/scrapy list
```

## Redis Keys Used

- `inchand:start_urls`: start queue for URL spider
- `shop_urls`: product URL queue
- `shop_urls:seen`: dedupe set for `shop_urls`
- `category_urls`: category URL queue
- `category_urls:seen`: dedupe set for `category_urls`
- `inchand_urls:dupefilter`: request dedupe fingerprints for URL spider
- `inchand_products:dupefilter`: request dedupe fingerprints for product spider
- `product:*`: stored normalized product records

## Logging

Configured in `settings.py`:

- `SPIDER_ERROR_LOG_FILE = "logs/spider_errors.jsonl"`
- `PIPELINE_LOG_FILE = "logs/pipeline_events.jsonl"`

Generated under `inchand/logs/`.

### `spider_errors.jsonl`

One JSON object per line for:

- non-200 responses (`event: "http_error"`)
- request failures (`event: "request_error"`)

### `pipeline_events.jsonl`

One JSON object per line for:

- `redis_created`
- `redis_updated`
- `redis_unchanged`
- `skip_missing_url`
- `pipeline_error`

Event meanings:

- `redis_created`: product key did not exist in Redis and was created.
- `redis_updated`: product key existed, data changed, and Redis value was updated.
- `redis_unchanged`: product key existed and incoming data matched stored data, so no write happened.
- `skip_missing_url`: item did not contain a valid `url`, so pipeline skipped storing it.
- `pipeline_error`: unexpected exception happened during pipeline processing.

## Why Empty Fields Are Stored as `null`

Product records are normalized to a consistent schema with all expected fields present.  
If a field is missing/empty on the page, it is stored as `null` instead of being omitted.

Reasons:

- Keeps product JSON structure consistent across all records.
- Makes existence checks simpler (no need to handle missing keys vs empty values).
- Makes downstream tracking and analytics easier.

Examples:

- If `discounted_price` is `null`, product is currently not discounted.
- If `original_price` is `null`, product is likely not currently active/sellable.

Tail logs live:

```bash
tail -f logs/spider_errors.jsonl
tail -f logs/pipeline_events.jsonl
```

## Inspecting Data in Redis

List product keys:

```bash
redis-cli --raw --scan --pattern 'product:*' | head
```

Fetch one product:

```bash
redis-cli --raw GET 'product:https://inchand.com/shop/your-product-slug' | jq .
```

## Reset / Cleanup

Delete URL queues and dedupe sets:

```bash
redis-cli DEL shop_urls shop_urls:seen category_urls category_urls:seen inchand:start_urls
```

Delete Scrapy dupefilter state:

```bash
redis-cli DEL inchand_urls:dupefilter inchand_products:dupefilter
```

Delete all stored products:

```bash
redis-cli --scan --pattern 'product:*' | xargs -r redis-cli DEL
```

## Notes

- This project currently does not export feed files (`FEEDS` is not configured).
- `scrapy_redis` scheduler persistence is enabled (`SCHEDULER_PERSIST = True`), so queues/dupefilters survive restarts unless you clear keys manually.
