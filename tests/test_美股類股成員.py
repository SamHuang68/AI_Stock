"""美股類股持股來源與行情缺值契約。"""

import importlib.util
import io
import pathlib
import unittest
import urllib.error
import zipfile
from unittest.mock import Mock, patch
from xml.sax.saxutils import escape


_PATH = pathlib.Path(__file__).resolve().parents[1] / 'server' / '美股類股成員.py'
_SPEC = importlib.util.spec_from_file_location('us_sector_members_tested', _PATH)
members = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(members)


def workbook(symbol='XLK', as_of='As of 08-Sep-2026', missing_column=False, inline=False):
    """建立具有共用字串與真實資料結構的最小持股檔。"""
    rows = [
        ['Fund Name:', '科技類股基金'], ['Ticker Symbol:', symbol], ['Holdings:', as_of], [],
        ['Name', 'Ticker', 'Identifier', 'SEDOL', 'Weight', 'Sector', 'Shares Held', 'Local Currency'],
        ['輝達', 'NVDA', '67066G104', '2379504', '14.580383', '-', '78979017', 'USD'],
        ['波克夏', 'BRK.B', '084670702', '2073390', '1.2', '-', '10', 'USD'],
        ['政府貨幣基金', '-', '924QSGII3', '-', '0.014797', '-', '100', 'USD'],
        ['美元現金', '-', '999USDZ92', '-', '0.009194', '-', '100', 'USD'],
        ['科技期貨', 'IXTU6', 'ADI394XJ2', '-', '-0.001997', '-', '21200', 'USD'],
        [], ['資料使用說明'],
    ]
    if missing_column:
        rows[4][3] = '其他欄位'
    strings = []
    xml_rows = []
    for index, row in enumerate(rows, 1):
        cells = []
        for col, value in enumerate(row):
            coordinate = f'{chr(65 + col)}{index}'
            if inline:
                cells.append(f'<c r="{coordinate}" t="inlineStr"><is><t>{escape(value)}</t></is></c>')
            else:
                strings.append(value)
                cells.append(f'<c r="{coordinate}" t="s"><v>{len(strings) - 1}</v></c>')
        xml_rows.append(f'<row r="{index}">{"".join(cells)}</row>')
    output = io.BytesIO()
    namespace = members._NS['s']
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('xl/worksheets/sheet1.xml', f'<worksheet xmlns="{namespace}"><sheetData>{"".join(xml_rows)}</sheetData></worksheet>')
        if not inline:
            archive.writestr('xl/sharedStrings.xml', f'<sst xmlns="{namespace}">' + ''.join(f'<si><t>{escape(value)}</t></si>' for value in strings) + '</sst>')
    return output.getvalue()


