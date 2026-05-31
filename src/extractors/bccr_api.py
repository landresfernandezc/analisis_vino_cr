from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date

import pandas as pd
import requests

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
