from __future__ import annotations

import re
import pandas as pd


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
    out['producto_normalizado'] = out['producto'].apply(normalize_text)
    out['retailer_normalizado'] = out['retailer'].apply(normalize_text)
    # Keep rows that can support price comparison and remove repeated products
    # from the same retailer at the same final price.
    out = out.dropna(subset=['producto_normalizado', 'precio_final_crc', 'presentacion_ml'])
    out = out[out['precio_final_crc'] > 0]
    out = out.drop_duplicates(['retailer_normalizado', 'producto_normalizado', 'precio_final_crc'])
    # Convert all bottles to a comparable 750 ml price before assigning the
    # descriptive price segment.
    out['precio_equivalente_750ml_crc'] = (out['precio_final_crc'] / out['presentacion_ml'] * 750).round(2)
    out['segmento_precio'] = pd.cut(
        out['precio_equivalente_750ml_crc'],
        bins=[0, 5000, 10000, 15000, 999999],
        labels=['económico', 'medio', 'premium', 'super premium']
    )
    return out
