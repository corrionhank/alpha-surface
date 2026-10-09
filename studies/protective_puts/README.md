# Do protective puts actually protect you?

> ## EXPLORATORY. NOT FINDINGS.
>
> Most of this is hypothesis generation on a single 21-year sample. None of the positive
> risk-adjusted results are statistically significant:
>
> | Comparison | ΔSharpe | p | Bootstrap 95% CI |
> |---|---|---|---|
> | Vol target 15% vs buy-and-hold | +0.160 | 0.175 | [-0.06, +0.37] |
> | Vol expansion + put vs buy-and-hold | +0.076 | 0.475 | [-0.08, +0.22] |
>
> The standard error on a single 21-year Sharpe is 0.24, wider than any Sharpe gap reported here.
> Detecting the headline effect at 80% power would need **89 years** of data. The pre-registered
> study is in [PROTOCOL.md](PROTOCOL.md).
>
> **The trustworthy parts are the negative results and the drawdown reductions.** Signals that
> failed against a random control failed honestly, and drawdown is far less noisy than Sharpe. What
> is *not* trustworthy is any risk-adjusted-return ranking on this sample.

21 years of S&P 500 data, 2005-07 to 2026-07. NumPy, pandas, SciPy, Matplotlib, yfinance.

```
pip install -e ".[studies]"                       # matplotlib, for the figures
make study
make study ARGS="--skew 0.0 --years 10"           # flat VIX, shorter window
```

Reads SPY, ^VIX and ^IRX daily bars from storage. Seed them first (a one-time 25-year pull):

```
python -m alphasurface.collector.yfinance_collector --interval 1d --period 25y --symbols 'SPY,^VIX,^IRX'
```

## The answer

Yes, but only against gaps, and never for free.

| Strategy | CAGR | Vol | Sharpe | Max DD | Premium paid | Recovered |
|---|---|---|---|---|---|---|
| Buy and hold SPY | 10.98% | 19.2% | 0.55 | -55.4% | 0 | n/a |
| Put ATM, monthly | 0.56% | 7.9% | -0.11 | -40.2% | 47,291 | 61% |
| Put 5% OTM, monthly | 5.60% | 12.4% | 0.36 | -50.8% | 26,058 | 40% |
| Put 10% OTM, monthly | 8.67% | 15.2% | 0.51 | -56.3% | 12,099 | 33% |

Three things fall out of this.

**The protection is real and it is priced.** An ATM put rolled monthly cuts volatility from 19% to
8% and cuts the worst drawdown by 15 points. It also eats the entire equity risk premium: 10.98%
becomes 0.56%, which is worse than the T-bills it was hedged against. The market is not mispricing
insurance in your favour. Premium recovery never exceeds 61% for any strike.

**Puts hedge gaps, not grinds.** COVID was a four-week crash and the hedge worked exactly as
advertised, cutting the drawdown from -34% to -7%. The GFC was a 17-month bleed, and the 10% OTM
put made it *worse* (-56.3% against -55.4% unhedged): you pay premium every month while the index
rarely falls 10% inside any single 21-day window, so the puts expire worthless on the way down. A
slow bear market defeats a rolling OTM hedge.

**Rolling less often is the only version that beats the benchmark risk-adjusted.** The 5% OTM put
rolled annually returns 6.69% at 8.3% vol, a 0.62 Sharpe against buy-and-hold's 0.55, with the max
drawdown cut from -55% to -20%. Fewer, longer-dated puts survive a grind that monthly puts sleep
through. This is the one result that would survive contact with a real trading desk, and it is also
the most model-dependent, so treat it as a hypothesis and not a conclusion.

## Can you just hedge when a recession is coming?

```
python -m studies.protective_puts.conditional
```

The always-on hedge loses because it pays premium in the 90% of months that turn out fine. The
obvious fix is to buy protection only when a recession indicator fires. It does not work.

| Signal | Duty | CAGR | Sharpe | Max DD | Beats random |
|---|---|---|---|---|---|
| Buy and hold | 0% | 10.98% | 0.55 | -55.4% | n/a |
| Always hedged | 100% | 5.60% | 0.36 | -50.8% | n/a |
| Yield curve (10Y-3M) | 40% | 8.72% | 0.48 | -55.8% | 42% |
| Credit spread (Baa) | 25% | 8.10% | 0.46 | -50.1% | **6%** |
| Sahm rule | 16% | 9.36% | 0.52 | -49.8% | 52% |
| High CAPE | 88% | 7.93% | 0.48 | -49.0% | 100% |
| Below 200d MA | 24% | 8.58% | 0.50 | -51.0% | 40% |
| Any 2 of 5 | 64% | 6.45% | 0.41 | -50.8% | 26% |

