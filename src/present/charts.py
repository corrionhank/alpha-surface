"""TradingView Lightweight Charts embed (candlestick + volume) for the dashboard.

Rendered in a Streamlit HTML component so bars space by index (no time gaps) and get the
TradingView crosshair. The library loads from a CDN, so the browser needs internet.
"""

from __future__ import annotations

import json

import pandas as pd

# Monochrome candles, the classic hollow style: up is a white body with an ink outline, down is
# solid ink. No hue, so direction never borrows a status color. Volume sits behind in gray.
INK, PAPER = "#111111", "#ffffff"
VOL_UP, VOL_DOWN = "rgba(17,17,17,0.12)", "rgba(17,17,17,0.28)"
_LWC_CDN = "https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"


def _time(ts: pd.Timestamp, interval: str):
    return ts.strftime("%Y-%m-%d") if interval == "1d" else int(ts.timestamp())


def tradingview_html(
    df: pd.DataFrame, interval: str, height: int = 480, colors: dict[str, str] | None = None
) -> str:
    """colors comes from present.theme.chart_colors(); the iframe cannot read the page theme."""
    c_ = colors or {"text": "#686868", "grid": "rgba(17,17,17,0.06)", "axis": "#e4e4e1"}
    candles = [
        {"time": _time(t, interval), "open": float(o), "high": float(h),
         "low": float(low), "close": float(c)}
        for t, o, h, low, c in zip(df["ts"], df["open"], df["high"], df["low"], df["close"])
    ]
    volumes = [
        {"time": _time(t, interval), "value": int(v), "color": (VOL_UP if c >= o else VOL_DOWN)}
        for t, o, c, v in zip(df["ts"], df["open"], df["close"], df["volume"])
    ]
    time_visible = "false" if interval == "1d" else "true"

    return f"""
<style>html, body {{ margin: 0; padding: 0; overflow: hidden; }}</style>
<div id="tvchart" style="width:100%;height:{height}px;"></div>
<script src="{_LWC_CDN}"></script>
<script>
  const el = document.getElementById('tvchart');
  const chart = LightweightCharts.createChart(el, {{
    autoSize: true,
    layout: {{
      background: {{ type: 'solid', color: 'transparent' }},
      textColor: '{c_["text"]}', fontSize: 11,
      fontFamily: 'Inter, -apple-system, "Segoe UI", sans-serif',
    }},
    grid: {{ vertLines: {{ visible: false }}, horzLines: {{ color: '{c_["grid"]}' }} }},
    timeScale: {{ timeVisible: {time_visible}, secondsVisible: false, borderColor: '{c_["axis"]}',
                  rightOffset: 2, fixLeftEdge: true, fixRightEdge: true }},
    // Candles keep the top three quarters; volume sits in the band below, on its own hidden scale.
    rightPriceScale: {{ borderColor: '{c_["axis"]}', scaleMargins: {{ top: 0.06, bottom: 0.24 }} }},
    crosshair: {{ mode: LightweightCharts.CrosshairMode.Normal }},
    // The page scrolls under the cursor; a wheel over the chart must not zoom it instead.
    handleScroll: {{ mouseWheel: false, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false }},
    handleScale: {{ mouseWheel: false, pinch: true, axisPressedMouseMove: true }},
  }});
  const candle = chart.addCandlestickSeries({{
    upColor: '{PAPER}', downColor: '{INK}', borderUpColor: '{INK}', borderDownColor: '{INK}',
    wickUpColor: '{INK}', wickDownColor: '{INK}', borderVisible: true, priceLineVisible: false,
  }});
  candle.setData({json.dumps(candles)});
  const vol = chart.addHistogramSeries({{
    priceFormat: {{ type: 'volume' }}, priceScaleId: 'vol', lastValueVisible: false,
    priceLineVisible: false,
  }});
  chart.priceScale('vol').applyOptions({{ scaleMargins: {{ top: 0.8, bottom: 0 }}, visible: false }});
  vol.setData({json.dumps(volumes)});
  chart.timeScale().fitContent();
  new ResizeObserver(() => chart.timeScale().fitContent()).observe(el);
</script>
"""
