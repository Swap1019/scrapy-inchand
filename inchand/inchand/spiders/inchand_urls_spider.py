import scrapy
import redis
from scrapy_redis.spiders import RedisSpider
from inchand.log_store import append_jsonl


class InchandUrlsSpider(RedisSpider):
    name = "inchand_urls"
    redis_key = "inchand:start_urls"
    allowed_domains = ["inchand.com"]
    category_queue_key = "category_urls"
    shop_queue_key = "shop_urls"

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        spider.spider_error_log_file = crawler.settings.get(
            "SPIDER_ERROR_LOG_FILE", "logs/spider_errors.jsonl"
        )
        return spider

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.r = redis.Redis(host="localhost", port=6379, decode_responses=True)

    def make_request_from_data(self, data):
        request = super().make_request_from_data(data)
        if request is None:
            return None
        request.errback = self.handle_request_error
        request.meta["handle_httpstatus_all"] = True
        return request

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

    def push_unique(self, queue_key, url):
        seen_key = f"{queue_key}:seen"
        added = self.r.sadd(seen_key, url)
        if added:
            self.r.lpush(queue_key, url)
            return True
        return False

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
                is_new = self.push_unique(self.category_queue_key, url)
                if is_new:
                    yield scrapy.Request(
                        url,
                        callback=self.parse,
                        errback=self.handle_request_error,
                        meta={"handle_httpstatus_all": True},
                    )

            elif "/shop/" in url:
                is_new = self.push_unique(self.shop_queue_key, url)
                if is_new:
                    yield {
                        "type": "shop",
                        "url": url
                    }