Every signal beats the always-on hedge, which proves nothing: they hedge less, so they pay less
premium. **Not one of them beats buy-and-hold.** The best is the Sahm rule at 0.52 Sharpe against
0.55 for doing nothing at all.

The "beats random" column is the column that matters. It is the share of 200 random-timing twins,
hedging the same fraction of cycles, that the signal outperformed. 50% is a coin flip.

- **The yield curve, the Sahm rule and the 200d filter all land at a coin flip.** They add nothing
  that hedging less often would not have done by itself.
- **Credit spreads beat 6% of random.** They are *worse* than randomly hedging the same amount. By
  the time Baa spreads are in their top quintile, the drawdown has already happened: the signal
  fired on 2020-03-10, three weeks into a crash that ended on 2020-03-23. You buy insurance after
  the fire and then keep paying for it through the recovery.
- **High CAPE beats 100% of random, and it is not what it looks like.** It is on 88% of the time,
  because CAPE has been above its own historical 80th percentile almost continuously since 2005.
  "Hedge when PE is high" has meant "hedge always" for twenty years. Its only sustained off period
  is 2008-10 to 2010-04, so its entire edge is that it *removed* the hedge in the middle of the
  crash and rode the recovery unhedged. CAPE is price over earnings, so a crash mechanically
  lowers it. It is an inverse-price signal that always says un-hedge after a fall. That is buying
  the dip, not forecasting a recession, and it is the opposite of protection.

The yield curve is the one signal with a real hit: it inverted in January 2006 and stayed on
through August 2008, with SPY down 20.6% over the following year. It then fired again in March
2019 and stayed on for two years while the market rose 16%, and it has been on continuously since
October 2022 through the largest bull run in the sample. One hit, two very expensive false alarms.

**The honest conclusion: the market prices this insurance correctly.** Recession indicators are
either late (credit, Sahm), early by years (the curve), or a disguised price signal (CAPE), and
none of them clears the bar set by hedging at random.

## What the exploratory strategy search taught us

An early pass searched ~30 strategies over two "generations" (pick, look, breed the winners on the
same sample). That search was in-sample selection and its leaderboard is not quotable, so the code
was removed; `frontier.py` below is the honest, non-selective version and carries the numbers. But
three lessons survived the search and shaped everything after it:

**Cheapness is not an edge.** Every rule that bought protection when it looked cheap (low VIX,
negative VRP, steep contango) failed against a random control, the worst of them *worse than
random*. The option is cheap precisely when nothing is about to happen. You are offered a fair
price.

**Vol clustering is an edge.** Rules that hedged once vol had already turned up (vol expansion,
backwardation) beat their random twins across every parameterization. This is not a recession
forecast; it is the observation that high vol follows high vol, the most robust autocorrelation in
finance. It reappears, confirmed, in the downside study below.

**Owning less beats insuring more,** and once you size by vol, options add nothing: stacking a put
on top of a vol target moves Sharpe by a rounding error and makes the drawdown *worse*, because the
premium bleed shrinks the equity the sizing rule is compounding. This became the frontier study.

**The single-trade trap.** The best-looking line in that search (a 1-year backwardation put, 11.7%
CAGR, beats 100% of random) fired exactly once in 21 years. A coincidence with a Sharpe ratio
attached. Every table since prints hedge *counts*, not duty percentages, so a one-trade result
cannot masquerade as a strategy.

```
python -m studies.protective_puts.skill   # how right does the hunch have to be?
```

## Hedging when the market looks stretched

```
python -m studies.protective_puts.exhaustion
```

A natural intuition: after a big bullish run, a reversal is due, so buy a put. "Stretched" measured
three ways: a multi-sigma price run-up (z-score of the trailing return), VIX at a complacent low
percentile, and steep contango. Each is a timing claim, so each answers to one question before any
backtest: **after the signal fires, is a bear more likely than at a random moment?**

| Signal | Events in 21y | P(bear \| signal) | Base rate | Beats base? |
|---|---|---|---|---|
| 3m run-up, 3.0 sigma -> 3m put | 6 | **0%** | 7% | No |
| 6m run-up, 2.0 sigma -> 1y put | 12 | 0% | 23% | No |
| 12m run-up, 2.0 sigma -> 1y put | 11 | 9% | 23% | No |
| VIX below 20th percentile | 129 | 21% | 23% | No |
| VIX below 10th percentile | 55 | 5% | 23% | No |
| Steep contango (>10%) | 252 | 18% | 23% | No |

