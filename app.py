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
def load_latest_dataset() -> pd.DataFrame:
    """Load the latest clean dataset from S3, falling back to the local CSV."""
    bucket = get_setting('AWS_S3_BUCKET')
    prefix = get_setting('AWS_S3_PREFIX')
    key = '/'.join(part.strip('/') for part in [prefix, 'latest/webscraping_precios_vino_clean.csv'] if part.strip('/'))

    if bucket:
        client = build_s3_client()
        response = client.get_object(Bucket=bucket, Key=key)
        return pd.read_csv(BytesIO(response['Body'].read()))

    local_path = ROOT / 'results' / 'webscraping_precios_vino_clean.csv'
    return pd.read_csv(local_path)


st.set_page_config(page_title='Vinos CR', layout='wide')
st.title('Vinos CR')

df = load_latest_dataset()

latest_date = df['fecha_extraccion'].max() if 'fecha_extraccion' in df else 'sin fecha'
col1, col2, col3 = st.columns(3)
col1.metric('Fecha latest', latest_date)
col2.metric('Productos', len(df))
col3.metric('Retailers', df['retailer'].nunique() if 'retailer' in df else 0)

st.dataframe(df, use_container_width=True)

if {'retailer', 'precio_equivalente_750ml_crc'}.issubset(df.columns):
    chart_data = (
        df.groupby('retailer')['precio_equivalente_750ml_crc']
        .mean()
        .sort_values()
        .reset_index()
    )
    st.bar_chart(chart_data, x='retailer', y='precio_equivalente_750ml_crc')
