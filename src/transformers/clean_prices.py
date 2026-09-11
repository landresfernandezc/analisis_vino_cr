from __future__ import annotations

import re
import pandas as pd


CLEAN_OUTPUT_COLUMNS = [
    'fecha_extraccion',
    'categoria',
    'precio_lista_crc',
    'precio_oferta_crc',
    'descuento_pct',
    'presentacion_ml',
    'precio_final_crc',
    'producto',
    'retailer',
    'precio_equivalente_750ml_crc',
    'segmento_precio',
    'tipo_cambio_compra_usd',
    'tipo_cambio_venta_usd',
]


def normalize_text(value: object) -> str | None:
    """Lowercase text and collapse whitespace, preserving null-like values."""
    if pd.isna(value):
        return None
    return re.sub(r'\s+', ' ', str(value).strip().lower())


def clean_price_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Clean raw scraped prices and add fields needed for analysis.

    The function keeps the original input unchanged, coerces price and volume
    columns to numeric values, removes unusable rows, deduplicates products,
    and computes equivalent prices for a 750 ml bottle.
    """
    out = df.copy()
    # Coerce extraction fields to numeric values so invalid text becomes NaN
    # and can be filtered consistently.
    out['precio_lista_crc'] = pd.to_numeric(out['precio_lista_crc'], errors='coerce')
    out['precio_oferta_crc'] = pd.to_numeric(out['precio_oferta_crc'], errors='coerce')
    out['precio_final_crc'] = out['precio_oferta_crc'].fillna(out['precio_lista_crc'])
    out['precio_final_crc'] = pd.to_numeric(out['precio_final_crc'], errors='coerce')
    out['presentacion_ml'] = pd.to_numeric(out['presentacion_ml'], errors='coerce')
    out['producto'] = out['producto'].apply(normalize_text)
    out['retailer'] = out['retailer'].apply(normalize_text)
    # Keep rows that can support price comparison and remove repeated products
    # from the same retailer at the same final price.
    out = out.dropna(subset=['producto', 'precio_final_crc', 'presentacion_ml'])
    out = out[out['precio_final_crc'] > 0]
    out = out.drop_duplicates(['retailer', 'producto', 'precio_final_crc'])
    # Convert all bottles to a comparable 750 ml price before assigning the
    # descriptive price segment.
    out['precio_equivalente_750ml_crc'] = (out['precio_final_crc'] / out['presentacion_ml'] * 750).round(2)
    out['segmento_precio'] = pd.cut(
        out['precio_equivalente_750ml_crc'],
        bins=[0, 5000, 10000, 15000, 999999],
        labels=['económico', 'medio', 'premium', 'super premium']
    )
    return out[[column for column in CLEAN_OUTPUT_COLUMNS if column in out.columns]]
