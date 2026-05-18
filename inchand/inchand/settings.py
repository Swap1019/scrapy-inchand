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

# Redis connection (disabled for now)
# REDIS_HOST = "localhost"
# REDIS_PORT = 6379
# ITEM_PIPELINES = {
#     "inchand.pipelines.RedisStorePipeline": 100,
# }

# scrapy-redis core settings (disabled for now)
# SCHEDULER = "scrapy_redis.scheduler.Scheduler"
# DUPEFILTER_CLASS = "scrapy_redis.dupefilter.RFPDupeFilter"

# Keep queue after shutdown (disabled for now)
# SCHEDULER_PERSIST = True

DUPEFILTER_DEBUG = True

# prevent memory blowup (disabled for now)
# SCHEDULER_QUEUE_CLASS = "scrapy_redis.queue.SpiderQueue"

AUTOTHROTTLE_ENABLED = True

SPIDER_ERROR_LOG_FILE = "data/logs/spider_errors.jsonl"
PIPELINE_LOG_FILE = "data/logs/pipeline_events.jsonl"
CRAWL_TIMING_LOG_FILE = "data/logs/crawl_timings.jsonl"
