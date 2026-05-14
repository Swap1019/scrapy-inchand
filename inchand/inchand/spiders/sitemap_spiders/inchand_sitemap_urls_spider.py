import json
from pathlib import Path
import scrapy
from scrapy import signals
from inchand.log_store import append_jsonl


class InchandSitemapUrlsSpider(scrapy.Spider):
    name = "inchand_sitemap_urls"
    custom_settings = {"ROBOTSTXT_OBEY": False}
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
        self.index_file = kwargs.get(
            "index_file", "data/sitemap-extracted-data/sitemap_index.json"
        )
        self.category_output_file = kwargs.get(
            "category_output_file", "data/sitemap-extracted-data/my_categories.json"
        )
        self.shop_output_file = kwargs.get(
            "shop_output_file", "data/sitemap-extracted-data/my_shops.json"
        )
        self.vendor_output_file = kwargs.get(
            "vendor_output_file", "data/sitemap-extracted-data/my_vendors.json"
        )
        self._category_urls = set()
        self._shop_urls = set()
        self._vendor_urls = set()

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

    def _load_sitemap_urls(self):
        path = Path(self.index_file)
        if not path.exists():
            self.logger.error("Index file not found: %s", path)
            return []

        # Support both `-O sitemap_index.json` and line-by-line JSON files.
        try:
            raw = path.read_text(encoding="utf-8").strip()
            if not raw:
                return []
            if raw[0] == "[":
                records = json.loads(raw)
            else:
                records = [
                    json.loads(line)
                    for line in raw.splitlines()
                    if line.strip()
                ]
        except Exception as exc:
            self.logger.error("Failed to parse sitemap index file %s: %r", path, exc)
            return []

        urls = []
        seen = set()
        for rec in records:
            sitemap_url = str(rec.get("sitemap_url", "")).strip()
            if not sitemap_url or sitemap_url in seen:
                continue
            seen.add(sitemap_url)
            urls.append(sitemap_url)
        return urls

    def start_requests(self):
        sitemap_urls = self._load_sitemap_urls()
        if not sitemap_urls:
            self.logger.warning("No sitemap URLs loaded from %s", self.index_file)
            return

        for url in sitemap_urls:
            yield scrapy.Request(
                url,
                callback=self.parse_sitemap_urls,
                errback=self.handle_request_error,
                meta={"handle_httpstatus_all": True, "dont_retry": True},
            )

    def parse_sitemap_urls(self, response):
        if response.status != 200:
            self.log_http_error(response)
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
            elif "/vendors/" in page_url:
                self._vendor_urls.add(page_url)
                yield {
                    "sitemap_url": response.url,
                    "type": "vendor",
                    "page_url": page_url,
                }

    def spider_closed(self, spider, reason):
        self._write_json_file(self.category_output_file, sorted(self._category_urls))
        self._write_json_file(self.shop_output_file, sorted(self._shop_urls))
        self._write_json_file(self.vendor_output_file, sorted(self._vendor_urls))

    def _write_json_file(self, file_path, urls):
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "count": len(urls),
            "urls": urls,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
