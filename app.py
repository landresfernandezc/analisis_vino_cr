from __future__ import annotations

import os
from io import BytesIO

import pandas as pd
import streamlit as st

from src.utils.io import ROOT


def get_setting(name: str, default: str = '') -> str:
    """Read Streamlit secrets first, then environment variables."""
    try:
        value = st.secrets.get(name)
    except Exception:
        value = None
    return str(value or os.getenv(name, default))


def build_s3_client():
    """Create an S3 client using Streamlit secrets or environment credentials."""
    import boto3

    credentials = {
        'aws_access_key_id': get_setting('AWS_ACCESS_KEY_ID'),
        'aws_secret_access_key': get_setting('AWS_SECRET_ACCESS_KEY'),
        'aws_session_token': get_setting('AWS_SESSION_TOKEN'),
        'region_name': get_setting('AWS_REGION') or get_setting('AWS_DEFAULT_REGION'),
    }
    credentials = {key: value for key, value in credentials.items() if value}
    return boto3.client('s3', **credentials)


@st.cache_data(ttl=900)
def load_clean_dataset() -> pd.DataFrame:
    """Load the accumulated clean dataset from S3, falling back to local CSV."""
    bucket = get_setting('AWS_S3_BUCKET')
    prefix = get_setting('AWS_S3_PREFIX')
    key = '/'.join(part.strip('/') for part in [prefix, 'clean/webscraping_precios_vino_clean.csv'] if part.strip('/'))

    if bucket:
        client = build_s3_client()
        response = client.get_object(Bucket=bucket, Key=key)
        return pd.read_csv(BytesIO(response['Body'].read()))

    local_path = ROOT / 'results' / 'webscraping_precios_vino_clean.csv'
    return pd.read_csv(local_path)


@st.cache_data(ttl=900)
def load_exchange_rate_dataset() -> pd.DataFrame | None:
    """Load accumulated exchange-rate data when it exists."""
    bucket = get_setting('AWS_S3_BUCKET')
    prefix = get_setting('AWS_S3_PREFIX')
    key = '/'.join(part.strip('/') for part in [prefix, 'latest/tipo_cambio_bccr.csv'] if part.strip('/'))

    try:
        if bucket:
            client = build_s3_client()
            response = client.get_object(Bucket=bucket, Key=key)
            return pd.read_csv(BytesIO(response['Body'].read()))

        local_path = ROOT / 'results' / 'tipo_cambio_bccr.csv'
        if local_path.exists():
            return pd.read_csv(local_path)
    except Exception:
        return None
    return None


st.set_page_config(page_title='Vinos CR', layout='wide')
st.title('Vinos CR')

df = load_clean_dataset()
exchange_df = load_exchange_rate_dataset()

for column in ['precio_equivalente_750ml_crc', 'precio_final_crc', 'descuento_pct']:
    if column in df.columns:
        df[column] = pd.to_numeric(df[column], errors='coerce')
if 'fecha_extraccion' in df.columns:
    df['fecha_extraccion'] = pd.to_datetime(df['fecha_extraccion'], errors='coerce')

st.sidebar.header('Filtros')
selected_retailers = st.sidebar.multiselect(
    'Retailer', sorted(df['retailer'].dropna().unique()) if 'retailer' in df else []
)
selected_categories = st.sidebar.multiselect(
    'Categoría', sorted(df['categoria'].dropna().unique()) if 'categoria' in df else []
)
selected_segments = st.sidebar.multiselect(
    'Segmento de precio', sorted(df['segmento_precio'].dropna().astype(str).unique())
    if 'segmento_precio' in df else []
)
exchange_column = st.sidebar.selectbox(
    'Tipo de cambio para traspaso',
    ['tipo_cambio_venta_usd', 'tipo_cambio_compra_usd'],
)

filtered_df = df.copy()
if selected_retailers:
    filtered_df = filtered_df[filtered_df['retailer'].isin(selected_retailers)]
if selected_categories:
    filtered_df = filtered_df[filtered_df['categoria'].isin(selected_categories)]
if selected_segments:
    filtered_df = filtered_df[filtered_df['segmento_precio'].astype(str).isin(selected_segments)]
if filtered_df.empty:
    st.warning('No hay registros para los filtros seleccionados.')
    st.stop()

latest_date = filtered_df['fecha_extraccion'].max().date().isoformat() if 'fecha_extraccion' in filtered_df else 'sin fecha'
average_price = filtered_df['precio_equivalente_750ml_crc'].mean()
median_price = filtered_df['precio_equivalente_750ml_crc'].median()
average_discount = filtered_df['descuento_pct'].mean() if 'descuento_pct' in filtered_df else None
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric('Última extracción', latest_date)
col2.metric('Registros', len(filtered_df))
col3.metric('Precio medio / 750 ml', f'₡{average_price:,.0f}')
col4.metric('Descuento medio', f'{average_discount:.1f}%' if average_discount is not None else 'n/d')
if exchange_df is not None and {'indicador', 'valor_crc'}.issubset(exchange_df.columns):
    latest_exchange = exchange_df.sort_values('fecha_extraccion').groupby('indicador').tail(1)
    venta = latest_exchange.loc[latest_exchange['indicador'].str.contains('venta', case=False, na=False), 'valor_crc']
    col5.metric('USD venta CRC', round(float(venta.iloc[-1]), 2) if not venta.empty else 'n/d')
