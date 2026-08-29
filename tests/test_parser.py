from pathlib import Path

import pytest

from portfolio_copilot.parsers.broker_export import _read_rows, _to_float, parse_portfolio_export


def test_parse_synthetic_semicolon_csv(tmp_path: Path):
    content = "\n".join(
        [
            "Titolo;Tipo;Valuta;Quantità;P.zo medio di carico;P.zo di mercato;"
            "Val di mercato;Var €;Var %",
            "Vanguard FTSE All-World UCITS ETF;ETF;EUR;26;169,00;168,49;4380,74;-13,29;-0,30",
            "LEVA FISSA EXAMPLE LONG 5X;Certificate;EUR;9;21,54;22,11;198,99;5,13;2,65",
            "",
        ]
    )
    path = tmp_path / "export.csv"
    path.write_text(content, encoding="utf-8")
    p = parse_portfolio_export(str(path))
    assert len(p.holdings) == 2
    assert round(p.total_value, 2) == 4579.73
    assert p.holdings[1].leverage == 5.0


def test_parse_ignores_total_row_label_variants(tmp_path: Path):
    """Summary/footer rows whose label is a variant of 'Totale' (not an exact match
    against the hardcoded allowlist) must still be filtered out, not ingested as a
    phantom holding that duplicates the portfolio's total value."""
    content = "\n".join(
        [
            "Titolo;Tipo;Valuta;Quantità;P.zo medio di carico;P.zo di mercato;"
            "Val di mercato;Var €;Var %",
            "ACME BIOTECH;Azione;EUR;10;10,00;4,50;45,00;-18,00;-28,57",
            "Totale Titoli;;;;;;45,00;-18,00;-28,57",
            "",
        ]
    )
    path = tmp_path / "export.csv"
    path.write_text(content, encoding="utf-8")
    p = parse_portfolio_export(str(path))
    names = [h.name for h in p.holdings]

    assert "Totale Titoli" not in names
    assert len(p.holdings) == 1
    assert round(p.total_value, 2) == 45.0


FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_layout_with_strumento_and_multiline_headers():
    """Layout observed in a real Italian broker export (values are synthetic).

    - multi-line headers ("P.zo medio\\ndi carico", "Val di mercato €\\n(Margine)");
    - asset type lives in the "Strumento" column (Azione / ETF / Certificate);
    - USD instruments are valued in EUR (the header says €);
    - Italian decimals with thousands separator, signed values, percent suffix.
    """
    p = parse_portfolio_export(str(FIXTURES / "broker_export_sample.csv"))
    by_name = {h.name: h for h in p.holdings}

    assert len(p.holdings) == 7
    assert round(p.total_value, 2) == 4147.02

    assert by_name["ACME BIOTECH"].asset_type.value == "equity"
    assert by_name["FOO ROBOTICS ADR"].asset_type.value == "equity"
    assert by_name["FOO ROBOTICS ADR"].currency == "USD"
    assert by_name["Vanguard FTSE All-World UCITS ETF (USD) Acc"].asset_type.value == "etf"
    assert by_name["LEVA FISSA EXAMPLE LONG 5X"].asset_type.value == "certificate"

    vwrl = by_name["Vanguard FTSE All-World UCITS ETF (USD) Acc"]
    assert vwrl.quantity == 20
    assert vwrl.avg_cost == 150.0
    assert vwrl.market_price == 160.0
    assert vwrl.market_value == 3200.0
    assert vwrl.pnl_value == 200.0
    assert round(vwrl.pnl_pct, 4) == 0.0667

    assert round(by_name["ACME BIOTECH"].pnl_pct, 4) == -0.2857
    assert by_name["LEVA FISSA EXAMPLE LONG 5X"].leverage == 5.0
    assert by_name["LEVA FISSA OTHER LONG 3X"].leverage == 3.0
    assert by_name["iShares Core Global Aggregate Bond UCITS ETF EUR Hedged (Acc)"].leverage == 1.0


def test_parse_page_export_with_preamble_ticker_lines_and_total_row():
    """'Portafoglio' page export: summary rows before the table, ticker code on the
    first line of the Titolo cell, and a trailing 'Totale' row that must not become a holding."""
    p = parse_portfolio_export(str(FIXTURES / "broker_export_page_layout.csv"))
    names = [h.name for h in p.holdings]

    assert "Totale" not in names
    assert len(p.holdings) == 7
    assert round(p.total_value, 2) == 4147.02

    by_name = {h.name: h for h in p.holdings}
    assert by_name["ACME BIOTECH"].symbol == "AB"
    assert by_name["FOO ROBOTICS ADR"].symbol == "FR"
    assert by_name["FOO ROBOTICS ADR"].asset_type.value == "equity"
    assert by_name["Vanguard FTSE All-World UCITS ETF (USD) Acc"].symbol is None
    assert by_name["Vanguard FTSE All-World UCITS ETF (USD) Acc"].market_value == 3200.0


