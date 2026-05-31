from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import date

import pandas as pd
import requests
import urllib3
from bs4 import BeautifulSoup

from src.extractors.base import BaseExtractor
from src.utils.logging_config import get_logger

HEADERS = {'User-Agent': 'Mozilla/5.0 academic-research-tfm-vino-cr/1.0'}
logger = get_logger(__name__)


@dataclass
class RetailSource:
    """Single retailer category page that can be scraped for wine prices."""

    retailer: str
    category: str
    url: str


class RetailWineScraper(BaseExtractor):
    """Extractor generico para paginas de listado de vino."""

    def __init__(self, sources: list[RetailSource], sleep_seconds: float = 2.0, verify_ssl: bool = True):
        """Store scraping configuration shared by all requested sources."""
        self.sources = sources
        self.sleep_seconds = sleep_seconds
        self.verify_ssl = verify_ssl
        if not self.verify_ssl:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def extract(self) -> pd.DataFrame:
        """Scrape all configured sources and return one raw dataframe."""
        rows = []
        for source in self.sources:
            try:
                source_rows = self._scrape_source(source)
                logger.info('Fuente procesada: %s | %s | filas=%s', source.retailer, source.category, len(source_rows))
                rows.extend(source_rows)
            except requests.RequestException as exc:
                logger.warning('Fuente omitida por error de red: %s | %s | %s', source.retailer, source.url, exc)
            time.sleep(self.sleep_seconds)
        return pd.DataFrame(rows)

    def _scrape_source(self, source: RetailSource) -> list[dict]:
        """Download one category page and extract product rows from HTML."""
        response = requests.get(source.url, headers=HEADERS, timeout=30, verify=self.verify_ssl)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'lxml')
        # Prefer structured product data when available, then supplement it
        # with visible page text for sites that do not publish JSON-LD.
        rows = self._extract_json_ld_rows(soup, source)
        rows.extend(self._extract_text_rows(soup, source))
        return self._deduplicate_rows(rows)

    def _extract_json_ld_rows(self, soup: BeautifulSoup, source: RetailSource) -> list[dict]:
        """Extract product names and prices from JSON-LD script tags."""
        rows = []
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                payload = json.loads(script.string or '{}')
            except Exception:
                continue
            for product in self._walk_products(payload):
                name = product.get('name')
                price = self._price_from_offer(product.get('offers'))
                if name and price:
                    rows.append(self._build_row(source, name, str(price)))
        return rows

    def _extract_text_rows(self, soup: BeautifulSoup, source: RetailSource) -> list[dict]:
        """Extract product-price pairs from visible text as a fallback."""
        text = soup.get_text(' ', strip=True)
        price_pattern = r'(?:₡|CRC|\\u20a1)\s*([0-9][0-9\.\,\s]{2,})'
        candidates = re.findall(r'(Vino[^₡]{3,140})\s+' + price_pattern, text, flags=re.I)
        rows = [self._build_row(source, product, price) for product, price in candidates]

        if rows:
            return rows

        chunks = re.split(r'\s{2,}|(?=Vino\b)', text)
        for chunk in chunks:
            if not re.search(r'\bVino\b', chunk, flags=re.I):
                continue
            price_match = re.search(price_pattern, chunk, flags=re.I)
            if price_match:
                product = re.sub(price_pattern, ' ', chunk, flags=re.I)
                rows.append(self._build_row(source, product[:140], price_match.group(1)))
        return rows

    def _walk_products(self, payload: object):
        """Yield product-like dictionaries from nested JSON-LD payloads."""
        if isinstance(payload, dict):
            graph = payload.get('@graph')
            if graph:
                yield from self._walk_products(graph)
            type_value = payload.get('@type')
            type_values = type_value if isinstance(type_value, list) else [type_value]
            if 'Product' in type_values or ('name' in payload and 'offers' in payload):
                yield payload
            for value in payload.values():
                yield from self._walk_products(value)
        elif isinstance(payload, list):
            for item in payload:
                yield from self._walk_products(item)

    def _price_from_offer(self, offers: object) -> object | None:
        """Return the first usable price from a JSON-LD Offer structure."""
        if isinstance(offers, list):
            for offer in offers:
                price = self._price_from_offer(offer)
                if price:
                    return price
        if isinstance(offers, dict):
            return offers.get('price') or offers.get('lowPrice') or offers.get('highPrice')
        return None

    def _build_row(self, source: RetailSource, product: str, price_text: str) -> dict:
        """Create a raw extraction row using the common project schema."""
        product_clean = self._clean_product(product)
        price = self._parse_price(price_text)
        return {
            'fecha_extraccion': date.today().isoformat(),
            'retailer': source.retailer,
            'categoria': source.category,
            'producto': product_clean,
            'precio_lista_crc': price,
            'precio_oferta_crc': None,
            'descuento_pct': 0,
            'presentacion_ml': self._parse_presentation_ml(product_clean),
            'url_fuente': source.url,
            'tipo_extraccion': 'web_scraping_live',
        }

    def _clean_product(self, value: object) -> str:
        """Normalize whitespace and trim punctuation around product names."""
        text = re.sub(r'\s+', ' ', str(value)).strip()
        return text.strip(' -|,.;:')

    def _parse_price(self, value: object) -> float | None:
        """Convert Costa Rican price text into a numeric CRC value.

        Retailer pages mix comma and dot separators. The parser treats a final
        three-digit group as a thousands separator and otherwise preserves
        decimal cents when present.
        """
        text = re.sub(r'[^\d\.,]', '', str(value))
        if not text:
            return None
        if ',' in text and '.' in text:
            if text.rfind(',') > text.rfind('.'):
                text = text.replace('.', '').replace(',', '.')
            else:
                text = text.replace(',', '')
        elif ',' in text:
            parts = text.split(',')
            text = ''.join(parts) if len(parts[-1]) == 3 else text.replace(',', '.')
        elif text.count('.') > 1:
            text = text.replace('.', '')
        elif '.' in text:
            parts = text.split('.')
            text = ''.join(parts) if len(parts[-1]) == 3 else text
        try:
            return float(text)
        except ValueError:
            return None

    def _parse_presentation_ml(self, product: str) -> float | None:
        """Infer bottle volume in milliliters from the product name."""
        match = re.search(r'(\d+(?:[\.,]\d+)?)\s*(ml|mL|ML|l|L|litro|litros)\b', product)
        if not match:
            # Standard wine listings often omit the size; 750 ml is the common
            # bottle format and is used later for equivalent-price comparison.
            return 750.0
        value = float(match.group(1).replace(',', '.'))
        unit = match.group(2).lower()
        if unit in {'l', 'litro', 'litros'}:
            return value * 1000
        return value

    def _deduplicate_rows(self, rows: list[dict]) -> list[dict]:
        """Remove duplicate or price-less rows before returning scraper output."""
        seen = set()
        unique = []
        for row in rows:
            key = (row['retailer'], row['categoria'], row['producto'].lower(), row['precio_lista_crc'])
            if row['precio_lista_crc'] is None or key in seen:
                continue
            seen.add(key)
            unique.append(row)
        return unique
