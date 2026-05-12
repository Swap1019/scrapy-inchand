import json
import redis

class RedisStorePipeline:
    def open_spider(self, spider):
        self.r = redis.Redis(host="localhost", port=6379, decode_responses=True)

    def process_item(self, item, spider):
        if spider.name == "inchand_products":
            key = f"product:{item['url']}"
            self.r.set(key, json.dumps(dict(item)))
        return item