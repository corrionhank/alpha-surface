# systemd Service Files

Copy the `.service` and `.timer` files to `/etc/systemd/system/` (system-wide) or `~/.config/systemd/user/` (user-level).

**Before installing**, edit each `.service` file to set:
- `User=` — your Linux username
- `WorkingDirectory=` — absolute path to this repo
- `ExecStart=` — absolute path to the venv Python binary

```bash
# Install and enable (system-wide example)
sudo cp systemd/*.service systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now market-hourly.timer
sudo systemctl enable --now market-eod.timer

# Check status
systemctl status market-hourly.timer
journalctl -u market-hourly.service -f
```

## Timer schedule

| Timer | Runs | What it collects |
|-------|------|-----------------|
| `market-hourly` | Every hour Mon–Fri 09:30–16:30 ET | tastytrade chains + /market-metrics; yfinance OHLCV/VIX |
| `market-eod` | 17:00 ET Mon–Fri | FRED (rates/spreads/breakevens); vix_utils (VIX-futures term structure) |

A news-collection timer can be added similarly (every 30 min during market hours).
