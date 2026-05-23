from itemadapter import ItemAdapter

from inchand.log_store import append_jsonl
from inchand.storage import (
    ElasticsearchProductStore,
    ElasticsearchUrlStore,
    RedisProductStore,
    RedisUrlStore,
)


class _BasePipeline:
    supported_spiders = set()

    def open_spider(self, spider):
        self.spider = spider
        settings = spider.crawler.settings
        self.pipeline_log_file = settings.get(
            "PIPELINE_LOG_FILE", "data/logs/pipeline_events.jsonl"
        )

    def _is_supported(self, spider):
        return getattr(spider, "name", "") in self.supported_spiders

    def _normalize_item(self, item):
        return ItemAdapter(item).asdict()


class UrlElasticsearchPipeline(_BasePipeline):
    supported_spiders = {"inchand_sitemap_urls"}

    def open_spider(self, spider):
        super().open_spider(spider)
        settings = spider.crawler.settings
        timeout = settings.getfloat("ELASTICSEARCH_TIMEOUT", 15.0)
        self.shop_store = ElasticsearchUrlStore(
            base_url=settings.get("ELASTICSEARCH_URL"),
            index_name=settings.get("ELASTICSEARCH_SHOP_URL_INDEX"),
            timeout=timeout,
        )
        self.category_store = ElasticsearchUrlStore(
            base_url=settings.get("ELASTICSEARCH_URL"),
            index_name=settings.get("ELASTICSEARCH_CATEGORY_URL_INDEX"),
            timeout=timeout,
        )

    def process_item(self, item, spider):
        if not self._is_supported(spider):
            return item

        record = self._normalize_item(item)
        page_url = str(record.get("page_url") or "").strip()
        url_type = str(record.get("type") or "").strip()
        if not page_url or url_type not in {"shop", "category"}:
            append_jsonl(
                self.pipeline_log_file,
                {
                    "spider": spider.name,
                    "event": "url_elasticsearch_skip_invalid",
                    "type": url_type or None,
                },
            )
            return item

        store = self.shop_store if url_type == "shop" else self.category_store
        store.upsert(record)
        spider.crawler.stats.inc_value(f"elasticsearch/{url_type}_url_upserted")
        append_jsonl(
            self.pipeline_log_file,
            {
                "spider": spider.name,
                "event": "url_elasticsearch_upsert",
                "type": url_type,
                "url": page_url,
            },
        )
        return item


class UrlRedisPipeline(_BasePipeline):
    supported_spiders = {"inchand_sitemap_urls"}

    def open_spider(self, spider):
        super().open_spider(spider)
        settings = spider.crawler.settings
        self.shop_store = RedisUrlStore(
            redis_url=settings.get("REDIS_URL"),
            key_prefix=settings.get("REDIS_SHOP_URL_KEY_PREFIX"),
        )
        self.category_store = RedisUrlStore(
            redis_url=settings.get("REDIS_URL"),
            key_prefix=settings.get("REDIS_CATEGORY_URL_KEY_PREFIX"),
        )
        self.use_redis_start_urls = settings.getbool("USE_REDIS_START_URLS")
        self.products_start_urls_key = settings.get("REDIS_PRODUCTS_START_URLS_KEY")

    def process_item(self, item, spider):
        if not self._is_supported(spider):
            return item

        record = self._normalize_item(item)
        page_url = str(record.get("page_url") or "").strip()
        url_type = str(record.get("type") or "").strip()
        if not page_url or url_type not in {"shop", "category"}:
            append_jsonl(
                self.pipeline_log_file,
                {
                    "spider": spider.name,
                    "event": "url_redis_skip_invalid",
                    "type": url_type or None,
                },
            )
            return item

        store = self.shop_store if url_type == "shop" else self.category_store
        store.set(page_url, record)
        spider.crawler.stats.inc_value(f"redis/{url_type}_url_cached")
        append_jsonl(
            self.pipeline_log_file,
            {
                "spider": spider.name,
                "event": "url_redis_cache_set",
                "type": url_type,
                "url": page_url,
            },
        )

        if self.use_redis_start_urls and url_type == "shop":
            store.enqueue_request(
                self.products_start_urls_key,
                page_url,
                priority=0,
                meta={"source": "sitemap_urls"},
            )
            spider.crawler.stats.inc_value("redis/shop_url_enqueued")
            append_jsonl(
                self.pipeline_log_file,
                {
                    "spider": spider.name,
                    "event": "url_redis_start_queue_add",
                    "type": url_type,
                    "url": page_url,
                    "queue_key": self.products_start_urls_key,
                },
            )

        return item


class ProductElasticsearchPipeline(_BasePipeline):
    supported_spiders = {
        "inchand_sitemap_products",
        "inchand_sitemap_products_update",
    }

    def open_spider(self, spider):
        super().open_spider(spider)
        settings = spider.crawler.settings
        self.store = ElasticsearchProductStore(
            base_url=settings.get("ELASTICSEARCH_URL"),
            index_name=settings.get("ELASTICSEARCH_INDEX"),
            timeout=settings.getfloat("ELASTICSEARCH_TIMEOUT", 15.0),
        )

    def process_item(self, item, spider):
        if not self._is_supported(spider):
            return item

        record = self._normalize_item(item)
        url = str(record.get("url") or "").strip()
        if not url:
            append_jsonl(
                self.pipeline_log_file,
                {
                    "spider": spider.name,
                    "event": "elasticsearch_skip_missing_url",
                },
            )
            return item

        self.store.upsert(record)
        spider.crawler.stats.inc_value("elasticsearch/upserted")
        append_jsonl(
            self.pipeline_log_file,
            {
                "spider": spider.name,
                "event": "elasticsearch_upsert",
                "url": url,
            },
        )
        return item


class ProductRedisPipeline(_BasePipeline):
    supported_spiders = {
        "inchand_sitemap_products",
        "inchand_sitemap_products_update",
    }

    def open_spider(self, spider):
        super().open_spider(spider)
        settings = spider.crawler.settings
        self.store = RedisProductStore(
            redis_url=settings.get("REDIS_URL"),
            key_prefix=settings.get("REDIS_KEY_PREFIX"),
        )

    def process_item(self, item, spider):
        if not self._is_supported(spider):
            return item

        record = self._normalize_item(item)
        url = str(record.get("url") or "").strip()
        if not url:
            append_jsonl(
                self.pipeline_log_file,
                {
                    "spider": spider.name,
                    "event": "redis_skip_missing_url",
                },
            )
            return item

        self.store.set(url, record)
        spider.crawler.stats.inc_value("redis/cached")
        append_jsonl(
            self.pipeline_log_file,
            {
                "spider": spider.name,
                "event": "redis_cache_set",
                "url": url,
            },
        )
        return item
