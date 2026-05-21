import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import jdatetime
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
        "mean_of_prices",
        "variants",
        "variant_id",
    ]

    output_fields = tracked_fields + ["updated_date"]
    list_like_fields = {"image_url", "variants"}

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

    def _today_jalali_string(self):
        return jdatetime.datetime.now().strftime("%Y-%m-%d")

    def _unwrap(self, value):
        if isinstance(value, list):
            if not value:
                return ""
            return self._unwrap(value[0])
        return value

    def _normalize_field_value(self, field, value):
        if field in self.list_like_fields:
            if value in ("", None):
                return []
            return value
        if isinstance(value, list):
            if not value:
                return ""
            if len(value) == 1:
                return self._normalize_field_value(field, value[0])
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

    def _extract_offers(self, response, product=None):
        page_props = self._extract_page_props(response)
        offers = page_props.get("offers")
        if isinstance(offers, list) and offers:
            return offers
        if isinstance(product, dict):
            product_offers = product.get("offers")
            if isinstance(product_offers, list) and product_offers:
                return product_offers
            single_offer = product.get("offer")
            if isinstance(single_offer, dict):
                return [single_offer]
        return []

    def _is_offer_active(self, offer):
        if not isinstance(offer, dict):
            return False
        availability = offer.get("availability")
        return availability == 1 or availability == "1"

    def _build_offer_price_point(self, offer, zero_if_inactive=False):
        if not isinstance(offer, dict):
            return {
                "selling_price": 0 if zero_if_inactive else None,
                "rrp_price": 0 if zero_if_inactive else None,
                "discount_percent": 0 if zero_if_inactive else None,
                "is_active": False,
            }

        if not self._is_offer_active(offer):
            return {
                "selling_price": 0 if zero_if_inactive else None,
                "rrp_price": 0 if zero_if_inactive else None,
                "discount_percent": 0 if zero_if_inactive else None,
                "is_active": False,
            }

        selling_price = offer.get("price")
        rrp_price = offer.get("base_price")
        if rrp_price in ("", None):
            rrp_price = selling_price

        discount_percent = offer.get("discount_percent")
        if discount_percent in ("", None):
            discount_percent = 0

        return {
            "selling_price": selling_price,
            "rrp_price": rrp_price,
            "discount_percent": discount_percent,
            "is_active": True,
        }

    def _parse_jalali_date(self, value):
        try:
            year_str, month_str, day_str = str(value).split("-")
            return int(year_str), int(month_str), int(day_str)
        except (TypeError, ValueError):
            return None

    def _sort_jalali_dates(self, dates):
        return sorted(
            (date for date in dates if self._parse_jalali_date(date) is not None),
            key=self._parse_jalali_date,
        )

    def _is_180_days_or_more_apart(self, older_date, newer_date):
        older = self._parse_jalali_date(older_date)
        newer = self._parse_jalali_date(newer_date)
        if older is None or newer is None:
            return False
        older_date_obj = jdatetime.date(*older)
        newer_date_obj = jdatetime.date(*newer)
        return (newer_date_obj - older_date_obj).days >= 180

    def _pick_earliest_entry(self, mapping):
        if not isinstance(mapping, dict) or not mapping:
            return None, None
        first_date = self._sort_jalali_dates(mapping.keys())[0]
        return first_date, mapping.get(first_date)

    def _pick_latest_entry(self, mapping):
        if not isinstance(mapping, dict) or not mapping:
            return None, None
        last_date = self._sort_jalali_dates(mapping.keys())[-1]
        return last_date, mapping.get(last_date)

    def merge_product_variants(self, offers):
        merged_variants = []
        seen_ids = set()
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            offer_id = offer.get("id")
            if offer_id is None or offer_id in seen_ids:
                continue
            seen_ids.add(offer_id)
            merged_variants.append(offer)
        return merged_variants

    def _prices_payload_from_offer(self, offer):
        price_point = self._build_offer_price_point(offer, zero_if_inactive=True)
        return {
            "rrp_price": price_point.get("rrp_price"),
            "selling_price": price_point.get("selling_price"),
            "discount_percent": price_point.get("discount_percent"),
        }

    def update_price(self, updating_variant, prices):
        today_jdate = jdatetime.date.today()
        today_str = today_jdate.strftime("%Y-%m-%d")
        current_price_data = {
            "rrp_price": prices.get("rrp_price"),
            "selling_price": prices.get("selling_price"),
            "discount_percent": prices.get("discount_percent"),
        }

        updating_variant = dict(updating_variant) if isinstance(updating_variant, dict) else {}
        price_history = updating_variant.get("price_history", {})
        if not isinstance(price_history, dict):
            price_history = {}

        start_price = dict(price_history.get("start_price", {}) or {})
        middle_prices = dict(price_history.get("middle_prices", {}) or {})
        end_price = dict(price_history.get("end_price", {}) or {})

        if not end_price and start_price:
            start_date_str = self._sort_jalali_dates(start_price.keys())[0]
            end_price = {start_date_str: start_price[start_date_str]}

        last_date_str, last_prices = self._pick_latest_entry(end_price)
        if last_date_str is None or last_prices is None:
            start_price = {today_str: current_price_data}
            middle_prices = {}
            end_price = {today_str: current_price_data}
        else:
            price_changed = (
                current_price_data["rrp_price"] != last_prices.get("rrp_price")
                or current_price_data["selling_price"] != last_prices.get("selling_price")
                or current_price_data["discount_percent"] != last_prices.get("discount_percent")
            )

            if price_changed and last_date_str is not None:
                middle_prices[last_date_str] = last_prices
            end_price = {today_str: current_price_data}

            if not start_price:
                start_price = {today_str: current_price_data}

        start_date_str, start_price_data = self._pick_earliest_entry(start_price)
        if start_date_str is None or start_price_data is None:
            start_price = {today_str: current_price_data}
        else:
            start_jdate = jdatetime.date(*map(int, start_date_str.split("-")))
            days_diff = (today_jdate - start_jdate).days

            if days_diff >= 180:
                last_price = start_price_data
                if middle_prices:
                    middle_dates = self._sort_jalali_dates(middle_prices.keys())
                    suitable_date = None
                    to_delete = []

                    for date_str in middle_dates:
                        date_obj = jdatetime.date(*map(int, date_str.split("-")))
                        gap = (today_jdate - date_obj).days

                        if gap > 180:
                            if gap < days_diff:
                                last_price = middle_prices[date_str]
                            to_delete.append(date_str)
                        elif gap == 180:
                            suitable_date = date_str
                            break

                    for date_str in to_delete:
                        middle_prices.pop(date_str, None)

                    if suitable_date:
                        start_price = {suitable_date: middle_prices[suitable_date]}
                        middle_prices.pop(suitable_date, None)
                    else:
                        new_start_date = today_jdate - timedelta(days=180)
                        start_price = {new_start_date.strftime("%Y-%m-%d"): last_price}
                else:
                    new_start_date = today_jdate - timedelta(days=180)
                    start_price = {new_start_date.strftime("%Y-%m-%d"): last_price}

        price_history = {
            "start_price": start_price,
            "middle_prices": middle_prices,
            "end_price": end_price,
        }

        price_points = []
        for section in ("start_price", "middle_prices", "end_price"):
            for date_str, section_prices in price_history.get(section, {}).items():
                if not isinstance(section_prices, dict):
                    continue
                selling_price = section_prices.get("selling_price")
                if selling_price:
                    price_points.append((date_str, selling_price))

        price_points.sort(key=lambda item: item[0])

        if len(price_points) == 0:
            mean_price = 0
        elif len(price_points) == 1:
            mean_price = price_points[0][1]
        else:
            total_weighted_price = 0
            total_days = 0

            for index in range(len(price_points) - 1):
                current_date_str, current_price = price_points[index]
                next_date_str, _ = price_points[index + 1]

                current_date = jdatetime.date(*map(int, current_date_str.split("-")))
                next_date = jdatetime.date(*map(int, next_date_str.split("-")))
                days = (next_date - current_date).days

                total_weighted_price += current_price * days
                total_days += days

            last_date_str, last_price = price_points[-1]
            last_date = jdatetime.date(*map(int, last_date_str.split("-")))
            days_to_today = (today_jdate - last_date).days

            total_weighted_price += last_price * days_to_today
            total_days += days_to_today
            mean_price = total_weighted_price / total_days if total_days > 0 else 0

        updating_variant["mean_of_prices"] = mean_price
        updating_variant["price_history"] = price_history
        return updating_variant

    def process_variants(self, merged_variants, existing_variants):
        today_str = jdatetime.date.today().strftime("%Y-%m-%d")
        existing_variants = [
            dict(item) if isinstance(item, dict) else item for item in existing_variants
        ]
        ids = [
            item.get("id")
            for item in existing_variants
            if isinstance(item, dict) and item.get("id") is not None
        ]

        for variant in merged_variants:
            variant_id = variant.get("id")
            if variant_id is None:
                continue

            prices = self._prices_payload_from_offer(variant)

            if variant_id in ids:
                ids.remove(variant_id)
                updating_variant = next(
                    (
                        existing_variants.pop(index)
                        for index, item in enumerate(existing_variants)
                        if isinstance(item, dict) and item.get("id") == variant_id
                    ),
                    None,
                )
                updating_variant = self.update_price(updating_variant, prices)
                existing_variants.append(updating_variant)
            else:
                current_price_data = {
                    "rrp_price": prices["rrp_price"],
                    "selling_price": prices["selling_price"],
                    "discount_percent": prices["discount_percent"],
                }
                price_history = {
                    "start_price": {today_str: current_price_data},
                    "middle_prices": {},
                    "end_price": {today_str: current_price_data},
                }
                existing_variants.append(
                    {
                        "id": variant_id,
                        "price_history": price_history,
                        "mean_of_prices": current_price_data["selling_price"] or 0,
                    }
                )

        for variant_id in ids:
            updating_variant = next(
                (
                    existing_variants.pop(index)
                    for index, item in enumerate(existing_variants)
                    if isinstance(item, dict) and item.get("id") == variant_id
                ),
                None,
            )
            prices = {
                "rrp_price": 0,
                "selling_price": 0,
                "discount_percent": 0,
            }
            updating_variant = self.update_price(updating_variant, prices)
            existing_variants.append(updating_variant)

        return existing_variants

    def _update_variants_and_prices(self, response, product, old_plain):
        current_offers = self.merge_product_variants(self._extract_offers(response, product))
        old_variants = old_plain.get("variants")
        if not isinstance(old_variants, list):
            old_variants = []

        updated_variants = self.process_variants(current_offers, old_variants)
        variants_by_id = {
            variant.get("id"): variant
            for variant in updated_variants
            if isinstance(variant, dict) and variant.get("id") is not None
        }

        active_offers = [offer for offer in current_offers if self._is_offer_active(offer)]
        old_inactivity = self._parse_inactivity(old_plain.get("number_of_inactivity"))

        selected_offer = None
        current_offer = product.get("offer") if isinstance(product, dict) else None
        if self._is_offer_active(current_offer):
            selected_offer = current_offer
        elif active_offers:
            selected_offer = active_offers[0]

        if selected_offer is not None:
            selected_variant_id = selected_offer.get("id")
            selected_price_point = self._build_offer_price_point(selected_offer)
            selected_variant = variants_by_id.get(selected_variant_id)
            mean_of_prices = (
                selected_variant.get("mean_of_prices")
                if isinstance(selected_variant, dict)
                else selected_price_point.get("selling_price")
            )
            return {
                "variants": updated_variants,
                "variant_id": selected_variant_id,
                "mean_of_prices": mean_of_prices,
                "is_active": True,
                "selling_price": selected_price_point.get("selling_price"),
                "rrp_price": selected_price_point.get("rrp_price"),
                "discount_percent": selected_price_point.get("discount_percent"),
                "number_of_inactivity": 0,
            }

        fallback_variant_id = old_plain.get("variant_id")
        fallback_mean = old_plain.get("mean_of_prices")
        fallback_variant = variants_by_id.get(fallback_variant_id)
        if isinstance(fallback_variant, dict):
            fallback_mean = fallback_variant.get("mean_of_prices", fallback_mean)

        return {
            "variants": updated_variants,
            "variant_id": fallback_variant_id,
            "mean_of_prices": fallback_mean,
            "is_active": False,
            "selling_price": None,
            "rrp_price": None,
            "discount_percent": 0,
            "number_of_inactivity": old_inactivity + 1,
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
            if field in plain_record:
                out[field] = plain_record.get(field)
            elif field in self.list_like_fields:
                out[field] = []
            else:
                out[field] = ""
        return out

    def _line_to_plain(self, line_record):
        plain = {}
        if isinstance(line_record, dict):
            for field, value in line_record.items():
                plain[field] = self._normalize_field_value(field, value)
        for field in self.output_fields:
            if field in self.list_like_fields:
                plain.setdefault(field, [])
            else:
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
        updated_variant_state = self._update_variants_and_prices(response, product, old_plain)
        now_str = self._now_string()

        rec = dict(old_plain)
        rec["is_active"] = updated_variant_state["is_active"]
        rec["selling_price"] = updated_variant_state["selling_price"]
        rec["rrp_price"] = updated_variant_state["rrp_price"]
        rec["discount_percent"] = updated_variant_state["discount_percent"]
        rec["number_of_inactivity"] = updated_variant_state["number_of_inactivity"]
        rec["mean_of_prices"] = updated_variant_state["mean_of_prices"]
        rec["variants"] = updated_variant_state["variants"]
        rec["variant_id"] = updated_variant_state["variant_id"]
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
