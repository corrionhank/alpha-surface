"""TradingView Lightweight Charts embed (candlestick + volume) for the dashboard.

Rendered in a Streamlit HTML component so bars space by index (no time gaps) and get the
TradingView crosshair. The library loads from a CDN, so the browser needs internet.
"""

from __future__ import annotations

import json

import pandas as pd

# Teal up, red down. Teal separates from red under red-green CVD; candle shape is redundant.
UP, DOWN = "#26A69A", "#EF5350"
_LWC_CDN = "https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"


def _time(ts: pd.Timestamp, interval: str):
    return ts.strftime("%Y-%m-%d") if interval == "1d" else int(ts.timestamp())


def tradingview_html(df: pd.DataFrame, interval: str, height: int = 480) -> str:
    candles = [
        {"time": _time(t, interval), "open": float(o), "high": float(h),
         "low": float(low), "close": float(c)}
        for t, o, h, low, c in zip(df["ts"], df["open"], df["high"], df["low"], df["close"])
    ]
    volumes = [
        {"time": _time(t, interval), "value": int(v), "color": (UP if c >= o else DOWN)}
        for t, o, c, v in zip(df["ts"], df["open"], df["close"], df["volume"])
    ]
    time_visible = "false" if interval == "1d" else "true"

    return f"""
<div id="tvchart" style="width:100%;height:{height}px;"></div>
<script src="{_LWC_CDN}"></script>
<script>
  const el = document.getElementById('tvchart');
  const chart = LightweightCharts.createChart(el, {{
    autoSize: true,
    layout: {{ background: {{ type: 'solid', color: 'transparent' }}, textColor: '#4B5563', fontSize: 12 }},
    grid: {{ vertLines: {{ color: 'rgba(15,23,42,0.06)' }}, horzLines: {{ color: 'rgba(15,23,42,0.06)' }} }},
    timeScale: {{ timeVisible: {time_visible}, secondsVisible: false, borderColor: 'rgba(15,23,42,0.12)' }},
    rightPriceScale: {{ borderColor: 'rgba(15,23,42,0.12)' }},
    crosshair: {{ mode: LightweightCharts.CrosshairMode.Normal }},
  }});
  const candle = chart.addCandlestickSeries({{
    upColor: '{UP}', downColor: '{DOWN}', wickUpColor: '{UP}', wickDownColor: '{DOWN}', borderVisible: false,
  }});
  candle.setData({json.dumps(candles)});
  const vol = chart.addHistogramSeries({{ priceFormat: {{ type: 'volume' }}, priceScaleId: '' }});
  vol.priceScale().applyOptions({{ scaleMargins: {{ top: 0.82, bottom: 0 }} }});
  vol.setData({json.dumps(volumes)});
  chart.timeScale().fitContent();
  new ResizeObserver(() => chart.timeScale().fitContent()).observe(el);
</script>
"""
