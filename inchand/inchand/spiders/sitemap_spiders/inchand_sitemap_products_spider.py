import json
import re
from pathlib import Path
import scrapy
from datetime import datetime
from zoneinfo import ZoneInfo
from scrapy.loader import ItemLoader
from inchand.items import ProductItem
from inchand.log_store import append_jsonl


class InchandSitemapProductsSpider(scrapy.Spider):
    name = "inchand_sitemap_products"
    allowed_domains = ["inchand.com"]
    default_urls_file = "data/sitemap-extracted-data/my_shop.json"
    default_products_file = "data/sitemap-extracted-data/my_products.jsonl"

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
        self.products_file = kwargs.get("products_file", self.default_products_file)
        self._seen_urls = set()
        self._existing_product_urls = self._load_existing_product_urls()

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

    def _resolve_products_path(self):
        configured = Path(self.products_file)
        if configured.is_absolute():
            return configured

        candidates = [configured]
        project_root = Path(__file__).resolve().parents[3]
        candidates.append(project_root / configured)

        for candidate in candidates:
            if candidate.exists():
                return candidate
        return configured

    def _extract_url_value(self, record):
        if not isinstance(record, dict):
            return None

        value = record.get("url")
        if isinstance(value, list):
            if not value:
                return None
            value = value[0]
        if value is None:
            return None
        value = str(value).strip()
        return value or None

    def _extract_records_from_payload(self, payload):
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("items", "products", "results", "data"):
                maybe = payload.get(key)
                if isinstance(maybe, list):
                    return maybe
        return []

    def _parse_records_tolerant(self, raw):
        try:
            payload = json.loads(raw)
            return self._extract_records_from_payload(payload), False
        except json.JSONDecodeError:
            pass

        decoder = json.JSONDecoder()
        n = len(raw)
        i = 0
        while i < n and raw[i].isspace():
            i += 1
        if i >= n:
            return [], False

        recovered = []
        recovered_from_corruption = False

        if raw[i] == "[":
            i += 1
            while i < n:
                while i < n and raw[i].isspace():
                    i += 1
                if i < n and raw[i] == ",":
                    i += 1
                    continue
                if i < n and raw[i] == "]":
                    break
                try:
                    obj, j = decoder.raw_decode(raw, i)
                except json.JSONDecodeError:
                    recovered_from_corruption = True
                    break
                if isinstance(obj, dict):
                    recovered.append(obj)
                i = j
            return recovered, recovered_from_corruption

        return [], False

    def _load_existing_product_urls(self):
        path = self._resolve_products_path()
        if not path.exists():
            return set()

        try:
            raw = path.read_text(encoding="utf-8").strip()
            if not raw:
                return set()
        except Exception as exc:
            self.logger.warning(
                "Failed reading products file %s: %r. Continuing without resume-skip.",
                path,
                exc,
            )
            return set()

        urls = set()
        try:
            if path.suffix.lower() == ".jsonl":
                for line in raw.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("http"):
                        urls.add(line)
                        continue
                    record = json.loads(line)
                    url_value = self._extract_url_value(record)
                    if url_value:
                        urls.add(url_value)
            else:
                records, recovered = self._parse_records_tolerant(raw)
                if recovered:
                    self.logger.warning(
                        "Products file %s is malformed/truncated. Recovered %d records for resume-skip.",
                        path,
                        len(records),
                    )
                for record in records:
                    url_value = self._extract_url_value(record)
                    if url_value:
                        urls.add(url_value)
        except Exception as exc:
            self.logger.warning(
                "Failed parsing products file %s: %r. Continuing without resume-skip.",
                path,
                exc,
            )
            return set()

        if urls:
            self.logger.info(
                "Loaded %d existing product URLs from %s for restart-safe skipping.",
                len(urls),
                path,
            )
        return urls

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
            for entry in urls:
                if isinstance(entry, dict):
                    if "url" in entry:
                        url = entry.get("url")
                    elif "page_url" in entry:
                        url = entry.get("page_url")
                    else:
                        url = None
                else:
                    url = entry

                url = str(url).strip() if url is not None else ""
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

        skipped_existing = 0
        for url in urls:
            if url in self._seen_urls:
                continue
            if url in self._existing_product_urls:
                skipped_existing += 1
                continue
            self._seen_urls.add(url)
            yield scrapy.Request(
                url,
                callback=self.parse,
                errback=self.handle_request_error,
                meta={"handle_httpstatus_all": True},
            )
        if skipped_existing:
            self.logger.info(
                "Skipped %d URLs already present in %s.",
                skipped_existing,
                self.products_file,
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

    def extract_dbid_and_uuid(self, response):
        persian_to_english = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
        text = response.xpath(
            '//div[contains(@class, "text-center") and contains(@class, "text-neutral-400")]/text()[last()]'
        ).get()
        if text:
            product_id = text.strip().translate(persian_to_english)
            return {
                "dbid" : f"inchand-{product_id}",
                "uuid" : product_id
            }
        return {
                "dbid" : "",
                "uuid" : ""
            }

    def extract_price_related(self, response):
        selling_price = response.css(".font-semibold.text-black.text-2xl::text").get()
        if not selling_price:
            return {
                "selling_price" : "",
                "rrp_price" : "",
                "discount_percent" : "",
                "is_active": False,
                "number_of_inactivity" : 1
            }
        
        discount_percent = response.css(".bg-secondary-color.px-2\\.5.text-black.font-medium.rounded-2xl::text").get()
        if discount_percent:
            return {
                "selling_price" : selling_price,
                "rrp_price" : response.css(".font-light.text-lg.text-neutral-400.line-through.relative.top-0\\.5.ml-2::text").get(),
                "discount_percent" : discount_percent,
                "is_active" : True,
                "number_of_inactivity" : 0
            }
        else:
            return {
                "selling_price" : selling_price,
                "rrp_price" : selling_price,
                "discount_percent" : "",
                "is_active" : True,
                "number_of_inactivity" : 0
            }
    
    def extract_brand(self, response):
        brand = response.xpath(
            '//span[contains(@class, "pl-3") and contains(@class, "ml-3") and contains(@class, "border-l") and contains(@class, "border-slate-300")]/text()[last()]'
        ).get()
        
        if brand:
            return brand.strip()
        return ""
    
    def extract_title_en(self, response):
        """
        Extracts the product title. If the text is a Jalali date, returns an empty string.
        """
        # Regex pattern for Jalali dates: 4 digits / 2 digits / 2 digits
        # [۰-۹] matches both Persian and English digits
        jalali_date_pattern = re.compile(r'^[۰-۹]{4}/[۰-۹]{2}/[۰-۹]{2}$')
        
        text = response.css('div.text-neutral-400.text-sm::text').get()
        
        if not text:
            return ""
            
        text = text.strip()
        
        # If the text matches the Jalali date pattern, return empty string
        if jalali_date_pattern.match(text):
            return ""
            
        # Otherwise, return the text as the title
        return text

    def extract_primary_image(self, response):
        return response.css("img.object-contain.h-full.w-full::attr(src)").get() or ""

        

    def parse(self, response):
        if response.status != 200:
            self.log_http_error(response)
            return
        if response.url in self._existing_product_urls:
            return
        
        extracted_price_related = self.extract_price_related(response)
        extracted_dbid_and_uuid = self.extract_dbid_and_uuid(response)

        loader = ItemLoader(item=ProductItem(), response=response)
        loader.add_value("dbid", extracted_dbid_and_uuid["dbid"])
        loader.add_value("uuid", extracted_dbid_and_uuid["uuid"])
        loader.add_css("title_fa", "h1.text-black.text-lg.font-semibold::text")
        loader.add_value("description", "") #For now it's just empty
        loader.add_value("title_en", self.extract_title_en(response))
        loader.add_value("supply_category", "")
        loader.add_value("category1", "")
        loader.add_value("category2", "")
        loader.add_value("category3", "")
        loader.add_value("category4", "")
        loader.add_value("category5", "")
        loader.add_value("brand", self.extract_brand(response))
        loader.add_css("website", "inchand.com")
        loader.add_value("url", response.url)
        loader.add_value("selling_price", extracted_price_related["selling_price"])
        loader.add_value("rrp_price", extracted_price_related["rrp_price"])
        loader.add_value("discount_percent", extracted_price_related["discount_percent"])
        loader.add_value("number_of_inactivity", extracted_price_related["number_of_inactivity"])
        loader.add_value("is_active", extracted_price_related["is_active"])
        loader.add_value("is_fake", False)
        loader.add_value("admin_marked_fake", False)
        loader.add_value("user_like", 0)
        loader.add_value("user_dislike", 0)
        loader.add_value("mean_of_prices", extracted_price_related["selling_price"])
        loader.add_value("created_date", datetime.now(ZoneInfo("Asia/Tehran")))
        loader.add_value("updated_date", datetime.now(ZoneInfo("Asia/Tehran")))
        loader.add_value("variants", "")
        loader.add_value("variant_id", "")
        loader.add_value("scam_score", "")
        loader.add_value("is_vectorized", False)
        loader.add_value("image_url", self.extract_primary_image(response))

        #loader.add_value("specs", self.extract_specs(response)) For now they just don't extract it

        item = loader.load_item()
        yield item