**Not one signal beats the base rate. Every lift is zero or negative.** A stretched market is
followed by a bear *less* often than a random day is. The intuition is not merely unproven, it is
backwards, and the reason is visible in the six 3-sigma up-moves the 21 years contain:

    2009-06   (out of the GFC bottom)     next 3m: +8.0%
    2020-06   (out of the COVID crash)    next 3m: +8.7%
    2020-06                               next 3m: +7.7%
    2020-07                               next 3m: +7.9%
    2020-07                               next 3m: +8.3%
    2025-07                               next 3m: +7.6%

Every one is a V-recovery. The biggest up-moves in equity indices happen coming *out* of a crash,
not before the next one, and each was followed by more gains. A 3-sigma up-move is a bottom
signature, so hedging on it buys insurance the day after you needed it, at the one moment the
market is most likely to keep rising. This is the same failure as the CAPE signal in the
conditional study: a price-derived trigger that mechanically points backwards.

The event-driven backtest (buy the put the day the signal fires, hold to expiry) confirms it: every
configuration underperforms buy-and-hold, and the drawdowns barely improve (-50% to -55%) because
the puts are almost never on when the crash comes. The results rest on 3 to 9 trades, so they are
noise on top of a null, which is exactly what the precision table predicted.

This is exploratory (see PROTOCOL.md). The signal count alone (6 events) forbids a strategy claim.
But the precision diagnostic is robust in a way a Sharpe ranking is not: "this trigger points the
wrong way" survives the small sample, because it is a statement about direction, not magnitude.

## The mirror: hedging after a downside move

```
python -m studies.protective_puts.downside
```

If a 3-sigma up-move is a bottom (hedging on it is backwards), what about a 2-sigma *down* move?
Here the prior is the opposite and stronger: volatility clusters and declines have short-term
momentum, so a drop plausibly predicts more drop. It is the first place in the study where the
crux comes back positive.

**Crux 1, does a drop predict more drop?** For once, yes.

| Signal | Events | P(further bear \| signal) | Base rate | Beats base? |
|---|---|---|---|---|
| 1m drop 2.0 sigma -> 3m put | 45 | 20% | 7% | **Yes** |
| 3m drop 2.0 sigma -> 3m put | 27 | **33%** | 7% | **Yes**, CI [19%, 52%] |
| Backwardation (VIX > VIX3M) | 150 | 11% | 7% | Yes |
| VIX > 80th percentile | 87 | 6% | 7% | No |

The 3m-drop signal nearly quintuples the odds of a further 15% drawdown, and its whole confidence
interval clears the base rate. Downside momentum is real, which the up-move never was.

**Crux 2, but are you hedging a fall or a bounce?** This is where it gets honest. Mean forward
return over the tenor, conditional on the signal:

| Signal | Return after signal | Baseline | |
|---|---|---|---|
| 3m drop 2.0 sigma | +0.0% | +2.5% | lower, hedge justified |
| 1m drop 2.0 sigma | +1.4% | +2.5% | lower, hedge justified |
| **VIX > 80th percentile** | **+3.9%** | +2.5% | **higher, buying the dip** |

The drop signals leave the market lower than average, so a hedge is at least pointed the right way.
But VIX at an 80th-percentile spike leaves it *higher* than average: by the time vol has fully
blown out, the drop is done and you would be buying the rebound. Same lesson as the CAPE and
up-move signals, one more time.

**The backtest, and the catch.**

| Strategy | CAGR | Sharpe | MaxDD | Hedges | Beats random |
|---|---|---|---|---|---|
| Buy and hold | 10.98% | 0.55 | -55.4% | 0 | n/a |
| 1m drop 2.0 sigma -> 3m put | 9.14% | 0.58 | **-38.9%** | 16 | 90% |
| 3m drop 2.0 sigma -> 3m put | 10.45% | 0.57 | -42.3% | 8 | 85% |
| VIX > 80th pct (event-driven) | 5.84% | 0.33 | -54.6% | 31 | 0% |

The drop signals cut the worst drawdown by 13 to 16 points and beat 85-90% of random-timed twins.
That is the best-looking hedge in the study. Three caveats keep it honest:

- **It is mostly 2008.** Of the 3m-drop signal's 9 bear-hits, 8 are the 2008 cascade and one is
  March 2020. A fresh drop predicts more drop *while a slow-motion crash is already underway*. The
  drawdown reduction is real but it is one crisis wearing a track record.
