from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date

import pandas as pd
import requests
import urllib3

from src.extractors.base import BaseExtractor

@dataclass
class BCCRIndicator:
    """BCCR economic indicator definition used by the API extractor."""

    name: str
    code: int

class BCCRApiExtractor(BaseExtractor):
    """Extractor para indicadores económicos del BCCR.

    El Web Service clásico requiere correo y token. Los indicadores 317 y 318
    se usan comúnmente para tipo de cambio compra/venta USD.
    """

    URL = 'https://gee.bccr.fi.cr/Indicadores/Suscripciones/WS/wsindicadoreseconomicos.asmx/ObtenerIndicadoresEconomicos'

    def __init__(self, indicators: list[BCCRIndicator], start_date='01/01/2025', end_date=None):
        """Configure the indicator range and read BCCR credentials from env."""
        self.indicators = indicators
        self.start_date = start_date
        self.end_date = end_date or date.today().strftime('%d/%m/%Y')
        self.email = os.getenv('BCCR_EMAIL')
        self.token = os.getenv('BCCR_TOKEN')

    def extract(self) -> pd.DataFrame:
        """Download all configured indicators and combine them into one frame."""
        if not self.email or not self.token:
            raise RuntimeError('Configura BCCR_EMAIL y BCCR_TOKEN para ejecutar esta extracción.')
        frames = []
        for ind in self.indicators:
            frames.append(self._fetch_indicator(ind))
        return pd.concat(frames, ignore_index=True)

    def _fetch_indicator(self, indicator: BCCRIndicator) -> pd.DataFrame:
        """Request a single BCCR indicator and annotate the returned rows."""
        params = {
            'Indicador': indicator.code,
            'FechaInicio': self.start_date,
            'FechaFinal': self.end_date,
            'Nombre': 'TFM_Vino_CR',
            'SubNiveles': 'N',
            'CorreoElectronico': self.email,
            'Token': self.token,
        }
        response = requests.get(self.URL, params=params, timeout=45)
        response.raise_for_status()
        df = pd.read_xml(response.text)
        df['indicador'] = indicator.name
        df['codigo_indicador'] = indicator.code
        return df


class BCCRPublicExchangeRateExtractor(BaseExtractor):
    """Extractor for the public BCCR exchange-rate JSON used by bccr.fi.cr."""

    BASE_URL = 'https://www.bccr.fi.cr'
    RESOURCES = {
        317: '/content/bccr/cr/es/home/jcr:content/root/container/container/economicindicators/cardindicador',
        318: '/content/bccr/cr/es/home/jcr:content/root/container/container/economicindicators/item_1774647976317',
    }
    NAMES = {
        317: 'tipo_cambio_compra_usd',
        318: 'tipo_cambio_venta_usd',
    }

    def __init__(self, indicators: list[BCCRIndicator], verify_ssl: bool = True):
        """Configure public exchange-rate indicators from the BCCR website."""
        self.indicators = indicators
        self.verify_ssl = verify_ssl
        if not self.verify_ssl:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def extract(self) -> pd.DataFrame:
        """Download buy/sell exchange-rate JSON rows from the public BCCR site."""
        rows = []
        for indicator in self.indicators:
            resource = self.RESOURCES.get(indicator.code)
            if not resource:
                raise RuntimeError(f'Indicador BCCR publico no configurado: {indicator.code}')
            rows.extend(self._fetch_indicator(indicator, resource))
        return pd.DataFrame(rows)

    def _fetch_indicator(self, indicator: BCCRIndicator, resource: str) -> list[dict]:
        """Request one public BCCR JSON indicator and return normalized rows."""
        url = f'{self.BASE_URL}{resource}.indicator.{indicator.code}.json'
        response = requests.get(url, timeout=45, verify=self.verify_ssl)
        response.raise_for_status()
        payload = response.json()
        rows = []
        for serie in payload.get('series', []):
            rows.append({
                'fecha': serie.get('fecha'),
                'indicador': self.NAMES.get(indicator.code, indicator.name),
                'codigo_indicador': indicator.code,
                'valor_crc': serie.get('valorDatoPorPeriodo'),
                'fuente': 'bccr_public_json',
                'url_fuente': url,
            })
        return rows


class GoMetaExchangeRateExtractor(BaseExtractor):
    """Extractor for GoMeta's public Costa Rica exchange-rate mirror."""

    URL = 'https://apis.gometa.org/tdc/tdc.json'

    def __init__(self, verify_ssl: bool = True):
        """Configure the GoMeta request."""
        self.verify_ssl = verify_ssl
        if not self.verify_ssl:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def extract(self) -> pd.DataFrame:
        """Download buy/sell exchange rates from GoMeta's public JSON API."""
        response = requests.get(self.URL, timeout=45, verify=self.verify_ssl)
        response.raise_for_status()
        payload = response.json()
        return pd.DataFrame([
            {
                'fecha': payload.get('compra_date'),
                'indicador': 'tipo_cambio_compra_usd',
                'codigo_indicador': 317,
                'valor_crc': payload.get('compra'),
                'fuente': 'gometa_tdc',
                'url_fuente': self.URL,
                'updated': payload.get('updated'),
            },
            {
                'fecha': payload.get('venta_date'),
                'indicador': 'tipo_cambio_venta_usd',
                'codigo_indicador': 318,
                'valor_crc': payload.get('venta'),
                'fuente': 'gometa_tdc',
                'url_fuente': self.URL,
                'updated': payload.get('updated'),
            },
        ])
