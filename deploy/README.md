# Deploy

The dashboard is one Streamlit process. Collection is two scheduled jobs that call the same
collectors as `make collect` and `make collect-bars`:

| Job | Runs | Writes |
|---|---|---|
| collect | hourly, weekdays 09:35 to 16:35 ET | `market_metrics`, `iv_term`, SPY and QQQ `option_chain` (tastytrade) |
| bars | weekdays 17:15 ET | daily and hourly `ohlcv` top-up for the universe (Yahoo) |

Pages also fetch and store on demand, so the schedule fills gaps when nobody has the app open.
The tastytrade job needs credentials in `.env` at the repo root; without them it exits with an
error naming the missing variables.

## Docker

```bash
docker compose up -d                                        # dashboard on :8501, data in ./data
docker compose run --rm app python -m alphasurface.collector.tastytrade_collector
```

The image is published to `ghcr.io/corrionhank/alpha-surface` on every push to main.
Credentials come from `.env` at run time and are never baked into the image.

## macOS (launchd)

The plists in `launchd/` use `__REPO__` for the repo path. launchd has no time zone setting, so
the hours are local time; the files are written for a Mac on Pacific time. Shift the `Hour`
values if yours is elsewhere.

```bash
mkdir -p data/logs
for f in deploy/launchd/*.plist; do
  sed "s#__REPO__#$PWD#g" "$f" > ~/Library/LaunchAgents/"$(basename "$f")"
done
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.alphasurface.collect.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.alphasurface.bars.plist
```

Check and run by hand:

```bash
launchctl print gui/$(id -u)/local.alphasurface.collect
launchctl kickstart gui/$(id -u)/local.alphasurface.collect
tail -f data/logs/collect.log
```

Remove with `launchctl bootout gui/$(id -u)/local.alphasurface.collect` (and
`local.alphasurface.bars`), then delete the files from `~/Library/LaunchAgents`. A sleeping Mac
runs a missed job when it wakes.

## Linux (systemd)

The units in `systemd/` use `__REPO__` and `__USER__`. Timers are pinned to New York time, so the
host's zone does not matter (systemd 235 or later).

```bash
for f in deploy/systemd/*; do
  sed -e "s#__REPO__#$PWD#g" -e "s#__USER__#$USER#g" "$f" | sudo tee /etc/systemd/system/"$(basename "$f")" >/dev/null
done
sudo systemctl daemon-reload
sudo systemctl enable --now alphasurface-collect.timer alphasurface-bars.timer
```

Check and run by hand:

```bash
systemctl list-timers 'alphasurface-*'
sudo systemctl start alphasurface-collect.service
journalctl -u alphasurface-collect.service -f
```

`Persistent=true` runs a job missed while the host was off once at boot.
