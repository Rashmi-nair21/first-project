"""Portfolio Projector: a Monte Carlo projection of a stock and ETF portfolio.

Runs thousands of random "possible futures" for your holdings, month by month,
and reports the range of values your portfolio could reach.

Usage:
    python3 portfolio_projector.py                        # uses the example portfolio
    python3 portfolio_projector.py portfolio.csv          # uses your holdings
    python3 portfolio_projector.py portfolio.csv --years 30 --monthly 800 --goal 500000
    python3 portfolio_projector.py --help                 # lists every option

The CSV needs columns `ticker,value`. You can add `return` and `vol` columns
(in percent) to override the default assumptions for any holding.

The default assumptions are rough long-run estimates, not predictions.
This is an educational tool, not financial advice.
"""

import argparse
import csv
import math
import random
import sys

# Long-run assumptions for common tickers:
# ticker: (expected annual return %, annual volatility %, correlation with the US stock market)
PRESETS = {
    "VOO": (8, 16, 0.99), "SPY": (8, 16, 0.99), "IVV": (8, 16, 0.99),
    "VTI": (8, 16.5, 1.0), "SCHB": (8, 16.5, 1.0), "ITOT": (8, 16.5, 1.0),
    "QQQ": (9, 22, 0.9), "QQQM": (9, 22, 0.9), "VUG": (8.5, 19, 0.95), "VTV": (7.5, 15, 0.9),
    "SCHD": (7.5, 15, 0.88), "VIG": (7.5, 14.5, 0.93), "VYM": (7.5, 15, 0.88),
    "IWM": (8.5, 21, 0.85), "VB": (8.5, 20, 0.88), "VO": (8, 18, 0.93),
    "VXUS": (7.5, 17, 0.85), "VEA": (7.5, 17, 0.85), "IXUS": (7.5, 17, 0.85), "EFA": (7.5, 17, 0.85),
    "VWO": (8, 21, 0.72), "IEMG": (8, 21, 0.72), "VT": (7.8, 16, 0.96),
    "BND": (4.5, 6, 0.15), "AGG": (4.5, 6, 0.15), "BNDX": (4, 5, 0.1), "TLT": (4.5, 14, -0.1),
    "SHY": (4, 2, 0.0), "SGOV": (4, 0.5, 0.0), "BIL": (4, 0.5, 0.0), "TIP": (4.2, 6, 0.2),
    "VNQ": (7, 20, 0.75), "GLD": (5, 15, 0.05), "IAU": (5, 15, 0.05), "ARKK": (9, 45, 0.75),
    "AAPL": (9, 28, 0.7), "MSFT": (9, 25, 0.75), "NVDA": (11, 50, 0.62), "AMZN": (9.5, 32, 0.68),
    "GOOGL": (9, 29, 0.68), "GOOG": (9, 29, 0.68), "META": (9.5, 38, 0.62), "TSLA": (10, 58, 0.5),
    "BRK.B": (8, 18, 0.8), "JPM": (8.5, 25, 0.7), "JNJ": (6.5, 16, 0.5), "KO": (6.5, 16, 0.5),
    "V": (8.5, 22, 0.72), "COST": (8.5, 22, 0.6), "AMD": (10.5, 52, 0.55),
}
# Used for any ticker not listed above (a typical single stock)
STOCK_DEFAULT = (8, 30, 0.6)

# Used when you don't pass a CSV file
EXAMPLE_PORTFOLIO = [("VOO", 12000), ("QQQ", 5000), ("VXUS", 4000), ("BND", 3000), ("AAPL", 2000), ("NVDA", 1500)]


def make_holding(ticker, value, expected_return=None, volatility=None):
    """Build a holding, filling in default assumptions for anything not given."""
    ticker = ticker.strip().upper()
    default_return, default_vol, correlation = PRESETS.get(ticker, STOCK_DEFAULT)
    return {
        "ticker": ticker,
        "value": float(value),
        "return": default_return if expected_return is None else float(expected_return),
        "vol": default_vol if volatility is None else float(volatility),
        "corr": correlation,
    }


def load_portfolio(path):
    """Read holdings from a CSV file with columns ticker,value and optional return,vol."""
    holdings = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            row = {key.strip().lower(): (val or "").strip() for key, val in row.items() if key}
            if not row.get("ticker"):
                continue
            holdings.append(make_holding(
                row["ticker"],
                row.get("value") or 0,
                row.get("return") or None,
                row.get("vol") or None,
            ))
    if not holdings:
        sys.exit(f"No holdings found in {path}. It needs a header row like: ticker,value")
    return holdings


def percentile(sorted_values, p):
    """Return the value p of the way up a sorted list (p=0.5 is the median)."""
    index = min(len(sorted_values) - 1, int(p * len(sorted_values)))
    return sorted_values[index]