- **The same signal buys bottoms.** It also fires at 2009-03-09 (the exact GFC low, +38% over the
  next quarter), 2020-05 and 2025-04. It cannot tell a cascade from a capitulation, so it hedges
  both, and pays premium at the lows.
- **The Sharpe edge is inside the noise; the drawdown edge is not.** +0.03 of Sharpe over
  buy-and-hold is well within the 0.24 standard error. The 16-point drawdown cut is the robust
  part, and it comes at 1.8 points of CAGR. This is tail insurance that works, not free alpha.
- **VIX > 80th fails as an entry** (beats 0% of random) exactly as crux 2 predicted: it fires last,
  buys the most expensive puts, and sits through the bounce.

Verdict: a 2-sigma drop is the one signal that genuinely forecasts more downside, and buying a put
on it is real, cheap-ish tail protection that roughly halves the worst drawdown. It is not a return
engine, it leans hard on 2008, and it wastes premium buying capitulation lows it cannot distinguish
from continuation. Which is a fair description of protective puts in general: they work when you
most need them and bleed the rest of the time, and a drop-trigger concentrates both.

## How right does the hunch have to be?

Every signal failed, so `skill.py` asks the question they were only ever a proxy for: suppose you
just *knew*, some of the time. Deploy a 1-year put on a third of the cycles, with a known fraction
of your bear calls being correct.

| Your precision | CAGR | Sharpe | MaxDD | Beats buy-and-hold |
|---|---|---|---|---|
| 29% (dart board) | 9.4% | 0.53 | -47% | 30% |
| **40% (breakeven)** | 9.8% | 0.57 | -44% | 52% |
| 50% | 10.2% | 0.62 | -39% | 87% |
| 70% | 10.7% | 0.71 | -30% | 100% |
| 100% (perfect foresight) | 11.0% | 0.78 | -23% | 100% |

**You need to be right 40% of the time. A dart board scores 29%.** So the bar is 11 points above
chance, and at 50% precision you beat buy-and-hold in 87% of trials. That is a *low* bar, and it is
the most encouraging number in the whole project: this is a bet a human with a genuine macro read
could plausibly win, which is not something any of the mechanical signals could say.

It is also just pot odds (section 11 of the formula sheet). The hedge is a bet with a breakeven hit
rate, and 40% is that rate. The reason it is reachable is the 1-year tenor: annual puts cost far
less per unit of protection than monthly ones, so the hedge does not need to be right often.

## Where the results point: the defensive-exposure frontier

```
python -m studies.protective_puts.frontier
```

Every study above converges on three facts: options are a tax, Sharpe edges are inside the noise
band, and the one robust, repeatable result is that volatility-responsive de-risking cuts drawdown.
So this drops options entirely, sweeps 74 no-option dynamic-exposure strategies across six families,
and maps them on the return-vs-drawdown plane. The question is reframed from "beat buy-and-hold on
Sharpe" (which needs ~89 years to answer) to "what CAGR do you give up per point of drawdown
removed", which rests on drawdown, the least noisy statistic here.

The whole cloud is plotted (`16-frontier.png`), so nothing is cherry-picked. Buy-and-hold sits
alone at the far edge: 10.98% CAGR, **-55% drawdown**, 19% vol. Every one of the 74 strategies
sits inside it, at less drawdown and less volatility. The efficient frontier (non-dominated on CAGR
and drawdown) runs from:

| Strategy | Family | CAGR | Vol | Sharpe | MaxDD | Calmar |
|---|---|---|---|---|---|---|
| Buy and hold | n/a | 10.98% | 19.2% | 0.55 | -55.4% | 0.20 |
| Vol target 15%/21d/1.5x | Vol target | 11.72% | 15.4% | 0.69 | -35.5% | 0.33 |
| **De-risk after 2σ drop, 21d** | Downside | **10.27%** | 11.4% | **0.77** | **-23.3%** | 0.44 |
| TS momentum 189d | Trend | 9.65% | 12.1% | 0.68 | -21.0% | 0.46 |
| TS momentum 126d | Trend | 8.94% | 11.3% | 0.66 | -18.0% | 0.50 |
| Drawdown control 10% | Drawdown | 4.90% | 7.4% | 0.45 | -13.6% | 0.36 |

