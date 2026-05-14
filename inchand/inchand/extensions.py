import time
from scrapy import signals
from inchand.log_store import append_jsonl


class CrawlTimingExtension:
    def __init__(self, log_file):
        self.log_file = log_file
        self._started_at = {}

    @classmethod
    def from_crawler(cls, crawler):
        log_file = crawler.settings.get("CRAWL_TIMING_LOG_FILE", "logs/crawl_timings.jsonl")
        ext = cls(log_file)
        crawler.signals.connect(ext.spider_opened, signal=signals.spider_opened)
        crawler.signals.connect(ext.spider_closed, signal=signals.spider_closed)
        return ext

    def spider_opened(self, spider):
        self._started_at[spider.name] = time.perf_counter()

    def spider_closed(self, spider, reason):
        started = self._started_at.pop(spider.name, None)
        duration_seconds = None
        if started is not None:
            duration_seconds = round(time.perf_counter() - started, 3)

        stats = spider.crawler.stats.get_stats()
        append_jsonl(
            self.log_file,
            {
                "event": "crawl_timing",
                "spider": spider.name,
                "reason": reason,
                "duration_seconds": duration_seconds,
                "requests": stats.get("downloader/request_count", 0),
                "responses": stats.get("downloader/response_count", 0),
                "items": stats.get("item_scraped_count", 0),
            },
        )
