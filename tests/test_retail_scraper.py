from src.extractors.retail_scraper import RetailSource, RetailWineScraper


def test_parse_price_costa_rican_thousands_format():
    """Prices like 2.330 and 2,330 should be interpreted as thousands."""
    scraper = RetailWineScraper([RetailSource('retailer', 'categoria', 'https://example.com')])

    assert scraper._parse_price('2.330') == 2330.0
    assert scraper._parse_price('2,330') == 2330.0
    assert scraper._parse_price('12.280') == 12280.0
    assert scraper._parse_price('₡ 2.330') == 2330.0
    assert scraper._parse_price('₡ 12.280') == 12280.0


def test_parse_price_decimal_format_when_decimal_part_is_not_three_digits():
    """Decimal cents should be preserved when the final group is not thousands."""
    scraper = RetailWineScraper([RetailSource('retailer', 'categoria', 'https://example.com')])

    assert scraper._parse_price('2330.50') == 2330.50
    assert scraper._parse_price('2.330,50') == 2330.50
    assert scraper._parse_price('2,330.50') == 2330.50


def test_parse_pricesmart_pack_presentation_as_total_volume():
    """PriceSmart pack labels should be converted into total milliliters."""
    scraper = RetailWineScraper([RetailSource('retailer', 'categoria', 'https://example.com')])

    assert scraper._parse_presentation_ml('Vino Ejemplo 6 Unidades / 750 mL') == 4500.0
