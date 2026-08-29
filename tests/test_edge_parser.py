"""Edge-case coverage for the broker export parser.

Every test below asserts the parser's INTENDED behaviour per CLAUDE.md (never invent
missing financial data; degrade to None rather than fabricate) and docs/FINANCIAL_LOGIC.md.
Every test encodes the CORRECT behaviour; the defects these tests exposed during the
audit (two-row headers, fabricated pnl_pct, Totale-row variants, leverage regex false
positives, thousands-only numbers) were fixed in the parser, never in the tests.
"""

from __future__ import annotations

import time
from pathlib import Path

import openpyxl
import pytest

from portfolio_copilot.parsers.broker_export import _to_float, parse_portfolio_export

FIXTURES = Path(__file__).parent / "fixtures"

HEADER = (
    "Titolo;Strumento;Valuta;Quantità;P.zo medio di carico;P.zo di mercato;"
    "Val di mercato;Var €;Var %"
)


def _write(tmp_path: Path, name: str, lines: list[str]) -> Path:
    path = tmp_path / name
    path.write_text("\n".join([*lines, ""]), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# NaN / None / placeholder cells
# ---------------------------------------------------------------------------


def test_blank_optional_cells_yield_none_not_zero_or_crash(tmp_path: Path):
    """Blank cells in optional numeric/text columns must degrade to None, never a
    fabricated 0.0 or empty-string placeholder (CLAUDE.md rule 4/6)."""
    path = _write(
        tmp_path,
        "blank_cells.csv",
        [
            "Titolo;Strumento;Valuta;Quantità;P.zo medio di carico;P.zo di mercato;"
            "Val di mercato;Var €;Var %;Ticker;Isin",
            "ACME BIOTECH;Azione;EUR;10;;;82,00;;;;",
        ],
    )
    p = parse_portfolio_export(str(path))
    assert len(p.holdings) == 1
    h = p.holdings[0]
    assert h.avg_cost is None
    assert h.market_price is None
    assert h.pnl_value is None
    assert h.pnl_pct is None
    assert h.symbol is None
    assert h.isin is None
    assert h.market_value == 82.0


def test_dash_placeholder_numeric_cell_yields_none(tmp_path: Path):
    """A '-' placeholder cell (common for 'no P/L yet') must parse to None, not 0.0
    or a crash. Locks in _to_float("-") == None."""
    assert _to_float("-") is None

    path = _write(
        tmp_path,
        "dash.csv",
        [HEADER, "ACME BIOTECH;Azione;EUR;10;10,00;8,20;82,00;-;-"],
    )
    p = parse_portfolio_export(str(path))
    h = p.holdings[0]
    assert h.pnl_value is None
    assert h.pnl_pct is None


def test_nd_placeholder_numeric_cell_yields_none(tmp_path: Path):
    """Italian broker exports use 'n.d.' ('non disponibile') for unavailable figures;
    it must parse to None, not 0.0 or a fabricated value."""
    assert _to_float("n.d.") is None

    path = _write(
        tmp_path,
        "nd.csv",
        [HEADER, "ACME BIOTECH;Azione;EUR;10;10,00;n.d.;82,00;-18,00;n.d."],
    )
    p = parse_portfolio_export(str(path))
    h = p.holdings[0]
    assert h.market_price is None
    assert h.pnl_pct is None
    assert h.pnl_value == -18.0


# ---------------------------------------------------------------------------
# US-format numbers ("1,234.56")
# ---------------------------------------------------------------------------


def test_us_format_number_is_not_fabricated_into_a_wrong_value():
    """_to_float is documented (see module source) as Italian-locale only: a lone dot
    is always a thousands grouping, never a decimal point, precisely to avoid guessing
    between locales. A genuinely US-formatted number ('1,234.56') is therefore outside
    the supported locale; the intended, safe response is None (degrade), never a
    silently wrong numeric value such as 123456.0 or 1.23456. CLAUDE.md rule 4/6:
    never invent financial data - an unparseable-in-locale cell must not corrupt into
    a plausible-looking but wrong number."""
    assert _to_float("1,234.56") is None
    assert _to_float("-1,234.56") is None
    # Sanity: this is not a generic "any comma+dot fails" - the Italian mixed case
    # (comma decimal, dot thousands) is fully supported.
    assert _to_float("1.234,56") == 1234.56


def test_us_format_market_value_row_is_dropped_not_corrupted(tmp_path: Path):
    """A holding whose market value cell is US-formatted cannot be reliably
    interpreted under the Italian-only contract, so the parser must drop that row
    rather than ingest a corrupted value. This mirrors the existing 'n.d./missing
    market_value' skip path."""
    path = _write(
        tmp_path,
        "us_format.csv",
        [
            HEADER,
            "ACME BIOTECH;Azione;EUR;10;10,00;8,20;82,00;-18,00;-10,00",
            "US STYLE CO;Azione;USD;5;10,00;8,20;1,234.56;-18,00;-10,00",
        ],
    )
    p = parse_portfolio_export(str(path))
    names = [h.name for h in p.holdings]
    assert names == ["ACME BIOTECH"]


# ---------------------------------------------------------------------------
# Real XLSX (openpyxl): multi-line headers, preamble rows, Totale row
# ---------------------------------------------------------------------------


def test_parse_real_xlsx_with_multiline_headers_preamble_and_total(tmp_path: Path):
    """A genuine .xlsx (not a CSV renamed) with a 'Portafoglio' summary preamble
    block, embedded newlines inside header cells (as Excel wraps long labels), and
    a trailing 'Totale' row must parse identically to the equivalent CSV layout."""
    path = tmp_path / "export.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active

    preamble = [
        ["Portafoglio"],
        ["Dossier"],
        ["00000000"],
        ["Strumenti"],
        ["Tutti"],
        ["Valorizzazione EUR"],
        ["4.147,02"],
        [],
    ]
    for row in preamble:
        ws.append(row)

    header = [
        "Titolo",
        "Strumento",
        "Valuta",
        "Quantità",
        "P.zo medio\ndi carico",
        "P.zo di\nmercato",
        "Val di mercato €\n(Margine)",
        "Var €",
        "Var %",
    ]
    ws.append(header)

    data_rows = [
        ["ACME BIOTECH", "Azione", "EUR", 10, "10,00", "8,20", "82,00", "-18,00", "-10,00"],
        [
            "Vanguard FTSE All-World UCITS ETF (USD) Acc",
            "ETF",
            "EUR",
            20,
            "150,00",
            "160,00",
            "3.200,00",
            "+200,00",
            "+6,67",
        ],
        [
            "LEVA FISSA EXAMPLE LONG 5X",
            "Certificate",
            "EUR",
            10,
            "20,00",
            "22,00",
            "220,00",
            "+20,00",
            "+10,00",
        ],
    ]
    for row in data_rows:
        ws.append(row)

    ws.append(["Totale", "", "", "", "", "", "3.502,00", "+202,00", "+5,77"])
    wb.save(path)

    p = parse_portfolio_export(str(path))
    by_name = {h.name: h for h in p.holdings}

    assert "Totale" not in by_name
    assert len(p.holdings) == 3
    assert round(p.total_value, 2) == 3502.0

    acme = by_name["ACME BIOTECH"]
    assert acme.asset_type.value == "equity"
    assert acme.market_value == 82.0
    assert acme.avg_cost == 10.0
    assert acme.market_price == 8.2

    vwrl = by_name["Vanguard FTSE All-World UCITS ETF (USD) Acc"]
    assert vwrl.asset_type.value == "etf"
    assert vwrl.market_value == 3200.0

    leva = by_name["LEVA FISSA EXAMPLE LONG 5X"]
    assert leva.asset_type.value == "certificate"
    assert leva.leverage == 5.0


# ---------------------------------------------------------------------------
# Header spread over two physical rows (merged-cell Excel layout)
# ---------------------------------------------------------------------------


def test_header_spread_over_two_physical_rows(tmp_path: Path):
    """Real broker exports sometimes render a header as TWO distinct physical rows
    via merged cells: row 1 carries group labels ('P.zo medio', 'Val di mercato')
    over blanks, row 2 carries the completing sub-labels ('di carico', ...). This is
    different from the already-covered 'multi-line header in one wrapped cell' case.
    The parser must still locate name/market_value by joining the two header rows
    column-by-column, exactly as it already does for a single wrapped cell."""
    path = _write(
        tmp_path,
        "two_row_header.csv",
        [
            ";;;;P.zo medio;P.zo di;Val di mercato;;",
            "Titolo;Strumento;Valuta;Quantità;di carico;mercato;;Var €;Var %",
            "ACME BIOTECH;Azione;EUR;10;10,00;8,20;82,00;-18,00;-10,00",
        ],
    )
    p = parse_portfolio_export(str(path))
    assert len(p.holdings) == 1
    h = p.holdings[0]
    assert h.name == "ACME BIOTECH"
    assert h.market_value == 82.0
    assert h.avg_cost == 10.0
    assert h.market_price == 8.2


# ---------------------------------------------------------------------------
# Name whose first line looks like a ticker but is not ("3M COMPANY")
# ---------------------------------------------------------------------------


def test_single_line_name_resembling_a_ticker_prefix_is_not_split(tmp_path: Path):
    """'3M COMPANY' is a single-line name whose leading token ('3M') structurally
    matches the inline-ticker pattern used for genuine two-line cells such as
    'AB\\nACME BIOTECH'. Because it is one line (no embedded newline), it must be
    kept intact and never mistaken for a ticker + name split."""
    path = _write(
        tmp_path,
        "3m.csv",
        [HEADER, "3M COMPANY;Azione;USD;10;100,00;110,00;1100,00;100,00;10,00"],
    )
    p = parse_portfolio_export(str(path))
    assert len(p.holdings) == 1
    h = p.holdings[0]
    assert h.name == "3M COMPANY"
    assert h.symbol is None


# ---------------------------------------------------------------------------
# Currency USD with EUR-denominated broker values
# ---------------------------------------------------------------------------


def test_usd_instrument_currency_with_broker_eur_values_no_conversion(tmp_path: Path):
    """The Valuta column records the instrument's own trading currency; the broker's
    market-value figures are its own (EUR) valuation. The parser must record the
    stated currency as-is and must NOT attempt any FX conversion (that is out of this
    module's scope) - the numeric fields stay exactly what was in the EUR columns."""
    path = _write(
        tmp_path,
        "usd.csv",
        [HEADER, "FOO ROBOTICS ADR;Azione;USD;40;6,25000;5,80;199,52;-15,48;-7,20"],
    )
    p = parse_portfolio_export(str(path))
    h = p.holdings[0]
    assert h.currency == "USD"
    assert h.market_value == 199.52
    assert h.avg_cost == 6.25
    assert h.market_price == 5.80


# ---------------------------------------------------------------------------
# Duplicate instrument names (separate lots, not merged)
# ---------------------------------------------------------------------------


def test_duplicate_instrument_names_are_kept_as_separate_holdings(tmp_path: Path):
    """Two rows for the same security name (e.g. lots bought on different dates)
    must both be ingested as separate Holding entries - the parser never merges or
    deduplicates by name, since silently combining lots would require inventing an
    aggregation policy (avg cost, blended P/L) that CLAUDE.md forbids doing without
    being asked."""
    path = _write(
        tmp_path,
        "dup.csv",
        [
            HEADER,
            "ACME BIOTECH;Azione;EUR;10;10,00;8,20;82,00;-18,00;-10,00",
            "ACME BIOTECH;Azione;EUR;5;9,00;8,20;41,00;-4,00;-8,89",
        ],
    )
    p = parse_portfolio_export(str(path))
    acme_rows = [h for h in p.holdings if h.name == "ACME BIOTECH"]
    assert len(acme_rows) == 2
    assert round(p.total_value, 2) == 123.0


# ---------------------------------------------------------------------------
# Empty file / header-only file
# ---------------------------------------------------------------------------


def test_completely_empty_file_raises_clear_error(tmp_path: Path):
    """A zero-byte file has no header at all; the parser must fail loudly with a
    clear, actionable error rather than silently returning an empty portfolio (which
    would be indistinguishable from a genuinely-empty-but-valid account)."""
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="no header row found"):
        parse_portfolio_export(str(path))


def test_header_only_file_returns_empty_portfolio_not_error(tmp_path: Path):
    """A file with a valid, mappable header and zero data rows is a legitimate
    'empty portfolio' export (e.g. a brand-new account) and must parse successfully
    to an empty holdings list, not raise."""
    path = _write(tmp_path, "header_only.csv", [HEADER])
    p = parse_portfolio_export(str(path))
    assert p.holdings == []
    assert p.total_value == 0.0


# ---------------------------------------------------------------------------
# Performance sanity: 500 rows
# ---------------------------------------------------------------------------


def test_parses_500_rows_within_two_seconds(tmp_path: Path):
    """A realistically large single-account export (hundreds of lines) must parse
    fast enough for interactive MCP tool calls."""
    lines = [HEADER]
    for i in range(500):
        lines.append(f"STOCK {i};Azione;EUR;10;10,00;8,20;82,00;-18,00;-10,00")
    path = _write(tmp_path, "big.csv", lines)

    start = time.perf_counter()
    p = parse_portfolio_export(str(path))
    elapsed = time.perf_counter() - start

    assert len(p.holdings) == 500
    assert elapsed < 2.0
