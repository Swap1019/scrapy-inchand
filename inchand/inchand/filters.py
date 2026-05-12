class CategoryFilter:
    def accepts(self, item):
        return item.get("type") == "category"

class ShopFilter:
    def accepts(self, item):
        return item.get("type") == "shop"