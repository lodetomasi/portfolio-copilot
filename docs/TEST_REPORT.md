# Test report

Generated 2026-08-29 12:04 UTC by `scripts/test_report.py`. Every test is offline and deterministic.

## Gates

| gate | result |
|---|---|
| pytest | 1 failed, 1361 passed in 18.16s |
| tests total / passed / failed+error / xfail / skipped | 1362 / 1361 / 1 / 0 / 0 |
| total test time | 15.60 s |
| ruff check . | clean |
| claude plugin validate --strict . | pass |
| claude plugin validate --strict skills | pass |
| claude plugin validate --strict agents | pass |
| line coverage (src/portfolio_copilot) | 94.7% |

## Coverage per module

| module | statements | missing | covered |
|---|---:|---:|---:|
| __init__.py | 1 | 0 | 100% |
| analytics/__init__.py | 0 | 0 | 100% |
| analytics/evidence.py | 102 | 5 | 95% |
| analytics/merge.py | 46 | 1 | 98% |
| analytics/metrics.py | 39 | 0 | 100% |
| cli.py | 24 | 4 | 83% |
| models.py | 123 | 0 | 100% |
| parsers/__init__.py | 0 | 0 | 100% |
| parsers/broker_export.py | 148 | 10 | 93% |
| portfolio/__init__.py | 0 | 0 | 100% |
| portfolio/auction.py | 108 | 10 | 91% |
| portfolio/backtest.py | 48 | 0 | 100% |
| portfolio/config.py | 26 | 0 | 100% |
| portfolio/edge.py | 45 | 0 | 100% |
| portfolio/exposure.py | 112 | 6 | 95% |
| portfolio/ledger.py | 115 | 0 | 100% |
| portfolio/mapping.py | 86 | 0 | 100% |
| portfolio/opportunity.py | 101 | 2 | 98% |
| portfolio/orders.py | 6 | 0 | 100% |
| portfolio/picker.py | 115 | 1 | 99% |
| portfolio/picker_backtest.py | 198 | 17 | 91% |
| portfolio/plan.py | 77 | 2 | 97% |
| portfolio/quality.py | 63 | 0 | 100% |
| portfolio/rebalance.py | 77 | 4 | 95% |
| portfolio/replacement.py | 92 | 4 | 96% |
| portfolio/risk.py | 18 | 0 | 100% |
| portfolio/snapshots.py | 141 | 10 | 93% |
| portfolio/thesis.py | 118 | 1 | 99% |
| providers/__init__.py | 0 | 0 | 100% |
| providers/base.py | 6 | 6 | 0% |
| providers/cache.py | 21 | 0 | 100% |
| providers/ecb_fx.py | 39 | 1 | 97% |
| providers/ecb_rates.py | 32 | 0 | 100% |
| providers/eurostat.py | 82 | 4 | 95% |
| providers/fallback.py | 45 | 0 | 100% |
| providers/finviz.py | 93 | 0 | 100% |
| providers/investor_relations.py | 208 | 5 | 98% |
| providers/macro.py | 28 | 1 | 96% |
| providers/openfigi.py | 116 | 4 | 97% |
| providers/sec_edgar.py | 79 | 1 | 99% |
| providers/sec_filings.py | 142 | 3 | 98% |
| providers/stooq.py | 52 | 3 | 94% |
| providers/yahooquery_provider.py | 56 | 2 | 96% |
| providers/yfinance_estimates.py | 241 | 5 | 98% |
| providers/yfinance_provider.py | 77 | 7 | 91% |
| providers/yfinance_surprises.py | 91 | 4 | 96% |
| scoring/__init__.py | 0 | 0 | 100% |
| scoring/engine.py | 86 | 2 | 98% |
| server.py | 796 | 105 | 87% |

## Slowest 10 tests

| test | seconds |
|---|---:|
| test_server_edge_quality::test_analyze_stock_evidence_uses_pre_override_snapshot_for_the_cross_check | 4.595 |
| test_server_capital_auction::test_negative_holding_value_never_crashes_the_auction | 4.415 |
| test_server_picker::test_resolve_isins_does_not_leak_stale_errors_from_an_unrelated_prior_call | 2.507 |
| test_server_tools::test_tools_list_over_stdio_includes_every_new_tool | 0.701 |
| test_server_tools::test_tools_list_over_stdio_still_includes_every_pre_existing_tool | 0.639 |
| test_cli_and_orders::test_cli_help_lists_commands | 0.282 |
| test_hook_etoro_allowlist::test_header_names_and_client_lib_in_docs_are_not_credentials | 0.083 |
| test_hook_etoro_allowlist::test_basic_auth_and_bearer_on_command_line_are_still_denied | 0.079 |
| test_edge_hooks_skills::test_guard_processes_one_megabyte_input_quickly | 0.074 |
| test_plugin::test_guard_denies_url_with_userinfo_credentials | 0.055 |

## Every test


### test_auction — 17 tests, 0.01 s

| test | status | seconds | note |
|---|---|---:|---|
| test_cap_weight_is_never_exceeded | ✅ | 0.000 |  |
| test_capital_auction_never_overspends_cash_with_realistic_variable_fee | ✅ | 0.000 |  |
| test_cash_kind_candidate_never_receives_an_order | ✅ | 0.000 |  |
| test_deficit_bonus_lets_underweight_bucket_beat_a_better_stock | ✅ | 0.000 |  |
| test_determinism | ✅ | 0.000 |  |
| test_duplicate_symbol_candidates_cannot_jointly_exceed_cap_weight | ✅ | 0.000 |  |
| test_fully_empty_bucket_clears_the_buy_threshold_with_cash_sized_for_its_own_gap | ✅ | 0.000 |  |
| test_low_confidence_stock_is_never_bought | ✅ | 0.000 |  |
| test_marginal_utility_bucket_bonus_uses_own_target_as_denominator | ✅ | 0.000 |  |
| test_marginal_utility_forces_zero_for_low_confidence_stock_directly | ✅ | 0.000 |  |
| test_minimum_economic_order_is_respected | ✅ | 0.000 |  |
| test_negative_cash_raises | ✅ | 0.000 |  |
| test_no_buy_when_all_utilities_at_or_below_cash_utility | ✅ | 0.000 |  |
| test_partially_funded_bucket_gets_a_proportionally_smaller_bonus | ✅ | 0.000 |  |
| test_random_scenarios_invariants | ✅ | 0.004 |  |
| test_ranking_order_is_descending_by_utility | ✅ | 0.001 |  |
| test_size_order_retry_branch_never_overspends_remaining_cash | ✅ | 0.000 |  |

### test_backtest — 22 tests, 0.05 s

| test | status | seconds | note |
|---|---|---:|---|
| test_constant_prices_accounting_identity | ✅ | 0.003 |  |
| test_constant_prices_converge_inside_band | ✅ | 0.002 |  |
| test_invariants_hold_on_random_paths[0] | ✅ | 0.003 |  |
| test_invariants_hold_on_random_paths[10] | ✅ | 0.003 |  |
| test_invariants_hold_on_random_paths[11] | ✅ | 0.003 |  |
| test_invariants_hold_on_random_paths[1] | ✅ | 0.003 |  |
| test_invariants_hold_on_random_paths[2] | ✅ | 0.003 |  |
| test_invariants_hold_on_random_paths[3] | ✅ | 0.003 |  |
| test_invariants_hold_on_random_paths[4] | ✅ | 0.003 |  |
| test_invariants_hold_on_random_paths[5] | ✅ | 0.003 |  |
| test_invariants_hold_on_random_paths[6] | ✅ | 0.003 |  |
| test_invariants_hold_on_random_paths[7] | ✅ | 0.003 |  |
| test_invariants_hold_on_random_paths[8] | ✅ | 0.003 |  |
| test_invariants_hold_on_random_paths[9] | ✅ | 0.003 |  |
| test_months_out_of_band_pct_denominator_excludes_pre_investment_months | ✅ | 0.001 |  |
| test_months_out_of_band_pct_zero_when_never_invested | ✅ | 0.001 |  |
| test_never_sells_units_only_grow | ✅ | 0.002 |  |
| test_pooling_every_three_months_reduces_orders_and_fees | ✅ | 0.005 |  |
| test_rejects_bad_price_inputs[prices0-Missing price series] | ✅ | 0.001 |  |
| test_rejects_bad_price_inputs[prices1-at least two] | ✅ | 0.001 |  |
| test_rejects_bad_price_inputs[prices2-positive] | ✅ | 0.001 |  |
| test_rejects_bad_price_inputs[prices3-positive] | ✅ | 0.001 |  |

### test_cli_and_orders — 7 tests, 0.30 s

| test | status | seconds | note |
|---|---|---:|---|
| test_cli_help_lists_commands | ✅ | 0.282 |  |
| test_cli_parse_missing_file_fails_loudly | ✅ | 0.001 |  |
| test_cli_parse_prints_normalized_portfolio_json | ✅ | 0.016 |  |
| test_cli_risk_prints_concentration_and_leverage | ✅ | 0.005 |  |
| test_estimate_order_cost_default_model_minimum_is_295 | ✅ | 0.000 |  |
| test_estimate_order_cost_flags_fee_larger_than_order_as_uneconomic | ✅ | 0.000 |  |
| test_estimate_order_cost_zero_order_has_no_ratio | ✅ | 0.000 |  |

### test_edge_allocator — 412 tests, 0.00 s

| test | status | seconds | note |
|---|---|---:|---|
| test_band_of_one_swallows_every_deficit | ✅ | 0.000 |  |
| test_cash_exactly_at_minimum_order_plus_fee_produces_full_order | ✅ | 0.000 |  |
| test_cash_exactly_at_minimum_order_produces_no_order | ✅ | 0.000 |  |
| test_commissions_exceed_cash_no_order_generated | ✅ | 0.000 |  |
| test_current_values_with_symbols_outside_targets_are_counted_but_not_ordered | ✅ | 0.000 |  |
| test_huge_cash_precision | ✅ | 0.000 |  |
| test_infinite_minimum_order_when_variable_fee_at_or_above_cap | ✅ | 0.000 |  |
| test_negative_current_values_do_not_break_safety_invariants | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[0] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[100] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[101] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[102] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[103] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[104] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[105] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[106] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[107] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[108] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[109] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[10] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[110] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[111] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[112] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[113] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[114] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[115] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[116] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[117] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[118] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[119] | ✅ | 0.001 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[11] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[120] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[121] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[122] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[123] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[124] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[125] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[126] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[127] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[128] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[129] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[12] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[130] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[131] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[132] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[133] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[134] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[135] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[136] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[137] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[138] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[139] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[13] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[140] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[141] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[142] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[143] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[144] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[145] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[146] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[147] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[148] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[149] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[14] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[150] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[151] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[152] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[153] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[154] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[155] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[156] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[157] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[158] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[159] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[15] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[160] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[161] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[162] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[163] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[164] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[165] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[166] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[167] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[168] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[169] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[16] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[170] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[171] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[172] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[173] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[174] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[175] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[176] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[177] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[178] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[179] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[17] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[180] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[181] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[182] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[183] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[184] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[185] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[186] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[187] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[188] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[189] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[18] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[190] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[191] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[192] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[193] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[194] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[195] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[196] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[197] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[198] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[199] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[19] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[1] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[20] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[21] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[22] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[23] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[24] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[25] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[26] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[27] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[28] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[29] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[2] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[30] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[31] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[32] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[33] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[34] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[35] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[36] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[37] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[38] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[39] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[3] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[40] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[41] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[42] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[43] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[44] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[45] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[46] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[47] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[48] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[49] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[4] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[50] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[51] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[52] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[53] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[54] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[55] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[56] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[57] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[58] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[59] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[5] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[60] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[61] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[62] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[63] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[64] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[65] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[66] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[67] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[68] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[69] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[6] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[70] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[71] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[72] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[73] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[74] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[75] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[76] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[77] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[78] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[79] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[7] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[80] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[81] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[82] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[83] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[84] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[85] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[86] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[87] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[88] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[89] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[8] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[90] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[91] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[92] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[93] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[94] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[95] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[96] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[97] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[98] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[99] | ✅ | 0.000 |  |
| test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent[9] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[0] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[100] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[101] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[102] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[103] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[104] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[105] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[106] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[107] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[108] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[109] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[10] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[110] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[111] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[112] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[113] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[114] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[115] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[116] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[117] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[118] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[119] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[11] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[120] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[121] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[122] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[123] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[124] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[125] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[126] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[127] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[128] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[129] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[12] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[130] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[131] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[132] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[133] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[134] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[135] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[136] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[137] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[138] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[139] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[13] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[140] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[141] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[142] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[143] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[144] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[145] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[146] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[147] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[148] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[149] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[14] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[150] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[151] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[152] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[153] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[154] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[155] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[156] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[157] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[158] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[159] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[15] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[160] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[161] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[162] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[163] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[164] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[165] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[166] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[167] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[168] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[169] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[16] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[170] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[171] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[172] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[173] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[174] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[175] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[176] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[177] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[178] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[179] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[17] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[180] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[181] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[182] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[183] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[184] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[185] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[186] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[187] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[188] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[189] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[18] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[190] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[191] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[192] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[193] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[194] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[195] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[196] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[197] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[198] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[199] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[19] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[1] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[20] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[21] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[22] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[23] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[24] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[25] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[26] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[27] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[28] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[29] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[2] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[30] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[31] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[32] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[33] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[34] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[35] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[36] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[37] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[38] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[39] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[3] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[40] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[41] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[42] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[43] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[44] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[45] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[46] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[47] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[48] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[49] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[4] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[50] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[51] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[52] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[53] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[54] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[55] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[56] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[57] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[58] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[59] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[5] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[60] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[61] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[62] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[63] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[64] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[65] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[66] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[67] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[68] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[69] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[6] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[70] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[71] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[72] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[73] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[74] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[75] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[76] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[77] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[78] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[79] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[7] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[80] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[81] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[82] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[83] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[84] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[85] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[86] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[87] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[88] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[89] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[8] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[90] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[91] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[92] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[93] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[94] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[95] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[96] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[97] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[98] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[99] | ✅ | 0.000 |  |
| test_property_top_up_never_exceeds_target_plus_band[9] | ✅ | 0.000 |  |
| test_targets_sum_within_1e7_tolerance_does_not_raise[-1e-07] | ✅ | 0.000 |  |
| test_targets_sum_within_1e7_tolerance_does_not_raise[1e-07] | ✅ | 0.000 |  |
| test_zero_band_only_buys_positions_still_at_zero | ✅ | 0.000 |  |
| test_zero_weight_bucket_never_receives_orders | ✅ | 0.000 |  |

