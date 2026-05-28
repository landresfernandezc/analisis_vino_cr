from src.extractors.retail_scraper import RetailSource, RetailWineScraper


def test_parse_price_costa_rican_thousands_format():
    scraper = RetailWineScraper([RetailSource('retailer', 'categoria', 'https://example.com')])

    assert scraper._parse_price('2.330') == 2330.0
    assert scraper._parse_price('2,330') == 2330.0
    assert scraper._parse_price('12.280') == 12280.0
    assert scraper._parse_price('₡ 2.330') == 2330.0


def test_parse_price_decimal_format_when_decimal_part_is_not_three_digits():
    scraper = RetailWineScraper([RetailSource('retailer', 'categoria', 'https://example.com')])

    assert scraper._parse_price('2330.50') == 2330.50
    assert scraper._parse_price('2.330,50') == 2330.50
    assert scraper._parse_price('2,330.50') == 2330.50
