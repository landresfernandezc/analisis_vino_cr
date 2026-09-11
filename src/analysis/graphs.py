from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault('MPLCONFIGDIR', str(PROJECT_ROOT / '.matplotlib'))

import matplotlib
import matplotlib.pyplot as plt
import pandas as pd

from src.utils.io import ROOT, load_yaml

matplotlib.use('Agg')

GRAPH_COLUMNS = {'retailer', 'precio_equivalente_750ml_crc'}


def configured_retailers(config_path: Path | None = None) -> list[str]:
    """Return enabled retailer names from the scraping configuration."""
    config_path = config_path or ROOT / 'src' / 'config' / 'sources.yaml'
    config = load_yaml(config_path)
    retailers = []
    for source in config.get('scraping_sources', []):
        if source.get('enabled', True):
            retailers.append(source['retailer'])
    return retailers


def validate_graph_columns(df: pd.DataFrame) -> None:
    """Ensure the cleaned dataset has the fields required by the graphs."""
    missing = GRAPH_COLUMNS.difference(df.columns)
    if missing:
        raise RuntimeError(f'El dataset limpio no tiene las columnas requeridas para graficos: {sorted(missing)}')


def _prepare_price_data(df: pd.DataFrame) -> pd.DataFrame:
    """Return only valid retailer and 750 ml equivalent price rows."""
    validate_graph_columns(df)
    out = df.copy()
    out['precio_equivalente_750ml_crc'] = pd.to_numeric(out['precio_equivalente_750ml_crc'], errors='coerce')
    out = out.dropna(subset=['retailer', 'precio_equivalente_750ml_crc'])
    out = out[out['precio_equivalente_750ml_crc'] > 0]
    if out.empty:
        raise RuntimeError('No hay datos validos para generar graficos de precios.')
    return out


def save_average_price_by_retailer(
    df: pd.DataFrame,
    output_dir: Path,
    retailers: list[str] | None = None,
) -> Path:
    """Generate a bar chart with average equivalent 750 ml price by retailer."""
    data = _prepare_price_data(df)
    summary = (
        data.groupby('retailer', as_index=False)['precio_equivalente_750ml_crc']
        .mean()
        .sort_values('retailer')
    )
    if retailers:
        summary = (
            pd.DataFrame({'retailer': retailers})
            .merge(summary, on='retailer', how='left')
        )

    fig, ax = plt.subplots(figsize=(8, 4.5))
    plot_values = summary['precio_equivalente_750ml_crc'].fillna(0)
    bars = ax.bar(summary['retailer'], plot_values)
    ax.set_title('Precio promedio equivalente por 750 ml')
    ax.set_xlabel('retailer')
    ax.set_ylabel('CRC')
    ax.tick_params(axis='x', labelrotation=90)

    for bar, value in zip(bars, summary['precio_equivalente_750ml_crc']):
        if pd.isna(value):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                0,
                'Sin datos',
                ha='center',
                va='bottom',
                rotation=90,
                fontsize=8,
            )
    fig.tight_layout()

    output_path = output_dir / 'precio_promedio_equivalente_750ml_por_retailer.png'
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    return output_path


def save_price_distribution(df: pd.DataFrame, output_dir: Path) -> Path:
    """Generate a histogram of equivalent 750 ml prices."""
    data = _prepare_price_data(df)

    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.hist(data['precio_equivalente_750ml_crc'], bins=10)
    ax.set_title('Distribucion de precios equivalentes 750 ml')
    ax.set_xlabel('CRC')
    ax.set_ylabel('Frequency')
    fig.tight_layout()

    output_path = output_dir / 'distribucion_precios_equivalentes_750ml.png'
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    return output_path


def generate_graphs(
    df: pd.DataFrame,
    output_dir: Path | None = None,
    retailers: list[str] | None = None,
) -> list[Path]:
    """Generate all project graphs from the cleaned price dataset."""
    output_dir = output_dir or ROOT / 'graphs'
    output_dir.mkdir(parents=True, exist_ok=True)
    retailers = retailers or configured_retailers()
    return [
        save_average_price_by_retailer(df, output_dir, retailers),
        save_price_distribution(df, output_dir),
    ]


def generate_graphs_from_results(clean_path: Path | None = None, output_dir: Path | None = None) -> list[Path]:
    """Load the cleaned CSV from results and generate the graph PNG files."""
    clean_path = clean_path or ROOT / 'results' / 'webscraping_precios_vino_clean.csv'
    clean = pd.read_csv(clean_path)
    return generate_graphs(clean, output_dir)
