import scrapy
from inchand.log_store import append_jsonl


class InchandSitemapIndexSpider(scrapy.Spider):
    name = "inchand_sitemap_index"
    custom_settings = {"ROBOTSTXT_OBEY": False}
    start_urls = [
        "https://inchand.com/sitemap.xml",
        "https://app.inchand.com/sitemap.xml",
    ]
    allowed_domains = ["app.inchand.com", "inchand.com"]

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        spider.spider_error_log_file = crawler.settings.get(
            "SPIDER_ERROR_LOG_FILE", "data/logs/spider_errors.jsonl"
        )
        return spider

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

    def start_requests(self):
        for url in self.start_urls:
            yield scrapy.Request(
                url,
                callback=self.parse,
                errback=self.handle_request_error,
                meta={"handle_httpstatus_all": True, "dont_retry": True},
            )

    def parse(self, response):
        if response.status != 200:
            self.log_http_error(response)
            return

        loc_values = response.xpath("//*[local-name()='sitemap']/*[local-name()='loc']/text()").getall()
        seen = set()
        for loc in loc_values:
            sitemap_url = (loc or "").strip()
            if not sitemap_url or sitemap_url in seen:
                continue
            seen.add(sitemap_url)
            yield {
                "primary_sitemap_url": response.url,
                "sitemap_url": sitemap_url,
            }
