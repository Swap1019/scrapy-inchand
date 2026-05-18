#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRAPY_DIR="$ROOT_DIR/inchand"
SCRAPY_BIN_DEFAULT="$ROOT_DIR/.venv/bin/scrapy"

SITEMAP_SHOP_FILE="${SITEMAP_SHOP_FILE:-data/sitemap-extracted-data/my_shops.json}"
SITEMAP_CATEGORY_FILE="${SITEMAP_CATEGORY_FILE:-data/sitemap-extracted-data/my_categories.json}"
SITEMAP_PRODUCTS_FILE="${SITEMAP_PRODUCTS_FILE:-data/sitemap-extracted-data/my_products.jsonl}"
SITEMAP_OUTPUT_MODE="${SITEMAP_OUTPUT_MODE:-resume}"
LOG_DIR="${LOG_DIR:-data/logs}"

usage() {
  cat <<'USAGE'
Usage:
  ./scripts/run_spiders.sh <command>

Commands:
  list               List available spiders

  sitemap-urls       Run sitemap URLs spider (shop/category extraction)
  sitemap-products   Run sitemap products spider
  sitemap-update     Run sitemap products updater spider
  sitemap-all        Run full sitemap flow: urls -> products

  logs               Tail spider error + crawl timing logs
  help               Show this help

Notes:
  - Run this script from anywhere inside the repository.
  - By default it uses ./.venv/bin/scrapy if available.
  - Output paths can be overridden with environment variables:
    SITEMAP_SHOP_FILE, SITEMAP_CATEGORY_FILE, SITEMAP_PRODUCTS_FILE,
    SITEMAP_OUTPUT_MODE (resume|overwrite), LOG_DIR
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

run_sitemap_urls() {
  run_scrapy crawl inchand_sitemap_urls \
    -a shop_output_file="$SITEMAP_SHOP_FILE" \
    -a category_output_file="$SITEMAP_CATEGORY_FILE"
}

run_sitemap_products() {
  local output_file="$SITEMAP_PRODUCTS_FILE"
  local mode="$SITEMAP_OUTPUT_MODE"

  if [[ "$mode" == "resume" ]]; then
    if [[ "$output_file" != *.jsonl ]]; then
      echo "Error: resume mode requires a .jsonl output file. Current: $output_file" >&2
      echo "Hint: use SITEMAP_PRODUCTS_FILE=data/sitemap-extracted-data/my_products.jsonl" >&2
      exit 1
    fi
    run_scrapy crawl inchand_sitemap_products \
      -a urls_file="$SITEMAP_SHOP_FILE" \
      -a products_file="$output_file" \
      -o "$output_file"
    return
  fi

  run_scrapy crawl inchand_sitemap_products \
    -a urls_file="$SITEMAP_SHOP_FILE" \
    -a products_file="$output_file" \
    -O "$output_file"
}

run_sitemap_update() {
  run_scrapy crawl inchand_sitemap_products_update \
    -a products_file="$SITEMAP_PRODUCTS_FILE"
}

case "${1:-help}" in
  list)
    run_scrapy list
    ;;
  sitemap-urls)
    run_sitemap_urls
    ;;
  sitemap-products)
    run_sitemap_products
    ;;
  sitemap-update)
    run_sitemap_update
    ;;
  sitemap-all)
    run_sitemap_urls
    run_sitemap_products
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
