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

    immutable_fields = {
        "dbid",
        "uuid",
        "brand",
        "website",
        "url",
        "user_like",
        "user_dislike",
        "created_date",
        "admin_marked_fake",
        "scam_score",
        "is_vectorized",
    }

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
        self._line_fields_order = []
        self.comparable_fields = [
            f for f in self.tracked_fields if f not in self.immutable_fields
        ]
        self._seen_request_urls = set()
        self._updated_count = 0
        self._unchanged_count = 0
        self._new_count = 0
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

    def _extract_url_from_record(self, record):
        if not isinstance(record, dict):
            return ""
        value = self._unwrap(record.get("url", ""))
        return str(value).strip() if value is not None else ""

    def _to_line_record(self, plain_record, template_line=None):
        keys = []
        if template_line and isinstance(template_line, dict):
            keys = list(template_line.keys())
        elif self._line_fields_order:
            keys = list(self._line_fields_order)
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

            if not self._line_fields_order and isinstance(rec, dict):
                self._line_fields_order = list(rec.keys())

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

    def extract_dbid_and_uuid(self, response):
        persian_to_english = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
        text = response.xpath(
            '//div[contains(@class, "text-center") and contains(@class, "text-neutral-400")]/text()[last()]'
        ).get()
        if text:
            product_id = text.strip().translate(persian_to_english)
            return {"dbid": f"inchand-{product_id}", "uuid": product_id}
        return {"dbid": "", "uuid": ""}

    def extract_price_related(self, response, old_plain):
        selling_price = response.css(".font-semibold.text-black.text-2xl::text").get()
        if not selling_price:
            old_inactivity = old_plain.get("number_of_inactivity", 0)
            try:
                old_inactivity = int(old_inactivity)
            except (TypeError, ValueError):
                old_inactivity = 0
            return {
                "selling_price": "",
                "rrp_price": "",
                "discount_percent": "",
                "is_active": False,
                "number_of_inactivity": old_inactivity + 1,
            }

        discount_percent = response.css(
            ".bg-secondary-color.px-2\\.5.text-black.font-medium.rounded-2xl::text"
        ).get()
        if discount_percent:
            return {
                "selling_price": selling_price,
                "rrp_price": response.css(
                    ".font-light.text-lg.text-neutral-400.line-through.relative.top-0\\.5.ml-2::text"
                ).get(),
                "discount_percent": discount_percent,
                "is_active": True,
                "number_of_inactivity": 0,
            }
        return {
            "selling_price": selling_price,
            "rrp_price": selling_price,
            "discount_percent": "",
            "is_active": True,
            "number_of_inactivity": 0,
        }

    def extract_brand(self, response):
        brand = response.xpath(
            '//span[contains(@class, "pl-3") and contains(@class, "ml-3") and contains(@class, "border-l") and contains(@class, "border-slate-300")]/text()[last()]'
        ).get()
        return brand.strip() if brand else ""

    def extract_title_en(self, response):
        jalali_date_pattern = re.compile(r"^[۰-۹]{4}/[۰-۹]{2}/[۰-۹]{2}$")
        text = response.css("div.text-neutral-400.text-sm::text").get()
        if not text:
            return ""
        text = text.strip()
        if jalali_date_pattern.match(text):
            return ""
        return text

    def extract_primary_image(self, response):
        return response.css("img.object-contain.h-full.w-full::attr(src)").get() or ""

    def _build_plain_record(self, response, old_plain):
        extracted_price_related = self.extract_price_related(response, old_plain)
        extracted_dbid_and_uuid = self.extract_dbid_and_uuid(response)
        now_str = self._now_string()

        created_date = old_plain.get("created_date") if old_plain else now_str

        rec = {
            "dbid": old_plain.get("dbid") or extracted_dbid_and_uuid["dbid"],
            "uuid": old_plain.get("uuid") or extracted_dbid_and_uuid["uuid"],
            "title_fa": (response.css("h1.text-black.text-lg.font-semibold::text").get() or ""),
            "description": "",
            "title_en": self.extract_title_en(response),
            "supply_category": "",
            "category1": "",
            "category2": "",
            "category3": "",
            "category4": "",
            "category5": "",
            "brand": old_plain.get("brand") or self.extract_brand(response),
            "website": old_plain.get("website", ""),
            "url": old_plain.get("url") or response.url,
            "is_active": extracted_price_related["is_active"],
            "image_url": self.extract_primary_image(response),
            "selling_price": extracted_price_related["selling_price"],
            "rrp_price": extracted_price_related["rrp_price"],
            "discount_percent": extracted_price_related["discount_percent"],
            "number_of_inactivity": extracted_price_related["number_of_inactivity"],
            "is_fake": old_plain.get("is_fake", False) if old_plain else False,
            "user_like": old_plain.get("user_like", 0) if old_plain else 0,
            "user_dislike": old_plain.get("user_dislike", 0) if old_plain else 0,
            "created_date": created_date,
            "admin_marked_fake": old_plain.get("admin_marked_fake", False) if old_plain else False,
            "mean_of_prices": extracted_price_related["selling_price"],
            "variants": "",
            "variant_id": "",
            "scam_score": old_plain.get("scam_score", "") if old_plain else "",
            "is_vectorized": old_plain.get("is_vectorized", False) if old_plain else False,
            "updated_date": old_plain.get("updated_date", now_str) if old_plain else now_str,
        }
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
        old_plain = self._line_to_plain(old_line) if old_line else {}

        new_plain = self._build_plain_record(response, old_plain)

        if not old_line:
            new_plain["updated_date"] = self._now_string()
            self._records_by_url[url] = self._to_line_record(new_plain)
            if url not in self._ordered_urls:
                self._ordered_urls.append(url)
            self._new_count += 1
            return

        if self._has_changed(old_plain, new_plain):
            new_plain["updated_date"] = self._now_string()
            self._records_by_url[url] = self._to_line_record(new_plain, template_line=old_line)
            self._updated_count += 1
        else:
            self._unchanged_count += 1

    def closed(self, reason):
        changed = self._new_count + self._updated_count
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
            "Update finished. updated=%d new=%d unchanged=%d written=%s",
            self._updated_count,
            self._new_count,
            self._unchanged_count,
            path,
        )
