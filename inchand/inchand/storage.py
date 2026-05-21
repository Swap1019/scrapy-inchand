import hashlib
import json

import redis
import requests


def parse_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def product_doc_id(url):
    normalized = str(url or "").strip()
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


class ElasticsearchProductStore:
    def __init__(self, base_url, index_name, timeout=15):
        self.base_url = str(base_url or "").rstrip("/")
        self.index_name = str(index_name or "").strip()
        self.timeout = timeout
        self.session = requests.Session()

    def _doc_url(self, url):
        doc_id = product_doc_id(url)
        return f"{self.base_url}/{self.index_name}/_doc/{doc_id}"

    def upsert(self, record):
        url = str(record.get("url") or "").strip()
        if not url:
            raise ValueError("Cannot index product without url")
        response = self.session.put(
            self._doc_url(url),
            json=record,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return product_doc_id(url)

    def get(self, url):
        response = self.session.get(self._doc_url(url), timeout=self.timeout)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        payload = response.json()
        if not payload.get("found"):
            return None
        source = payload.get("_source")
        return source if isinstance(source, dict) else None

    def iter_documents(self, page_size=500):
        search_url = f"{self.base_url}/{self.index_name}/_search?scroll=1m"
        response = self.session.post(
            search_url,
            json={"size": page_size, "sort": ["_doc"], "query": {"match_all": {}}},
            timeout=self.timeout,
        )
        if response.status_code == 404:
            return
        response.raise_for_status()
        payload = response.json()
        scroll_id = payload.get("_scroll_id")
        hits = payload.get("hits", {}).get("hits", [])
        try:
            while hits:
                for hit in hits:
                    source = hit.get("_source")
                    if isinstance(source, dict):
                        yield source

                response = self.session.post(
                    f"{self.base_url}/_search/scroll",
                    json={"scroll": "1m", "scroll_id": scroll_id},
                    timeout=self.timeout,
                )
                response.raise_for_status()
                payload = response.json()
                scroll_id = payload.get("_scroll_id")
                hits = payload.get("hits", {}).get("hits", [])
        finally:
            if scroll_id:
                self.session.delete(
                    f"{self.base_url}/_search/scroll",
                    json={"scroll_id": [scroll_id]},
                    timeout=self.timeout,
                )


class RedisProductStore:
    def __init__(self, redis_url, key_prefix):
        self.key_prefix = str(key_prefix or "")
        self.client = redis.from_url(redis_url, decode_responses=True)

    def key(self, url):
        return f"{self.key_prefix}{product_doc_id(url)}"

    def set(self, url, record):
        self.client.set(self.key(url), json.dumps(record, ensure_ascii=False))

    def get(self, url):
        raw = self.client.get(self.key(url))
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