The frontier is a menu, not a winner. It says: the first 20 points of drawdown (from -55% to -35%)
cost essentially **nothing** in CAGR, and after that each further point of protection costs
progressively more return. Where you sit on it is a risk-tolerance choice, not an optimization.

**The standout, and the payoff of the whole line of research:** the down-move signal from
downside.py, used as a *sizing rule* (go to cash for 63 days after a 2-sigma drop) instead of a put.
As a put it returned 9.14% at -39% drawdown, bleeding premium. As a de-risking rule it returns
10.27%, a hair under buy-and-hold, at less than half the drawdown (-23%) and the highest Sharpe in
the sweep (0.77). Same signal, same crises caught, but no premium tax. This is "own less, do not
insure" stated as cleanly as the data can state it.

Honesty bounds, unchanged from the rest of the study:
- **Sharpe is not the takeaway.** The whole frontier sits at 0.6-0.77 against buy-and-hold's 0.55,
  but that spread is inside the 0.24 standard error. The drawdown axis is the robust one.
- **The tail-catchers lean on 2008 and 2020.** The de-risk and vol-target drawdown reductions come
  disproportionately from being out during those two crashes. Two crises is a thin sample.
- **This maps a tradeoff, it does not certify a strategy.** No parameter was tuned on the result,
  but 74 strategies on one sample path is a search, and the frontier picks are the extreme order
  statistics of that search. Live, expect less.

## Method, and where it can be wrong

There is no free 21-year history of SPX option prices, so **the puts are modeled, not observed.**
That is the load-bearing weakness of this study and every retail version of it. What is real: the
SPY price path, VIX, and the 13-week bill. What is assumed:

- **Skew.** VIX is roughly at-the-money vol, but an OTM put is the most bid-up contract on the
  board and trades several vol points above it. Pricing protection at flat VIX undercharges the
  exact thing being bought. `--skew` is vol points per 1% OTM, default 0.5, so a 5% OTM put is
  priced 2.5 points over VIX. Scenario 4 sweeps it, and it moves the 5% OTM CAGR from 7.77% (flat
  VIX) to 3.23% (stressed surface). Half the apparent performance of an OTM hedge is an artifact of
  how you price its skew.
- **Term structure.** VIX is a 30-day number. The SPX term structure normally slopes up, so pricing
  a one-year put at VIX would hand every slow-rolling strategy a subsidy the real market never
  gives it. `--term-premium` adds vol points at a one-year tenor, default 2.5, scaled in sqrt(time)
  so a 30-day option is untouched. Without this correction the annual roll's Sharpe reads 0.71
  instead of 0.62.
- **Dividends** are a constant continuous yield (default 1.8%), credited to the share leg and fed
  to the pricer. Stored closes are raw prices, which is right for strikes and payoffs but pays no
  dividend.
- **Frictions are ignored.** No commissions, no bid-ask, no slippage on the roll. Every one of
  those makes the hedge worse, so the results here are an upper bound on how well protective puts
  perform.

The conditional study adds one more trap and one more defence. The trap is that **I already know
when the recessions were**, so any threshold picked by eye is the answer key, not a forecast. So:
every percentile is expanding-window (`_pit_high` shifts the threshold, and a test asserts that
truncating the series cannot change a past signal), every series is lagged by its real publication
delay, and the hedge decision is read only at roll dates. The defence is the **random-timing
control**: a signal must beat coin-flip hedging at its own duty cycle, because otherwise it is
just hedging less. Most retail versions of this study skip both and conclude that timing works.

Shiller's CAPE stops in 2024-06. The last 24 months are extended by holding real 10-year average
earnings constant and letting real price move the ratio, which is flagged in `signals.cape()`.

The book is always 100% invested and 100% hedged: it buys `V / (S + premium)` units of the
"share plus put" package, which is how it pays for the put without selling the shares the put is
supposed to cover. The put is marked to model daily against the live VIX, so drawdowns are what
the hedged book would actually print rather than what it settles at on expiry.

## Layout

```
bsm.py         vectorized Black-Scholes put, cross-checked against derive.black_scholes
data.py        aligned daily SPY / VIX / IRX out of storage
engine.py      the backtest: rolls, marks, skew, term structure, dividends
metrics.py     CAGR, vol, Sharpe, Sortino, drawdown, Calmar
scenarios.py   the four experiments
report.py      matplotlib figures
```

Invariants are pinned in `tests/test_protective_puts.py`: the vectorized pricer must match the
scalar model, a flat market must lose exactly the premium and nothing else, and a crash must be
floored by the strike. A backtest that is quietly wrong still prints a confident table.
