#!/usr/bin/env python3
"""Fetch portfolio data from Yahoo Finance and generate dashboard JSON."""

import json
import datetime
import sys
import time
import numpy as np

try:
    import yfinance as yf
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "yfinance", "-q"])
    import yfinance as yf

TICKERS = [
    "GOOG", "META", "NFLX", "ABNB", "AMZN", "PLNT", "SHAK", "COIN",
    "PRAA", "XYZ", "DXCM", "ISRG", "TMDX", "VEEV", "AXON", "BWXT",
    "SYM", "UBER", "VRT", "XMTR", "AAPL", "APPF", "MU", "CRM",
    "DOCU", "DT", "IOT", "MDB", "MSFT", "NOW", "NVDA", "OKTA",
    "PANW", "PCOR", "SHOP", "TEAM", "TWLO", "TYL", "U", "MPWR"
]

BENCHMARK = "SPY"

def safe_get(info, key, default=None):
    try:
        v = info.get(key, default)
        if v is None:
            return default
        if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
            return default
        return v
    except:
        return default

def fetch_all():
    print(f"Fetching data for {len(TICKERS)} tickers + {BENCHMARK}...")
    today = datetime.date.today()
    start_5y = today - datetime.timedelta(days=5*365+30)

    all_symbols = TICKERS + [BENCHMARK]

    # --- Historical prices (5Y) ---
    print("Downloading 5Y historical prices...")
    hist = yf.download(all_symbols, start=str(start_5y), end=str(today), auto_adjust=True, progress=True)
    close = hist["Close"].ffill().bfill()
    volume = hist["Volume"].ffill().fillna(0)

    dates = [d.strftime("%Y-%m-%d") for d in close.index]
    price_data = {}
    for t in all_symbols:
        if t in close.columns:
            prices = close[t].tolist()
            price_data[t] = [None if (p != p) else round(p, 4) for p in prices]
        else:
            print(f"  WARNING: No price data for {t}")
            price_data[t] = [None] * len(dates)

    # --- Volume data (current + 20-day avg) ---
    print("Computing volume data...")
    volume_data = {}
    for t in TICKERS:
        if t in volume.columns:
            vol_series = volume[t]
            current_vol = float(vol_series.iloc[-1]) if len(vol_series) > 0 else 0
            avg_20 = float(vol_series.iloc[-20:].mean()) if len(vol_series) >= 20 else float(vol_series.mean())
            volume_data[t] = {
                "current": current_vol,
                "avg20": round(avg_20, 0),
                "ratio": round(current_vol / avg_20, 2) if avg_20 > 0 else 1.0
            }
        else:
            volume_data[t] = {"current": 0, "avg20": 0, "ratio": 1.0}

    # --- Returns for all periods ---
    print("Computing returns for all periods...")
    returns_map = {}
    for period_label, days in [("1D", 1), ("1W", 7), ("1M", 30), ("6M", 182), ("YTD", None), ("1Y", 365), ("3Y", 1095), ("5Y", 1825)]:
        if period_label == "YTD":
            start_dt = datetime.date(today.year, 1, 1)
        else:
            start_dt = today - datetime.timedelta(days=days)
        mask = close.index >= str(start_dt)
        subset = close.loc[mask]
        if len(subset) < 2:
            returns_map[period_label] = {}
            continue
        first = subset.iloc[0]
        last = subset.iloc[-1]
        period_returns = {}
        for t in all_symbols:
            if t in subset.columns and first[t] > 0:
                ret = (last[t] - first[t]) / first[t]
                period_returns[t] = round(float(ret), 6)
            else:
                period_returns[t] = 0
        returns_map[period_label] = period_returns

    # --- Rolling alpha/beta (60-day) vs SPY ---
    print("Computing rolling alpha/beta...")
    rolling_window = 60
    full_returns = close.pct_change().dropna()
    port_daily = full_returns[[t for t in TICKERS if t in full_returns.columns]].mean(axis=1)
    full_bench = full_returns[BENCHMARK] if BENCHMARK in full_returns.columns else None

    rolling_dates = []
    rolling_alpha = []
    rolling_beta = []

    if full_bench is not None:
        port_arr = port_daily.values
        bench_arr = full_bench.values
        idx = port_daily.index
        for i in range(rolling_window, len(port_arr)):
            p_slice = port_arr[i-rolling_window:i]
            b_slice = bench_arr[i-rolling_window:i]
            if np.any(np.isnan(p_slice)) or np.any(np.isnan(b_slice)):
                continue
            cov_pb = np.cov(p_slice, b_slice)
            beta = cov_pb[0,1] / cov_pb[1,1] if cov_pb[1,1] != 0 else 1.0
            alpha = (np.mean(p_slice) - beta * np.mean(b_slice)) * 252
            rolling_dates.append(idx[i].strftime("%Y-%m-%d"))
            rolling_alpha.append(round(float(alpha), 4))
            rolling_beta.append(round(float(beta), 4))

    # --- Drawdown ---
    print("Computing drawdown profile...")
    port_prices = close[[t for t in TICKERS if t in close.columns]].copy()
    for t in port_prices.columns:
        port_prices[t] = port_prices[t] / port_prices[t].iloc[0]
    port_line = port_prices.mean(axis=1)
    running_max = port_line.cummax()
    drawdown = (port_line - running_max) / running_max
    dd_dates = [d.strftime("%Y-%m-%d") for d in drawdown.index]
    dd_values = [round(float(v), 4) if v == v else 0 for v in drawdown.values]

    stock_drawdowns = {}
    for t in TICKERS:
        if t in close.columns:
            p = close[t]
            rm = p.cummax()
            dd = (p - rm) / rm
            stock_drawdowns[t] = [round(float(v), 4) if v == v else 0 for v in dd.values]

    # --- Earnings calendar ---
    print("Fetching earnings dates...")
    earnings_calendar = {}
    for i, t in enumerate(TICKERS):
        print(f"  [{i+1}/{len(TICKERS)}] {t} earnings...", end=" ", flush=True)
        try:
            tk = yf.Ticker(t)
            cal = tk.calendar
            if cal is not None:
                if isinstance(cal, dict):
                    ed = cal.get('Earnings Date')
                    if ed:
                        if isinstance(ed, list):
                            earnings_calendar[t] = [str(d) for d in ed]
                        else:
                            earnings_calendar[t] = [str(ed)]
                    else:
                        earnings_calendar[t] = []
                elif hasattr(cal, 'columns'):
                    if 'Earnings Date' in cal.index:
                        ed = cal.loc['Earnings Date']
                        earnings_calendar[t] = [str(v) for v in ed.values if str(v) != 'NaT']
                    else:
                        earnings_calendar[t] = []
                else:
                    earnings_calendar[t] = []
            else:
                earnings_calendar[t] = []
            print("OK")
        except Exception as e:
            print(f"skip ({e})")
            earnings_calendar[t] = []
        time.sleep(0.15)

    # --- Per-stock fundamentals ---
    print("Fetching fundamentals for each ticker...")
    stock_info = {}
    for i, t in enumerate(TICKERS):
        print(f"  [{i+1}/{len(TICKERS)}] {t}...", end=" ", flush=True)
        try:
            tk = yf.Ticker(t)
            info = tk.info or {}

            sector = safe_get(info, "sector", "Unknown")
            industry = safe_get(info, "industry", "Unknown")
            name = safe_get(info, "shortName", t)
            market_cap = safe_get(info, "marketCap", 0)
            pe_trailing = safe_get(info, "trailingPE")
            pe_forward = safe_get(info, "forwardPE")
            peg = safe_get(info, "pegRatio")
            if peg is None:
                _pe = safe_get(info, "trailingPE") or safe_get(info, "forwardPE")
                _eg = safe_get(info, "earningsGrowth") or safe_get(info, "revenueGrowth")
                if _pe and _eg and _eg > 0:
                    peg = round(_pe / (_eg * 100), 2)
            revenue_growth = safe_get(info, "revenueGrowth")
            earnings_growth = safe_get(info, "earningsGrowth")
            earnings_quarterly_growth = safe_get(info, "earningsQuarterlyGrowth")
            forward_eps = safe_get(info, "forwardEps")
            trailing_eps = safe_get(info, "trailingEps")
            free_cashflow = safe_get(info, "freeCashflow")
            operating_cashflow = safe_get(info, "operatingCashflow")
            revenue = safe_get(info, "totalRevenue")
            gross_margins = safe_get(info, "grossMargins")
            profit_margins = safe_get(info, "profitMargins")
            current_price = safe_get(info, "currentPrice") or safe_get(info, "regularMarketPrice")
            fifty_two_wk_high = safe_get(info, "fiftyTwoWeekHigh")
            fifty_two_wk_low = safe_get(info, "fiftyTwoWeekLow")
            roe = safe_get(info, "returnOnEquity")

            fwd_earnings_growth = None
            if forward_eps and trailing_eps and trailing_eps > 0:
                fwd_earnings_growth = round((forward_eps - trailing_eps) / abs(trailing_eps), 4)

            # Fetch annual financials for acceleration data
            rev_growth_prior = None
            fcf_growth_current = None
            fcf_growth_prior = None
            gross_margin_yoy = None
            gross_margin_prior_yoy = None

            try:
                fin = tk.financials  # annual income statement
                cf = tk.cashflow     # annual cash flow
                if fin is not None and not fin.empty and fin.shape[1] >= 3:
                    # Revenue growth: current year vs prior, and prior vs 2 years ago
                    rev_cols = fin.columns[:3]  # most recent 3 years
                    rev_row = None
                    for label in ['Total Revenue', 'Revenue']:
                        if label in fin.index:
                            rev_row = label
                            break
                    if rev_row:
                        r0 = fin.loc[rev_row, rev_cols[0]]
                        r1 = fin.loc[rev_row, rev_cols[1]]
                        r2 = fin.loc[rev_row, rev_cols[2]]
                        if r1 and r1 != 0:
                            rev_growth_current_calc = (r0 - r1) / abs(r1)
                        else:
                            rev_growth_current_calc = None
                        if r2 and r2 != 0:
                            rev_growth_prior = round(float((r1 - r2) / abs(r2)), 4)
                        # Override revenue_growth with calculated if available
                        if rev_growth_current_calc is not None:
                            revenue_growth = round(float(rev_growth_current_calc), 4)

                    # Gross margin: current and prior year
                    gp_row = None
                    for label in ['Gross Profit']:
                        if label in fin.index:
                            gp_row = label
                            break
                    if gp_row and rev_row:
                        gp0 = fin.loc[gp_row, rev_cols[0]]
                        gp1 = fin.loc[gp_row, rev_cols[1]]
                        gp2 = fin.loc[gp_row, rev_cols[2]]
                        rv0 = fin.loc[rev_row, rev_cols[0]]
                        rv1 = fin.loc[rev_row, rev_cols[1]]
                        rv2 = fin.loc[rev_row, rev_cols[2]]
                        if rv0 and rv0 != 0 and rv1 and rv1 != 0:
                            gm0 = gp0 / rv0
                            gm1 = gp1 / rv1
                            gross_margin_yoy = round(float(gm0 - gm1), 4)
                        if rv1 and rv1 != 0 and rv2 and rv2 != 0:
                            gm1b = gp1 / rv1
                            gm2 = gp2 / rv2
                            gross_margin_prior_yoy = round(float(gm1b - gm2), 4)

                if cf is not None and not cf.empty and cf.shape[1] >= 3:
                    cf_cols = cf.columns[:3]
                    # FCF = Operating Cash Flow - Capital Expenditure
                    ocf_row = None
                    capex_row = None
                    for label in ['Operating Cash Flow', 'Total Cash From Operating Activities']:
                        if label in cf.index:
                            ocf_row = label
                            break
                    for label in ['Capital Expenditure', 'Capital Expenditures']:
                        if label in cf.index:
                            capex_row = label
                            break
                    if ocf_row and capex_row:
                        fcf0 = float(cf.loc[ocf_row, cf_cols[0]]) + float(cf.loc[capex_row, cf_cols[0]])
                        fcf1 = float(cf.loc[ocf_row, cf_cols[1]]) + float(cf.loc[capex_row, cf_cols[1]])
                        fcf2 = float(cf.loc[ocf_row, cf_cols[2]]) + float(cf.loc[capex_row, cf_cols[2]])
                        if fcf1 and abs(fcf1) > 0:
                            fcf_growth_current = round(float((fcf0 - fcf1) / abs(fcf1)), 4)
                        if fcf2 and abs(fcf2) > 0:
                            fcf_growth_prior = round(float((fcf1 - fcf2) / abs(fcf2)), 4)
                    elif ocf_row:
                        # Use operating cash flow as proxy
                        ocf0 = float(cf.loc[ocf_row, cf_cols[0]])
                        ocf1 = float(cf.loc[ocf_row, cf_cols[1]])
                        ocf2 = float(cf.loc[ocf_row, cf_cols[2]])
                        if ocf1 and abs(ocf1) > 0:
                            fcf_growth_current = round(float((ocf0 - ocf1) / abs(ocf1)), 4)
                        if ocf2 and abs(ocf2) > 0:
                            fcf_growth_prior = round(float((ocf1 - ocf2) / abs(ocf2)), 4)
            except Exception as e2:
                print(f" (financials err: {e2})", end="")

            stock_info[t] = {
                "name": name, "sector": sector, "industry": industry,
                "marketCap": market_cap, "currentPrice": current_price,
                "peTrailing": pe_trailing, "peForward": pe_forward,
                "pegRatio": peg, "revenueGrowth": revenue_growth,
                "revenueGrowthPrior": rev_growth_prior,
                "earningsGrowth": earnings_growth,
                "earningsQuarterlyGrowth": earnings_quarterly_growth,
                "forwardEarningsGrowth": fwd_earnings_growth,
                "forwardEps": forward_eps, "trailingEps": trailing_eps,
                "freeCashflow": free_cashflow, "operatingCashflow": operating_cashflow,
                "fcfGrowth": fcf_growth_current, "fcfGrowthPrior": fcf_growth_prior,
                "revenue": revenue, "grossMargins": gross_margins,
                "grossMarginYoY": gross_margin_yoy,
                "grossMarginPriorYoY": gross_margin_prior_yoy,
                "profitMargins": profit_margins,
                "fiftyTwoWeekHigh": fifty_two_wk_high,
                "fiftyTwoWeekLow": fifty_two_wk_low,
                "returnOnEquity": roe,
            }
            print("OK")
        except Exception as e:
            print(f"ERROR: {e}")
            stock_info[t] = {
                "name": t, "sector": "Unknown", "industry": "Unknown",
                "marketCap": 0, "currentPrice": None, "peTrailing": None,
                "peForward": None, "pegRatio": None, "revenueGrowth": None,
                "earningsGrowth": None, "earningsQuarterlyGrowth": None,
                "forwardEarningsGrowth": None, "forwardEps": None,
                "trailingEps": None, "freeCashflow": None,
                "operatingCashflow": None, "revenue": None,
                "grossMargins": None, "profitMargins": None,
                "fiftyTwoWeekHigh": None, "fiftyTwoWeekLow": None,
                "returnOnEquity": None,
            }
        time.sleep(0.2)

    # --- Rolling PEG (use trailing PE / earnings growth proxy over time) ---
    # We'll compute a snapshot-based rolling PEG using available data
    print("Computing rolling PEG data...")
    rolling_peg_dates = []
    rolling_peg_values = []
    # We can approximate by computing P/E from price/EPS at various points
    # For simplicity, compute current portfolio avg PEG and store as single point
    pegs_valid = [stock_info[t]["pegRatio"] for t in TICKERS if stock_info[t].get("pegRatio") and 0 < stock_info[t]["pegRatio"] < 100]
    avg_peg = round(sum(pegs_valid) / len(pegs_valid), 2) if pegs_valid else None

    # --- Portfolio volatility ---
    one_year_ago = today - datetime.timedelta(days=365)
    close_1y = close.loc[close.index >= str(one_year_ago)]
    returns_1y = close_1y.pct_change().dropna()
    ticker_returns = returns_1y[[t for t in TICKERS if t in returns_1y.columns]]
    cov_matrix = ticker_returns.cov() * 252
    n_stocks = len(ticker_returns.columns)
    w = np.ones(n_stocks) / n_stocks
    port_var = w @ cov_matrix.values @ w
    port_vol = np.sqrt(port_var)

    # --- Build output ---
    output = {
        "generated": datetime.datetime.now().isoformat(),
        "tickers": TICKERS,
        "dates": dates,
        "prices": price_data,
        "volumeData": volume_data,
        "portfolioVolatility": round(float(port_vol), 4),
        "rollingDates": rolling_dates,
        "rollingAlpha": rolling_alpha,
        "rollingBeta": rolling_beta,
        "drawdownDates": dd_dates,
        "drawdownValues": dd_values,
        "stockDrawdowns": stock_drawdowns,
        "earningsCalendar": earnings_calendar,
        "stockInfo": stock_info,
        "returns": returns_map,
        "avgPeg": avg_peg,
    }

    # Replace NaN/Infinity with None for valid JSON
    import math
    def sanitize(obj):
        if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
            return None
        if isinstance(obj, dict):
            return {k: sanitize(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [sanitize(v) for v in obj]
        return obj

    output = sanitize(output)
    out_path = "dashboard_data.json"
    with open(out_path, "w") as f:
        json.dump(output, f)

    size_mb = round(len(json.dumps(output)) / 1024 / 1024, 2)
    print(f"\nDone! Wrote {out_path} ({size_mb} MB)")
    print(f"Generated at: {output['generated']}")

if __name__ == "__main__":
    fetch_all()
