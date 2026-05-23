import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import jdatetime

import scrapy

from inchand.items import ProductItem
from inchand.log_store import append_jsonl


class InchandSitemapProductsSpider(scrapy.Spider):
    name = "inchand_sitemap_products"
    allowed_domains = ["inchand.com"]
    default_urls_file = "data/sitemap-extracted-data/my_shops.json"
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
        self._existing_product_urls = set()

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

    def _now_string(self):
        return datetime.now(ZoneInfo("Asia/Tehran")).strftime("%Y-%m-%d %H:%M:%S")

    def _extract_next_data(self, response):
        raw = response.xpath('//script[@id="__NEXT_DATA__"]/text()').get()
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            self.logger.warning("Failed to parse __NEXT_DATA__ from %s: %r", response.url, exc)
            return {}
        return payload if isinstance(payload, dict) else {}

    def _extract_page_props(self, response):
        payload = self._extract_next_data(response)
        page_props = payload.get("props", {}).get("pageProps", {})
        return page_props if isinstance(page_props, dict) else {}

    def _extract_product(self, response):
        page_props = self._extract_page_props(response)
        product = page_props.get("product")
        return product if isinstance(product, dict) else None

    def _extract_offers(self, response, product=None):
        page_props = self._extract_page_props(response)
        offers = page_props.get("offers")
        if isinstance(offers, list) and offers:
            return offers
        return []

    def _extract_dbid_and_uuid(self, product=None):
        product_id = ""
        if isinstance(product, dict):
            product_id = product.get("id", "")
        product_id = str(product_id).strip() if product_id is not None else ""
        return {
            "dbid": f"inchand-{product_id}" if product_id else "",
            "uuid": product_id,
        }

    def _build_offer_price_point(self, offer):
        if not isinstance(offer, dict):
            return {
                "selling_price": None,
                "rrp_price": None,
                "discount_percent": None,
                "is_active": False,
            }

        availability = offer.get("availability")
        is_active = availability == 1
        discount_percent = offer.get("discount_percent")
        if discount_percent in ("", None):
            discount_percent = None

        if not is_active:
            return {
                "selling_price": None,
                "rrp_price": None,
                "discount_percent": discount_percent,
                "is_active": False,
            }

        selling_price = offer.get("price")
        rrp_price = offer.get("base_price")
        if rrp_price in ("", None):
            rrp_price = selling_price

        return {
            "selling_price": selling_price,
            "rrp_price": rrp_price,
            "discount_percent": discount_percent,
            "is_active": True,
        }

    def _extract_price_related(self, product):
        if not isinstance(product, dict):
            return {
                "selling_price": None,
                "rrp_price": None,
                "discount_percent": None,
                "is_active": False,
                "number_of_inactivity": 1,
            }

        offer = product.get("offer")
        if not isinstance(offer, dict):
            return {
                "selling_price": None,
                "rrp_price": None,
                "discount_percent": None,
                "is_active": False,
                "number_of_inactivity": 1,
            }
        price_point = self._build_offer_price_point(offer)

        return {
            "selling_price": price_point["selling_price"],
            "rrp_price": price_point["rrp_price"],
            "discount_percent": price_point["discount_percent"],
            "is_active": price_point["is_active"],
            "number_of_inactivity": 0 if price_point["is_active"] else 1,
        }
    
    def _extract_brand_value(self, product):
        brand = product.get("brand") if isinstance(product, dict) else {}
        if not isinstance(brand, dict):
            brand = {}
        return {
            "title_fa": brand.get("name") or "",
            "title_en": brand.get("en_name") or "",
        }

    def _extract_website_value(self):
        return {"title": "inchand", "url": "www.inchand.com"}

    def _extract_image_url(self, product):
        image = product.get("image") if isinstance(product, dict) else {}
        if isinstance(image, dict):
            return image.get("src") or ""
        if isinstance(image, list):
            for entry in image:
                if isinstance(entry, dict) and entry.get("src"):
                    return entry.get("src")
        return ""

    def _extract_variants(self, response, product):
        today = jdatetime.datetime.today().strftime("%Y-%m-%d")
        if not isinstance(product, dict):
            return [], None, None

        offers = self._extract_offers(response, product)

        variants = []
        seen_ids = set()
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            offer_id = offer.get("id")
            if offer_id in seen_ids:
                continue
            seen_ids.add(offer_id)

            price_point = self._build_offer_price_point(offer)
            history_point = {
                "selling_price": price_point["selling_price"],
                "discount_percent": price_point["discount_percent"],
                "rrp_price": price_point["rrp_price"],
            }
            mean_of_prices = price_point["selling_price"]

            variants.append(
                {
                    "mean_of_prices": mean_of_prices,
                    "id": offer_id,
                    "price_history": {
                        "end_price": {today: history_point},
                        "start_price": {today: history_point},
                        "middle_prices": {},
                    },
                }
            )

        current_offer = product.get("offer")
        current_variant_id = None
        current_mean = None
        if isinstance(current_offer, dict):
            current_variant_id = current_offer.get("id")
            for variant in variants:
                if variant.get("id") == current_variant_id:
                    current_mean = variant.get("mean_of_prices")
                    break
        if current_variant_id is None and variants:
            current_variant_id = variants[0].get("id")
            current_mean = variants[0].get("mean_of_prices")

        return variants, current_variant_id, current_mean

    def _build_item(self, response, product):
        prices = self._extract_price_related(product)
        ids = self._extract_dbid_and_uuid(product)
        now_str = self._now_string()
        variants, variant_id, mean_of_prices = self._extract_variants(response, product)
        image_url = self._extract_image_url(product)

        item = ProductItem()
        item["dbid"] = ids["dbid"]
        item["uuid"] = ids["uuid"]
        item["title_fa"] = (product.get("name") if isinstance(product, dict) else "") or ""
        item["description"] = ""
        item["title_en"] = (product.get("en_name") if isinstance(product, dict) else "") or ""
        item["supply_category"] = ""
        item["category1"] = ""
        item["category2"] = ""
        item["category3"] = ""
        item["category4"] = ""
        item["category5"] = ""
        item["brand"] = self._extract_brand_value(product)
        item["website"] = self._extract_website_value()
        item["url"] = response.url
        item["is_active"] = prices["is_active"]
        item["image_url"] = [image_url] if image_url else []
        item["selling_price"] = prices["selling_price"]
        item["rrp_price"] = prices["rrp_price"]
        item["discount_percent"] = prices["discount_percent"]
        item["number_of_inactivity"] = prices["number_of_inactivity"]
        item["is_fake"] = False
        item["user_like"] = 0
        item["user_dislike"] = 0
        item["mean_of_prices"] = mean_of_prices
        item["created_date"] = now_str
        item["updated_date"] = now_str
        item["variants"] = variants
        item["variant_id"] = variant_id
        item["scam_score"] = ""
        item["is_vectorized"] = False
        return item

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
        if not self._existing_product_urls:
            self._existing_product_urls = self._load_existing_product_urls()
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

    def parse(self, response):
        if response.status != 200:
            self.log_http_error(response)
            return
        if response.url in self._existing_product_urls:
            return
        product = self._extract_product(response)
        if not product:
            self.logger.info("No product payload found in __NEXT_DATA__ for %s; marking inactive.", response.url)
        yield self._build_item(response, product)