### test_edge_hooks_skills — 27 tests, 0.44 s

| test | status | seconds | note |
|---|---|---:|---|
| test_every_backticked_tool_call_in_skill_md_names_a_real_mcp_tool[deploy-cash] | ✅ | 0.001 |  |
| test_every_backticked_tool_call_in_skill_md_names_a_real_mcp_tool[investment-plan] | ✅ | 0.000 |  |
| test_every_backticked_tool_call_in_skill_md_names_a_real_mcp_tool[portfolio-review] | ✅ | 0.000 |  |
| test_every_backticked_tool_call_in_skill_md_names_a_real_mcp_tool[position-review] | ✅ | 0.000 |  |
| test_every_backticked_tool_call_in_skill_md_names_a_real_mcp_tool[rebalance] | ✅ | 0.000 |  |
| test_every_backticked_tool_call_in_skill_md_names_a_real_mcp_tool[start] | ✅ | 0.000 |  |
| test_every_backticked_tool_call_in_skill_md_names_a_real_mcp_tool[stock-picker] | ✅ | 0.000 |  |
| test_every_slash_command_reference_in_skill_md_points_to_an_existing_skill[deploy-cash] | ✅ | 0.000 |  |
| test_every_slash_command_reference_in_skill_md_points_to_an_existing_skill[investment-plan] | ✅ | 0.000 |  |
| test_every_slash_command_reference_in_skill_md_points_to_an_existing_skill[portfolio-review] | ✅ | 0.000 |  |
| test_every_slash_command_reference_in_skill_md_points_to_an_existing_skill[position-review] | ✅ | 0.000 |  |
| test_every_slash_command_reference_in_skill_md_points_to_an_existing_skill[rebalance] | ✅ | 0.000 |  |
| test_every_slash_command_reference_in_skill_md_points_to_an_existing_skill[start] | ✅ | 0.000 |  |
| test_every_slash_command_reference_in_skill_md_points_to_an_existing_skill[stock-picker] | ✅ | 0.000 |  |
| test_guard_allows_docs_write_naming_a_credential_shaped_env_var_in_a_code_fence | ✅ | 0.037 |  |
| test_guard_allows_grep_for_a_bare_credential_shaped_word_in_source | ✅ | 0.036 |  |
| test_guard_allows_webfetch_of_a_public_doc_whose_name_merely_contains_auth | ✅ | 0.040 |  |
| test_guard_denies_accedi_path | ✅ | 0.040 |  |
| test_guard_denies_curl_carrying_an_authorization_basic_header | ✅ | 0.041 |  |
| test_guard_denies_signon_path | ✅ | 0.041 |  |
| test_guard_denies_url_with_inline_userinfo_credentials | ✅ | 0.042 |  |
| test_guard_processes_one_megabyte_input_quickly | ✅ | 0.074 |  |
| test_guard_tolerates_empty_stdin | ✅ | 0.038 |  |
| test_guard_tolerates_null_tool_input | ✅ | 0.041 |  |
| test_plugin_marketplace_and_pyproject_versions_all_agree | ✅ | 0.001 |  |
| test_session_banner_exits_zero_and_names_every_skill | ✅ | 0.010 |  |
| test_tool_name_regex_extraction_matches_the_live_server_module | ✅ | 0.000 |  |

### test_edge_ledger_providers — 26 tests, 0.01 s

| test | status | seconds | note |
|---|---|---:|---|
| test_convert_to_eur_returns_none_for_currency_missing_from_ecb_rates | ✅ | 0.000 |  |
| test_ecb_provider_get_rates_without_usd | ✅ | 0.001 |  |
| test_ecb_provider_propagates_timeout | ✅ | 0.000 |  |
| test_ecb_provider_raises_http_status_error_on_server_and_client_errors[404] | ✅ | 0.000 |  |
| test_ecb_provider_raises_http_status_error_on_server_and_client_errors[500] | ✅ | 0.000 |  |
| test_evaluate_decisions_excludes_future_dated_decision_without_crashing | ✅ | 0.001 |  |
| test_evaluate_decisions_self_referential_alternative_computes_deterministically | ✅ | 0.001 |  |
| test_ledger_path_raises_when_parent_of_home_is_not_writable | ✅ | 0.001 |  |
| test_load_decisions_raises_on_schema_violating_line | ✅ | 0.002 |  |
| test_load_decisions_raises_on_syntactically_corrupted_line | ✅ | 0.003 |  |
| test_parse_ecb_xml_without_usd_still_parses_other_currencies | ✅ | 0.000 |  |
| test_parse_stooq_csv_raises_value_error_when_close_column_missing | ✅ | 0.002 |  |
| test_record_decision_raises_when_home_directory_is_not_writable | ✅ | 0.001 |  |
| test_sec_company_tickers_shape_drift_degrades_in_mcp_tool[body0] | ✅ | 0.000 |  |
| test_sec_company_tickers_shape_drift_degrades_in_mcp_tool[body1] | ✅ | 0.000 |  |
| test_sec_company_tickers_shape_drift_raises_readable_value_error[body0] | ✅ | 0.001 |  |
| test_sec_company_tickers_shape_drift_raises_readable_value_error[body1] | ✅ | 0.000 |  |
| test_sec_provider_propagates_timeout | ✅ | 0.000 |  |
| test_sec_provider_raises_http_status_error_on_server_and_client_errors[404] | ✅ | 0.000 |  |
| test_sec_provider_raises_http_status_error_on_server_and_client_errors[500] | ✅ | 0.001 |  |
| test_stooq_get_closes_raises_when_response_has_no_close_column | ✅ | 0.001 |  |
| test_stooq_provider_propagates_timeout | ✅ | 0.000 |  |
| test_stooq_provider_raises_http_status_error_on_server_and_client_errors[404] | ✅ | 0.000 |  |
| test_stooq_provider_raises_http_status_error_on_server_and_client_errors[500] | ✅ | 0.000 |  |
| test_ttl_cache_zero_ttl_does_not_accumulate_dead_entries_forever | ✅ | 0.000 |  |
| test_ttl_cache_zero_ttl_never_serves_a_stored_value | ✅ | 0.000 |  |

### test_edge_parser — 13 tests, 0.06 s

| test | status | seconds | note |
|---|---|---:|---|
| test_blank_optional_cells_yield_none_not_zero_or_crash | ✅ | 0.003 |  |
| test_completely_empty_file_raises_clear_error | ✅ | 0.001 |  |
| test_dash_placeholder_numeric_cell_yields_none | ✅ | 0.002 |  |
| test_duplicate_instrument_names_are_kept_as_separate_holdings | ✅ | 0.002 |  |
| test_header_only_file_returns_empty_portfolio_not_error | ✅ | 0.001 |  |
| test_header_spread_over_two_physical_rows | ✅ | 0.002 |  |
| test_nd_placeholder_numeric_cell_yields_none | ✅ | 0.002 |  |
| test_parse_real_xlsx_with_multiline_headers_preamble_and_total | ✅ | 0.014 |  |
| test_parses_500_rows_within_two_seconds | ✅ | 0.022 |  |
| test_single_line_name_resembling_a_ticker_prefix_is_not_split | ✅ | 0.002 |  |
| test_us_format_market_value_row_is_dropped_not_corrupted | ✅ | 0.002 |  |
| test_us_format_number_is_not_fabricated_into_a_wrong_value | ✅ | 0.000 |  |
| test_usd_instrument_currency_with_broker_eur_values_no_conversion | ✅ | 0.002 |  |

### test_edge_plan_backtest — 22 tests, 0.04 s

| test | status | seconds | note |
|---|---|---:|---|
| test_backtest_accounting_identity_holds_for_random_target_mixes | ✅ | 0.008 |  |
| test_backtest_contribution_every_months_larger_than_available_history | ✅ | 0.001 |  |
| test_backtest_flat_then_crash_then_recovery_reports_exact_drawdown | ✅ | 0.001 |  |
| test_backtest_low_priced_bucket_stays_numerically_sane | ✅ | 0.001 |  |
| test_backtest_never_sells_implied_units_are_non_decreasing_through_crash_and_recovery | ✅ | 0.009 |  |
| test_backtest_unsorted_index_gives_same_result_as_default_index | ✅ | 0.001 |  |
| test_backtest_zero_cash_zero_contribution_drawdown_is_none_not_nan | ✅ | 0.001 |  |
| test_backtest_zero_initial_cash_and_zero_contribution_places_no_orders | ✅ | 0.001 |  |
| test_build_calendar_review_every_one_flags_review_or_annual_every_month | ✅ | 0.000 |  |
| test_build_calendar_review_every_twelve_only_flags_annual_review | ✅ | 0.000 |  |
| test_build_calendar_start_date_jan31_rolls_into_next_year | ✅ | 0.000 |  |
| test_build_calendar_start_date_leap_day_clamps_and_rolls_into_next_year | ✅ | 0.000 |  |
| test_build_calendar_zero_months_returns_no_events | ✅ | 0.000 |  |
| test_build_plan_calendar_months_zero_produces_empty_calendar | ✅ | 0.003 |  |
| test_build_plan_calendar_survives_month_end_start_dates_and_review_cadences[1-start_date_0] | ✅ | 0.003 |  |
| test_build_plan_calendar_survives_month_end_start_dates_and_review_cadences[1-start_date_1] | ✅ | 0.003 |  |
| test_build_plan_calendar_survives_month_end_start_dates_and_review_cadences[12-start_date_0] | ✅ | 0.003 |  |
| test_build_plan_calendar_survives_month_end_start_dates_and_review_cadences[12-start_date_1] | ✅ | 0.003 |  |
| test_build_plan_half_year_horizon_with_huge_monthly_contribution_invests_every_month | ✅ | 0.003 |  |
| test_build_plan_half_year_horizon_with_tiny_monthly_contribution_warns_and_never_invents | ✅ | 0.003 |  |
| test_contribution_cadence_handles_extreme_monthly_amounts[1000000.0-1] | ✅ | 0.000 |  |
| test_contribution_cadence_handles_extreme_monthly_amounts[1e-06-12] | ✅ | 0.000 |  |

### test_edge_quality — 43 tests, 0.00 s

| test | status | seconds | note |
|---|---|---:|---|
| test_decision_outcome_matrix_alpha_none_is_not_yet_measurable_regardless_of_quality | ✅ | 0.000 |  |
| test_decision_outcome_matrix_bad_decision_bad_outcome | ✅ | 0.000 |  |
| test_decision_outcome_matrix_bad_decision_bad_outcome_on_zero_alpha | ✅ | 0.000 |  |
| test_decision_outcome_matrix_bad_decision_lucky_outcome | ✅ | 0.000 |  |
| test_decision_outcome_matrix_good_decision_bad_outcome_on_negative_alpha | ✅ | 0.000 |  |
| test_decision_outcome_matrix_good_decision_bad_outcome_on_zero_alpha | ✅ | 0.000 |  |
| test_decision_outcome_matrix_good_decision_good_outcome | ✅ | 0.000 |  |
| test_decision_quality_alternative_recorded | ✅ | 0.000 |  |
| test_decision_quality_amount_exactly_at_cap_counts_as_within | ✅ | 0.000 |  |
| test_decision_quality_amount_exceeding_cap_scores_zero | ✅ | 0.000 |  |
| test_decision_quality_amount_unknown_when_either_field_missing | ✅ | 0.000 |  |
| test_decision_quality_amount_within_cap_scores_full_points | ✅ | 0.000 |  |
| test_decision_quality_bucket_fill_can_reach_good_quality_threshold | ✅ | 0.000 |  |
| test_decision_quality_bucket_fill_ignores_inapplicable_criteria | ✅ | 0.000 |  |
| test_decision_quality_confidence_below_threshold_scores_zero | ✅ | 0.000 |  |
| test_decision_quality_criteria_points_sum_to_score | ✅ | 0.000 |  |
| test_decision_quality_empty_record_scores_zero | ✅ | 0.000 |  |
| test_decision_quality_full_score_when_everything_present | ✅ | 0.000 |  |
| test_decision_quality_price_recorded | ✅ | 0.000 |  |
| test_decision_quality_reason_length_threshold_is_forty_chars | ✅ | 0.000 |  |
| test_decision_quality_red_team_must_equal_passed | ✅ | 0.000 |  |
| test_decision_quality_score_is_deterministic | ✅ | 0.000 |  |
| test_decision_quality_sources_criterion_needs_at_least_one | ✅ | 0.000 |  |
| test_decision_quality_stock_buy_still_uses_the_full_rubric_by_default | ✅ | 0.000 |  |
| test_decision_quality_thesis_status_missing_key_scores_zero_with_note | ✅ | 0.000 |  |
| test_decision_quality_thesis_status_other_value_scores_zero | ✅ | 0.000 |  |
| test_decision_quality_thesis_status_stable_and_strengthening_score_full | ✅ | 0.000 |  |
| test_personal_edge_below_min_sample_reports_insufficient_and_warning | ✅ | 0.000 |  |
| test_personal_edge_category_takes_precedence_over_theme_when_both_present | ✅ | 0.000 |  |
| test_personal_edge_default_min_sample_is_ten | ✅ | 0.000 |  |
| test_personal_edge_empty_input_is_insufficient_and_has_no_categories | ✅ | 0.000 |  |
| test_personal_edge_groups_by_category_with_fallback_uncategorized | ✅ | 0.000 |  |
| test_personal_edge_hit_rate_counts_strictly_positive_alpha_only | ✅ | 0.000 |  |
| test_personal_edge_is_deterministic_and_pure | ✅ | 0.000 |  |
| test_personal_edge_keep_when_neither_extreme | ✅ | 0.000 |  |
| test_personal_edge_lower_when_mean_alpha_high_and_hit_rate_high | ✅ | 0.000 |  |
| test_personal_edge_negative_min_sample_with_empty_ledger_does_not_crash | ✅ | 0.000 |  |
| test_personal_edge_overall_aggregates_across_categories | ✅ | 0.000 |  |
| test_personal_edge_raise_when_hit_rate_low_even_if_mean_alpha_ok | ✅ | 0.000 |  |
| test_personal_edge_raise_when_mean_alpha_very_negative | ✅ | 0.000 |  |
| test_personal_edge_rows_with_none_decision_alpha_are_excluded_from_stats | ✅ | 0.000 |  |
| test_personal_edge_uses_theme_when_category_absent | ✅ | 0.000 |  |
| test_personal_edge_zero_min_sample_with_empty_ledger_does_not_crash | ✅ | 0.000 |  |