def test_parse_missing_pnl_pct_cell_stays_none(tmp_path: Path):
    """A row whose Var % cell is unparseable ('n.d.') must yield pnl_pct=None,
    not a fabricated 0.0 that is indistinguishable from a genuine 0% change."""
    content = "\n".join(
        [
            "Titolo;Tipo;Valuta;Quantità;P.zo medio di carico;P.zo di mercato;"
            "Val di mercato;Var €;Var %",
            "ACME BIOTECH;Azione;EUR;10;10,00;8,20;82,00;-18,00;n.d.",
            "OTHER STOCK;Azione;EUR;10;10,00;10,00;100,00;0,00;0,00",
            "",
        ]
    )
    path = tmp_path / "export.csv"
    path.write_text(content, encoding="utf-8")
    p = parse_portfolio_export(str(path))
    by_name = {h.name: h for h in p.holdings}

    acme = by_name["ACME BIOTECH"]
    assert acme.pnl_value == -18.0
    assert acme.pnl_pct is None

    other = by_name["OTHER STOCK"]
    assert other.pnl_value == 0.0
    assert other.pnl_pct == 0.0


def test_parse_does_not_false_positive_leverage_on_equity_name(tmp_path: Path):
    """The 'digitX' leverage fallback regex must not fire on a plain equity whose
    name happens to contain a digit immediately followed by 'x' (e.g. '10x Genomics
    Inc', a real NASDAQ:TXG biotech, not a leveraged instrument). With no explicit
    leverage column, a non-certificate holding must default to leverage=1.0."""
    content = "\n".join(
        [
            "Titolo;Tipo;Valuta;Quantità;P.zo medio di carico;P.zo di mercato;"
            "Val di mercato;Var €;Var %",
            "10x Genomics Inc;Azione;USD;5;50,00;55,00;275,00;25,00;10,00",
            "",
        ]
    )
    path = tmp_path / "export.csv"
    path.write_text(content, encoding="utf-8")
    p = parse_portfolio_export(str(path))
    by_name = {h.name: h for h in p.holdings}

    holding = by_name["10x Genomics Inc"]
    assert holding.asset_type.value == "equity"
    assert holding.leverage == 1.0


def test_to_float_bare_italian_thousands_no_decimal():
    """A bare Italian thousands separator with no decimal comma (e.g. '1.500' meaning
    1500 units) must not be silently misread as 1.5 - a 1000x understatement. Broker
    exports are Italian-locale only: a lone dot with no comma is always a thousands
    grouping, never a decimal point."""
    assert _to_float("1.500") == 1500.0
    assert _to_float("12.345") == 12345.0
    assert _to_float("1.234.567") == 1234567.0


def test_parse_bare_thousands_quantity_no_decimal_comma(tmp_path: Path):
    """A Quantità cell using a bare dot as an Italian thousands separator with no
    decimal comma (e.g. '1.500' meaning 1500 shares) must parse as 1500.0, not 1.5."""
    content = "\n".join(
        [
            "Titolo;Tipo;Valuta;Quantità;P.zo medio di carico;P.zo di mercato;"
            "Val di mercato;Var €;Var %",
            "ACME BIOTECH;Azione;EUR;1.500;10,00;12,00;18000,00;+3000,00;+20,00",
            "",
        ]
    )
    path = tmp_path / "export.csv"
    path.write_text(content, encoding="utf-8")
    p = parse_portfolio_export(str(path))
    assert p.holdings[0].quantity == 1500.0


def test_parse_empty_and_unmappable_files(tmp_path: Path):
    empty = tmp_path / "empty.csv"
    empty.write_text("Titolo;Val di mercato\n", encoding="utf-8")
    assert parse_portfolio_export(str(empty)).holdings == []

    bad = tmp_path / "bad.csv"
    bad.write_text("a;b;c\n1;2;3\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Could not map"):
        parse_portfolio_export(str(bad))


def test_delimiter_detection_ignores_commas_inside_numeric_cells(tmp_path: Path):
    """A genuinely semicolon-delimited file must not be mis-split on ',' just because
    large numeric values use comma thousands-grouping (e.g. '1,234,567.89' contributes
    two commas per cell). Delimiter detection must not count characters that sit inside
    numeric-looking substrings."""
    content = "\n".join(
        [
            "Titolo;Val di mercato",
            "Global Macro Fund;1,234,567.89",
            "Something Else Fund;2,345,678.90",
            "Another Thing Fund;3,456,789.01",
            "",
        ]
    )
    path = tmp_path / "export.csv"
    path.write_text(content, encoding="utf-8")

    rows = _read_rows(path)
    assert rows[0] == ["Titolo", "Val di mercato"]
    assert all(len(row) == 2 for row in rows)