class HoldingsTests(unittest.TestCase):
    def setUp(self):
        members._cache.clear()

    def test_parser_keeps_source_date_and_excludes_cash_futures(self):
        parsed = members._parse_holdings(workbook(), 'XLK')
        self.assertEqual(parsed['holdingsAsOf'], '2026-09-08')
        self.assertEqual([row['code'] for row in parsed['members']], ['NVDA', 'BRK-B'])
        self.assertEqual(parsed['excludedNonStockCount'], 3)
        self.assertAlmostEqual(parsed['members'][0]['weightPct'], 14.580383)

    def test_inline_strings_supported(self):
        self.assertEqual(len(members._parse_holdings(workbook(inline=True), 'XLK')['members']), 2)

    def test_invalid_date_symbol_and_columns_fail_closed(self):
        for content, code in [
            (workbook(as_of=''), 'holdings_date_missing'),
            (workbook(as_of='As of 31-Feb-2026'), 'holdings_date_invalid'),
            (workbook(symbol='XLE'), 'holdings_symbol_mismatch'),
            (workbook(missing_column=True), 'holdings_columns_missing'),
            ('<html>暫時無法取得</html>'.encode('utf-8'), 'holdings_format_invalid'),
        ]:
            with self.subTest(code=code), self.assertRaises(members.HoldingsError) as raised:
                members._parse_holdings(content, 'XLK')
            self.assertEqual(raised.exception.code, code)

    def test_only_exact_allowlisted_etfs_can_request(self):
        with patch.object(members, '_download_holdings') as fetch:
            response = members.get_members('../XLK', Mock())
        fetch.assert_not_called()
        self.assertFalse(response['ok'])
        self.assertEqual(len(members.HOLDINGS_URLS), 11)

    def test_download_uses_source_date_and_caches_only_holdings(self):
        source = Mock(status=200, url=members.HOLDINGS_URLS['XLK'])
        source.read.return_value = workbook()
        source.__enter__ = Mock(return_value=source)
        source.__exit__ = Mock(return_value=False)
        with patch.object(members.urllib.request, 'urlopen', return_value=source) as fetch:
            first = members._download_holdings('XLK')
            second = members._download_holdings('XLK')
        self.assertEqual(first['holdingsAsOf'], '2026-09-08')
        self.assertIs(first, second)
        fetch.assert_called_once()

    def test_http_failure_and_timeout_are_diagnostic(self):
        errors = [urllib.error.HTTPError('https://www.ssga.com/', 503, '', {}, None), TimeoutError()]
        for error in errors:
            with self.subTest(error=type(error).__name__), patch.object(members.urllib.request, 'urlopen', side_effect=error):
                response = members.get_members('XLK', Mock())
            self.assertFalse(response['ok'])
            self.assertTrue(response['unavailableReason'])
            self.assertEqual(response['count'], 0)

    def test_partial_quotes_preserve_all_members_without_filling_zero(self):
        holdings = members._parse_holdings(workbook(), 'XLK')
        quotes = Mock(return_value=[{'symbol': 'NVDA', 'price': 110, 'prevClose': 100,
                                    'changePct': 10, 'asOf': '2026-09-09T20:00:00Z', 'source': 'yahoo-mktbar'}])
        with patch.object(members, '_download_holdings', return_value=holdings):
            response = members.get_members('XLK', quotes)
        self.assertTrue(response['ok'])
        self.assertEqual(response['holdingsAsOf'], '2026-09-08')
        self.assertEqual(response['quoteAsOf'], '2026-09-09T20:00:00Z')
        self.assertEqual(response['rows'][0]['change'], 10)
        self.assertIsNone(response['rows'][1]['price'])
        self.assertIsNone(response['rows'][1]['changePct'])
        self.assertIsNone(response['rows'][1]['asOf'])
        self.assertEqual(response['count'], 2)
        self.assertEqual(response['quotedCount'], 1)

    def test_batches_are_bounded_and_failure_retains_rows(self):
        holdings = {'holdingsAsOf': '2026-09-08', 'excludedNonStockCount': 0,
                    'members': [{'code': f'股{i}', 'name': f'股票 {i}'} for i in range(53)]}
        quotes = Mock(side_effect=TimeoutError())
        with patch.object(members, '_download_holdings', return_value=holdings):
            response = members.get_members('XLK', quotes)
        self.assertEqual([len(call.args[0]) for call in quotes.call_args_list], [12, 12, 12, 12, 5])
        self.assertEqual(response['count'], 53)
        self.assertEqual(response['quotedCount'], 0)
        self.assertTrue(all(row['price'] is None for row in response['rows']))

    def test_nan_prices_and_mixed_quote_dates_are_not_fabricated(self):
        holdings = members._parse_holdings(workbook(), 'XLK')
        rows = [{'symbol': 'NVDA', 'price': 20, 'changePct': 1, 'asOf': '2026-09-09T20:00:00Z'},
                {'symbol': 'BRK-B', 'price': 40, 'changePct': 2, 'asOf': '2026-09-08T20:00:00Z'}]
        with patch.object(members, '_download_holdings', return_value=holdings):
            response = members.get_members('XLK', lambda _: rows)
        self.assertIsNone(response['quoteAsOf'])
        self.assertEqual(response['quoteAsOfFrom'], '2026-09-08T20:00:00Z')
        rows[1]['price'] = float('nan')
        with patch.object(members, '_download_holdings', return_value=holdings):
            response = members.get_members('XLK', lambda _: rows)
        self.assertIsNone(response['rows'][1]['price'])
        self.assertIsNone(response['rows'][1]['changePct'])


if __name__ == '__main__':
    unittest.main()
