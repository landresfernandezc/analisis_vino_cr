from __future__ import annotations

from io import BytesIO
import os
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st


ROOT = Path(__file__).resolve().parent
PRICE_COLUMN = 'precio_equivalente_750ml_crc'
FINAL_PRICE_COLUMN = 'precio_final_crc'
DISCOUNT_COLUMN = 'descuento_pct'
DATE_COLUMN = 'fecha_extraccion'


def get_setting(name: str, default: str = '') -> str:
    """Read environment variables first, then Streamlit secrets."""
    value = os.getenv(name)
    if value:
        return str(value)
    try:
        value = st.secrets.get(name)
    except Exception:
        value = None
    if not value:
        try:
            value = st.secrets.get('aws', {}).get(name)
        except Exception:
            value = None
    return str(value or default)


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


def join_s3_key(*parts: str) -> str:
    return '/'.join(part.strip('/') for part in parts if part and part.strip('/'))


def s3_clean_dataset_keys(prefix: str) -> list[str]:
    """Return S3 clean dataset keys in the order the Streamlit app should try them."""
    configured_key = get_setting('AWS_S3_CLEAN_KEY') or get_setting('AWS_S3_KEY')
    keys = [
        configured_key,
        join_s3_key(prefix, 'clean', 'webscraping_precios_vino_clean.csv'),
        join_s3_key(prefix, 'latest', 'webscraping_precios_vino_clean.csv'),
    ]
    return list(dict.fromkeys(key for key in keys if key))


@st.cache_data(ttl=900)
def load_clean_dataset() -> tuple[pd.DataFrame, str]:
    """Load the daily clean dataset from S3, falling back to local CSV."""
    bucket = get_setting('AWS_S3_BUCKET')
    prefix = get_setting('AWS_S3_PREFIX')

    if bucket:
        from botocore.exceptions import ClientError

        client = build_s3_client()
        errors = []
        for key in s3_clean_dataset_keys(prefix):
            try:
                response = client.get_object(Bucket=bucket, Key=key)
                return pd.read_csv(BytesIO(response['Body'].read())), f's3://{bucket}/{key}'
            except ClientError as exc:
                error_code = exc.response.get('Error', {}).get('Code')
                if error_code in {'NoSuchKey', '404'}:
                    errors.append(f's3://{bucket}/{key}')
                    continue
                raise
        missing = ', '.join(errors)
        raise FileNotFoundError(f'No se encontro el CSV limpio en S3. Rutas probadas: {missing}')

    local_path = ROOT / 'results' / 'webscraping_precios_vino_clean.csv'
    if local_path.exists():
        return pd.read_csv(local_path), str(local_path)
    raise FileNotFoundError(
        'No se encontro el CSV local y AWS_S3_BUCKET no esta configurado. '
        'En produccion Streamlit debe tener configurados los secrets de S3.'
    )


@st.cache_data(ttl=900)
def load_exchange_rate_dataset() -> tuple[pd.DataFrame, str] | tuple[None, None]:
    """Load accumulated exchange-rate data when it exists."""
    bucket = get_setting('AWS_S3_BUCKET')
    prefix = get_setting('AWS_S3_PREFIX')
    configured_key = get_setting('AWS_S3_EXCHANGE_KEY')
    key = configured_key or join_s3_key(prefix, 'latest', 'tipo_cambio_bccr.csv')

    try:
        if bucket:
            client = build_s3_client()
            response = client.get_object(Bucket=bucket, Key=key)
            return pd.read_csv(BytesIO(response['Body'].read())), f's3://{bucket}/{key}'

        local_path = ROOT / 'results' / 'tipo_cambio_bccr.csv'
        if local_path.exists():
            return pd.read_csv(local_path), str(local_path)
    except Exception:
        return None, None
    return None, None


def normalize_text(value: object) -> object:
    """Fix common Windows/UTF-8 mojibake while leaving normal values untouched."""
    if not isinstance(value, str):
        return value
    replacements = {
        'econ�mico': 'económico',
        'economico': 'económico',
    }
    return replacements.get(value, value)


