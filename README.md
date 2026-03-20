# Portfolio Dashboard

An interactive, dark-mode portfolio dashboard for a 40-stock equal-weighted portfolio.

## Features
- **Portfolio Performance Chart** — equal-weighted blend with YTD/6M/1Y/3Y/5Y toggles
- **Individual Stock Overlay** — click any ticker to compare against portfolio
- **40×40 Correlation Matrix** — interactive heatmap
- **Top 5 Contributors / Bottom 5 Detractors**
- **PEG Ratio Chart** — with portfolio average line
- **Growth Metrics Table** — revenue, earnings, FCF, margins
- **Sector Breakdown** — donut chart

## Quick Start

### 1. Fetch Data
```bash
python fetch_data.py
```
This creates `dashboard_data.json` with all price history and fundamentals from Yahoo Finance.

### 2. Serve the Dashboard
```bash
python -m http.server 8080
```
Then open http://localhost:8080 in your browser.

### 3. Refresh Data
Re-run `python fetch_data.py` anytime to update. Refresh the browser to see new data.

## Requirements
- Python 3.10+
- `yfinance` and `numpy` (`pip install yfinance numpy`)

## Files
- `fetch_data.py` — Python script to fetch all data from Yahoo Finance
- `index.html` — Single-page dashboard (uses Plotly.js from CDN)
- `dashboard_data.json` — Generated data file (not committed)
