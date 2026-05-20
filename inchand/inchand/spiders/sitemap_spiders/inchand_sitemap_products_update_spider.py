import json
import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import scrapy

from inchand.log_store import append_jsonl


class InchandSitemapProductsUpdateSpider(scrapy.Spider):
    name = "inchand_sitemap_products_update"
    allowed_domains = ["inchand.com"]
    default_products_file = "data/sitemap-extracted-data/my_products.jsonl"

    tracked_fields = [
        "dbid",
        "uuid",
        "title_fa",
        "description",
        "title_en",
        "supply_category",
        "category1",
        "category2",
        "category3",
        "category4",
        "category5",
        "brand",
        "website",
        "url",
        "is_active",
        "image_url",
        "selling_price",
        "rrp_price",
        "discount_percent",
        "number_of_inactivity",
        "is_fake",
        "user_like",
        "user_dislike",
        "created_date",
        "admin_marked_fake",
        "mean_of_prices",
        "variants",
        "variant_id",
        "scam_score",
        "is_vectorized",
    ]

    mutable_fields = [
        "is_active",
        "selling_price",
        "rrp_price",
        "discount_percent",
        "number_of_inactivity",
    ]

    output_fields = tracked_fields + ["updated_date"]

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        spider.spider_error_log_file = crawler.settings.get(
            "SPIDER_ERROR_LOG_FILE", "data/logs/spider_errors.jsonl"
        )
        return spider

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.products_file = kwargs.get("products_file", self.default_products_file)
        self._records_by_url = {}
        self._ordered_urls = []
        self._orphan_records = []
        self.comparable_fields = list(self.mutable_fields)
        self._seen_request_urls = set()
        self._updated_count = 0
        self._unchanged_count = 0
        self._load_existing_records()

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

    def _now_string(self):
        return datetime.now(ZoneInfo("Asia/Tehran")).strftime("%Y-%m-%d %H:%M:%S")

    def _unwrap(self, value):
        if isinstance(value, list):
            if not value:
                return ""
            return self._unwrap(value[0])
        return value

    def _extract_next_data(self, response):
        raw = response.xpath('//script[@id="__NEXT_DATA__"]/text()').get()
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            self.logger.warning(
                "Failed to parse __NEXT_DATA__ from %s: %r", response.url, exc
            )
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

    def _extract_price_related(self, product, old_plain):
        old_inactivity = self._parse_inactivity(old_plain.get("number_of_inactivity"))

        if not isinstance(product, dict):
            return {
                "selling_price": "",
                "rrp_price": "",
                "discount_percent": "",
                "is_active": False,
                "number_of_inactivity": old_inactivity + 1,
            }

        offer = product.get("offer")
        if not isinstance(offer, dict):
            return {
                "selling_price": "",
                "rrp_price": "",
                "discount_percent": "",
                "is_active": False,
                "number_of_inactivity": old_inactivity + 1,
            }
        
        availability = offer.get("availability")
        if not availability:
            return {
                "selling_price": "",
                "rrp_price": "",
                "discount_percent": "",
                "is_active": False,
                "number_of_inactivity": old_inactivity + 1,
            }

        selling_price = offer.get("price") or ""
        rrp_price = offer.get("base_price") or selling_price

        discount_percent = offer.get("discount_percent")
        if discount_percent in (None, ""):
            discount_percent = ""

        return {
            "selling_price": selling_price,
            "rrp_price": rrp_price,
            "discount_percent": discount_percent,
            "is_active": True,
            "number_of_inactivity": 0,
        }

    def _extract_url_from_record(self, record):
        if not isinstance(record, dict):
            return ""
        value = self._unwrap(record.get("url", ""))
        return str(value).strip() if value is not None else ""

    def _to_line_record(self, plain_record, template_line=None):
        if template_line and isinstance(template_line, dict):
            keys = list(template_line.keys())
        else:
            keys = list(self.output_fields)

        out = {}
        for field in keys:
            out[field] = [plain_record.get(field, "")]
        return out

    def _line_to_plain(self, line_record):
        plain = {}
        if isinstance(line_record, dict):
            for field, value in line_record.items():
                plain[field] = self._unwrap(value)
        for field in self.output_fields:
            plain.setdefault(field, "")
        return plain

    def _normalize_digits_if_needed(self, text):
        if not isinstance(text, str):
            return text
        if re.search(r"[۰-۹]", text):
            return text.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
        return text

    def _parse_discount_percent(self, value):
        if isinstance(value, (int, float)):
            return int(value)

        text = self._normalize_digits_if_needed(str(value or ""))
        match = re.search(r"\d+", text)
        if not match:
            return 0
        try:
            return int(match.group(0))
        except ValueError:
            return 0

    def _parse_inactivity(self, value):
        if isinstance(value, (int, float)):
            return int(value)

        text = self._normalize_digits_if_needed(str(value or "")).strip()
        if not text:
            return 0
        try:
            return int(text)
        except ValueError:
            return 0

    def _priority_sort_key(self, url):
        line_rec = self._records_by_url.get(url, {})
        plain = self._line_to_plain(line_rec) if line_rec else {}

        discount = self._parse_discount_percent(plain.get("discount_percent"))
        has_discount = discount > 0
        inactivity = self._parse_inactivity(plain.get("number_of_inactivity"))

        # Priority:
        # 1) discounted products first
        # 2) higher discount first
        # 3) lower inactivity first
        return (0 if has_discount else 1, -discount, inactivity)

    def _load_existing_records(self):
        path = self._resolve_products_path()
        if not path.exists():
            self.logger.warning("Products file not found: %s", path)
            return

        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                self.logger.warning("Skipping malformed JSONL line in %s", path)
                continue

            url = self._extract_url_from_record(rec)
            if not url:
                self._orphan_records.append(rec)
                continue
            if url not in self._records_by_url:
                self._ordered_urls.append(url)
            self._records_by_url[url] = rec

        self.logger.info(
            "Loaded %d product records from %s",
            len(self._records_by_url),
            path,
        )

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

    def start_requests(self):
        if not self._ordered_urls:
            self.logger.warning("No URLs loaded from %s", self.products_file)
            return

        prioritized_urls = sorted(self._ordered_urls, key=self._priority_sort_key)
        for url in prioritized_urls:
            if url in self._seen_request_urls:
                continue
            self._seen_request_urls.add(url)
            yield scrapy.Request(
                url,
                callback=self.parse,
                errback=self.handle_request_error,
                meta={"handle_httpstatus_all": True},
            )

    def _build_plain_record(self, response, old_plain):
        product = self._extract_product(response)
        extracted_price_related = self._extract_price_related(product, old_plain)
        now_str = self._now_string()

        rec = dict(old_plain)
        rec["is_active"] = extracted_price_related["is_active"]
        rec["selling_price"] = extracted_price_related["selling_price"]
        rec["rrp_price"] = extracted_price_related["rrp_price"]
        rec["discount_percent"] = extracted_price_related["discount_percent"]
        rec["number_of_inactivity"] = extracted_price_related["number_of_inactivity"]
        rec["updated_date"] = now_str
        return rec

    def _has_changed(self, old_plain, new_plain):
        for field in self.comparable_fields:
            if old_plain.get(field, "") != new_plain.get(field, ""):
                return True
        return False

    def parse(self, response):
        if response.status != 200:
            self.log_http_error(response)
            return

        url = response.url
        old_line = self._records_by_url.get(url)
        if not old_line:
            self.logger.warning("Skipping URL not found in existing products file: %s", url)
            return

        old_plain = self._line_to_plain(old_line)

        new_plain = self._build_plain_record(response, old_plain)

        if self._has_changed(old_plain, new_plain):
            new_plain["updated_date"] = self._now_string()
            self._records_by_url[url] = self._to_line_record(new_plain, template_line=old_line)
            self._updated_count += 1
        else:
            self._unchanged_count += 1

    def closed(self, reason):
        changed = self._updated_count
        if changed == 0:
            self.logger.info(
                "Update finished. No changes detected. unchanged=%d",
                self._unchanged_count,
            )
            return

        path = self._resolve_products_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")

        with tmp_path.open("w", encoding="utf-8") as fh:
            for url in self._ordered_urls:
                rec = self._records_by_url.get(url)
                if not rec:
                    continue
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            for rec in self._orphan_records:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

        os.replace(tmp_path, path)
        self.logger.info(
            "Update finished. updated=%d unchanged=%d written=%s",
            self._updated_count,
            self._unchanged_count,
            path,
        )