### test_edge_scoring_merge — 15 tests, 0.00 s

| test | status | seconds | note |
|---|---|---:|---|
| test_all_fields_none_snapshot_scores_50_confidence_is_floored_and_warns | ✅ | 0.000 |  |
| test_annualized_volatility_on_constant_series_is_zero_not_none | ✅ | 0.000 |  |
| test_annualized_volatility_on_empty_series_returns_none | ✅ | 0.000 |  |
| test_concentration_on_empty_weights_returns_all_zero | ✅ | 0.000 |  |
| test_extreme_magnitude_inputs_clamp_to_valid_bounds | ✅ | 0.000 |  |
| test_hhi_on_empty_weights_is_zero | ✅ | 0.000 |  |
| test_max_drawdown_on_constant_series_is_zero_not_none | ✅ | 0.000 |  |
| test_max_drawdown_on_empty_and_single_element_series_returns_none | ✅ | 0.000 |  |
| test_merge_with_ok_facts_but_missing_fiscal_year_still_overrides_and_bumps_confidence | ✅ | 0.000 |  |
| test_merge_zero_revenue_growth_from_facts_overrides_existing_estimate | ✅ | 0.000 |  |
| test_nan_ret_field_via_f_is_excluded_from_momentum_average_not_propagated | ✅ | 0.000 |  |
| test_negative_price_does_not_alter_score_since_price_is_not_a_score_input | ✅ | 0.000 |  |
| test_pct_return_on_empty_and_single_element_series_returns_none | ✅ | 0.000 |  |
| test_provider_f_converts_nan_and_inf_to_none | ✅ | 0.000 |  |
| test_score_snapshot_is_pure_and_json_reproducible | ✅ | 0.000 |  |

### test_evidence — 27 tests, 0.00 s

| test | status | seconds | note |
|---|---|---:|---|
| test_builder_combines_all_three_sources_per_metric | ✅ | 0.000 |  |
| test_builder_handles_missing_snapshot_provenance_gracefully | ✅ | 0.000 |  |
| test_builder_ignores_non_numeric_finviz_pe | ✅ | 0.000 |  |
| test_builder_ignores_unavailable_facts_and_finviz_inputs | ✅ | 0.000 |  |
| test_builder_skips_facts_fields_outside_its_known_shape | ✅ | 0.000 |  |
| test_builder_treats_infinite_snapshot_value_as_missing | ✅ | 0.000 |  |
| test_builder_treats_nan_facts_value_as_missing | ✅ | 0.000 |  |
| test_builder_treats_nan_finviz_pe_string_as_missing_not_a_real_reading | ✅ | 0.000 |  |
| test_builder_with_only_snapshot_reports_missing_for_absent_fields | ✅ | 0.000 |  |
| test_conflict_with_an_official_tier_a_source_is_still_flagged_but_used | ✅ | 0.000 |  |
| test_evidence_report_on_empty_metrics_dict | ✅ | 0.000 |  |
| test_evidence_report_tallies_every_status | ✅ | 0.000 |  |
| test_highest_tier_wins_regardless_of_list_order | ✅ | 0.000 |  |
| test_missing_when_all_values_are_none | ✅ | 0.000 |  |
| test_missing_when_values_list_is_empty | ✅ | 0.000 |  |
| test_none_values_are_dropped_before_a_single_real_value_is_used | ✅ | 0.000 |  |
| test_relative_tolerance_scales_with_magnitude | ✅ | 0.000 |  |
| test_same_tier_no_recency_difference_keeps_the_first_listed | ✅ | 0.000 |  |
| test_same_tier_recency_tiebreak_handles_differing_utc_offsets | ✅ | 0.000 |  |
| test_same_tier_ties_broken_by_most_recent_as_of | ✅ | 0.000 |  |
| test_single_source_is_used_but_flagged_unverified | ✅ | 0.000 |  |
| test_single_source_tier_b_is_still_used_in_score | ✅ | 0.000 |  |
| test_single_source_tier_c_is_never_used_in_score | ✅ | 0.000 |  |
| test_spread_is_max_minus_min_across_present_sources | ✅ | 0.000 |  |
| test_tolerance_boundary_is_inclusive | ✅ | 0.000 |  |
| test_two_sources_outside_tolerance_are_a_conflict_and_unused_without_tier_a | ✅ | 0.000 |  |
| test_two_sources_within_tolerance_are_verified | ✅ | 0.000 |  |

### test_exposure — 34 tests, 0.01 s

| test | status | seconds | note |
|---|---|---:|---|
| test_classify_5x_certificate_on_a_bank | ✅ | 0.000 |  |
| test_classify_chip_stock | ✅ | 0.000 |  |
| test_classify_defense_stock | ✅ | 0.000 |  |
| test_classify_degrades_gracefully_on_custom_graph_missing_leveraged_theme | ✅ | 0.000 |  |
| test_classify_emerging_markets_etf | ✅ | 0.000 |  |
| test_classify_global_bond_etf | ✅ | 0.000 |  |
| test_classify_high_leverage_without_certificate_asset_type_still_flags_leverage | ✅ | 0.000 |  |
| test_classify_leverage_forces_leveraged_theme_even_without_underlying_match | ✅ | 0.000 |  |
| test_classify_small_cap_etf_also_carries_world_equity | ✅ | 0.000 |  |
| test_classify_unclassified_when_nothing_matches | ✅ | 0.000 |  |
| test_classify_world_equity_etf | ✅ | 0.000 |  |
| test_default_graph_every_theme_has_keywords_and_drivers | ✅ | 0.000 |  |
| test_default_graph_has_exactly_the_curated_themes | ✅ | 0.006 |  |
| test_fit_score_cap_not_breached_when_below_threshold | ✅ | 0.000 |  |
| test_fit_score_full_when_no_overlap_and_no_cap | ✅ | 0.000 |  |
| test_fit_score_reduced_by_shared_driver_weight_when_semis_already_20pct | ✅ | 0.000 |  |
| test_fit_score_zero_when_theme_cap_would_be_breached | ✅ | 0.000 |  |
| test_load_graph_missing_file_raises | ✅ | 0.001 |  |
| test_load_graph_reflects_on_disk_edit_without_restart | ✅ | 0.002 |  |
| test_load_graph_rejects_empty_themes | ✅ | 0.001 |  |
| test_load_graph_rejects_theme_missing_drivers | ✅ | 0.002 |  |
| test_portfolio_exposure_all_nan_market_values_returns_all_empty_not_nan | ✅ | 0.000 |  |
| test_portfolio_exposure_empty_portfolio | ✅ | 0.000 |  |
| test_portfolio_exposure_infinite_market_value_is_treated_as_missing | ✅ | 0.000 |  |
| test_portfolio_exposure_italian_formatted_market_value_string | ✅ | 0.000 |  |
| test_portfolio_exposure_leveraged_equivalent_map_scales_by_leverage | ✅ | 0.001 |  |
| test_portfolio_exposure_missing_optional_fields_default_safely | ✅ | 0.000 |  |
| test_portfolio_exposure_nan_leverage_defaults_to_unleveraged | ✅ | 0.000 |  |
| test_portfolio_exposure_nan_market_value_is_treated_as_missing_not_poisoning | ✅ | 0.000 |  |
| test_portfolio_exposure_sample_theme_weights | ✅ | 0.001 |  |
| test_portfolio_exposure_unclassified_holding | ✅ | 0.000 |  |
| test_portfolio_exposure_unparsable_leverage_string_defaults_to_one | ✅ | 0.000 |  |
| test_portfolio_exposure_unparsable_market_value_string_degrades_to_zero | ✅ | 0.000 |  |
| test_portfolio_exposure_zero_value_holdings_treated_like_empty | ✅ | 0.000 |  |

### test_finviz — 13 tests, 0.01 s

| test | status | seconds | note |
|---|---|---:|---|
| test_presets_use_valid_finviz_filters[momentum] | ✅ | 0.000 |  |
| test_presets_use_valid_finviz_filters[quality_growth] | ✅ | 0.000 |  |
| test_presets_use_valid_finviz_filters[quality_value] | ✅ | 0.000 |  |
| test_screen_degrades_when_scraper_call_raises | ✅ | 0.000 |  |
| test_screen_does_not_cache_a_failed_scrape | ✅ | 0.001 |  |
| test_screen_handles_empty_result_and_nan | ✅ | 0.001 |  |
| test_screen_orders_by_the_preset_own_style_order_not_market_cap[momentum] | ✅ | 0.001 |  |
| test_screen_orders_by_the_preset_own_style_order_not_market_cap[quality_growth] | ✅ | 0.001 |  |
| test_screen_orders_by_the_preset_own_style_order_not_market_cap[quality_value] | ✅ | 0.001 |  |
| test_screen_rejects_bad_arguments[momentum-0] | ✅ | 0.000 |  |
| test_screen_rejects_bad_arguments[nope-10] | ✅ | 0.000 |  |
| test_screen_returns_candidates_with_provenance_and_caches | ✅ | 0.001 |  |
| test_validate_preset_rejects_unknown_option | ✅ | 0.000 |  |

### test_finviz_universe — 15 tests, 0.01 s

| test | status | seconds | note |
|---|---|---:|---|
| test_discover_universe_all_screens_failing_is_not_ok | ✅ | 0.000 |  |
| test_discover_universe_caches_by_styles_sizes_per_screen | ✅ | 0.001 |  |
| test_discover_universe_does_not_cache_a_fully_failed_sample | ✅ | 0.001 |  |
| test_discover_universe_drops_rows_with_nan_ticker | ✅ | 0.001 |  |
| test_discover_universe_empty_screen_is_not_a_failure | ✅ | 0.000 |  |
| test_discover_universe_keeps_other_screens_when_one_fails | ✅ | 0.001 |  |
| test_discover_universe_rejects_non_positive_per_screen | ✅ | 0.000 |  |
| test_discover_universe_rejects_unknown_style_or_size[bad_styles0-bad_sizes0] | ✅ | 0.000 |  |
| test_discover_universe_rejects_unknown_style_or_size[bad_styles1-bad_sizes1] | ✅ | 0.000 |  |
| test_discover_universe_runs_one_screen_per_style_size_pair_with_size_override | ✅ | 0.001 |  |
| test_discover_universe_screener_factory_override_bypasses_provider_default | ✅ | 0.001 |  |
| test_discover_universe_unions_and_dedupes_merging_styles_hit | ✅ | 0.001 |  |
| test_size_buckets_are_valid_finviz_market_cap_options | ✅ | 0.000 |  |
| test_style_order_covers_every_preset | ✅ | 0.000 |  |
| test_style_order_names_are_valid_finviz_order_names | ✅ | 0.000 |  |

### test_hook_etoro_allowlist — 11 tests, 0.52 s