def prepare_dataset(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce dates, numeric columns, and text fields used by the dashboard."""
    out = df.copy()
    numeric_columns = [
        PRICE_COLUMN,
        FINAL_PRICE_COLUMN,
        'precio_lista_crc',
        'precio_oferta_crc',
        DISCOUNT_COLUMN,
        'presentacion_ml',
        'tipo_cambio_compra_usd',
        'tipo_cambio_venta_usd',
    ]
    for column in numeric_columns:
        if column in out.columns:
            out[column] = pd.to_numeric(out[column], errors='coerce')
    if DATE_COLUMN in out.columns:
        out[DATE_COLUMN] = pd.to_datetime(out[DATE_COLUMN], errors='coerce')
    for column in ['retailer', 'categoria', 'segmento_precio', 'producto']:
        if column in out.columns:
            out[column] = out[column].map(normalize_text)
    return out


def format_crc(value: float | int | None) -> str:
    if pd.isna(value):
        return 'n/d'
    return f'₡{value:,.0f}'


def filter_with_multiselect(df: pd.DataFrame, column: str, label: str) -> list[str]:
    if column not in df.columns:
        return []
    options = sorted(df[column].dropna().astype(str).unique())
    return st.sidebar.multiselect(label, options)


def price_summary(df: pd.DataFrame, group_columns: list[str]) -> pd.DataFrame:
    return (
        df.dropna(subset=[PRICE_COLUMN])
        .groupby(group_columns, dropna=False)
        .agg(
            productos=('producto', 'nunique') if 'producto' in df.columns else (PRICE_COLUMN, 'count'),
            registros=(PRICE_COLUMN, 'count'),
            precio_promedio=(PRICE_COLUMN, 'mean'),
            precio_mediana=(PRICE_COLUMN, 'median'),
            precio_minimo=(PRICE_COLUMN, 'min'),
            precio_maximo=(PRICE_COLUMN, 'max'),
            descuento_promedio=(DISCOUNT_COLUMN, 'mean') if DISCOUNT_COLUMN in df.columns else (PRICE_COLUMN, 'size'),
        )
        .round(2)
        .reset_index()
        .sort_values('precio_promedio', ascending=False)
    )


def top_products(df: pd.DataFrame, ascending: bool) -> pd.DataFrame:
    if 'producto' not in df.columns:
        return pd.DataFrame()
    columns = ['producto', 'retailer', 'categoria', PRICE_COLUMN, FINAL_PRICE_COLUMN, DISCOUNT_COLUMN]
    columns = [column for column in columns if column in df.columns]
    return (
        df.dropna(subset=[PRICE_COLUMN])
        .sort_values(PRICE_COLUMN, ascending=ascending)
        .loc[:, columns]
        .head(10)
    )


def build_model_dataset(df: pd.DataFrame, exchange_column: str) -> pd.DataFrame:
    """Build a modeling table for wine price behavior and exchange-rate pass-through."""
    required_columns = [PRICE_COLUMN, exchange_column, DATE_COLUMN]
    optional_columns = [
        DISCOUNT_COLUMN,
        'presentacion_ml',
        'retailer',
        'categoria',
        'segmento_precio',
    ]
    columns = [column for column in required_columns + optional_columns if column in df.columns]
    model_df = df.loc[:, columns].copy()
    model_df = model_df.dropna(subset=required_columns)
    model_df = model_df[(model_df[PRICE_COLUMN] > 0) & (model_df[exchange_column] > 0)]
    if model_df.empty:
        return model_df

    model_df = model_df.sort_values(DATE_COLUMN)
    model_df['dias_desde_inicio'] = (model_df[DATE_COLUMN] - model_df[DATE_COLUMN].min()).dt.days
    model_df['log_precio_750ml'] = np.log(model_df[PRICE_COLUMN])
    model_df = model_df.rename(columns={exchange_column: 'tipo_cambio_crc_usd'})
    return model_df


def fit_price_regression(model_df: pd.DataFrame) -> dict[str, pd.DataFrame | dict[str, float] | int] | None:
    """Fit a lightweight linear regression without adding extra ML dependencies."""
    if len(model_df) < 30:
        return None

    feature_columns = ['tipo_cambio_crc_usd', 'dias_desde_inicio']
    for column in [DISCOUNT_COLUMN, 'presentacion_ml']:
        if column in model_df.columns:
            feature_columns.append(column)

    features = model_df[feature_columns].copy()
    features = features.fillna(features.median(numeric_only=True))

    categorical_columns = [
        column
        for column in ['retailer', 'categoria', 'segmento_precio']
        if column in model_df.columns and model_df[column].notna().nunique() > 1
    ]
    if categorical_columns:
        dummies = pd.get_dummies(
            model_df[categorical_columns].fillna('Sin dato'),
            columns=categorical_columns,
            drop_first=True,
            dtype=float,
        )
        features = pd.concat([features, dummies], axis=1)

    y = model_df['log_precio_750ml'].to_numpy(dtype=float)
    dates = model_df[DATE_COLUMN]
    unique_dates = dates.dropna().sort_values().unique()
    if len(unique_dates) > 1:
        split_date = unique_dates[max(1, int(len(unique_dates) * 0.8)) - 1]
        train_mask = dates <= split_date
    else:
        train_cutoff = max(1, int(len(model_df) * 0.8))
        train_mask = pd.Series(np.arange(len(model_df)) < train_cutoff, index=model_df.index)
    test_mask = ~train_mask
    if test_mask.sum() == 0:
        test_mask.iloc[-max(1, len(model_df) // 5):] = True
        train_mask = ~test_mask

    x_train = features.loc[train_mask].astype(float)
    x_test = features.loc[test_mask].astype(float)
    y_train = y[train_mask.to_numpy()]
    y_test = y[test_mask.to_numpy()]

    means = x_train.mean()
    stds = x_train.std(ddof=0)
    usable_columns = stds[stds > 1e-9].index
    if len(usable_columns) == 0:
        return None

    x_train = x_train.loc[:, usable_columns]
    x_test = x_test.loc[:, usable_columns]
    means = means.loc[usable_columns]
    stds = stds.loc[usable_columns]
    x_train_scaled = (x_train - means) / stds
    x_test_scaled = (x_test - means) / stds

    x_train_matrix = np.column_stack([np.ones(len(x_train_scaled)), x_train_scaled.to_numpy()])
    x_test_matrix = np.column_stack([np.ones(len(x_test_scaled)), x_test_scaled.to_numpy()])
    penalty = np.eye(x_train_matrix.shape[1]) * 1.0
    penalty[0, 0] = 0.0
    coefficients = np.linalg.solve(
        x_train_matrix.T @ x_train_matrix + penalty,
        x_train_matrix.T @ y_train,
    )
    predicted_log = np.clip(x_test_matrix @ coefficients, np.log(100), np.log(10_000_000))

    predicted_price = np.exp(predicted_log)
    actual_price = np.exp(y_test)
    errors = actual_price - predicted_price
    mae = float(np.mean(np.abs(errors)))
    rmse = float(np.sqrt(np.mean(errors**2)))
    denominator = float(np.sum((actual_price - actual_price.mean()) ** 2))
    r2 = float(1 - np.sum(errors**2) / denominator) if denominator else np.nan

    coefficient_table = pd.DataFrame({
        'variable': usable_columns,
        'coeficiente_estandarizado_log_precio': coefficients[1:],
    })
    coefficient_table['impacto_abs'] = coefficient_table['coeficiente_estandarizado_log_precio'].abs()
    coefficient_table = coefficient_table.sort_values('impacto_abs', ascending=False).drop(columns='impacto_abs')

    predictions = model_df.loc[test_mask, [DATE_COLUMN, PRICE_COLUMN]].copy()
    predictions['precio_predicho_750ml_crc'] = predicted_price
    predictions['error_crc'] = predictions[PRICE_COLUMN] - predictions['precio_predicho_750ml_crc']
    predictions = predictions.round({
        PRICE_COLUMN: 2,
        'precio_predicho_750ml_crc': 2,
        'error_crc': 2,
    })

    return {
        'metrics': {'mae': mae, 'rmse': rmse, 'r2': r2},
        'coefficients': coefficient_table,
        'predictions': predictions,
        'train_rows': int(train_mask.sum()),
        'test_rows': int(test_mask.sum()),
        'feature_count': int(features.shape[1]),
    }


st.set_page_config(page_title='Vinos CR', layout='wide')
st.title('Vinos CR')
st.caption('Dashboard de precios de vinos en Costa Rica')

if st.sidebar.button('Actualizar datos desde S3'):
    st.cache_data.clear()
    st.rerun()

try:
    df_raw, clean_source = load_clean_dataset()
except Exception as exc:
    st.error('No pude cargar el CSV limpio de precios.')
    st.info(
        'En Streamlit Cloud configura estos secrets: '
        '`AWS_S3_BUCKET`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, '
        '`AWS_REGION` y, si aplica, `AWS_S3_PREFIX`. '
        'La app busca primero `clean/webscraping_precios_vino_clean.csv` dentro del prefijo.'
    )
    with st.expander('Detalle técnico'):
        st.exception(exc)
    st.stop()

df = prepare_dataset(df_raw)
exchange_df, exchange_source = load_exchange_rate_dataset()
if exchange_df is not None and DATE_COLUMN in exchange_df.columns:
    exchange_df[DATE_COLUMN] = pd.to_datetime(exchange_df[DATE_COLUMN], errors='coerce')

st.sidebar.caption(f'Fuente precios: {clean_source}')
if exchange_source:
    st.sidebar.caption(f'Fuente tipo de cambio: {exchange_source}')

st.sidebar.header('Filtros')
selected_retailers = filter_with_multiselect(df, 'retailer', 'Retailer')
selected_categories = filter_with_multiselect(df, 'categoria', 'Categoría')
selected_segments = filter_with_multiselect(df, 'segmento_precio', 'Segmento de precio')
exchange_column = st.sidebar.selectbox(
    'Tipo de cambio para traspaso',
    ['tipo_cambio_venta_usd', 'tipo_cambio_compra_usd'],
)

filtered_df = df.copy()
if selected_retailers:
    filtered_df = filtered_df[filtered_df['retailer'].astype(str).isin(selected_retailers)]
if selected_categories:
    filtered_df = filtered_df[filtered_df['categoria'].astype(str).isin(selected_categories)]
if selected_segments:
    filtered_df = filtered_df[filtered_df['segmento_precio'].astype(str).isin(selected_segments)]

if filtered_df.empty:
    st.warning('No hay registros para los filtros seleccionados.')
    st.stop()

latest_date = (
    filtered_df[DATE_COLUMN].max().date().isoformat()
    if DATE_COLUMN in filtered_df and filtered_df[DATE_COLUMN].notna().any()
    else 'sin fecha'
)
average_price = filtered_df[PRICE_COLUMN].mean()
median_price = filtered_df[PRICE_COLUMN].median()
average_discount = filtered_df[DISCOUNT_COLUMN].mean() if DISCOUNT_COLUMN in filtered_df else None
retailer_count = filtered_df['retailer'].nunique() if 'retailer' in filtered_df else 0
category_count = filtered_df['categoria'].nunique() if 'categoria' in filtered_df else 0

metric_cols = st.columns(6)
metric_cols[0].metric('Última extracción', latest_date)
metric_cols[1].metric('Registros', f'{len(filtered_df):,}')
metric_cols[2].metric('Retailers', retailer_count)
metric_cols[3].metric('Categorías', category_count)
metric_cols[4].metric('Precio medio / 750 ml', format_crc(average_price))
metric_cols[5].metric('Mediana / 750 ml', format_crc(median_price))

discount_col, min_col, max_col = st.columns(3)
discount_col.metric('Descuento medio', f'{average_discount:.1f}%' if average_discount is not None else 'n/d')
min_col.metric('Precio mínimo / 750 ml', format_crc(filtered_df[PRICE_COLUMN].min()))
max_col.metric('Precio máximo / 750 ml', format_crc(filtered_df[PRICE_COLUMN].max()))

tab_overview, tab_stats, tab_trends, tab_models, tab_data = st.tabs(
    ['Resumen visual', 'Estadísticas', 'Tendencias', 'Modelos', 'Datos']
)

with tab_overview:
    chart_col1, chart_col2 = st.columns(2)
    with chart_col1:
        st.subheader('Precio promedio por retailer')
        retailer_prices = (
            filtered_df.groupby('retailer', as_index=False)[PRICE_COLUMN]
            .mean()
            .sort_values(PRICE_COLUMN)
        )
        st.bar_chart(retailer_prices, x='retailer', y=PRICE_COLUMN)

    with chart_col2:
        st.subheader('Precio promedio por categoría')
        category_prices = (
            filtered_df.groupby('categoria', as_index=False)[PRICE_COLUMN]
            .mean()
            .sort_values(PRICE_COLUMN)
        )
        st.bar_chart(category_prices, x='categoria', y=PRICE_COLUMN)

    distribution_col1, distribution_col2 = st.columns(2)
    with distribution_col1:
        st.subheader('Catálogo por segmento')
        if 'segmento_precio' in filtered_df.columns and filtered_df['segmento_precio'].notna().any():
            segment_counts = (
                filtered_df['segmento_precio']
                .fillna('Sin segmento')
                .value_counts()
                .rename_axis('segmento_precio')
                .reset_index(name='registros')
            )
            st.bar_chart(segment_counts, x='segmento_precio', y='registros')
        else:
            st.info('No hay segmentos de precio disponibles para los filtros actuales.')

    with distribution_col2:
        st.subheader('Distribución de precios')
        prices = filtered_df[PRICE_COLUMN].dropna()
        if not prices.empty:
            bins = pd.cut(prices, bins=10)
            histogram = (
                bins.value_counts()
                .sort_index()
                .rename_axis('rango_precio')
                .reset_index(name='registros')
            )
            histogram['rango_precio'] = histogram['rango_precio'].astype(str)
            st.bar_chart(histogram, x='rango_precio', y='registros')
        else:
            st.info('No hay precios válidos para construir la distribución.')

    st.subheader('Productos extremos')
    low_col, high_col = st.columns(2)
    with low_col:
        st.caption('10 productos con menor precio equivalente')
        st.dataframe(top_products(filtered_df, ascending=True), use_container_width=True, hide_index=True)
    with high_col:
        st.caption('10 productos con mayor precio equivalente')
        st.dataframe(top_products(filtered_df, ascending=False), use_container_width=True, hide_index=True)

with tab_stats:
    st.subheader('Resumen estadístico de precios')
    descriptive_columns = [
        column
        for column in [PRICE_COLUMN, FINAL_PRICE_COLUMN, DISCOUNT_COLUMN, 'presentacion_ml']
        if column in filtered_df.columns
    ]
    descriptive = (
        filtered_df[descriptive_columns]
        .dropna(how='all')
        .describe()
        .T
        .round(2)
    )
    st.dataframe(descriptive, use_container_width=True)

    stats_col1, stats_col2 = st.columns(2)
    with stats_col1:
        st.subheader('Por retailer y categoría')
        st.dataframe(price_summary(filtered_df, ['retailer', 'categoria']), use_container_width=True, hide_index=True)
    with stats_col2:
        st.subheader('Por segmento de precio')
        if 'segmento_precio' in filtered_df.columns and filtered_df['segmento_precio'].notna().any():
            st.dataframe(price_summary(filtered_df, ['segmento_precio']), use_container_width=True, hide_index=True)
        else:
            st.info('No hay suficientes datos de segmento para resumir.')

    if DISCOUNT_COLUMN in filtered_df.columns:
        st.subheader('Descuentos por retailer')
        discount_summary = (
            filtered_df.groupby('retailer', as_index=False)
            .agg(
                descuento_promedio=(DISCOUNT_COLUMN, 'mean'),
                productos_con_descuento=(DISCOUNT_COLUMN, lambda values: (values > 0).sum()),
                registros=(DISCOUNT_COLUMN, 'count'),
            )
            .round(2)
            .sort_values('descuento_promedio', ascending=False)
        )
        st.dataframe(discount_summary, use_container_width=True, hide_index=True)

with tab_trends:
    st.subheader('Evolución temporal')
    daily_columns = {DATE_COLUMN, PRICE_COLUMN}
    if daily_columns.issubset(filtered_df.columns):
        agg_spec = {
            'precio_promedio_750ml_crc': (PRICE_COLUMN, 'mean'),
            'precio_mediana_750ml_crc': (PRICE_COLUMN, 'median'),
            'registros': (PRICE_COLUMN, 'count'),
        }
        if exchange_column in filtered_df.columns:
            agg_spec['tipo_cambio'] = (exchange_column, 'mean')
        daily = (
            filtered_df.dropna(subset=[DATE_COLUMN, PRICE_COLUMN])
            .groupby(DATE_COLUMN, as_index=False)
            .agg(**agg_spec)
            .sort_values(DATE_COLUMN)
        )

        if daily.empty:
            st.info('No hay fechas válidas para analizar tendencias.')
        else:
            price_col, records_col = st.columns(2)
            with price_col:
                st.caption('Precio promedio y mediana equivalente a 750 ml')
                st.line_chart(
                    daily.set_index(DATE_COLUMN)[['precio_promedio_750ml_crc', 'precio_mediana_750ml_crc']]
                )
            with records_col:
                st.caption('Registros por fecha de extracción')
                st.bar_chart(daily, x=DATE_COLUMN, y='registros')

            if 'tipo_cambio' in daily.columns and daily['tipo_cambio'].notna().any():
                daily['variacion_precio_pct'] = daily['precio_promedio_750ml_crc'].pct_change(fill_method=None) * 100
                daily['variacion_tipo_cambio_pct'] = daily['tipo_cambio'].pct_change(fill_method=None) * 100
                daily['traspaso_tipo_cambio_pct'] = (
                    daily['variacion_precio_pct']
                    .div(daily['variacion_tipo_cambio_pct'].where(daily['variacion_tipo_cambio_pct'].abs() > 1e-9))
                    * 100
                )

                st.caption('Tipo de cambio diario')
                st.line_chart(daily.set_index(DATE_COLUMN)[['tipo_cambio']])

                pass_col1, pass_col2 = st.columns(2)
                with pass_col1:
                    st.caption('Variación % diaria: precio vs tipo de cambio')
                    st.line_chart(
                        daily.set_index(DATE_COLUMN)[
                            ['variacion_precio_pct', 'variacion_tipo_cambio_pct']
                        ]
                    )
                with pass_col2:
                    st.caption('% de traspaso diario del tipo de cambio al precio')
                    st.bar_chart(daily, x=DATE_COLUMN, y='traspaso_tipo_cambio_pct')

                if len(daily) > 1:
                    first_price = daily['precio_promedio_750ml_crc'].iloc[0]
                    last_price = daily['precio_promedio_750ml_crc'].iloc[-1]
                    first_exchange = daily['tipo_cambio'].iloc[0]
                    last_exchange = daily['tipo_cambio'].iloc[-1]
                    price_change = (last_price / first_price - 1) * 100 if first_price else None
                    exchange_change = (last_exchange / first_exchange - 1) * 100 if first_exchange else None
                    pass_through = daily['traspaso_tipo_cambio_pct'].dropna().median()
                    trend_metrics = st.columns(3)
                    trend_metrics[0].metric('Cambio acumulado precio', f'{price_change:.2f}%')
                    trend_metrics[1].metric('Cambio acumulado tipo de cambio', f'{exchange_change:.2f}%')
                    trend_metrics[2].metric(
                        'Traspaso mediano',
                        f'{pass_through:.2f}%' if pd.notna(pass_through) else 'n/d',
                        help='100% significa que el precio cambia proporcionalmente al tipo de cambio.',
                    )

            st.dataframe(daily, use_container_width=True, hide_index=True)
    else:
        st.info('El dataset no contiene fechas y precios suficientes para el análisis temporal.')

    if exchange_df is not None:
        st.subheader('Tipo de cambio BCCR')
        st.dataframe(exchange_df, use_container_width=True, hide_index=True)

with tab_models:
    st.subheader('Resultados de algoritmos')
    model_df = build_model_dataset(filtered_df, exchange_column)
    if model_df.empty:
        st.info(
            'No hay suficientes filas con precio, fecha y tipo de cambio para modelar. '
            'Prueba quitar filtros o ejecutar la extracción con tipo de cambio.'
        )
    else:
        corr_price_exchange = model_df[[PRICE_COLUMN, 'tipo_cambio_crc_usd']].corr().iloc[0, 1]
        corr_cols = st.columns(4)
        corr_cols[0].metric('Filas para modelado', f'{len(model_df):,}')
        corr_cols[1].metric('Fechas modeladas', model_df[DATE_COLUMN].nunique())
        corr_cols[2].metric('Correlación precio-dólar', f'{corr_price_exchange:.3f}')
        corr_cols[3].metric('Tipo de cambio medio', format_crc(model_df['tipo_cambio_crc_usd'].mean()))

        daily_model = (
            model_df.groupby(DATE_COLUMN, as_index=False)
            .agg(
                precio_promedio_750ml_crc=(PRICE_COLUMN, 'mean'),
                tipo_cambio_crc_usd=('tipo_cambio_crc_usd', 'mean'),
                registros=(PRICE_COLUMN, 'count'),
            )
            .sort_values(DATE_COLUMN)
        )
        daily_model['variacion_precio_pct'] = daily_model['precio_promedio_750ml_crc'].pct_change(fill_method=None) * 100
        daily_model['variacion_tipo_cambio_pct'] = daily_model['tipo_cambio_crc_usd'].pct_change(fill_method=None) * 100
        daily_model['traspaso_tipo_cambio_pct'] = (
            daily_model['variacion_precio_pct']
            .div(
                daily_model['variacion_tipo_cambio_pct'].where(
                    daily_model['variacion_tipo_cambio_pct'].abs() > 1e-9
                )
            )
            * 100
        )

        model_chart_col, pass_through_col = st.columns(2)
        with model_chart_col:
            st.caption('Precio promedio y tipo de cambio usados por los algoritmos')
            st.line_chart(
                daily_model.set_index(DATE_COLUMN)[
                    ['precio_promedio_750ml_crc', 'tipo_cambio_crc_usd']
                ]
            )
        with pass_through_col:
            st.caption('% de traspaso diario: variación % precio / variación % dólar')
            st.bar_chart(daily_model, x=DATE_COLUMN, y='traspaso_tipo_cambio_pct')

        st.caption('Variaciones % usadas para calcular el traspaso')
        st.line_chart(
            daily_model.set_index(DATE_COLUMN)[
                ['variacion_precio_pct', 'variacion_tipo_cambio_pct']
            ]
        )

        regression = fit_price_regression(model_df)
        if regression is None:
            st.info('Se necesitan al menos 30 filas válidas para entrenar la regresión lineal.')
        else:
            st.subheader('Regresión lineal para explicar el precio')
            metric_values = regression['metrics']
            model_metric_cols = st.columns(5)
            model_metric_cols[0].metric('Filas entrenamiento', regression['train_rows'])
            model_metric_cols[1].metric('Filas prueba', regression['test_rows'])
            model_metric_cols[2].metric('Variables', regression['feature_count'])
            model_metric_cols[3].metric('MAE prueba', format_crc(metric_values['mae']))
            model_metric_cols[4].metric('R² prueba', f"{metric_values['r2']:.3f}")

            coef_col, pred_col = st.columns(2)
            with coef_col:
                st.caption('Variables con mayor impacto en el logaritmo del precio')
                st.dataframe(regression['coefficients'].head(15), use_container_width=True, hide_index=True)
            with pred_col:
                st.caption('Comparación de precio real vs predicho en prueba')
                st.dataframe(regression['predictions'].tail(25), use_container_width=True, hide_index=True)

            prediction_chart = regression['predictions'].copy()
            if not prediction_chart.empty:
                prediction_chart = prediction_chart.groupby(DATE_COLUMN, as_index=False).agg(
                    precio_real_750ml_crc=(PRICE_COLUMN, 'mean'),
                    precio_predicho_750ml_crc=('precio_predicho_750ml_crc', 'mean'),
                )
                st.caption('Precio real vs precio estimado por el modelo')
                st.line_chart(
                    prediction_chart.set_index(DATE_COLUMN)[
                        ['precio_real_750ml_crc', 'precio_predicho_750ml_crc']
                    ]
                )

        st.subheader('Base diaria para análisis de comportamiento')
        st.dataframe(daily_model.round(4), use_container_width=True, hide_index=True)

with tab_data:
    st.subheader('Datos filtrados')
    st.dataframe(filtered_df, use_container_width=True, hide_index=True)

    csv = filtered_df.to_csv(index=False).encode('utf-8')
    st.download_button(
        'Descargar datos filtrados',
        data=csv,
        file_name='vinos_cr_filtrado.csv',
        mime='text/csv',
    )
