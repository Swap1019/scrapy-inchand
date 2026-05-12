import scrapy
import redis
from scrapy_redis.spiders import RedisSpider

class InchandUrlsSpider(RedisSpider):
    name = "inchand_urls"
    redis_key = "inchand:start_urls"
    allowed_domains = ["inchand.com"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.r = redis.Redis(host="localhost", port=6379, decode_responses=True)

    def parse(self, response):
        links = response.css("a::attr(href)").getall()

        for link in links:
            url = response.urljoin(link)

            # filters
            if not url.startswith("http"):
                continue

            if any(x in url for x in ["#", "javascript:", ".jpg", ".png", ".svg", ".css", ".js"]):
                continue

            if "/product-category/" in url:
                self.r.lpush("category_urls", url)
                yield scrapy.Request(url, callback=self.parse)

            elif "/shop/" in url:
                self.r.lpush("shop_urls", url) 
                yield {
                    "type": "shop",
                    "url": url
                }