import json
from pathlib import Path
import scrapy
from scrapy.loader import ItemLoader
from inchand.items import InchandProductItem
from inchand.log_store import append_jsonl


class InchandSitemapProductsSpider(scrapy.Spider):
    name = "inchand_sitemap_products"
    allowed_domains = ["inchand.com"]
    default_urls_file = "data/sitemap-extracted-data/my_shop.json"

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        spider.spider_error_log_file = crawler.settings.get(
            "SPIDER_ERROR_LOG_FILE", "data/logs/spider_errors.jsonl"
        )
        return spider

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.urls_file = kwargs.get("urls_file", self.default_urls_file)
        self._seen_urls = set()

    def _resolve_urls_path(self):
        configured = Path(self.urls_file)
        if configured.is_absolute():
            return configured

        candidates = [configured]
        # Project root is .../inchand (next to scrapy.cfg and data/)
        project_root = Path(__file__).resolve().parents[3]
        candidates.append(project_root / configured)

        for candidate in candidates:
            if candidate.exists():
                return candidate
        return configured

    def log_http_error(self, response):
        append_jsonl(
            self.spider_error_log_file,
            {
                "spider": self.name,
                "event": "http_error",
                "status": response.status,
                "url": response.url,
                "referer": response.request.headers.get("Referer", b"").decode(
                    "utf-8", "ignore"
                ),
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

    def _load_shop_urls(self):
        path = self._resolve_urls_path()
        if not path.exists():
            self.logger.error("Shop URLs file not found: %s", path)
            return []

        def normalize_urls(urls):
            cleaned = []
            seen = set()
            for url in urls:
                url = str(url).strip()
                if not url or url in seen:
                    continue
                if "/shop/" not in url:
                    continue
                seen.add(url)
                cleaned.append(url)
            return cleaned

        try:
            raw = path.read_text(encoding="utf-8").strip()
            if not raw:
                return []
            if path.suffix.lower() == ".jsonl":
                urls = []
                for line in raw.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    # Support plain URL lines as well as JSON lines.
                    if line.startswith("http"):
                        urls.append(line)
                        continue
                    record = json.loads(line)
                    if isinstance(record, dict):
                        if "url" in record:
                            urls.append(record["url"])
                        elif "page_url" in record:
                            urls.append(record["page_url"])
                        elif "urls" in record and isinstance(record["urls"], list):
                            urls.extend(record["urls"])
                    elif isinstance(record, str):
                        urls.append(record)
                return normalize_urls(urls)

            payload = json.loads(raw)
        except Exception as exc:
            self.logger.error("Failed to parse shop URLs file %s: %r", path, exc)
            return []

        if isinstance(payload, dict):
            urls = payload.get("urls", [])
        elif isinstance(payload, list):
            urls = payload
        else:
            urls = []

        return normalize_urls(urls)

    def start_requests(self):
        urls = self._load_shop_urls()
        if not urls:
            self.logger.warning("No shop URLs loaded from %s", self.urls_file)
            return

        for url in urls:
            if url in self._seen_urls:
                continue
            self._seen_urls.add(url)
            yield scrapy.Request(
                url,
                callback=self.parse,
                errback=self.handle_request_error,
                meta={"handle_httpstatus_all": True},
            )

    def extract_specs(self, response):
        rows = response.xpath(
            "//div[contains(@class,'pt-11_')]"
            "//div[contains(@class,'flex') and contains(@class,'items-center') and contains(@class,'mb-4')]"
        )

        specs = {}
        for row in rows:
            key = row.xpath(
                "normalize-space(.//div[contains(@class,'w-1/3')][1])"
            ).get()
            value = " ".join(
                t.strip()
                for t in row.xpath(
                    ".//div[contains(@class,'w-2/3')][1]//text()"
                ).getall()
                if t.strip()
            )
            if key and value:
                specs[key] = value
        return specs

    def parse(self, response):
        if response.status != 200:
            self.log_http_error(response)
            return

        product_title = response.css("h1.text-black.text-lg.font-semibold::text").get()
        if not product_title:
            return

        loader = ItemLoader(item=InchandProductItem(), response=response)
        loader.add_value("url", response.url)
        loader.add_css("persian_title", "h1.text-black.text-lg.font-semibold::text")
        loader.add_css("english_title", ".text-neutral-400.text-sm::text")
        loader.add_css("original_price", ".font-semibold.text-black.text-2xl::text")
        loader.add_css(
            "discounted_price",
            ".font-light.text-lg.text-neutral-400.line-through.relative.top-0\\.5.ml-2::text",
        )
        loader.add_css(
            "discounted_percentage",
            ".bg-secondary-color.px-2\\.5.text-black.font-medium.rounded-2xl::text",
        )
        loader.add_css("description", ".font-light.leading-8::text")
        loader.add_css("thumbnail_image", "img.object-contain.h-full.w-full::attr(src)")

        image_urls = response.css(
            "img.w-full.h-full.rounded-md.object-contain::attr(src)"
        ).getall()
        loader.add_value("images", image_urls)
        loader.add_value("specs", self.extract_specs(response))
        yield loader.load_item()
