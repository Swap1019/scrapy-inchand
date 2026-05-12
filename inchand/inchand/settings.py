# Scrapy settings for inchand project

BOT_NAME = "inchand"

SPIDER_MODULES = ["inchand.spiders"]
NEWSPIDER_MODULE = "inchand.spiders"

ADDONS = {}


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

FEEDS = {
    "categories.json": {
        "format": "json",
        "item_filter": "inchand.filters.CategoryFilter",
    },
    "shop.json": {
        "format": "json",
        "item_filter": "inchand.filters.ShopFilter",
    },
}

# Redis connection
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_ITEMS_KEY = "%(spider)s:items"
REDIS_ITEMS_SERIALIZER = "json"

ITEM_PIPELINES = {
    "scrapy_redis.pipelines.RedisPipeline": 100,
    "inchand.pipelines.RedisStorePipeline": 200,
}

# scrapy-redis core settings
SCHEDULER = "scrapy_redis.scheduler.Scheduler"
DUPEFILTER_CLASS = "scrapy_redis.dupefilter.RFPDupeFilter"

# Keep queue after shutdown
SCHEDULER_PERSIST = True

DUPEFILTER_DEBUG = True

# prevent memory blowup
SCHEDULER_QUEUE_CLASS = "scrapy_redis.queue.SpiderQueue"

AUTOTHROTTLE_ENABLED = True
