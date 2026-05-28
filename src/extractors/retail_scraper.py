from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import date
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup

from src.extractors.base import BaseExtractor

HEADERS = {'User-Agent': 'Mozilla/5.0 academic-research-tfm-vino-cr/1.0'}

@dataclass
class RetailSource:
    retailer: str
    category: str
    url: str

class RetailWineScraper(BaseExtractor):
    """Extractor genérico para páginas de listado de vino.

    Los selectores son tolerantes, pero cada retailer debe validarse manualmente.
    El objetivo académico es documentar el proceso y dejarlo reproducible.
    """

    def __init__(self, sources: list[RetailSource], sleep_seconds: float = 2.0):
        self.sources = sources
        self.sleep_seconds = sleep_seconds

    def extract(self) -> pd.DataFrame:
        rows = []
        for source in self.sources:
            rows.extend(self._scrape_source(source))
            time.sleep(self.sleep_seconds)
        return pd.DataFrame(rows)

    def _scrape_source(self, source: RetailSource) -> list[dict]:
        html = requests.get(source.url, headers=HEADERS, timeout=30).text
        soup = BeautifulSoup(html, 'lxml')
        text = soup.get_text(' ', strip=True)
        candidates = re.findall(r'(Vino[^₡]{3,120})\s+₡\s*([0-9\.\s,]+)', text, flags=re.I)
        rows = []
        for product, price in candidates:
            rows.append({
                'fecha_extraccion': date.today().isoformat(),
                'retailer': source.retailer,
                'categoria': source.category,
                'producto': ' '.join(product.split()),
                'precio_texto': price,
                'url_fuente': source.url,
                'tipo_extraccion': 'web_scraping'
            })
        return rows
