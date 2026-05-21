from itemadapter import ItemAdapter

from inchand.log_store import append_jsonl
from inchand.storage import ElasticsearchProductStore, RedisProductStore


class _BaseProductPipeline:
    supported_spiders = {
        "inchand_sitemap_products",
        "inchand_sitemap_products_update",
    }

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


class ProductElasticsearchPipeline(_BaseProductPipeline):
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


class ProductRedisPipeline(_BaseProductPipeline):
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
