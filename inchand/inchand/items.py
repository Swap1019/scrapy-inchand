# items.py
import scrapy


class InchandProductItem(scrapy.Item):
    url = scrapy.Field()
    persian_title = scrapy.Field()
    english_title = scrapy.Field()
    original_price = scrapy.Field()
    discounted_price = scrapy.Field()
    discounted_percentage = scrapy.Field()
    description = scrapy.Field()
    thumbnail_image = scrapy.Field()
    images = scrapy.Field()
    specs = scrapy.Field()
