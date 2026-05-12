class CategoryFilter:
    def __init__(self, feed_options=None):
        pass

    def accepts(self, item):
        return item.get("type") == "category"


class ShopFilter:
    def __init__(self, feed_options=None):
        pass

    def accepts(self, item):
        return item.get("type") == "shop"