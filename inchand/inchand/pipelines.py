import json
import redis
from inchand.log_store import append_jsonl


class RedisStorePipeline:
    LIST_FIELDS = {"images"}
    DICT_FIELDS = {"specs"}
    PRODUCT_FIELDS = (
        "url",
        "persian_title",
        "english_title",
        "original_price",
        "discounted_price",
        "discounted_percentage",
        "description",
        "thumbnail_image",
        "images",
        "specs",
    )

    def open_spider(self, spider=None):
        self.spider = spider
        self.r = redis.Redis(host="localhost", port=6379, decode_responses=True)
        settings = getattr(getattr(spider, "crawler", None), "settings", None)
        if settings:
            self.pipeline_log_file = settings.get(
                "PIPELINE_LOG_FILE", "logs/pipeline_events.jsonl"
            )
        else:
            self.pipeline_log_file = "logs/pipeline_events.jsonl"

    def _normalize_value(self, field, value):
        if field in self.LIST_FIELDS:
            if not isinstance(value, list):
                value = [value] if value is not None else []
            cleaned = []
            for v in value:
                if isinstance(v, str):
                    v = v.strip()
                if v:
                    cleaned.append(v)
            # Preserve order while removing duplicates.
            cleaned = list(dict.fromkeys(cleaned))
            return cleaned if cleaned else None

        if field in self.DICT_FIELDS:
            if isinstance(value, list):
                for v in value:
                    if isinstance(v, dict):
                        return v if v else None
                return None
            if isinstance(value, dict):
                return value if value else None
            return None

        if isinstance(value, list):
            for v in value:
                if isinstance(v, str):
                    v = v.strip()
                if v:
                    return v
            return None

        if isinstance(value, str):
            return value.strip() or None

        return value

    def _normalize_item(self, item):
        raw = dict(item)
        normalized = {}
        for field in self.PRODUCT_FIELDS:
            value = raw.get(field)
            normalized[field] = self._normalize_value(field, value)
        return normalized

    def process_item(self, item, spider=None):
        try:
            active_spider = spider or getattr(self, "spider", None)
            spider_name = getattr(active_spider, "name", "")

            # On newer Scrapy versions process_item may be called without spider arg.
            if spider_name and spider_name != "inchand_products":
                return item

            product = self._normalize_item(item)
            url = product.get("url")
            if not url:
                if active_spider:
                    active_spider.logger.warning(
                        "Skipping product without URL: %r", dict(item)
                    )
                append_jsonl(
                    self.pipeline_log_file,
                    {
                        "spider": spider_name or None,
                        "event": "skip_missing_url",
                    },
                )
                return item

            key = f"product:{url}"
            existing_raw = self.r.get(key)
            if existing_raw:
                try:
                    existing = json.loads(existing_raw)
                except json.JSONDecodeError:
                    existing = None
                if existing == product:
                    if active_spider:
                        active_spider.crawler.stats.inc_value(
                            "redis/products_unchanged"
                        )
                        active_spider.logger.debug("Redis unchanged: %s", key)
                    append_jsonl(
                        self.pipeline_log_file,
                        {
                            "spider": spider_name or None,
                            "event": "redis_unchanged",
                            "key": key,
                        },
                    )
                    return item
                if active_spider:
                    active_spider.crawler.stats.inc_value("redis/products_updated")
                    active_spider.logger.info("Redis updated: %s", key)
                append_jsonl(
                    self.pipeline_log_file,
                    {
                        "spider": spider_name or None,
                        "event": "redis_updated",
                        "key": key,
                    },
                )
            else:
                if active_spider:
                    active_spider.crawler.stats.inc_value("redis/products_created")
                    active_spider.logger.info("Redis created: %s", key)
                append_jsonl(
                    self.pipeline_log_file,
                    {
                        "spider": spider_name or None,
                        "event": "redis_created",
                        "key": key,
                    },
                )

            self.r.set(key, json.dumps(product, ensure_ascii=False))
        except Exception as exc:
            append_jsonl(
                self.pipeline_log_file,
                {
                    "spider": getattr(spider, "name", None),
                    "event": "pipeline_error",
                    "error": repr(exc),
                },
            )
            raise
        return item
