from scrapy_redis.spiders import RedisSpider
from scrapy.loader import ItemLoader
from inchand.items import ProductItem

class InchandProductsSpider(RedisSpider):
    name = "inchand_products"
    redis_key = "shop_urls"
    allowed_domains = ["inchand.com"]  # ← was missing
    
    def parse(self, response):
        loader = ItemLoader(item=ProductItem(), response=response)

        loader.add_value("url",         response.url)
        loader.add_css("title",         "h1.product_title::text")
        loader.add_css("price",         ".price .woocommerce-Price-amount::text")
        loader.add_css("description",   ".woocommerce-product-details__short-description")
        loader.add_css("sku",           ".sku::text")
        loader.add_css("categories",    ".posted_in a::text")
        loader.add_css("images",        ".woocommerce-product-gallery__image img::attr(src)")

        yield loader.load_item()