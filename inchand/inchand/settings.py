import os


def _env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


# Scrapy settings for inchand project

BOT_NAME = "inchand"

SPIDER_MODULES = [
    "inchand.spiders.sitemap_spiders",
]
NEWSPIDER_MODULE = "inchand.spiders.sitemap_spiders"

ADDONS = {}

EXTENSIONS = {
    "inchand.extensions.CrawlTimingExtension": 500,
}


# Obey robots.txt rules
ROBOTSTXT_OBEY = True

# Concurrency and throttling settings
CONCURRENT_REQUESTS = 16
CONCURRENT_REQUESTS_PER_DOMAIN = 1
DOWNLOAD_DELAY = 0.5



FEED_EXPORT_ENCODING = "utf-8"

DEPTH_LIMIT = 5

DOWNLOADER_MIDDLEWARES = {
    'scrapy_user_agents.middlewares.RandomUserAgentMiddleware': 400,
}

USE_JSON_STORAGE = _env_bool("USE_JSON_STORAGE", False)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REDIS_KEY_PREFIX = os.getenv("REDIS_KEY_PREFIX", "inchand:product:")
REDIS_BATCH_KEY = os.getenv("REDIS_BATCH_KEY", "inchand:product_urls")
REDIS_SHOP_URL_KEY_PREFIX = os.getenv("REDIS_SHOP_URL_KEY_PREFIX", "inchand:shop_url:")
REDIS_CATEGORY_URL_KEY_PREFIX = os.getenv("REDIS_CATEGORY_URL_KEY_PREFIX", "inchand:category_url:")
REDIS_PRODUCTS_START_URLS_KEY = os.getenv(
    "REDIS_PRODUCTS_START_URLS_KEY", "inchand_sitemap_products:start_urls"
)

ELASTICSEARCH_URL = os.getenv("ELASTICSEARCH_URL", "http://localhost:9200")
ELASTICSEARCH_INDEX = os.getenv("ELASTICSEARCH_INDEX", "inchand-products")
ELASTICSEARCH_SHOP_URL_INDEX = os.getenv(
    "ELASTICSEARCH_SHOP_URL_INDEX", "inchand-shop-urls"
)
ELASTICSEARCH_CATEGORY_URL_INDEX = os.getenv(
    "ELASTICSEARCH_CATEGORY_URL_INDEX", "inchand-category-urls"
)
ELASTICSEARCH_TIMEOUT = float(os.getenv("ELASTICSEARCH_TIMEOUT", "15"))

ENABLE_REDIS_PIPELINE = _env_bool("ENABLE_REDIS_PIPELINE", True)
ENABLE_ELASTICSEARCH_PIPELINE = _env_bool("ENABLE_ELASTICSEARCH_PIPELINE", True)
USE_REDIS_SCHEDULER = _env_bool("USE_REDIS_SCHEDULER", False)
USE_REDIS_START_URLS = _env_bool("USE_REDIS_START_URLS", USE_REDIS_SCHEDULER)

ITEM_PIPELINES = {}
if ENABLE_ELASTICSEARCH_PIPELINE:
    ITEM_PIPELINES["inchand.pipelines.UrlElasticsearchPipeline"] = 150
    ITEM_PIPELINES["inchand.pipelines.ProductElasticsearchPipeline"] = 200
if ENABLE_REDIS_PIPELINE:
    ITEM_PIPELINES["inchand.pipelines.UrlRedisPipeline"] = 250
    ITEM_PIPELINES["inchand.pipelines.ProductRedisPipeline"] = 300

if USE_REDIS_SCHEDULER:
    SCHEDULER = "scrapy_redis.scheduler.Scheduler"
    DUPEFILTER_CLASS = "scrapy_redis.dupefilter.RFPDupeFilter"
    SCHEDULER_PERSIST = True
    SCHEDULER_QUEUE_CLASS = "scrapy_redis.queue.PriorityQueue"

if USE_REDIS_START_URLS:
    REDIS_START_URLS_AS_ZSET = True

DUPEFILTER_DEBUG = True

AUTOTHROTTLE_ENABLED = True

SPIDER_ERROR_LOG_FILE = "data/logs/spider_errors.jsonl"
PIPELINE_LOG_FILE = "data/logs/pipeline_events.jsonl"
CRAWL_TIMING_LOG_FILE = "data/logs/crawl_timings.jsonl"