| test | status | seconds | note |
|---|---|---:|---|
| test_basic_auth_and_bearer_on_command_line_are_still_denied | ✅ | 0.079 |  |
| test_etoro_api_and_docs_urls_are_allowed[curl -s https://builders.etoro.com/learn/authentication-and-api-keys] | ✅ | 0.036 |  |
| test_etoro_api_and_docs_urls_are_allowed[curl -s https://public-api.etoro.com/api/v2/trading/execution/demo/orders] | ✅ | 0.039 |  |
| test_etoro_api_and_docs_urls_are_allowed[curl -s https://public-api.etoro.com/api/v2/trading/info/portfolio] | ✅ | 0.041 |  |
| test_etoro_api_and_docs_urls_are_allowed[curl -sL -A 'portfolio-copilot' https://api-portal.etoro.com/ -o portal.html] | ✅ | 0.043 |  |
| test_etoro_api_and_docs_urls_are_allowed[uv run python -c "import httpx; httpx.post('https://public-api.etoro.com/api/v2/trading/execution/demo/orders', json={})"] | ✅ | 0.035 |  |
| test_header_names_and_client_lib_in_docs_are_not_credentials | ✅ | 0.083 |  |
| test_other_venues_and_credentials_still_denied[payload0] | ✅ | 0.040 |  |
| test_other_venues_and_credentials_still_denied[payload1] | ✅ | 0.041 |  |
| test_other_venues_and_credentials_still_denied[payload2] | ✅ | 0.041 |  |
| test_other_venues_and_credentials_still_denied[payload3] | ✅ | 0.042 |  |

### test_investor_relations — 24 tests, 0.01 s

| test | status | seconds | note |
|---|---|---:|---|
| test_candidate_ir_urls_accepts_website_without_scheme | ✅ | 0.000 |  |
| test_candidate_ir_urls_covers_paths_and_subdomains | ✅ | 0.000 |  |
| test_candidate_ir_urls_ignores_path_and_query | ✅ | 0.000 |  |
| test_candidate_ir_urls_rejects_empty_website | ✅ | 0.000 |  |
| test_extract_ir_links_classifies_kinds_and_dates | ✅ | 0.001 |  |
| test_extract_ir_links_deduplicates_repeated_hrefs | ✅ | 0.000 |  |
| test_extract_ir_links_empty_page | ✅ | 0.000 |  |
| test_extract_ir_links_skips_javascript_and_mailto_links | ✅ | 0.000 |  |
| test_investor_relations_accepts_website_without_scheme | ✅ | 0.001 |  |
| test_investor_relations_all_404_returns_readable_result | ✅ | 0.000 |  |
| test_investor_relations_finds_first_working_candidate | ✅ | 0.001 |  |
| test_investor_relations_low_kind_diversity_gives_low_confidence | ✅ | 0.000 |  |
| test_investor_relations_nav_only_page_with_no_dates_is_low_confidence | ✅ | 0.000 |  |
| test_investor_relations_network_error_on_a_candidate_is_recorded_and_skipped | ✅ | 0.001 |  |
| test_investor_relations_never_exceeds_request_cap | ✅ | 0.000 |  |
| test_investor_relations_skips_disallowed_path_and_tries_next_candidate | ✅ | 0.001 |  |
| test_investor_relations_uses_ttl_cache | ✅ | 0.001 |  |
| test_robots_allows_default_agent_from_fixture | ✅ | 0.000 |  |
| test_robots_allows_empty_disallow_means_allow_everything | ✅ | 0.000 |  |
| test_robots_allows_falls_back_to_star_for_unnamed_agent | ✅ | 0.000 |  |
| test_robots_allows_longest_match_wins_on_conflict | ✅ | 0.000 |  |
| test_robots_allows_no_groups_means_allowed | ✅ | 0.000 |  |
| test_robots_allows_path_without_leading_slash | ✅ | 0.000 |  |
| test_robots_allows_uses_named_group_over_star | ✅ | 0.000 |  |

### test_ledger — 20 tests, 0.02 s

| test | status | seconds | note |
|---|---|---:|---|
| test_candidate_at_decision_rejects_non_finite_price | ✅ | 0.000 |  |
| test_candidates_field_defaults_to_empty_list_for_pre_existing_ledger_lines | ✅ | 0.001 |  |
| test_candidates_field_round_trips_through_record_and_load | ✅ | 0.001 |  |
| test_decision_alpha_arithmetic_and_missing_alternative | ✅ | 0.000 |  |
| test_decision_alpha_rejects_nan_or_infinite_real_leg_prices | ✅ | 0.000 |  |
| test_decision_alpha_treats_nan_alternative_prices_as_missing_not_a_silent_nan | ✅ | 0.000 |  |
| test_decision_record_rejects_non_finite_alternative_price | ✅ | 0.000 |  |
| test_decision_record_rejects_non_finite_price | ✅ | 0.000 |  |
| test_evaluate_decisions_bad_date_is_unmeasurable_not_a_crash | ✅ | 0.001 |  |
| test_evaluate_decisions_marks_nonpositive_price_unmeasurable_without_crashing | ✅ | 0.002 |  |
| test_evaluate_decisions_nan_current_price_is_unmeasurable_not_a_poisoned_nan_alpha | ✅ | 0.002 |  |
| test_evaluate_decisions_respects_min_days_and_marks_unmeasurable | ✅ | 0.002 |  |
| test_evaluate_decisions_sell_treats_alternative_as_the_real_leg | ✅ | 0.001 |  |
| test_load_decisions_raises_on_nan_price_instead_of_silently_loading_it | ✅ | 0.001 |  |
| test_load_empty_ledger | ✅ | 0.001 |  |
| test_optional_enrichment_fields_default_to_none_and_are_backward_compatible | ✅ | 0.001 |  |
| test_optional_enrichment_fields_round_trip_through_record_and_load | ✅ | 0.001 |  |
| test_record_and_load_roundtrip | ✅ | 0.002 |  |
| test_record_decision_rejects_a_replayed_identical_id | ✅ | 0.001 |  |
| test_record_rejects_invalid_action_or_confidence | ✅ | 0.001 |  |

### test_macro_providers — 31 tests, 0.00 s

| test | status | seconds | note |
|---|---|---:|---|
| test_deposit_facility_rate_caches_and_uses_timeout | ✅ | 0.000 |  |
| test_deposit_facility_rate_degrades_on_error_without_raising | ✅ | 0.000 |  |
| test_eurostat_degrades_on_http_error_without_raising | ✅ | 0.000 |  |
| test_eurostat_degrades_on_malformed_payload_without_raising | ✅ | 0.000 |  |
| test_eurostat_degrades_when_every_observation_is_null | ✅ | 0.000 |  |
| test_eurostat_latest_degrades_on_non_dict_payload | ✅ | 0.000 |  |
| test_eurostat_latest_degrades_on_non_numeric_value_entry | ✅ | 0.000 |  |
| test_eurostat_reports_empty_geo_dimension_distinctly | ✅ | 0.000 |  |
| test_hicp_annual_rate_returns_latest_non_null_and_caches | ✅ | 0.000 |  |
| test_macro_snapshot_end_to_end_with_real_providers | ✅ | 0.001 |  |
| test_macro_snapshot_infinite_dfr_is_unknown_never_a_confident_regime | ✅ | 0.000 |  |
| test_macro_snapshot_missing_dfr_is_unknown_never_guessed | ✅ | 0.000 |  |
| test_macro_snapshot_missing_hicp_is_unknown_never_guessed | ✅ | 0.000 |  |
| test_macro_snapshot_nan_hicp_is_unknown_never_a_confident_regime | ✅ | 0.000 |  |
| test_macro_snapshot_regime_branches[1.0-3.0-accommodative] | ✅ | 0.000 |  |
| test_macro_snapshot_regime_branches[2.0-3.0-neutral] | ✅ | 0.000 |  |
| test_macro_snapshot_regime_branches[2.5-2.0-neutral] | ✅ | 0.000 |  |
| test_macro_snapshot_regime_branches[3.0-2.0-neutral] | ✅ | 0.000 |  |
| test_macro_snapshot_regime_branches[4.0-2.0-restrictive] | ✅ | 0.000 |  |
| test_macro_snapshot_shape_and_slimmed_fields | ✅ | 0.000 |  |
| test_macro_snapshot_shape_includes_confidence_for_every_series | ✅ | 0.000 |  |
| test_parse_ecb_csv_reads_latest_observation | ✅ | 0.000 |  |
| test_parse_ecb_csv_rejects_csv_with_no_observations | ✅ | 0.000 |  |
| test_parse_ecb_csv_skips_rows_with_empty_obs_value | ✅ | 0.000 |  |
| test_parse_jsonstat_hicp_sorted_with_nulls_for_missing_and_explicit_null | ✅ | 0.000 |  |
| test_parse_jsonstat_rejects_multi_category_non_time_dimension | ✅ | 0.000 |  |
| test_parse_jsonstat_rejects_payload_without_time_dimension | ✅ | 0.000 |  |
| test_parse_jsonstat_rejects_time_dimension_without_index | ✅ | 0.000 |  |
| test_parse_jsonstat_unemployment_series_fully_populated | ✅ | 0.000 |  |
| test_unemployment_default_geo_is_eu27_and_macro_uses_separate_geos | ✅ | 0.000 |  |
| test_unemployment_rate_uses_its_own_dataset_and_cache_key | ✅ | 0.000 |  |

### test_mapping — 30 tests, 0.00 s

| test | status | seconds | note |
|---|---|---:|---|
| test_certificate_is_unmapped | ✅ | 0.000 |  |
| test_certificate_matching_a_keyword_still_stays_satellite | ✅ | 0.000 |  |
| test_coverage_is_mapped_value_over_total_value | ✅ | 0.000 |  |
| test_duplicate_isin_across_buckets_raises_instead_of_picking_silently | ✅ | 0.000 |  |
| test_each_name_keyword_rule[Amundi Obbligazionario Governativo Euro-global_bonds_hedged] | ✅ | 0.000 |  |
| test_each_name_keyword_rule[SPDR MSCI World Small-Cap UCITS ETF-small_cap] | ✅ | 0.000 |  |
| test_each_name_keyword_rule[SPDR S&P 500 UCITS ETF-global_equity] | ✅ | 0.000 |  |
| test_each_name_keyword_rule[Vanguard FTSE All-World UCITS ETF-global_equity] | ✅ | 0.000 |  |
| test_each_name_keyword_rule[Vanguard FTSE Emerging Markets UCITS ETF-emerging_markets] | ✅ | 0.000 |  |
| test_each_name_keyword_rule[Xtrackers Developed World UCITS ETF-global_equity] | ✅ | 0.000 |  |
| test_each_name_keyword_rule[iShares Core Global Aggregate Bond UCITS ETF EUR Hedged-global_bonds_hedged] | ✅ | 0.000 |  |
| test_each_name_keyword_rule[iShares Core MSCI World UCITS ETF-global_equity] | ✅ | 0.000 |  |
| test_each_name_keyword_rule[iShares Global Govt Bond UCITS ETF-global_bonds_hedged] | ✅ | 0.000 |  |
| test_each_name_keyword_rule[iShares MSCI ACWI ETF-global_equity] | ✅ | 0.000 |  |
| test_each_name_keyword_rule[iShares MSCI World Small Cap UCITS ETF-small_cap] | ✅ | 0.000 |  |
| test_each_name_keyword_rule[iShares US Treasury Bond UCITS ETF-global_bonds_hedged] | ✅ | 0.000 |  |
| test_empty_holdings_returns_zeroed_targets_and_zero_coverage | ✅ | 0.000 |  |
| test_inverse_leveraged_instrument_is_classified_as_leveraged | ✅ | 0.000 |  |
| test_isin_exact_match_wins_over_name_keywords | ✅ | 0.000 |  |
| test_isin_match_is_case_and_whitespace_insensitive | ✅ | 0.000 |  |
| test_leveraged_instrument_is_unmapped_even_if_name_matches_a_keyword | ✅ | 0.000 |  |
| test_leveraged_instrument_matching_a_keyword_still_stays_satellite | ✅ | 0.000 |  |
| test_nan_market_value_does_not_poison_current_values | ✅ | 0.000 |  |
| test_non_numeric_market_value_string_does_not_crash | ✅ | 0.000 |  |
| test_result_can_be_fed_directly_into_allocate_cash_to_targets | ✅ | 0.000 |  |
| test_single_stock_equity_is_unmapped | ✅ | 0.000 |  |
| test_single_stock_equity_matching_a_keyword_still_stays_satellite | ✅ | 0.000 |  |
| test_small_cap_keyword_wins_over_world_keyword_in_same_name | ✅ | 0.000 |  |
| test_targets_bucket_absent_from_instruments_does_not_crash | ✅ | 0.000 |  |
| test_unrecognized_instrument_falls_back_to_generic_unmapped_reason | ✅ | 0.000 |  |

### test_merge — 7 tests, 0.00 s

| test | status | seconds | note |
|---|---|---:|---|
| test_apply_evidence_report_after_override_compares_against_the_pre_override_value | ✅ | 0.000 |  |
| test_apply_evidence_report_excludes_conflict_without_official_tiebreaker | ✅ | 0.000 |  |
| test_apply_evidence_report_keeps_conflict_resolved_by_an_official_source | ✅ | 0.000 |  |
| test_apply_evidence_report_single_source_metric_is_never_touched | ✅ | 0.000 |  |
| test_missing_sec_values_never_overwrite_with_none | ✅ | 0.000 |  |
| test_official_sec_values_override_yahoo_and_are_recorded | ✅ | 0.000 |  |
| test_unavailable_sec_leaves_snapshot_unchanged_but_noted | ✅ | 0.000 |  |

### test_metrics — 11 tests, 0.00 s

| test | status | seconds | note |
|---|---|---:|---|
| test_annualized_volatility_normal_case | ✅ | 0.001 |  |
| test_annualized_volatility_too_few_returns_none | ✅ | 0.001 |  |
| test_concentration | ✅ | 0.000 |  |
| test_max_drawdown | ✅ | 0.001 |  |
| test_max_drawdown_too_short_returns_none | ✅ | 0.000 |  |
| test_pct_return_normal_case | ✅ | 0.001 |  |
| test_pct_return_series_too_short_returns_none | ✅ | 0.000 |  |
| test_pct_return_zero_start_returns_none | ✅ | 0.000 |  |
| test_safe_ratio_finite_value | ✅ | 0.000 |  |
| test_safe_ratio_non_finite_value_returns_none | ✅ | 0.000 |  |
| test_safe_ratio_none_value_returns_none | ✅ | 0.000 |  |

### test_openfigi — 35 tests, 0.00 s

| test | status | seconds | note |
|---|---|---:|---|
| test_exchange_suffix_table_is_a_plain_dict_covering_the_documented_exchanges | ✅ | 0.000 |  |
| test_map_isins_cache_hit_skips_second_request | ✅ | 0.000 |  |
| test_map_isins_cache_is_scoped_by_exch_code | ✅ | 0.000 |  |
| test_map_isins_chunks_at_max_jobs_per_request | ✅ | 0.000 |  |
| test_map_isins_deduplicates_repeated_isins_in_one_call | ✅ | 0.000 |  |
| test_map_isins_does_not_sleep_when_enough_time_has_passed | ✅ | 0.000 |  |
| test_map_isins_error_item_returns_none_with_reason_recorded | ✅ | 0.000 |  |
| test_map_isins_expired_cache_entry_refetches | ✅ | 0.000 |  |
| test_map_isins_happy_path | ✅ | 0.000 |  |
| test_map_isins_miss_returns_none_with_reason_recorded | ✅ | 0.000 |  |
| test_map_isins_no_matching_exchange_is_a_miss_not_a_fabricated_ticker | ✅ | 0.000 |  |
| test_map_isins_normalizes_whitespace_and_case_before_dedup_and_cache | ✅ | 0.000 |  |
| test_map_isins_prefers_exchcode_match_over_first_row | ✅ | 0.000 |  |
| test_map_isins_raises_on_http_429 | ✅ | 0.000 |  |
| test_map_isins_response_length_mismatch_degrades_instead_of_crashing | ✅ | 0.000 |  |
| test_map_isins_spaces_requests_by_min_interval | ✅ | 0.000 |  |
| test_provenance_for_after_a_miss_response | ✅ | 0.000 |  |
| test_provenance_for_hit | ✅ | 0.000 |  |
| test_provenance_for_miss_without_lookup | ✅ | 0.000 |  |
| test_provenance_for_without_exch_code_resolves_the_last_successful_lookup | ✅ | 0.000 |  |
| test_rejects_negative_min_interval | ✅ | 0.000 |  |
| test_rejects_non_positive_max_jobs_per_request | ✅ | 0.000 |  |
| test_yf_ticker_for_miss_returns_none | ✅ | 0.000 |  |
| test_yf_ticker_for_no_matching_exchange_returns_none_not_fabricated | ✅ | 0.000 |  |
| test_yf_ticker_for_suffix_table[FP-.PA] | ✅ | 0.000 |  |
| test_yf_ticker_for_suffix_table[GR-.DE] | ✅ | 0.000 |  |
| test_yf_ticker_for_suffix_table[GY-.DE] | ✅ | 0.000 |  |
| test_yf_ticker_for_suffix_table[LN-.L] | ✅ | 0.000 |  |
| test_yf_ticker_for_suffix_table[MI-.MI] | ✅ | 0.000 |  |
| test_yf_ticker_for_suffix_table[NA-.AS] | ✅ | 0.000 |  |
| test_yf_ticker_for_suffix_table[UA-] | ✅ | 0.000 |  |
| test_yf_ticker_for_suffix_table[UN-] | ✅ | 0.000 |  |
| test_yf_ticker_for_suffix_table[US-] | ✅ | 0.000 |  |
| test_yf_ticker_for_suffix_table[UW-] | ✅ | 0.000 |  |
| test_yf_ticker_for_unknown_exchange_returns_none_without_a_request | ✅ | 0.000 |  |

### test_opportunity — 22 tests, 0.00 s

| test | status | seconds | note |
|---|---|---:|---|
| test_buy_measured_computes_regret_best_available_and_rank | ✅ | 0.000 |  |
| test_buy_unmeasurable_when_chosen_has_no_current_price | ✅ | 0.000 |  |
| test_buy_unmeasurable_when_chosen_has_no_decision_time_price | ✅ | 0.000 |  |
| test_buy_unmeasurable_when_no_candidates_are_priced | ✅ | 0.000 |  |
| test_cash_candidate_contributes_zero_return_without_needing_a_price | ✅ | 0.000 |  |
| test_ledger_round_trip_preserves_candidates_for_opportunity_cost | ✅ | 0.001 |  |
| test_nan_candidate_price_is_dropped_as_unmeasurable_not_a_silent_nan | ✅ | 0.000 |  |
| test_nan_current_price_is_unmeasurable_not_a_silent_nan_regret | ✅ | 0.000 |  |
| test_opportunity_cost_is_deterministic | ✅ | 0.000 |  |
| test_rank_ties_when_multiple_candidates_share_the_best_return | ✅ | 0.000 |  |
| test_report_bad_date_row_is_unmeasurable_not_a_crash | ✅ | 0.000 |  |
| test_report_min_days_filters_recent_decisions | ✅ | 0.000 |  |
| test_report_min_sample_gate_wording | ✅ | 0.000 |  |
| test_report_neutral_when_regret_moderate | ✅ | 0.000 |  |
| test_report_review_process_when_mean_regret_is_high | ✅ | 0.000 |  |
| test_report_skill_signal_when_regret_is_low_and_mostly_within_tolerance | ✅ | 0.000 |  |
| test_sell_chosen_is_the_alternative_and_sold_symbol_becomes_kept_it_candidate | ✅ | 0.000 |  |
| test_sell_chosen_leg_resolves_a_price_symbol_proxy_like_the_buy_branch | ✅ | 0.000 |  |
| test_sell_kept_it_candidate_resolves_a_price_symbol_proxy_too | ✅ | 0.000 |  |
| test_sell_regret_is_positive_when_keeping_the_position_would_have_won | ✅ | 0.000 |  |
| test_sell_without_recorded_alternative_is_unmeasurable | ✅ | 0.000 |  |
| test_unmeasurable_candidates_are_listed_by_name_with_reason | ✅ | 0.000 |  |

### test_parser — 10 tests, 0.02 s

| test | status | seconds | note |
|---|---|---:|---|
| test_delimiter_detection_ignores_commas_inside_numeric_cells | ✅ | 0.001 |  |
| test_parse_bare_thousands_quantity_no_decimal_comma | ✅ | 0.002 |  |
| test_parse_does_not_false_positive_leverage_on_equity_name | ✅ | 0.002 |  |
| test_parse_empty_and_unmappable_files | ✅ | 0.002 |  |
| test_parse_ignores_total_row_label_variants | ✅ | 0.002 |  |
| test_parse_layout_with_strumento_and_multiline_headers | ✅ | 0.002 |  |
| test_parse_missing_pnl_pct_cell_stays_none | ✅ | 0.002 |  |
| test_parse_page_export_with_preamble_ticker_lines_and_total_row | ✅ | 0.002 |  |
| test_parse_synthetic_semicolon_csv | ✅ | 0.002 |  |
| test_to_float_bare_italian_thousands_no_decimal | ✅ | 0.000 |  |

### test_picker — 45 tests, 0.00 s

| test | status | seconds | note |
|---|---|---:|---|
| test_annotate_core_overlap_note_absent_for_non_mega | ✅ | 0.000 |  |
| test_annotate_core_overlap_note_present_for_mega | ✅ | 0.000 |  |
| test_annotate_core_overlap_note_present_when_exposure_confirms_overlap | ✅ | 0.000 |  |
| test_annotate_core_overlap_note_suppressed_when_exposure_shows_no_overlap | ✅ | 0.000 |  |
| test_annotate_exposure_none_path_gives_no_overlap_data | ✅ | 0.000 |  |
| test_annotate_lane_core_like_for_mega_with_heavy_overlap | ✅ | 0.000 |  |
| test_annotate_lane_diversifying_for_mega_with_no_overlap | ✅ | 0.000 |  |
| test_annotate_lane_priority_mega_overlap_beats_high_risk_category | ✅ | 0.000 |  |
| test_annotate_lane_speculative_for_high_risk_category_non_mega | ✅ | 0.000 |  |
| test_annotate_nan_market_cap_size_bucket_is_none | ✅ | 0.000 |  |
| test_annotate_never_removes_the_item | ✅ | 0.000 |  |
| test_annotate_risk_cap_pct_asymmetric_maps_to_high_risk_cap | ✅ | 0.000 |  |
| test_annotate_risk_cap_pct_growth_maps_to_growth_cap | ✅ | 0.000 |  |
| test_annotate_risk_cap_pct_missing_caps_key_degrades_to_none | ✅ | 0.000 |  |
| test_annotate_risk_cap_pct_quality_maps_to_single_stock_cap | ✅ | 0.000 |  |
| test_annotate_risk_cap_pct_unrated_is_none | ✅ | 0.000 |  |
| test_annotate_size_bucket_boundaries_are_inclusive | ✅ | 0.000 |  |
| test_annotate_size_bucket_large | ✅ | 0.000 |  |
| test_annotate_size_bucket_mega | ✅ | 0.000 |  |
| test_annotate_size_bucket_micro | ✅ | 0.000 |  |
| test_annotate_size_bucket_mid | ✅ | 0.000 |  |
| test_annotate_size_bucket_none_when_market_cap_unknown | ✅ | 0.000 |  |
| test_annotate_size_bucket_small | ✅ | 0.000 |  |
| test_rank_by_potential_breaks_full_ties_by_ticker_asc | ✅ | 0.000 |  |
| test_rank_by_potential_breaks_score_ties_by_confidence_desc | ✅ | 0.000 |  |
| test_rank_by_potential_does_not_mutate_input | ✅ | 0.000 |  |
| test_rank_by_potential_is_deterministic | ✅ | 0.000 |  |
| test_rank_by_potential_never_drops_low_confidence_items | ✅ | 0.000 |  |
| test_rank_by_potential_no_min_confidence_tags_nothing | ✅ | 0.000 |  |
| test_rank_by_potential_orders_by_score_desc | ✅ | 0.000 |  |
| test_shortlist_available_components_stats | ✅ | 0.000 |  |
| test_shortlist_default_min_confidence_preserves_current_behavior | ✅ | 0.000 |  |
| test_shortlist_error_placeholder_is_labeled_and_excluded_from_summary | ✅ | 0.000 |  |
| test_shortlist_includes_fixed_note | ✅ | 0.000 |  |
| test_shortlist_is_deterministic | ✅ | 0.000 |  |
| test_shortlist_nothing_is_ever_excluded_from_the_full_ranking | ✅ | 0.000 |  |
| test_shortlist_ranks_and_bounds_by_top_n | ✅ | 0.001 |  |
| test_shortlist_sector_concentration_handles_no_sector_data | ✅ | 0.000 |  |
| test_shortlist_sector_concentration_no_warning_when_balanced | ✅ | 0.000 |  |
| test_shortlist_sector_concentration_warns_when_majority | ✅ | 0.000 |  |
| test_shortlist_size_mix_counts_including_unknown | ✅ | 0.000 |  |
| test_shortlist_summary_covers_the_full_scored_list_beyond_top_n | ✅ | 0.000 |  |
| test_shortlist_threads_min_confidence_to_low_confidence_tag | ✅ | 0.000 |  |
| test_shortlist_top_n_does_not_shrink_below_available_candidates | ✅ | 0.000 |  |
| test_size_bucket_nan_market_cap_is_none_not_micro | ✅ | 0.000 |  |

### test_picker_backtest — 23 tests, 0.04 s

| test | status | seconds | note |
|---|---|---:|---|
| test_better_stock_ranks_first_and_wins_the_backtest | ✅ | 0.003 |  |
| test_custom_weights_isolate_a_single_component | ✅ | 0.001 |  |
| test_disclosures_add_sample_size_warning_below_eight_periods | ✅ | 0.003 |  |
| test_disclosures_always_present_even_with_no_rebalance_dates | ✅ | 0.000 |  |
| test_empty_universe_never_raises_and_reports_zero | ✅ | 0.001 |  |
| test_forward_return_exact_arithmetic | ✅ | 0.001 |  |
| test_forward_return_none_on_empty_series | ✅ | 0.000 |  |
| test_forward_return_none_when_horizon_exceeds_available_history | ✅ | 0.001 |  |
| test_fundamentals_use_filed_date_not_end_date | ✅ | 0.001 |  |
| test_malformed_ticker_data_is_skipped_not_raised | ✅ | 0.002 |  |
| test_momentum_excludes_price_moves_after_d | ✅ | 0.001 |  |
| test_nothing_available_falls_back_to_neutral_fifty | ✅ | 0.000 |  |
| test_only_prices_available_score_equals_momentum | ✅ | 0.001 |  |
| test_proxy_score_at_is_deterministic | ✅ | 0.001 |  |
| test_rating_events_exclude_upgrades_after_d | ✅ | 0.000 |  |
| test_rating_events_outside_trailing_window_are_ignored | ✅ | 0.000 |  |
| test_revision_momentum_at_or_above_min_events_is_not_shrunk | ✅ | 0.000 |  |
| test_revision_momentum_below_min_events_is_shrunk_toward_neutral | ✅ | 0.000 |  |
| test_run_proxy_backtest_is_deterministic | ✅ | 0.011 |  |
| test_run_proxy_backtest_t_stat_matches_helper_at_eight_periods | ✅ | 0.011 |  |
| test_surprises_exclude_earnings_reported_after_d | ✅ | 0.001 |  |
| test_t_stat_manual_formula | ✅ | 0.000 |  |
| test_t_stat_none_below_two_and_zero_variance | ✅ | 0.000 |  |

### test_picker_backtest_report — 1 tests, 0.00 s

| test | status | seconds | note |
|---|---|---:|---|
| test_fetch_fundamentals_never_raises_on_a_malformed_cik_lookup | ✅ | 0.000 |  |

### test_plan — 23 tests, 0.01 s

| test | status | seconds | note |
|---|---|---:|---|
| test_build_plan_growth_profile_with_initial_orders_and_pooling | ✅ | 0.003 |  |
| test_build_plan_rejects_bad_inputs[kwargs0] | ✅ | 0.000 |  |
| test_build_plan_rejects_bad_inputs[kwargs1] | ✅ | 0.000 |  |
| test_build_plan_small_cash_keeps_unallocated_and_warns | ✅ | 0.003 |  |
| test_calendar_handles_month_end_dates | ✅ | 0.000 |  |
| test_calendar_marks_contributions_reviews_and_annual_review | ✅ | 0.000 |  |
| test_contribution_cadence_pools_until_order_is_economic[10-12] | ✅ | 0.000 |  |
| test_contribution_cadence_pools_until_order_is_economic[100-3] | ✅ | 0.000 |  |
| test_contribution_cadence_pools_until_order_is_economic[1000-1] | ✅ | 0.000 |  |
| test_contribution_cadence_pools_until_order_is_economic[150-2] | ✅ | 0.000 |  |
| test_contribution_cadence_pools_until_order_is_economic[24.58-12] | ✅ | 0.000 |  |
| test_contribution_cadence_pools_until_order_is_economic[24.59-12] | ✅ | 0.000 |  |
| test_contribution_cadence_pools_until_order_is_economic[295-1] | ✅ | 0.000 |  |
| test_contribution_cadence_rejects_zero | ✅ | 0.000 |  |
| test_model_portfolios_are_valid_and_sum_to_one | ✅ | 0.003 |  |
| test_suggest_profile_is_conservative_and_deterministic[1-high-cautious] | ✅ | 0.000 |  |
| test_suggest_profile_is_conservative_and_deterministic[10-low-balanced] | ✅ | 0.000 |  |
| test_suggest_profile_is_conservative_and_deterministic[10-medium-growth] | ✅ | 0.000 |  |
| test_suggest_profile_is_conservative_and_deterministic[20-high-growth] | ✅ | 0.000 |  |
| test_suggest_profile_is_conservative_and_deterministic[5-high-balanced] | ✅ | 0.000 |  |
| test_suggest_profile_is_conservative_and_deterministic[5-low-cautious] | ✅ | 0.000 |  |
| test_suggest_profile_is_conservative_and_deterministic[5-medium-balanced] | ✅ | 0.000 |  |
| test_suggest_profile_rejects_unknown_risk | ✅ | 0.000 |  |

### test_plugin — 39 tests, 0.97 s

| test | status | seconds | note |
|---|---|---:|---|
| test_architecture_doc_does_not_overclaim_provider_timeouts | ✅ | 0.001 |  |
| test_buy_emitting_skills_invoke_red_team_before_buy_small | ✅ | 0.000 |  |
| test_category_cap_skills_source_every_cap_from_config | ✅ | 0.000 |  |
| test_claude_md_except_exception_convention_matches_code | ✅ | 0.011 |  |
| test_config_sourcing_skills_use_the_config_tool_not_the_raw_file | ✅ | 0.001 |  |
| test_every_expected_skill_exists_with_description | ✅ | 0.002 |  |
| test_every_skill_states_no_broker_access_and_stays_short | ✅ | 0.001 |  |
| test_guard_allows_local_exports_and_public_data[payload0] | ✅ | 0.041 |  |
| test_guard_allows_local_exports_and_public_data[payload1] | ✅ | 0.040 |  |
| test_guard_allows_local_exports_and_public_data[payload2] | ✅ | 0.042 |  |
| test_guard_allows_local_exports_and_public_data[payload3] | ✅ | 0.039 |  |
| test_guard_allows_local_exports_and_public_data[payload4] | ✅ | 0.041 |  |
| test_guard_allows_local_exports_and_public_data[payload5] | ✅ | 0.044 |  |
| test_guard_allows_urls_with_keyword_as_bare_substring[https://api.example.com/v2/authors/12345] | ✅ | 0.042 |  |
| test_guard_allows_urls_with_keyword_as_bare_substring[https://developer.mozilla.org/en-US/docs/Web/API/Window/sessionStorage] | ✅ | 0.039 |  |
| test_guard_allows_urls_with_keyword_as_bare_substring[https://docs.example.org/whitepaper/tokenomics.pdf] | ✅ | 0.040 |  |
| test_guard_denies_additional_login_surface_paths[https://mybroker.example.com/accedi] | ✅ | 0.046 |  |
| test_guard_denies_additional_login_surface_paths[https://mybroker.example.com/portal/dashboard] | ✅ | 0.040 |  |
| test_guard_denies_additional_login_surface_paths[https://mybroker.example.com/signon] | ✅ | 0.043 |  |
| test_guard_denies_auth_surfaces_and_credentials[payload0] | ✅ | 0.038 |  |
| test_guard_denies_auth_surfaces_and_credentials[payload1] | ✅ | 0.040 |  |
| test_guard_denies_auth_surfaces_and_credentials[payload2] | ✅ | 0.038 |  |
| test_guard_denies_auth_surfaces_and_credentials[payload3] | ✅ | 0.038 |  |
| test_guard_denies_auth_surfaces_and_credentials[payload4] | ✅ | 0.039 |  |
| test_guard_denies_auth_surfaces_and_credentials[payload5] | ✅ | 0.040 |  |
| test_guard_denies_auth_surfaces_and_credentials[payload6] | ✅ | 0.039 |  |
| test_guard_denies_credentials_starting_a_non_first_line[payload0] | ✅ | 0.042 |  |
| test_guard_denies_credentials_starting_a_non_first_line[payload1] | ✅ | 0.041 |  |
| test_guard_denies_url_with_userinfo_credentials | ✅ | 0.055 |  |
| test_guard_tolerates_malformed_input | ✅ | 0.044 |  |
| test_hooks_json_wires_guard_and_banner | ✅ | 0.000 |  |
| test_makefile_install_target_installs_dev_dependencies | ✅ | 0.001 |  |
| test_plugin_and_marketplace_manifests_agree | ✅ | 0.000 |  |
| test_position_review_sell_step_does_not_double_add_the_sold_ticker | ✅ | 0.000 |  |
| test_position_review_sell_step_passes_alternative_price_to_log_decision | ✅ | 0.000 |  |
| test_prd_mvp_tools_list_has_no_nonexistent_compare_position_tool | ✅ | 0.000 |  |
| test_prd_mvp_tools_list_matches_screen_stocks_signature | ✅ | 0.000 |  |
| test_readme_install_command_is_directory_agnostic | ✅ | 0.002 |  |
| test_session_start_matcher_covers_fork_source | ✅ | 0.001 |  |

### test_portfolio_config — 6 tests, 0.01 s

| test | status | seconds | note |
|---|---|---:|---|
| test_example_targets_use_model_portfolio_bucket_names | ✅ | 0.004 |  |
| test_load_portfolio_config_falls_back_to_example_when_default_missing | ✅ | 0.003 |  |
| test_load_portfolio_config_prefers_the_users_own_file_when_present | ✅ | 0.002 |  |
| test_load_portfolio_config_raises_on_missing_explicit_path_without_falling_back | ✅ | 0.001 |  |
| test_load_portfolio_config_reports_as_of_from_file_mtime | ✅ | 0.001 |  |
| test_real_example_config_defines_all_three_stock_category_caps | ✅ | 0.002 |  |

### test_provider_resilience — 10 tests, 0.01 s

| test | status | seconds | note |
|---|---|---:|---|
| test_analyze_stock_degrades_instead_of_crashing_on_yfinance_failure | ✅ | 0.000 |  |
| test_convert_amount_to_eur_degrades_instead_of_crashing_on_ecb_network_failure | ✅ | 0.000 |  |
| test_fx_rates_degrades_instead_of_crashing_on_ecb_network_failure | ✅ | 0.000 |  |
| test_fx_rates_degrades_on_ecb_http_status_error | ✅ | 0.000 |  |
| test_fx_rates_still_returns_rates_when_ecb_is_reachable | ✅ | 0.000 |  |
| test_get_monthly_closes_aligns_tickers_with_different_trading_days | ✅ | 0.006 |  |
| test_get_monthly_closes_isolates_a_ticker_whose_fetch_raises | ✅ | 0.001 |  |
| test_get_monthly_closes_uses_ttl_cache | ✅ | 0.001 |  |
| test_get_stock_snapshot_uses_ttl_cache | ✅ | 0.001 |  |
| test_review_decisions_degrades_price_on_yfinance_rate_limit | ✅ | 0.000 |  |

### test_providers_free_data — 13 tests, 0.01 s

| test | status | seconds | note |
|---|---|---:|---|
| test_default_user_agent_satisfies_sec_fair_access_policy | ✅ | 0.000 |  |
| test_ecb_provider_uses_cache_and_timeout | ✅ | 0.000 |  |
| test_parse_ecb_xml_and_convert | ✅ | 0.000 |  |
| test_parse_ecb_xml_rejects_garbage | ✅ | 0.000 |  |
| test_parse_stooq_csv_and_no_data | ✅ | 0.001 |  |
| test_sec_403_raises_clear_actionable_error | ✅ | 0.000 |  |
| test_sec_provider_resolves_cik_and_sets_user_agent | ✅ | 0.001 |  |
| test_sec_summary_latest_two_years_and_derived_metrics | ✅ | 0.000 |  |
| test_sec_summary_without_us_gaap_facts_reports_everything_missing | ✅ | 0.000 |  |
| test_stooq_monthly_closes_accepts_uppercase_period | ✅ | 0.001 |  |
| test_stooq_monthly_closes_logs_failure_reason | ✅ | 0.002 |  |
| test_stooq_monthly_closes_reports_missing_buckets | ✅ | 0.002 |  |
| test_ttl_cache_expires_with_clock | ✅ | 0.000 |  |

### test_rebalance — 8 tests, 0.00 s

| test | status | seconds | note |
|---|---|---:|---|
| test_cash_never_negative | ✅ | 0.000 |  |
| test_fee_minimum_economic_order | ✅ | 0.000 |  |
| test_no_action_inside_band | ✅ | 0.000 |  |
| test_returned_fee_ratio_never_exceeds_cap_after_cent_rounding | ✅ | 0.000 |  |
| test_targets_must_sum_to_one | ✅ | 0.000 |  |
| test_top_up_never_pushes_a_bucket_beyond_band | ✅ | 0.000 |  |
| test_waterfall_fills_largest_deficit_first_and_never_splits_below_minimum | ✅ | 0.000 |  |
| test_zero_position_bucket_at_or_below_band_is_not_starved | ✅ | 0.000 |  |

### test_replacement — 37 tests, 0.00 s

| test | status | seconds | note |
|---|---|---:|---|
| test_candidate_matching_current_symbol_case_insensitive_still_ignored | ✅ | 0.000 |  |
| test_candidate_matching_current_symbol_never_produces_a_wash_trade | ✅ | 0.000 |  |
| test_hold_when_buy_below_minimum_economic_order | ✅ | 0.000 |  |
| test_hold_when_current_position_has_no_value | ✅ | 0.000 |  |
| test_hold_when_improvement_below_minimum | ✅ | 0.000 |  |
| test_hold_when_roundtrip_fees_too_high | ✅ | 0.000 |  |
| test_propose_sells_empty_when_allow_sells_false | ✅ | 0.000 |  |
| test_propose_sells_never_sells_underweight_or_in_band_buckets | ✅ | 0.000 |  |
| test_propose_sells_rejects_invalid_targets | ✅ | 0.000 |  |
| test_propose_sells_rejects_negative_cash | ✅ | 0.000 |  |
| test_propose_sells_respects_band_width | ✅ | 0.000 |  |
| test_propose_sells_sells_excess_down_to_target_not_below | ✅ | 0.000 |  |
| test_propose_sells_skips_uneconomic_orders | ✅ | 0.000 |  |
| test_real_candidate_named_cash_is_not_confused_with_the_cash_sentinel | ✅ | 0.000 |  |
| test_replace_buy_leg_fee_ratio_never_exceeds_cap_when_replace_happens[1000.0] | ✅ | 0.000 |  |
| test_replace_buy_leg_fee_ratio_never_exceeds_cap_when_replace_happens[10000.0] | ✅ | 0.000 |  |
| test_replace_buy_leg_fee_ratio_never_exceeds_cap_when_replace_happens[2500.0] | ✅ | 0.000 |  |
| test_replace_buy_leg_fee_ratio_never_exceeds_cap_when_replace_happens[500.0] | ✅ | 0.000 |  |
| test_replace_buy_leg_fee_ratio_never_exceeds_cap_when_replace_happens[601.89] | ✅ | 0.000 |  |
| test_replace_buy_leg_rejected_when_true_fee_ratio_would_exceed_the_cap | ✅ | 0.000 |  |
| test_replace_when_improvement_large_and_fees_fine | ✅ | 0.000 |  |
| test_sell_summary_reports_suppressed_count_when_sells_disabled | ✅ | 0.000 |  |
| test_sell_to_cash_requires_a_stricter_gap_than_a_plain_rotation | ✅ | 0.000 |  |
| test_sell_to_cash_when_utility_far_below_cash | ✅ | 0.000 |  |
| test_utility_basic_no_adjustment | ✅ | 0.000 |  |
| test_utility_rejects_out_of_range_inputs[kwargs0] | ✅ | 0.000 |  |
| test_utility_rejects_out_of_range_inputs[kwargs1] | ✅ | 0.000 |  |
| test_utility_rejects_out_of_range_inputs[kwargs2] | ✅ | 0.000 |  |
| test_utility_rejects_out_of_range_inputs[kwargs3] | ✅ | 0.000 |  |
| test_utility_rejects_out_of_range_inputs[kwargs4] | ✅ | 0.000 |  |
| test_utility_rejects_out_of_range_inputs[kwargs5] | ✅ | 0.000 |  |
| test_utility_rejects_out_of_range_inputs[kwargs6] | ✅ | 0.000 |  |
| test_utility_rejects_out_of_range_inputs[kwargs7] | ✅ | 0.000 |  |
| test_utility_risk_penalty_reduces_score | ✅ | 0.000 |  |
| test_utility_scales_with_confidence | ✅ | 0.000 |  |
| test_utility_scales_with_fit_and_thesis_health | ✅ | 0.000 |  |
| test_utility_zero_confidence_is_zero | ✅ | 0.000 |  |

### test_risk — 3 tests, 0.00 s

| test | status | seconds | note |
|---|---|---:|---|
| test_summarize_portfolio_risk_empty_portfolio | ✅ | 0.000 |  |
| test_summarize_portfolio_risk_unleveraged_only | ✅ | 0.000 |  |
| test_summarize_portfolio_risk_with_leveraged_holdings | ✅ | 0.000 |  |

### test_scoring — 3 tests, 0.00 s

| test | status | seconds | note |
|---|---|---:|---|
| test_prd_score_categories_are_all_reachable_in_engine | ✅ | 0.001 |  |
| test_score_is_bounded_and_has_confidence | ✅ | 0.000 |  |
| test_zero_coverage_snapshot_is_flagged_unrated_not_a_real_category | ✅ | 0.000 |  |

### test_scoring_revisions_catalysts — 23 tests, 0.00 s

| test | status | seconds | note |
|---|---|---:|---|
| test_all_none_snapshot_revisions_and_catalysts_unavailable_score_50 | ✅ | 0.000 |  |
| test_analyst_count_of_three_or_more_does_not_shrink | ✅ | 0.000 |  |
| test_analyst_count_of_zero_fully_shrinks_to_neutral | ✅ | 0.000 |  |
| test_catalysts_available_from_filings_flow_alone | ✅ | 0.000 |  |
| test_catalysts_available_from_insider_activity_alone | ✅ | 0.000 |  |
| test_catalysts_earnings_far_away_scores_low | ✅ | 0.000 |  |
| test_catalysts_earnings_proximity_high_score_when_earnings_imminent | ✅ | 0.000 |  |
| test_catalysts_is_mean_of_all_three_sub_indicators_when_present | ✅ | 0.000 |  |
| test_catalysts_negative_days_to_next_earnings_is_clamped_not_over_100 | ✅ | 0.000 |  |
| test_catalysts_reasons_never_imply_direction | ✅ | 0.000 |  |
| test_confidence_rises_less_for_a_single_thin_opinion_than_full_coverage | ✅ | 0.000 |  |
| test_coverage_and_confidence_rise_when_revisions_and_catalysts_present | ✅ | 0.000 |  |
| test_default_weights_unchanged | ✅ | 0.000 |  |
| test_revisions_available_with_single_sub_indicator | ✅ | 0.000 |  |
| test_revisions_is_mean_of_available_sub_indicators | ✅ | 0.000 |  |
| test_revisions_uses_all_documented_sub_indicators | ✅ | 0.000 |  |
| test_score_snapshot_with_revisions_and_catalysts_is_deterministic | ✅ | 0.000 |  |
| test_surprise_streak_feeds_the_revisions_component | ✅ | 0.000 |  |
| test_thin_analyst_count_does_not_shrink_purely_event_based_revisions | ✅ | 0.000 |  |
| test_thin_analyst_count_shrinks_only_the_opinion_based_share | ✅ | 0.000 |  |
| test_thin_analyst_coverage_shrinks_revisions_toward_50_and_flags_reason | ✅ | 0.000 |  |
| test_thin_coverage_with_no_revisions_data_stays_unavailable_no_reason | ✅ | 0.000 |  |
| test_top_level_reasons_list_available_components | ✅ | 0.000 |  |

### test_sec_filings — 23 tests, 0.00 s

| test | status | seconds | note |
|---|---|---:|---|
| test_extract_items_distinguishes_7_from_7a_and_caps_length | ✅ | 0.000 |  |
| test_extract_items_finds_1a_and_7_and_misses_9_gracefully | ✅ | 0.001 |  |
| test_extract_items_strips_scripts_and_styles | ✅ | 0.000 |  |
| test_filing_sections_foreign_filer_with_no_10k_is_readable_not_a_crash | ✅ | 0.000 |  |
| test_filing_sections_happy_path_has_provenance_and_sections | ✅ | 0.000 |  |
| test_filing_sections_unknown_ticker_is_readable_not_a_crash | ✅ | 0.000 |  |
| test_filing_url_strips_dashes_from_accession | ✅ | 0.000 |  |
| test_insider_activity_accepts_date_object_as_of | ✅ | 0.000 |  |
| test_insider_activity_confidence_degrades_when_recent_window_is_shallow | ✅ | 0.000 |  |
| test_insider_activity_confidence_stays_high_when_window_fully_covered | ✅ | 0.000 |  |
| test_insider_activity_counts_form4_within_window_inclusive | ✅ | 0.000 |  |
| test_insider_activity_default_as_of_uses_today_without_crashing | ✅ | 0.000 |  |
| test_insider_activity_raises_clear_error_on_non_dict_submissions_payload | ✅ | 0.000 |  |
| test_insider_activity_rejects_non_positive_days | ✅ | 0.000 |  |
| test_insider_activity_unknown_ticker_is_readable_not_a_crash | ✅ | 0.000 |  |
| test_list_filings_default_forms_excludes_form4_and_respects_limit | ✅ | 0.000 |  |
| test_list_filings_filters_by_form_and_sorts_newest_first | ✅ | 0.000 |  |
| test_list_filings_raises_clear_error_on_non_dict_submissions_payload | ✅ | 0.001 |  |
| test_list_filings_rejects_non_positive_limit | ✅ | 0.000 |  |
| test_list_filings_unknown_ticker_returns_empty_not_an_error | ✅ | 0.000 |  |
| test_rate_limiter_rejects_non_positive_rate | ✅ | 0.000 |  |
| test_rate_limiter_sleeps_only_when_calls_are_too_close | ✅ | 0.000 |  |
| test_uses_sec_edgar_provider_user_agent | ✅ | 0.000 |  |

### test_server_backtest_plan_zero_weight — 1 tests, 0.00 s

| test | status | seconds | note |
|---|---|---:|---|
| test_backtest_plan_degrades_when_usable_buckets_sum_to_zero_weight | ✅ | 0.000 |  |

### test_server_capital_auction — 5 tests, 4.43 s

| test | status | seconds | note |
|---|---|---:|---|
| test_capital_auction_raises_tool_error_on_ambiguous_instruments_config | ✅ | 0.001 |  |
| test_corrupted_theses_json_raises_tool_error_not_a_raw_crash | ✅ | 0.014 |  |
| test_map_holdings_to_targets_raises_tool_error_on_ambiguous_instruments_config | ✅ | 0.000 |  |
| test_negative_holding_value_never_crashes_the_auction | ✅ | 4.415 |  |
| test_stock_cap_defaults_conservatively_when_risk_limits_missing | ✅ | 0.001 |  |

### test_server_edge_quality — 6 tests, 4.60 s

| test | status | seconds | note |
|---|---|---:|---|
| test_analyze_stock_evidence_uses_pre_override_snapshot_for_the_cross_check | ✅ | 4.595 |  |
| test_decision_quality_surfaces_price_provenance | ✅ | 0.000 |  |
| test_investor_relations_links_no_website_carries_full_provenance | ✅ | 0.000 |  |
| test_investor_relations_links_yfinance_failure_carries_full_provenance | ✅ | 0.000 |  |
| test_log_decision_then_decision_quality_applies_bucket_rubric | ✅ | 0.002 |  |
| test_personal_edge_surfaces_price_provenance | ✅ | 0.001 |  |

### test_server_fee_pass_through — 3 tests, 0.00 s

| test | status | seconds | note |
|---|---|---:|---|
| test_backtest_plan_threads_variable_fee_pct_into_fee_model | ✅ | 0.001 |  |
| test_generate_order_plan_threads_variable_fee_pct_into_fee_model | ✅ | 0.000 |  |
| test_rebalance_portfolio_threads_variable_fee_pct_into_fee_model | ✅ | 0.000 |  |

### test_server_picker — 29 tests, 2.52 s

| test | status | seconds | note |
|---|---|---:|---|
| test_analyze_stock_exposes_estimates_key | ✅ | 0.000 |  |
| test_annual_fundamental_rows_keeps_earliest_filed_per_end | ✅ | 0.000 |  |
| test_annual_fundamental_rows_scans_every_tag_without_early_break | ✅ | 0.001 |  |
| test_backtest_picker_happy_path_skips_ticker_with_no_price_history | ✅ | 0.007 |  |
| test_backtest_picker_reports_missing_benchmark | ✅ | 0.000 |  |
| test_discover_stocks_default_mode_is_universe_and_forwards_styles_sizes | ✅ | 0.000 |  |
| test_discover_stocks_preset_mode_matches_old_behaviour | ✅ | 0.000 |  |
| test_discover_stocks_unknown_mode_raises_tool_error | ✅ | 0.000 |  |
| test_discover_stocks_unknown_preset_still_raises_tool_error_regardless_of_mode | ✅ | 0.000 |  |
| test_enrich_snapshot_degrades_to_none_and_notes_when_everything_fails | ✅ | 0.000 |  |
| test_enrich_snapshot_does_not_raise_a_lower_original_confidence | ✅ | 0.000 |  |
| test_enrich_snapshot_fills_revisions_and_catalysts_fields_on_success | ✅ | 0.000 |  |
| test_enrich_snapshot_folds_estimates_confidence_into_provenance_confidence | ✅ | 0.000 |  |
| test_enrich_snapshot_no_cik_never_calls_insider_or_8k | ✅ | 0.000 |  |
| test_fetch_asfiled_fundamentals_degrades_to_empty_on_fetch_error | ✅ | 0.001 |  |
| test_fetch_asfiled_fundamentals_degrades_to_empty_without_cik | ✅ | 0.001 |  |
| test_fetch_asfiled_fundamentals_merges_revenue_and_eps_by_end | ✅ | 0.001 |  |
| test_map_holdings_resolver_adds_ticker_only_on_success | ✅ | 0.001 |  |
| test_map_holdings_resolver_failure_degrades_silently | ✅ | 0.000 |  |
| test_map_holdings_resolver_skipped_when_symbol_already_present | ✅ | 0.001 |  |
| test_map_holdings_without_resolver_is_byte_for_byte_unchanged | ✅ | 0.001 |  |
| test_rank_candidates_min_confidence_surfaces_low_confidence_tag | ✅ | 0.000 |  |
| test_rank_candidates_ranks_every_ticker_without_excluding_anything | ✅ | 0.000 |  |
| test_rank_candidates_with_path_annotates_diversification | ✅ | 0.001 |  |
| test_resolve_isins_attaches_yf_ticker_when_exch_code_given | ✅ | 0.000 |  |
| test_resolve_isins_does_not_leak_stale_errors_from_an_unrelated_prior_call | ✅ | 2.507 |  |
| test_resolve_isins_no_exch_code_never_invents_a_yf_ticker | ✅ | 0.000 |  |
| test_resolve_isins_raises_tool_error_on_http_failure | ✅ | 0.002 |  |
| test_screen_stocks_reports_error_without_crashing_and_does_not_need_estimates_mock | ✅ | 0.000 |  |

### test_server_portfolio_config — 2 tests, 0.01 s

| test | status | seconds | note |
|---|---|---:|---|
| test_get_portfolio_config_raises_tool_error_on_missing_explicit_path | ✅ | 0.002 |  |
| test_get_portfolio_config_returns_the_repo_example_by_default | ❌ | 0.005 | assert False is True |

### test_server_portfolio_exposure — 1 tests, 0.00 s

| test | status | seconds | note |
|---|---|---:|---|
| test_portfolio_exposure_surfaces_sector_provenance | ✅ | 0.001 |  |

### test_server_propose_replacement — 8 tests, 0.01 s

| test | status | seconds | note |
|---|---|---:|---|
| test_cash_named_candidate_survives_the_full_tool_wiring | ✅ | 0.000 |  |
| test_current_holding_fit_excludes_itself_from_the_exposure_snapshot | ✅ | 0.008 |  |
| test_out_of_range_score_for_a_candidate_lands_in_candidate_errors_not_a_crash | ✅ | 0.000 |  |
| test_out_of_range_score_for_current_symbol_raises_tool_error_not_a_crash | ✅ | 0.000 |  |
| test_replace_buy_is_capped_by_configured_single_stock_weight | ✅ | 0.002 |  |
| test_replace_buy_within_the_single_stock_cap_still_goes_through | ✅ | 0.001 |  |
| test_result_surfaces_confidence_for_current_and_candidates | ✅ | 0.000 |  |
| test_score_symbol_for_replacement_wires_theme_caps_from_config | ✅ | 0.000 |  |

### test_server_schema_descriptions — 4 tests, 0.00 s

| test | status | seconds | note |
|---|---|---:|---|
| test_allocate_cash_schema_documents_current_values_and_targets_units | ✅ | 0.000 |  |
| test_backtest_plan_schema_documents_targets_units | ✅ | 0.000 |  |
| test_generate_order_plan_schema_documents_current_values_and_targets_units | ✅ | 0.000 |  |
| test_rebalance_portfolio_schema_documents_current_values_and_targets_units | ✅ | 0.000 |  |

### test_server_snapshots_opportunity — 15 tests, 0.02 s

| test | status | seconds | note |
|---|---|---:|---|
| test_capital_auction_candidates_for_ledger_bucket_with_no_instrument_has_no_price_symbol | ✅ | 0.001 |  |
| test_capital_auction_candidates_for_ledger_never_invents_a_missing_bucket_price | ✅ | 0.001 |  |
| test_capital_auction_candidates_for_ledger_prices_stock_bucket_and_cash | ✅ | 0.001 |  |
| test_compare_snapshots_raises_tool_error_on_missing_dates | ✅ | 0.002 |  |
| test_compare_snapshots_raises_tool_error_when_latest_snapshot_is_corrupted | ✅ | 0.002 |  |
| test_compare_snapshots_raises_tool_error_when_store_is_empty | ✅ | 0.001 |  |
| test_list_and_compare_snapshots_round_trip | ✅ | 0.003 |  |
| test_log_decision_candidates_defaults_to_empty_list | ✅ | 0.001 |  |
| test_log_decision_passes_candidates_through_to_the_ledger | ✅ | 0.001 |  |
| test_review_decisions_opportunity_marks_candidate_unmeasurable_on_price_failure | ✅ | 0.001 |  |
| test_review_decisions_opportunity_section_measures_regret_and_skips_cash_pricing | ✅ | 0.001 |  |
| test_save_portfolio_snapshot_maps_buckets_and_defaults_as_of | ✅ | 0.003 |  |
| test_save_portfolio_snapshot_prefers_investment_plan_targets_over_config | ✅ | 0.002 |  |
| test_save_portfolio_snapshot_raises_tool_error_on_bad_export_path | ✅ | 0.001 |  |
| test_save_portfolio_snapshot_refuses_overwrite_without_force | ✅ | 0.002 |  |

### test_server_tool_errors — 16 tests, 0.01 s

| test | status | seconds | note |
|---|---|---:|---|
| test_allocate_cash_raises_tool_error_with_message_when_targets_dont_sum_to_one | ✅ | 0.001 |  |
| test_build_investment_plan_raises_tool_error_on_invalid_risk_tolerance | ✅ | 0.004 |  |
| test_build_investment_plan_raises_tool_error_on_invalid_start_date | ✅ | 0.001 |  |
| test_build_investment_plan_raises_tool_error_on_negative_cash_now | ✅ | 0.001 |  |
| test_company_facts_degrades_instead_of_crashing_on_sec_http_error | ✅ | 0.000 |  |
| test_decision_quality_raises_tool_error_on_corrupted_ledger_line | ✅ | 0.002 |  |
| test_discover_stocks_raises_tool_error_on_unknown_preset | ✅ | 0.000 |  |
| test_filing_sections_degrades_instead_of_crashing_on_malformed_sec_json | ✅ | 0.000 |  |
| test_generate_order_plan_raises_tool_error_with_message_when_targets_dont_sum_to_one | ✅ | 0.000 |  |
| test_log_decision_raises_tool_error_on_replayed_identical_id | ✅ | 0.002 |  |
| test_parse_portfolio_export_tool_raises_tool_error_on_unmappable_columns | ✅ | 0.001 |  |
| test_parse_portfolio_export_tool_raises_tool_error_with_path_on_missing_file | ✅ | 0.001 |  |
| test_personal_edge_raises_tool_error_on_corrupted_ledger_line | ✅ | 0.001 |  |
| test_portfolio_risk_tool_raises_tool_error_with_path_on_missing_file | ✅ | 0.000 |  |
| test_rebalance_portfolio_raises_tool_error_with_message_when_targets_dont_sum_to_one | ✅ | 0.000 |  |
| test_review_decisions_raises_tool_error_on_corrupted_ledger_line | ✅ | 0.001 |  |

### test_server_tools — 2 tests, 1.34 s

| test | status | seconds | note |
|---|---|---:|---|
| test_tools_list_over_stdio_includes_every_new_tool | ✅ | 0.701 |  |
| test_tools_list_over_stdio_still_includes_every_pre_existing_tool | ✅ | 0.639 |  |

### test_snapshots — 20 tests, 0.03 s

| test | status | seconds | note |
|---|---|---:|---|
| test_diff_snapshots_aggregates_duplicate_isin_instead_of_dropping_a_lot | ✅ | 0.002 |  |
| test_diff_snapshots_matches_by_isin_then_name_and_aggregates_buckets | ✅ | 0.002 |  |
| test_diff_snapshots_no_buckets_yields_no_bucket_change | ✅ | 0.002 |  |
| test_latest_snapshot_none_when_no_snapshots_exist | ✅ | 0.001 |  |
| test_latest_snapshot_returns_most_recent | ✅ | 0.002 |  |
| test_list_snapshots_sorted | ✅ | 0.002 |  |
| test_load_snapshot_corrupted_file_raises_clear_value_error | ✅ | 0.001 |  |
| test_load_snapshot_missing_date_raises_file_not_found | ✅ | 0.001 |  |
| test_load_snapshot_rejects_nan_total_value | ✅ | 0.001 |  |
| test_load_snapshot_schema_mismatch_raises_clear_value_error | ✅ | 0.002 |  |
| test_save_and_load_roundtrip | ✅ | 0.002 |  |
| test_save_force_overwrites_existing_date | ✅ | 0.002 |  |
| test_save_refuses_to_overwrite_existing_date | ✅ | 0.001 |  |
| test_save_rejects_non_iso_date | ✅ | 0.001 |  |
| test_save_snapshot_concurrent_writes_for_the_same_date_are_mutually_exclusive | ✅ | 0.002 |  |
| test_save_snapshot_rejects_infinite_leverage | ✅ | 0.001 |  |
| test_save_snapshot_rejects_nan_market_price | ✅ | 0.001 |  |
| test_save_snapshot_rejects_nan_market_value | ✅ | 0.001 |  |
| test_save_snapshot_rejects_nan_quantity | ✅ | 0.001 |  |
| test_snapshot_path_rejects_non_iso_as_of_to_prevent_path_traversal | ✅ | 0.001 |  |

### test_thesis — 33 tests, 0.02 s

| test | status | seconds | note |
|---|---|---:|---|
| test_broken_at_exactly_half_boundary | ✅ | 0.000 |  |
| test_broken_when_half_or_more_of_checkable_trip | ✅ | 0.000 |  |
| test_check_thesis_blackout_after_broken_reports_unchanged_not_improved | ✅ | 0.002 |  |
| test_check_thesis_finds_thesis_saved_with_stray_whitespace | ✅ | 0.001 |  |
| test_check_thesis_full_flow_appends_history_and_reports_delta | ✅ | 0.002 |  |
| test_check_thesis_strips_whitespace_from_lookup_symbol | ✅ | 0.002 |  |
| test_check_thesis_unknown_symbol_raises | ✅ | 0.002 |  |
| test_check_thesis_worsened_delta | ✅ | 0.002 |  |
| test_evaluate_thesis_is_pure_same_inputs_same_output_and_no_mutation | ✅ | 0.000 |  |
| test_infinite_threshold_is_rejected_by_falsifier_validation | ✅ | 0.000 |  |
| test_invalid_op_rejected | ✅ | 0.000 |  |
| test_load_theses_raises_clear_value_error_on_corrupted_json | ✅ | 0.001 |  |
| test_load_theses_raises_clear_value_error_on_invalid_schema | ✅ | 0.001 |  |
| test_load_theses_returns_empty_dict_when_file_missing | ✅ | 0.001 |  |
| test_nan_metric_is_treated_as_unavailable_not_as_did_not_trip | ✅ | 0.000 |  |
| test_nan_threshold_is_rejected_by_falsifier_validation | ✅ | 0.000 |  |
| test_partial_unavailable_metrics_only_count_available_ones | ✅ | 0.000 |  |
| test_save_and_load_roundtrip | ✅ | 0.001 |  |
| test_save_thesis_strips_whitespace_from_symbol | ✅ | 0.001 |  |
| test_save_thesis_upserts_by_symbol | ✅ | 0.002 |  |
| test_stable_when_no_falsifier_trips_and_no_history | ✅ | 0.000 |  |
| test_status_delta_blackout_after_broken_is_not_improved | ✅ | 0.000 |  |
| test_status_delta_blackout_after_weakening_is_not_improved | ✅ | 0.000 |  |
| test_status_delta_unverifiable_after_stable_is_still_worsened | ✅ | 0.000 |  |
| test_strengthening_requires_all_previously_tripped_falsifiers_to_be_reverified | ✅ | 0.000 |  |
| test_strengthening_still_applies_when_all_previously_tripped_metrics_are_reverified | ✅ | 0.000 |  |
| test_strengthening_when_previous_check_had_trips_and_now_none_trip | ✅ | 0.000 |  |
| test_theses_json_is_plain_readable_json | ✅ | 0.001 |  |
| test_theses_path_creates_home_directory | ✅ | 0.001 |  |
| test_unverifiable_when_no_metric_available | ✅ | 0.000 |  |
| test_weakening_when_fewer_than_half_of_checkable_trip | ✅ | 0.000 |  |
| test_write_theses_failure_never_corrupts_existing_file | ✅ | 0.002 |  |
| test_write_theses_is_atomic_no_leftover_temp_file | ✅ | 0.001 |  |

### test_yahooquery_fallback — 12 tests, 0.00 s

| test | status | seconds | note |
|---|---|---:|---|
| test_fallback_all_providers_failing_raises_with_every_attempt_listed | ✅ | 0.000 |  |
| test_fallback_get_monthly_closes_all_empty_returns_empty_frame_with_missing | ✅ | 0.000 |  |
| test_fallback_get_monthly_closes_uses_first_provider_with_non_empty_data | ✅ | 0.001 |  |
| test_fallback_min_price_required_false_accepts_first_result_even_without_price | ✅ | 0.000 |  |
| test_fallback_picks_second_provider_when_first_has_no_price | ✅ | 0.000 |  |
| test_fallback_secondary_sources_accumulate_across_multiple_failed_attempts | ✅ | 0.000 |  |
| test_yahooquery_provider_caches_repeat_lookups | ✅ | 0.000 |  |
| test_yahooquery_provider_maps_fields_from_modules | ✅ | 0.001 |  |
| test_yahooquery_provider_missing_price_lowers_confidence_and_reports_missing | ✅ | 0.000 |  |
| test_yahooquery_provider_nan_values_become_none_not_missing | ✅ | 0.000 |  |
| test_yahooquery_provider_requires_ticker | ✅ | 0.000 |  |
| test_yahooquery_provider_wraps_library_exceptions_as_value_error | ✅ | 0.000 |  |

### test_yfinance_estimates — 38 tests, 0.02 s

| test | status | seconds | note |
|---|---|---:|---|
| test_coerce_date_handles_multiple_input_types | ✅ | 0.003 |  |
| test_consensus_score_codomain_is_bounded_for_any_recommendation_mix[0-0-0-5-10] | ✅ | 0.001 |  |
| test_consensus_score_codomain_is_bounded_for_any_recommendation_mix[0-0-10-0-0] | ✅ | 0.001 |  |
| test_consensus_score_codomain_is_bounded_for_any_recommendation_mix[1-0-0-0-0] | ✅ | 0.001 |  |
| test_consensus_score_codomain_is_bounded_for_any_recommendation_mix[10-5-3-1-0] | ✅ | 0.001 |  |
| test_consensus_score_codomain_is_bounded_for_any_recommendation_mix[3-3-3-3-3] | ✅ | 0.001 |  |
| test_consensus_score_matches_engine_consumer_scale | ✅ | 0.001 |  |
| test_consensus_score_never_exceeds_plus_minus_one | ✅ | 0.001 |  |
| test_derive_revision_momentum_arithmetic_and_window_filtering | ✅ | 0.000 |  |
| test_derive_revision_momentum_ignores_future_events_beyond_as_of | ✅ | 0.000 |  |
| test_derive_revision_momentum_no_events_returns_all_none | ✅ | 0.000 |  |
| test_derive_revision_momentum_zero_or_missing_prior_pt_excluded_from_average | ✅ | 0.000 |  |
| test_f_handles_nan_inf_and_none | ✅ | 0.000 |  |
| test_fetch_estimates_all_missing_but_data_present_and_empty | ✅ | 0.000 |  |
| test_fetch_estimates_all_sources_raise_degrades_gracefully_never_crashes | ✅ | 0.000 |  |
| test_fetch_estimates_analyst_count_falls_back_to_recommendations_total | ✅ | 0.001 |  |
| test_fetch_estimates_different_as_of_bypasses_cache | ✅ | 0.000 |  |
| test_fetch_estimates_does_not_cache_a_fully_failed_fetch | ✅ | 0.000 |  |
| test_fetch_estimates_empty_ticker_raises | ✅ | 0.000 |  |
| test_fetch_estimates_happy_path_all_fields_available | ✅ | 0.002 |  |
| test_fetch_estimates_malformed_calendar_scalar_earnings_date_degrades_not_crashes | ✅ | 0.000 |  |
| test_fetch_estimates_nan_values_become_none | ✅ | 0.001 |  |
| test_fetch_estimates_normalizes_and_strips_ticker | ✅ | 0.000 |  |
| test_fetch_estimates_partial_failure_isolates_the_failing_group | ✅ | 0.001 |  |
| test_fetch_estimates_partial_success_is_still_cached | ✅ | 0.000 |  |
| test_fetch_estimates_uses_cache_on_second_call | ✅ | 0.000 |  |
| test_fetch_estimates_zero_or_negative_base_blocks_growth | ✅ | 0.001 |  |
| test_fetch_estimates_zero_target_or_zero_revisions_return_none | ✅ | 0.000 |  |
| test_fetch_rating_events_a_bad_nat_grade_date_drops_only_that_row_not_the_whole_history | ✅ | 0.001 |  |
| test_fetch_rating_events_empty_dataframe_for_european_ticker | ✅ | 0.000 |  |
| test_fetch_rating_events_empty_ticker_raises | ✅ | 0.000 |  |
| test_fetch_rating_events_filters_to_as_of_and_sorts_newest_first | ✅ | 0.001 |  |
| test_fetch_rating_events_none_dataframe | ✅ | 0.000 |  |
| test_fetch_rating_events_raising_returns_empty_not_an_exception | ✅ | 0.000 |  |
| test_growth_1y_missing_period_or_column_returns_none | ✅ | 0.000 |  |
| test_next_earnings_date_missing_or_empty_calendar | ✅ | 0.000 |  |
| test_next_earnings_date_none_when_calendar_has_only_past_dates | ✅ | 0.000 |  |
| test_next_earnings_date_picks_earliest_future_date_ignoring_past_ones | ✅ | 0.000 |  |

### test_yfinance_surprises — 16 tests, 0.01 s

| test | status | seconds | note |
|---|---|---:|---|
| test_derive_surprise_stats_as_of_filters_out_a_backfilled_future_row | ✅ | 0.000 |  |
| test_derive_surprise_stats_empty_input | ✅ | 0.000 |  |
| test_derive_surprise_stats_streak_stops_at_first_non_positive_from_the_end | ✅ | 0.000 |  |
| test_fetch_surprise_history_computes_confidence_06_and_derived_stats_at_8_quarters | ✅ | 0.001 |  |
| test_fetch_surprise_history_confidence_04_for_4_to_7_quarters | ✅ | 0.000 |  |
| test_fetch_surprise_history_deduplicates_repeated_earnings_date_rows | ✅ | 0.001 |  |
| test_fetch_surprise_history_empty_result_is_labelled_not_fabricated | ✅ | 0.000 |  |
| test_fetch_surprise_history_excludes_future_and_unreported_rows | ✅ | 0.001 |  |
| test_fetch_surprise_history_handles_exception_without_crashing | ✅ | 0.000 |  |
| test_fetch_surprise_history_nan_surprise_counts_toward_quarters_but_not_mean | ✅ | 0.000 |  |
| test_fetch_surprise_history_negative_caches_a_failed_fetch_briefly | ✅ | 0.000 |  |
| test_fetch_surprise_history_parses_and_sorts_tz_aware_rows | ✅ | 0.002 |  |
| test_fetch_surprise_history_rejects_blank_ticker | ✅ | 0.000 |  |
| test_fetch_surprise_history_returns_none_derived_stats_below_4_quarters | ✅ | 0.000 |  |
| test_fetch_surprise_history_tz_naive_index_also_parses | ✅ | 0.001 |  |
| test_fetch_surprise_history_uses_ttl_cache_across_different_as_of | ✅ | 0.001 |  |
