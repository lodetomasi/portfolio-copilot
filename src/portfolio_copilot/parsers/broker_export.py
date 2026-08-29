from __future__ import annotations

import csv
import io
import re
from pathlib import Path

import pandas as pd

from portfolio_copilot.models import AssetType, Holding, Portfolio

ALIASES = {
    "name": ["titolo", "nome", "descrizione", "security"],
    "symbol": ["ticker", "simbolo", "symbol"],
    "isin": ["isin"],
    # Italian exports: "Strumento" holds the instrument type (Azione / ETF / Certificate).
    "asset_type": ["strumento", "tipo", "tipologia", "asset type", "strumento tipo"],
    "currency": ["valuta", "currency"],
    "quantity": ["quantità", "quantita", "qta", "quantity"],
    "avg_cost": ["p.zo medio di carico", "prezzo medio", "pmc", "avg cost", "average price"],
    "market_price": ["p.zo di mercato", "prezzo di mercato", "market price", "last price"],
    "market_value": ["val di mercato", "valore di mercato", "market value", "controvalore"],
    "pnl_value": ["p/l", "pl", "plus/minus", "profit loss", "var €", "var eur"],
    "pnl_pct": ["var %", "p/l %", "pl %", "performance %"],
    "leverage": ["leva", "leverage"],
}


def _norm_col(value: str) -> str:
    text = str(value).strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def _text(value) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    out = str(value).strip()
    return out if out and out.lower() != "nan" else None


def _to_float(value) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)):
        return float(value)

    s = str(value).strip().replace("\xa0", "").replace("€", "").replace("$", "")
    s = s.replace("%", "")
    if not s:
        return None

    # Italian numbers: 4.380,74 -> 4380.74
    if "," in s and "." in s and s.rfind(",") > s.rfind("."):
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    elif "." in s:
        # Broker exports are Italian-locale only (comma is always the decimal
        # separator when present). A lone dot with no comma at all is therefore
        # always a thousands grouping (e.g. "1.500" -> 1500), never a decimal
        # point - do not let it fall through untouched and be misread 1000x low.
        s = s.replace(".", "")

    s = re.sub(r"[^0-9.\-+]", "", s)
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _detect_asset_type(raw: str | None, name: str) -> AssetType:
    text = f"{raw or ''} {name}".lower()
    if "etf" in text:
        return AssetType.ETF
    if "certificate" in text or "leva fissa" in text:
        return AssetType.CERTIFICATE
    if "obblig" in text or "bond" in text:
        return AssetType.BOND
    if "azione" in text or "equity" in text:
        return AssetType.EQUITY
    return AssetType.OTHER


def _resolve_alias(columns: list[str], key: str) -> str | None:
    normalized = {_norm_col(c): c for c in columns}
    for alias in ALIASES[key]:
        if _norm_col(alias) in normalized:
            return normalized[_norm_col(alias)]
    # fuzzy substring fallback
    for norm, original in normalized.items():
        if any(_norm_col(alias) in norm for alias in ALIASES[key]):
            return original
    return None


def _find_column(df: pd.DataFrame, key: str) -> str | None:
    return _resolve_alias(list(df.columns), key)


_ALL_ALIASES = [_norm_col(a) for aliases in ALIASES.values() for a in aliases]
_TOTAL_ROW_PREFIXES = ("totale", "total")
_TICKER_LINE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,7}$")


def _is_total_row(name: str) -> bool:
    """True for summary/footer rows such as 'Totale', 'Totale Titoli',
    'Totale complessivo' or 'Total:' that must never be ingested as a holding."""
    text = name.strip().lower().rstrip(":")
    return text.startswith(_TOTAL_ROW_PREFIXES)


