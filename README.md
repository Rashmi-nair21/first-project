# first-project

## Portfolio Projector

`portfolio-projector.html` is a single-page tool that projects how a portfolio of stocks and ETFs could grow over time.

- Enter each holding's ticker and dollar value. Known tickers (VOO, QQQ, VXUS, BND, AAPL, NVDA, …) fill in a default expected return and volatility, and you can edit both.
- Set the number of years, a monthly contribution, an optional goal, and inflation.
- The page runs a 2,000-path Monte Carlo simulation (monthly steps, holdings correlated through a shared market factor). It shows the median outcome, the 10th–90th percentile range, milestone values, the chance of reaching your goal, and each holding's median ending value.

Open the file in a browser; it has no build step or server. The default assumptions are rough long-run estimates, not forecasts, and this is not financial advice.
