import json

import scrapy
from scrapy import FormRequest
from scrapy_redis.spiders import RedisMixin
from scrapy_redis.utils import bytes_to_str, is_dict

from inchand.storage import parse_bool


class OptionalRedisSpider(RedisMixin, scrapy.Spider):
    redis_enabled = False
    redis_queue_key_setting = None

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        obj = super().from_crawler(crawler, *args, **kwargs)
        obj.redis_enabled = parse_bool(
            kwargs.get("use_redis_start_urls"),
            crawler.settings.getbool("USE_REDIS_START_URLS"),
        )
        if obj.redis_enabled:
            if obj.redis_queue_key_setting:
                redis_key = crawler.settings.get(obj.redis_queue_key_setting)
                if redis_key:
                    obj.redis_key = redis_key
            obj.setup_redis(crawler)
        return obj

    def start_requests(self):
        if self.redis_enabled:
            return RedisMixin.start_requests(self)
        return self.local_start_requests()

    def local_start_requests(self):
        return ()

    def make_request_from_data(self, data):
        formatted_data = bytes_to_str(data, self.redis_encoding)
        if not is_dict(formatted_data):
            return FormRequest(formatted_data, dont_filter=True)

        payload = json.loads(formatted_data)
        if payload.get("url") is None:
            self.logger.warning("The data from Redis has no url key in push data")
            return []

        url = payload.pop("url")
        method = payload.pop("method", "GET").upper()
        metadata = payload.pop("meta", {})
        priority = payload.pop("priority", None)
        dont_filter = payload.pop("dont_filter", True)

        request = FormRequest(
            url,
            dont_filter=bool(dont_filter),
            method=method,
            formdata=payload,
            meta=metadata,
        )

        if priority is not None:
            try:
                request.priority = int(priority)
            except (TypeError, ValueError):
                pass

        return request