else:
    col5.metric('USD venta CRC', 'n/d')

st.caption(f'Mediana de precio equivalente: ₡{median_price:,.0f}')

st.subheader('Comparación de precios')
chart_col1, chart_col2 = st.columns(2)
with chart_col1:
    retailer_prices = (
        filtered_df.groupby('retailer', as_index=False)['precio_equivalente_750ml_crc']
        .mean()
        .sort_values('precio_equivalente_750ml_crc')
    )
    st.bar_chart(retailer_prices, x='retailer', y='precio_equivalente_750ml_crc')
with chart_col2:
    category_prices = (
        filtered_df.groupby('categoria', as_index=False)['precio_equivalente_750ml_crc']
        .mean()
        .sort_values('precio_equivalente_750ml_crc')
    )
    st.bar_chart(category_prices, x='categoria', y='precio_equivalente_750ml_crc')

st.subheader('Distribución del catálogo')
distribution_col1, distribution_col2 = st.columns(2)
with distribution_col1:
    segment_counts = (
        filtered_df['segmento_precio']
        .value_counts()
        .rename_axis('segmento_precio')
        .reset_index(name='registros')
    )
    st.bar_chart(segment_counts, x='segmento_precio', y='registros')
with distribution_col2:
    daily_counts = filtered_df.groupby('fecha_extraccion').size().rename('registros')
    st.line_chart(daily_counts, y='registros')

st.subheader('Precio y traspaso del tipo de cambio')
daily_columns = {'fecha_extraccion', 'precio_equivalente_750ml_crc', exchange_column}
if daily_columns.issubset(filtered_df.columns):
    daily = (
        filtered_df.dropna(subset=['fecha_extraccion', 'precio_equivalente_750ml_crc', exchange_column])
        .groupby('fecha_extraccion', as_index=False)
        .agg(
            precio_promedio_750ml_crc=('precio_equivalente_750ml_crc', 'mean'),
            tipo_cambio=(exchange_column, 'mean'),
            registros=('precio_equivalente_750ml_crc', 'count'),
        )
        .sort_values('fecha_extraccion')
    )
    daily['variacion_precio_pct'] = daily['precio_promedio_750ml_crc'].pct_change() * 100
    daily['variacion_tipo_cambio_pct'] = daily['tipo_cambio'].pct_change() * 100
    daily['traspaso_tipo_cambio_pct'] = (
        daily['variacion_precio_pct']
        .div(daily['variacion_tipo_cambio_pct'].where(daily['variacion_tipo_cambio_pct'].abs() > 1e-9))
        * 100
    )

    price_col, exchange_col = st.columns(2)
    with price_col:
        st.caption('Precio promedio equivalente a 750 ml')
        st.line_chart(daily.set_index('fecha_extraccion')[['precio_promedio_750ml_crc']])
    with exchange_col:
        st.caption('Tipo de cambio diario')
        st.line_chart(daily.set_index('fecha_extraccion')[['tipo_cambio']])

    valid_pass_through = daily['traspaso_tipo_cambio_pct'].dropna()
    if len(daily) > 1:
        first_price = daily['precio_promedio_750ml_crc'].iloc[0]
        last_price = daily['precio_promedio_750ml_crc'].iloc[-1]
        first_exchange = daily['tipo_cambio'].iloc[0]
        last_exchange = daily['tipo_cambio'].iloc[-1]
        price_change = (last_price / first_price - 1) * 100 if first_price else None
        exchange_change = (last_exchange / first_exchange - 1) * 100 if first_exchange else None
        pass_through = valid_pass_through.median() if not valid_pass_through.empty else None
        metric_price, metric_exchange, metric_pass = st.columns(3)
        metric_price.metric('Cambio acumulado precio', f'{price_change:.2f}%')
        metric_exchange.metric('Cambio acumulado tipo de cambio', f'{exchange_change:.2f}%')
        metric_pass.metric(
            'Traspaso mediano',
            f'{pass_through:.2f}%' if pass_through is not None else 'n/d',
            help='100% significa que el precio cambia proporcionalmente al tipo de cambio.',
        )
    else:
        st.info('Se necesitan al menos dos fechas de extracción para calcular variaciones y traspaso.')

    st.caption('Variaciones y traspaso por fecha')
    st.dataframe(
        daily[
            [
                'fecha_extraccion',
                'precio_promedio_750ml_crc',
                'tipo_cambio',
                'registros',
                'variacion_precio_pct',
                'variacion_tipo_cambio_pct',
                'traspaso_tipo_cambio_pct',
            ]
        ],
        use_container_width=True,
    )
else:
    st.info('El dataset no contiene precios y tipos de cambio suficientes para el análisis temporal.')

st.subheader('Datos filtrados')
st.dataframe(filtered_df, use_container_width=True)

if exchange_df is not None:
    st.subheader('Tipo de cambio BCCR')
    st.dataframe(exchange_df, use_container_width=True)