def simulate(holdings, years, monthly, inflation, real_dollars, rebalance, fee, sims, seed):
    """Run the Monte Carlo simulation.

    Returns a dict with portfolio percentiles for each year, plus per-holding results.
    """
    rng = random.Random(seed)  # same seed -> same results every run
    n = len(holdings)
    months = years * 12
    start_total = sum(h["value"] for h in holdings)
    weights = [h["value"] / start_total if start_total > 0 else 1 / n for h in holdings]

    # Convert yearly assumptions into monthly steps.
    # The "- vol**2 / 2" part is volatility drag: big swings lower the typical outcome.
    drift = [(math.log(1 + h["return"] / 100) - fee - (h["vol"] / 100) ** 2 / 2) / 12 for h in holdings]
    monthly_vol = [h["vol"] / 100 / math.sqrt(12) for h in holdings]
    # How strongly each holding follows the shared market factor
    market_link = [max(-1.0, min(1.0, h["corr"])) for h in holdings]
    own_luck = [math.sqrt(1 - a * a) for a in market_link]

    # In today's-dollar mode, contributions rise with inflation so they stay constant in real terms
    contribution = [0.0] + [
        monthly * ((1 + inflation / 100) ** (m / 12) if real_dollars else 1)
        for m in range(1, months + 1)
    ]
    total_contributed_nominal = start_total + sum(contribution)

    totals_by_year = [[] for _ in range(years + 1)]  # totals_by_year[y] = one total per simulation
    ending_by_holding = [[] for _ in range(n)]

    for _ in range(sims):
        values = [h["value"] for h in holdings]
        totals_by_year[0].append(start_total)
        for m in range(1, months + 1):
            market = rng.gauss(0, 1)  # one shared "market mood" this month
            for i in range(n):
                shock = market_link[i] * market + own_luck[i] * rng.gauss(0, 1)
                values[i] = values[i] * math.exp(drift[i] + monthly_vol[i] * shock) + contribution[m] * weights[i]
            if m % 12 == 0:  # end of a year
                total = sum(values)
                if rebalance:
                    values = [total * w for w in weights]
                totals_by_year[m // 12].append(total)
        for i in range(n):
            ending_by_holding[i].append(values[i])

    def deflator(year):
        return (1 + inflation / 100) ** year if real_dollars else 1

    yearly = []
    for year, totals in enumerate(totals_by_year):
        totals = sorted(totals)
        d = deflator(year)
        yearly.append({
            "year": year,
            "contributed": start_total + monthly * 12 * year,
            **{name: percentile(totals, p) / d for name, p in
               [("p10", 0.10), ("p25", 0.25), ("p50", 0.50), ("p75", 0.75), ("p90", 0.90)]},
        })

    final_totals = totals_by_year[years]
    d = deflator(years)
    return {
        "yearly": yearly,
        "start_total": start_total,
        "weights": weights,
        "drift": drift,
        "final_real": [t / d for t in final_totals],
        "chance_below_contributed": sum(t < total_contributed_nominal for t in final_totals) / sims,
        "median_by_holding": [percentile(sorted(v), 0.5) / d for v in ending_by_holding],
    }


def money(x):
    """Format a dollar amount like $12,345."""
    return f"${x:,.0f}"


def short_money(x):
    """Format a dollar amount compactly, like $247k or $1.25M."""
    if abs(x) >= 1e6:
        return f"${x / 1e6:.2f}M"
    if abs(x) >= 1e4:
        return f"${x / 1e3:.0f}k"
    return money(x)


def print_report(holdings, results, args):
    yearly = results["yearly"]
    end = yearly[-1]
    dollars = "today's dollars" if not args.nominal else "nominal dollars"

    print()
    print("PORTFOLIO PROJECTOR")
    print("=" * 66)
    print(f"{'Ticker':<8}{'Value':>12}{'Weight':>9}{'Return':>9}{'Vol':>7}")
    for h, w in zip(holdings, results["weights"]):
        print(f"{h['ticker']:<8}{money(h['value']):>12}{w:>8.0%}{h['return']:>8.1f}%{h['vol']:>6.0f}%")
    print(f"{'Total':<8}{money(results['start_total']):>12}")
    print()
    print(f"Plan: {args.years} years, {money(args.monthly)}/month, "
          f"{'yearly rebalancing' if not args.no_rebalance else 'no rebalancing'}, "
          f"values in {dollars}, {args.sims:,} simulations")
    print()

    print(f"AFTER {args.years} YEARS")
    print("-" * 66)
    print(f"  Typical outcome (median):    {money(end['p50'])}")
    print(f"  Likely range (10th-90th):    {money(end['p10'])} to {money(end['p90'])}")
    print(f"  You put in:                  {money(end['contributed'])}")
    print(f"  Chance of ending below what you put in: {results['chance_below_contributed']:.0%}")
    if args.goal > 0:
        chance = sum(v >= args.goal for v in results["final_real"]) / len(results["final_real"])
        print(f"  Chance of reaching {money(args.goal)}: {chance:.0%}")
    print()

    print("MILESTONES")
    print("-" * 66)
    print(f"{'Year':<6}{'Put in':>10}{'10th':>10}{'25th':>10}{'Median':>10}{'75th':>10}{'90th':>10}")
    milestones = [y for y in (1, 3, 5, 10, 15, 20, 25, 30, 40, 50) if y < args.years] + [args.years]
    for y in milestones:
        r = yearly[y]
        print(f"{y:<6}{short_money(r['contributed']):>10}{short_money(r['p10']):>10}{short_money(r['p25']):>10}"
              f"{short_money(r['p50']):>10}{short_money(r['p75']):>10}{short_money(r['p90']):>10}")
    print()

    print("MEDIAN ENDING VALUE BY HOLDING")
    print("-" * 66)
    largest = max(results["median_by_holding"]) or 1
    for h, med, drift in zip(holdings, results["median_by_holding"], results["drift"]):
        bar = "#" * round(30 * med / largest)
        print(f"{h['ticker']:<7}{bar:<31}{money(med):>12}   typical growth {drift * 12:+.1%}/yr")
    print()
    print("Assumptions are rough long-run estimates, not predictions. Not financial advice.")


def save_chart(results, args, path):
    """Save a fan chart as an image. Needs matplotlib (pip install matplotlib)."""
    try:
        import matplotlib
        matplotlib.use("Agg")  # draw to a file, no window needed
        import matplotlib.pyplot as plt
    except ImportError:
        print(f"\nSkipped the chart: matplotlib isn't installed. Run `pip install matplotlib` to enable it.")
        return

    yearly = results["yearly"]
    years = [r["year"] for r in yearly]
    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.fill_between(years, [r["p10"] for r in yearly], [r["p90"] for r in yearly],
                    color="#cde2fb", label="10th-90th percentile")
    ax.fill_between(years, [r["p25"] for r in yearly], [r["p75"] for r in yearly],
                    color="#86b6ef", label="25th-75th percentile")
    ax.plot(years, [r["p50"] for r in yearly], color="#1c5cab", linewidth=2.5, label="Median")
    ax.plot(years, [r["contributed"] for r in yearly], color="#7a8293", linestyle="--", label="Total contributed")
    if args.goal > 0:
        ax.axhline(args.goal, color="#0f7a3d", linestyle=":", linewidth=1, label=f"Goal {short_money(args.goal)}")
    ax.set_title("Projected portfolio value")
    ax.set_xlabel("Years from now")
    ax.set_ylabel("Today's dollars" if not args.nominal else "Nominal dollars")
    ax.yaxis.set_major_formatter(lambda v, _: short_money(v))
    ax.xaxis.get_major_locator().set_params(integer=True)  # whole years only
    ax.set_ylim(bottom=0)
    ax.grid(axis="y", color="#eef0f4")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(loc="upper left", frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    print(f"\nSaved chart to {path}")


def main():
    parser = argparse.ArgumentParser(description="Project how a stock and ETF portfolio could grow.")
    parser.add_argument("csv", nargs="?", help="CSV of holdings (ticker,value[,return,vol]). Omit to use the example.")
    parser.add_argument("--years", type=int, default=20, help="years to project (default 20)")
    parser.add_argument("--monthly", type=float, default=500, help="monthly contribution in dollars (default 500)")
    parser.add_argument("--goal", type=float, default=250000, help="goal in dollars, 0 to skip (default 250000)")
    parser.add_argument("--inflation", type=float, default=2.5, help="inflation %% per year (default 2.5)")
    parser.add_argument("--nominal", action="store_true", help="show nominal dollars instead of today's dollars")
    parser.add_argument("--no-rebalance", action="store_true", help="let holdings drift instead of rebalancing yearly")
    parser.add_argument("--fees", action="store_true", help="subtract 0.2%% per year for fund fees")
    parser.add_argument("--sims", type=int, default=2000, help="number of simulations (default 2000)")
    parser.add_argument("--seed", type=int, default=20261006, help="random seed, for repeatable results")
    parser.add_argument("--chart", metavar="FILE.png", help="also save a chart image (needs matplotlib)")
    args = parser.parse_args()

    if not 1 <= args.years <= 50:
        parser.error("--years must be between 1 and 50")
    if args.sims < 10:
        parser.error("--sims must be at least 10")

    if args.csv:
        holdings = load_portfolio(args.csv)
    else:
        print("No CSV given, so using the example portfolio. Pass your own: python3 portfolio_projector.py portfolio.csv")
        holdings = [make_holding(t, v) for t, v in EXAMPLE_PORTFOLIO]

    results = simulate(
        holdings,
        years=args.years,
        monthly=max(0.0, args.monthly),
        inflation=args.inflation,
        real_dollars=not args.nominal,
        rebalance=not args.no_rebalance,
        fee=0.002 if args.fees else 0.0,
        sims=args.sims,
        seed=args.seed,
    )
    print_report(holdings, results, args)
    if args.chart:
        save_chart(results, args, args.chart)


if __name__ == "__main__":
    main()
