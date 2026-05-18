import json
from pathlib import Path
import scrapy
from scrapy import signals
from inchand.log_store import append_jsonl


class InchandSitemapUrlsSpider(scrapy.Spider):
    name = "inchand_sitemap_urls"
    custom_settings = {"ROBOTSTXT_OBEY": False}
    start_urls = [
        "https://app.inchand.com/sitemap.xml",
    ]
    allowed_domains = ["app.inchand.com", "inchand.com"]

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
        start_sitemaps = kwargs.get("start_sitemaps")
        if start_sitemaps:
            self.start_urls = [
                u.strip()
                for u in str(start_sitemaps).split(",")
                if u.strip()
            ]
        self.category_output_file = kwargs.get(
            "category_output_file", "data/sitemap-extracted-data/my_categories.json"
        )
        self.shop_output_file = kwargs.get(
            "shop_output_file", "data/sitemap-extracted-data/my_shops.json"
        )
        self._category_urls = set()
        self._shop_urls = set()
        self._seen_sitemap_urls = set()

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
                callback=self.parse_sitemap_or_urlset,
                errback=self.handle_request_error,
                meta={"handle_httpstatus_all": True, "dont_retry": True},
            )

    def parse_sitemap_or_urlset(self, response):
        if response.status != 200:
            self.log_http_error(response)
            return

        sitemap_locs = response.xpath(
            "//*[local-name()='sitemap']/*[local-name()='loc']/text()"
        ).getall()
        if sitemap_locs:
            for loc in sitemap_locs:
                sitemap_url = (loc or "").strip()
                if not sitemap_url or sitemap_url in self._seen_sitemap_urls:
                    continue
                self._seen_sitemap_urls.add(sitemap_url)
                yield scrapy.Request(
                    sitemap_url,
                    callback=self.parse_sitemap_or_urlset,
                    errback=self.handle_request_error,
                    meta={"handle_httpstatus_all": True, "dont_retry": True},
                )
            return

        loc_values = response.xpath("//*[local-name()='url']/*[local-name()='loc']/text()").getall()
        seen_page_urls = set()
        for loc in loc_values:
            page_url = (loc or "").strip()
            if not page_url or page_url in seen_page_urls:
                continue
            seen_page_urls.add(page_url)

            if "/shop/" in page_url:
                self._shop_urls.add(page_url)
                yield {
                    "sitemap_url": response.url,
                    "type": "shop",
                    "page_url": page_url,
                }
            elif "/product-category/" in page_url:
                self._category_urls.add(page_url)
                yield {
                    "sitemap_url": response.url,
                    "type": "category",
                    "page_url": page_url,
                }

    def spider_closed(self, spider, reason):
        self._write_json_file(self.category_output_file, sorted(self._category_urls))
        self._write_json_file(self.shop_output_file, sorted(self._shop_urls))

    def _write_json_file(self, file_path, urls):
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = [{"url": url} for url in urls]
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
