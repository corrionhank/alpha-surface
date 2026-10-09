"""TradingView Lightweight Charts embed (candlestick + volume) for the dashboard.

Rendered in a Streamlit HTML component so bars space by index (no time gaps) and get the
TradingView crosshair. The library loads from a CDN, so the browser needs internet.
"""

from __future__ import annotations

import json

import pandas as pd

# Green up, red down, the convention traders read without thinking. Volume sits behind price in
# light gray so it never competes with the candles.
UP, DOWN = "#14804a", "#c0262d"
VOL_UP, VOL_DOWN = "rgba(22,26,51,0.12)", "rgba(22,26,51,0.22)"
_LWC_CDN = (
    "https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"
)


def _time(ts: pd.Timestamp, interval: str):
    return ts.strftime("%Y-%m-%d") if interval == "1d" else int(ts.timestamp())


def tradingview_html(
    df: pd.DataFrame, interval: str, height: int = 480, colors: dict[str, str] | None = None
) -> str:
    """colors comes from present.theme.chart_colors(); the iframe cannot read the page theme."""
    c_ = colors or {"text": "#6b7091", "grid": "rgba(22,26,51,0.06)", "axis": "#e4e6f0"}
    candles = [
        {
            "time": _time(t, interval),
            "open": float(o),
            "high": float(h),
            "low": float(low),
            "close": float(c),
        }
        for t, o, h, low, c in zip(
            df["ts"], df["open"], df["high"], df["low"], df["close"], strict=False
        )
    ]
    volumes = [
        {"time": _time(t, interval), "value": int(v), "color": (VOL_UP if c >= o else VOL_DOWN)}
        for t, o, c, v in zip(df["ts"], df["open"], df["close"], df["volume"], strict=False)
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
    upColor: '{UP}', downColor: '{DOWN}', borderUpColor: '{UP}', borderDownColor: '{DOWN}',
    wickUpColor: '{UP}', wickDownColor: '{DOWN}', borderVisible: true, priceLineVisible: false,
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
