import scrapy
import json
from pathlib import Path
from scrapy import signals
# import redis
# from scrapy_redis.spiders import RedisSpider
from inchand.log_store import append_jsonl


class InchandUrlsSpider(scrapy.Spider):
    name = "inchand_urls"
    start_urls = ["https://inchand.com"]
    allowed_domains = ["inchand.com"]
    # redis_key = "inchand:start_urls"
    # category_queue_key = "category_urls"
    # shop_queue_key = "shop_urls"

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        spider.spider_error_log_file = crawler.settings.get(
            "SPIDER_ERROR_LOG_FILE", "data/logs/spider_errors.jsonl"
        )
        crawler.signals.connect(spider.spider_closed, signal=signals.spider_closed)
        return spider

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Redis mode disabled for now.
        # self.r = redis.Redis(host="localhost", port=6379, decode_responses=True)
        self.category_output_file = kwargs.get(
            "category_output_file",
            "data/non-sitemap-extracted-data/my_categories_no_sitemap.json",
        )
        self.shop_output_file = kwargs.get(
            "shop_output_file",
            "data/non-sitemap-extracted-data/my_shops_no_sitemap.json",
        )
        self.vendor_output_file = kwargs.get(
            "vendor_output_file",
            "data/non-sitemap-extracted-data/my_vendors_no_sitemap.json",
        )
        self.seen_category_urls = set()
        self.seen_shop_urls = set()
        self.seen_vendor_urls = set()

    def log_http_error(self, response):
        append_jsonl(
            self.spider_error_log_file,
            {
                "spider": self.name,
                "event": "http_error",
                "status": response.status,
                "url": response.url,
                "referer": response.request.headers.get("Referer", b"").decode("utf-8", "ignore"),
            },
        )

    def handle_request_error(self, failure):
        request = getattr(failure, "request", None)
        append_jsonl(
            self.spider_error_log_file,
            {
                "spider": self.name,
                "event": "request_error",
                "url": getattr(request, "url", None),
                "error": repr(failure.value),
            },
        )

    # def push_unique(self, queue_key, url):
    #     seen_key = f"{queue_key}:seen"
    #     added = self.r.sadd(seen_key, url)
    #     if added:
    #         self.r.lpush(queue_key, url)
    #         return True
    #     return False

    def parse(self, response):
        if response.status != 200:
            self.log_http_error(response)
            return

        links = response.css("a::attr(href)").getall()

        for link in links:
            url = response.urljoin(link)

            # filters
            if not url.startswith("http"):
                continue

            if any(x in url for x in ["#", "javascript:", ".jpg", ".png", ".svg", ".css", ".js"]):
                continue

            if "/product-category/" in url:
                if url not in self.seen_category_urls:
                    self.seen_category_urls.add(url)
                    yield {"type": "category", "url": url}
                    yield scrapy.Request(
                        url,
                        callback=self.parse,
                        errback=self.handle_request_error,
                        meta={"handle_httpstatus_all": True},
                    )

            elif "/shop/" in url:
                if url not in self.seen_shop_urls:
                    self.seen_shop_urls.add(url)
                    yield {
                        "type": "shop",
                        "url": url
                    }
            
            elif "/vendors/" in url:
                if url not in self.seen_vendor_urls:
                    self.seen_vendor_urls.add(url)
                    yield {"type": "vendor", "url": url}
                    yield scrapy.Request(
                        url,
                        callback=self.parse,
                        errback=self.handle_request_error,
                        meta={"handle_httpstatus_all": True},
                    )


    def spider_closed(self, spider, reason):
        self._write_json_file(self.category_output_file, sorted(self.seen_category_urls))
        self._write_json_file(self.shop_output_file, sorted(self.seen_shop_urls))
        self._write_json_file(self.vendor_output_file, sorted(self.seen_vendor_urls))

    def _write_json_file(self, file_path, urls):
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "count": len(urls),
            "urls": urls,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
