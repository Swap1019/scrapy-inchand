# items.py
import scrapy

class InchandProductItem(scrapy.Item):
    url         = scrapy.Field()
    title       = scrapy.Field()
    price       = scrapy.Field()
    description = scrapy.Field()
    sku         = scrapy.Field()
    categories  = scrapy.Field()
    images      = scrapy.Field()