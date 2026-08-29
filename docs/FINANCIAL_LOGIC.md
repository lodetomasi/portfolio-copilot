# Financial logic

## 1. Concentration

Compute:
- top-1 weight;
- top-3 weight;
- top-5 weight;
- Herfindahl-Hirschman Index.

## 2. Risk

On available daily prices:
- annualized volatility;
- max drawdown;
- downside deviation;
- beta vs benchmark (optional);
- correlation matrix.

Do not present historical volatility as a forecast.

## 3. Momentum

Suggested normalized inputs:
- 1m return;
- 3m return;
- 6m return;
- 12m return;
- price / SMA50;
- price / SMA200;
- distance from 52w high.

Winsorize extreme values before cross-sectional ranking.

## 4. Growth

Use available:
- revenue growth YoY;
- earnings growth;
- FCF growth;
- forward revenue/earnings growth if source supports it.

## 5. Quality

Use:
- gross margin;
- operating margin;
- FCF margin;
- ROE/ROA/ROIC when reliable;
- net debt / EBITDA or debt/equity;
- current ratio;
- positive FCF.

## 6. Valuation

Context-sensitive:
- forward PE;
- EV/EBITDA;
- EV/Sales;
- P/FCF;
- PEG.

Do not compare biotech pre-revenue with mature industrials on PE.

## 7. Risk score

Higher risk must reduce the final composite or influence position sizing.
Signals:
- negative FCF;
- high dilution;
- high debt;
- extreme vol;
- drawdown;
- micro/small cap;
- binary clinical/event risk (when known).

## 8. Position sizing

Default:
- quality: up to 5%;
- growth: up to 4%;
- asymmetric/high-risk: up to 2%;
- leverage: separate nominal cap.

These are defaults, not universal truths.

## 9. Rebalancing

For asset i:

```text
drift_i = current_weight_i - target_weight_i
```

No action if:

```text
abs(drift_i) <= rebalance_band_abs
```

When cash exists:
1. compute target values after cash injection;
2. allocate cash to largest deficits;
3. respect minimum order and max weights;
4. only then consider sells.

## 10. Fee efficiency

```text
fee_ratio = estimated_fee / order_value
```

Default reject if > 1%.

For fixed fees, calculate a minimum economic order:

```text
min_order ~= fixed_fee / max_fee_ratio
```

Example:
€2.95 / 1% = €295.

## 11. Leveraged products

Store:
- nominal market value;
- declared leverage factor.

Report:
```text
indicative_equivalent_exposure = nominal_value * abs(leverage)
```

This is NOT a risk model and must be labelled as indicative.
