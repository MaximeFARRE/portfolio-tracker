"""Full functional test for bourse_advanced_analytics with person_id=3."""
import sqlite3
from services.bourse_advanced_analytics import (
    get_risk_return_payload,
    get_var_es_payload,
    get_correlation_payload,
    get_risk_contribution_payload,
    get_efficient_frontier_payload,
    get_benchmark_comparison_payload,
)

conn = sqlite3.connect("patrimoine.db")
conn.row_factory = sqlite3.Row
pid = 3
print(f"Testing with person_id={pid} (Maxime - 217 snapshots, 25 assets)")

print("\n=== 1. Risk/Return ===")
rr = get_risk_return_payload(conn, pid)
if "error" in rr:
    print(f"  ERROR: {rr['error']}")
else:
    print(f"  CAGR       = {rr.get('cagr_pct')}%")
    print(f"  Vol (ann)  = {rr.get('volatility_ann_pct')}%")
    print(f"  Sharpe     = {rr.get('sharpe')}")
    print(f"  Beta       = {rr.get('beta')}")
    print(f"  MaxDD      = {rr.get('max_drawdown_pct')}%")
    print(f"  Recovery   = {rr.get('recovery_days')} days")
    print(f"  Data pts   = {rr.get('data_points')}")

print("\n=== 2. Correlation ===")
corr = get_correlation_payload(conn, pid)
if "error" in corr:
    print(f"  ERROR: {corr['error']}")
else:
    print(f"  Avg corr = {corr.get('avg_correlation')}")
    print(f"  Div ratio = {corr.get('diversification_ratio')}")
    print(f"  N assets = {corr.get('n_assets')}")
    for a, b, c in corr.get("top_correlated_pairs", [])[:3]:
        print(f"  Top pair: {a}/{b} = {c}")

print("\n=== 3. Risk Contribution ===")
rc = get_risk_contribution_payload(conn, pid)
if "error" in rc:
    print(f"  ERROR: {rc['error']}")
else:
    print(f"  Portfolio vol (ann) = {rc.get('portfolio_vol_ann_pct')}%")
    for _, r in rc["contributions"].head(5).iterrows():
        print(f"  {r['ticker']}: W={r['weight_pct']}%, Risk={r['risk_contrib_pct']}%")

print("\n=== 4. VaR/ES ===")
var = get_var_es_payload(conn, pid)
if "error" in var:
    print(f"  ERROR: {var['error']}")
else:
    print(f"  VaR 95%  = {var.get('var_95_pct')}%  ({var.get('var_95_eur')} EUR)")
    print(f"  VaR 99%  = {var.get('var_99_pct')}%  ({var.get('var_99_eur')} EUR)")
    print(f"  ES 95%   = {var.get('es_95_pct')}%")
    print(f"  Method   = {var.get('method')}")
    print(f"  N obs    = {var.get('n_observations')}")

print("\n=== 5. Efficient Frontier ===")
ef = get_efficient_frontier_payload(conn, pid)
if "error" in ef:
    print(f"  ERROR: {ef['error']}")
else:
    print(f"  Current  = Vol {ef['current_portfolio']['vol']}% / Ret {ef['current_portfolio']['ret']}%")
    print(f"  MinVar   = Vol {ef['min_variance']['vol']}% / Ret {ef['min_variance']['ret']}%")
    print(f"  MaxSharpe= Vol {ef['max_sharpe']['vol']}% / Ret {ef['max_sharpe']['ret']}%")
    print(f"  Frontier = {len(ef.get('frontier_points', []))} points")

print("\n=== 6. Benchmark Comparison ===")
bc = get_benchmark_comparison_payload(conn, pid)
if "error" in bc:
    print(f"  ERROR: {bc['error']}")
else:
    print(f"  Ptf ret  = {bc.get('portfolio_return_ann_pct')}%/year")
    print(f"  Bench ret= {bc.get('benchmark_return_ann_pct')}%/year")
    print(f"  Alpha    = {bc.get('alpha_pct')}%")
    print(f"  TrackErr = {bc.get('tracking_error_pct')}%")
    print(f"  N weeks  = {bc.get('n_weeks')}")

conn.close()
print("\n=== ALL 6 TESTS COMPLETED ===")
