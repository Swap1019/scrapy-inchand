#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRAPY_DIR="$ROOT_DIR/inchand"
SCRAPY_BIN_DEFAULT="$ROOT_DIR/.venv/bin/scrapy"

INDEX_FILE="${INDEX_FILE:-data/sitemap-extracted-data/sitemap_index.json}"
SITEMAP_SHOP_FILE="${SITEMAP_SHOP_FILE:-data/sitemap-extracted-data/my_shop.json}"
SITEMAP_CATEGORY_FILE="${SITEMAP_CATEGORY_FILE:-data/sitemap-extracted-data/my_categories.json}"
SITEMAP_VENDOR_FILE="${SITEMAP_VENDOR_FILE:-data/sitemap-extracted-data/my_vendors.json}"
SITEMAP_PRODUCTS_FILE="${SITEMAP_PRODUCTS_FILE:-data/sitemap-extracted-data/my_products.json}"

DIRECT_SHOP_FILE="${DIRECT_SHOP_FILE:-data/non-sitemap-extracted-data/my_shops_no_sitemap.json}"
DIRECT_CATEGORY_FILE="${DIRECT_CATEGORY_FILE:-data/non-sitemap-extracted-data/my_categories_no_sitemap.json}"
DIRECT_VENDOR_FILE="${DIRECT_VENDOR_FILE:-data/non-sitemap-extracted-data/my_vendors_no_sitemap.json}"
DIRECT_PRODUCTS_FILE="${DIRECT_PRODUCTS_FILE:-data/non-sitemap-extracted-data/my_products_no_sitemap.json}"

LOG_DIR="${LOG_DIR:-data/logs}"

usage() {
  cat <<'USAGE'
Usage:
  ./scripts/run_spiders.sh <command>

Commands:
  list               List available spiders

  sitemap-index      Run sitemap index spider
  sitemap-urls       Run sitemap URLs spider (shop/category/vendor extraction)
  sitemap-products   Run sitemap products spider
  sitemap-all        Run full sitemap flow: index -> urls -> products

  direct-urls        Run direct URL discovery spider
  direct-products    Run direct products spider
  direct-all         Run full direct flow: urls -> products

  logs               Tail spider error + crawl timing logs
  help               Show this help

Notes:
  - Run this script from anywhere inside the repository.
  - By default it uses ./.venv/bin/scrapy if available.
  - Output paths can be overridden with environment variables:
    INDEX_FILE, SITEMAP_SHOP_FILE, SITEMAP_PRODUCTS_FILE,
    DIRECT_SHOP_FILE, DIRECT_PRODUCTS_FILE, LOG_DIR
USAGE
}

pick_scrapy_bin() {
  if [[ -x "$SCRAPY_BIN_DEFAULT" ]]; then
    echo "$SCRAPY_BIN_DEFAULT"
    return
  fi

  if command -v scrapy >/dev/null 2>&1; then
    command -v scrapy
    return
  fi

  echo "Error: scrapy not found. Activate your virtualenv or install dependencies." >&2
  exit 1
}

SCRAPY_BIN="$(pick_scrapy_bin)"

run_scrapy() {
  (
    cd "$SCRAPY_DIR"
    "$SCRAPY_BIN" "$@"
  )
}

run_sitemap_index() {
  run_scrapy crawl inchand_sitemap_index -O "$INDEX_FILE"
}

run_sitemap_urls() {
  run_scrapy crawl inchand_sitemap_urls \
    -a index_file="$INDEX_FILE" \
    -a shop_output_file="$SITEMAP_SHOP_FILE" \
    -a category_output_file="$SITEMAP_CATEGORY_FILE" \
    -a vendor_output_file="$SITEMAP_VENDOR_FILE"
}

run_sitemap_products() {
  run_scrapy crawl inchand_sitemap_products \
    -a urls_file="$SITEMAP_SHOP_FILE" \
    -O "$SITEMAP_PRODUCTS_FILE"
}

run_direct_urls() {
  run_scrapy crawl inchand_urls \
    -a shop_output_file="$DIRECT_SHOP_FILE" \
    -a category_output_file="$DIRECT_CATEGORY_FILE" \
    -a vendor_output_file="$DIRECT_VENDOR_FILE"
}

run_direct_products() {
  run_scrapy crawl inchand_products \
    -a urls_file="$DIRECT_SHOP_FILE" \
    -O "$DIRECT_PRODUCTS_FILE"
}

case "${1:-help}" in
  list)
    run_scrapy list
    ;;
  sitemap-index)
    run_sitemap_index
    ;;
  sitemap-urls)
    run_sitemap_urls
    ;;
  sitemap-products)
    run_sitemap_products
    ;;
  sitemap-all)
    run_sitemap_index
    run_sitemap_urls
    run_sitemap_products
    ;;
  direct-urls)
    run_direct_urls
    ;;
  direct-products)
    run_direct_products
    ;;
  direct-all)
    run_direct_urls
    run_direct_products
    ;;
  logs)
    tail -f "$SCRAPY_DIR/$LOG_DIR/spider_errors.jsonl" "$SCRAPY_DIR/$LOG_DIR/crawl_timings.jsonl"
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    echo "Unknown command: $1" >&2
    echo >&2
    usage
    exit 1
    ;;
esac