def _read_rows(path: Path) -> list[list[str]]:
    """Return the file as raw rows (strings). Handles XLSX/XLS and CSV with unknown
    delimiter/encoding, including quoted multi-line cells."""
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        df = pd.read_excel(path, header=None, dtype=str)
        return [["" if pd.isna(v) else str(v) for v in row] for row in df.itertuples(index=False)]

    if suffix != ".csv":
        raise ValueError(f"Unsupported portfolio file type: {path.suffix}")

    text: str | None = None
    for encoding in ("utf-8-sig", "cp1252", "latin1"):
        try:
            text = path.read_text(encoding=encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError(f"Unreadable portfolio file (encoding): {path}")

    # Count delimiter candidates only outside numeric-looking substrings: a large
    # value formatted with thousands separators (Italian "1.234.567,89" or US
    # "1,234,567.89") can otherwise contribute more ',' or '.' characters than
    # there are real field separators, causing the wrong delimiter to be chosen.
    numeric_stripped = re.sub(r"\d[\d.,]*", "", text)
    delimiter = max((";", "\t", ","), key=numeric_stripped.count)
    return [row for row in csv.reader(io.StringIO(text), delimiter=delimiter)]


def _header_index(rows: list[list[str]]) -> int | None:
    """Index of the first row that looks like the table header (>= 2 known column aliases).
    Page exports often have summary rows (Portafoglio, Dossier, Valorizzazione...) first."""
    for i, row in enumerate(rows):
        cells = [_norm_col(c) for c in row if str(c).strip()]
        hits = sum(1 for c in cells if any(alias == c or alias in c for alias in _ALL_ALIASES))
        if hits >= 2:
            return i
    return None


def _read_table(path: Path) -> pd.DataFrame:
    rows = _read_rows(path)
    idx = _header_index(rows)
    if idx is None:
        preview = [c for r in rows[:3] for c in r if str(c).strip()]
        raise ValueError(
            "Could not map required portfolio columns: no header row found. "
            f"First cells: {preview}. Need at least instrument/name and market value."
        )
    header = [str(c).strip() for c in rows[idx]]

    # Merged-cell Excel headers sometimes render across TWO physical rows: a group
    # label ("P.zo medio", "Val di mercato") on the row above, over blank cells, with
    # the completing sub-label ("di carico", "mercato", ...) on the header row itself.
    # The row above never scores >= 2 alias hits on its own (its fragments are short),
    # so _header_index already skipped past it; only fall back to merging it in when
    # the chosen header row alone still fails to resolve a required column, exactly
    # like the existing single-cell-with-embedded-newline case already handles it.
    if idx > 0 and (
        _resolve_alias(header, "name") is None or _resolve_alias(header, "market_value") is None
    ):
        ncols = len(header)
        above = [str(c).strip() for c in rows[idx - 1]]
        above = (above + [""] * (ncols - len(above)))[:ncols]
        merged = [
            " ".join(part for part in (a, b) if part)
            for a, b in zip(above, header, strict=True)
        ]
        if (
            _resolve_alias(merged, "name") is not None
            and _resolve_alias(merged, "market_value") is not None
        ):
            header = merged

    body = [
        (r + [""] * (len(header) - len(r)))[: len(header)]
        for r in rows[idx + 1 :]
        if any(str(c).strip() for c in r)
    ]
    return pd.DataFrame(body, columns=header).replace({"": None})


def _split_name_cell(raw: str) -> tuple[str | None, str]:
    """Some exports put the ticker code on the first line of the Titolo cell ("AB\nACME")."""
    lines = [ln.strip() for ln in str(raw).splitlines() if ln.strip()]
    if len(lines) >= 2 and _TICKER_LINE.match(lines[0]):
        return lines[0], " ".join(lines[1:])
    return None, " ".join(lines)


def parse_portfolio_export(path: str, base_currency: str = "EUR") -> Portfolio:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(str(p))

    df = _read_table(p)
    if df.empty:
        return Portfolio(holdings=[], base_currency=base_currency)

    cols = {key: _find_column(df, key) for key in ALIASES}

    if not cols["name"] or not cols["market_value"]:
        raise ValueError(
            "Could not map required portfolio columns. "
            f"Detected columns: {list(df.columns)}. "
            "Need at least instrument/name and market value."
        )

    holdings: list[Holding] = []
    for _, row in df.iterrows():
        raw_name = row[cols["name"]]
        if raw_name is None or str(raw_name).strip().lower() in {"", "nan"}:
            continue
        inline_symbol, name = _split_name_cell(raw_name)
        if _is_total_row(name):
            continue

        market_value = _to_float(row[cols["market_value"]])
        if market_value is None:
            continue

        raw_type = _text(row[cols["asset_type"]]) if cols["asset_type"] else None
        asset_type = _detect_asset_type(raw_type, name)
        leverage = _to_float(row[cols["leverage"]]) if cols["leverage"] else None

        if leverage is None:
            is_leveraged_type = asset_type == AssetType.CERTIFICATE or bool(
                re.search(r"\b(leva|leverage)\b", f"{raw_type or ''}".lower())
            )
            if is_leveraged_type:
                m = re.search(r"(\d+(?:[.,]\d+)?)x", name.lower())
                leverage = float(m.group(1).replace(",", ".")) if m else 1.0
            else:
                leverage = 1.0

        pnl_pct_raw = _to_float(row[cols["pnl_pct"]]) if cols["pnl_pct"] else None
        pnl_pct = pnl_pct_raw / 100.0 if pnl_pct_raw is not None else None

        holdings.append(
            Holding(
                symbol=_text(row[cols["symbol"]]) if cols["symbol"] else inline_symbol,
                isin=_text(row[cols["isin"]]) if cols["isin"] else None,
                name=name,
                asset_type=asset_type,
                currency=(_text(row[cols["currency"]]) or base_currency).upper()
                if cols["currency"]
                else base_currency,
                quantity=_to_float(row[cols["quantity"]]) or 0.0 if cols["quantity"] else 0.0,
                avg_cost=_to_float(row[cols["avg_cost"]]) if cols["avg_cost"] else None,
                market_price=(
                    _to_float(row[cols["market_price"]]) if cols["market_price"] else None
                ),
                market_value=market_value,
                pnl_value=_to_float(row[cols["pnl_value"]]) if cols["pnl_value"] else None,
                pnl_pct=pnl_pct,
                leverage=leverage,
            )
        )

    return Portfolio(holdings=holdings, base_currency=base_currency)
