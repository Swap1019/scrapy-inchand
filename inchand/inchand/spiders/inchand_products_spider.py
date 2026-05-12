from scrapy_redis.spiders import RedisSpider
from scrapy.loader import ItemLoader
from inchand.items import InchandProductItem
from inchand.log_store import append_jsonl


class InchandProductsSpider(RedisSpider):
    name = "inchand_products"
    redis_key = "shop_urls"
    allowed_domains = ["inchand.com"]

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        spider.spider_error_log_file = crawler.settings.get(
            "SPIDER_ERROR_LOG_FILE", "logs/spider_errors.jsonl"
        )
        return spider

    def make_request_from_data(self, data):
        request = super().make_request_from_data(data)
        if request is None:
            return None
        request.errback = self.handle_request_error
        request.meta["handle_httpstatus_all"] = True
        return request

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

    def extract_specs(self, response):
        rows = response.xpath(
            "//div[contains(@class,'pt-11_')]"
            "//div[contains(@class,'flex') and contains(@class,'items-center') and contains(@class,'mb-4')]"
        )

        specs = {}
        for row in rows:
            key = row.xpath("normalize-space(.//div[contains(@class,'w-1/3')][1])").get()
            value = " ".join(
                t.strip()
                for t in row.xpath(".//div[contains(@class,'w-2/3')][1]//text()").getall()
                if t.strip()
            )
            if key and value:
                specs[key] = value

        return specs

    def parse(self, response):
        if response.status != 200:
            self.log_http_error(response)
            return

        loader = ItemLoader(item=InchandProductItem(), response=response)
        loader.add_value("url", response.url)
        loader.add_css(
            "persian_title", 
            "h1.text-black.text-lg.font-semibold::text"
        )

        loader.add_css(
            "english_title",
            ".text-neutral-400.text-sm::text"
        )

        loader.add_css(
            "original_price",
            ".font-semibold.text-black.text-2xl::text"
        )

        loader.add_css(
            "discounted_price",
            ".font-light.text-lg.text-neutral-400.line-through.relative.top-0\\.5.ml-2::text",
        )

        loader.add_css(
            "discounted_percentage",
            ".bg-secondary-color.px-2\\.5.text-black.font-medium.rounded-2xl::text",
        )

        loader.add_css(
            "description", 
            ".font-light.leading-8::text"
        )

        # Extract images
        loader.add_css(
            "thumbnail_image", 
            "img.object-contain.h-full.w-full::attr(src)"
        )

        image_urls = response.css(
            "img.w-full.h-full.rounded-md.object-contain::attr(src)"
        ).getall()

        loader.add_value("images", image_urls)

        # Extract specifications
        loader.add_value("specs", self.extract_specs(response))

        yield loader.load_item()
