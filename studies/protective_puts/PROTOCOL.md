# Pre-registration: when is a protective put worth owning?

**Status: DRAFT, awaiting sign-off. Frozen before any analysis is run.**

Nothing in this document may be changed once the analysis starts. If a change is unavoidable, it
gets logged in the amendments section with a date and a reason, and the affected result is
reported as exploratory. The point of writing this down is to stop the analyst (me) from choosing
the hypothesis after seeing the answer, which is exactly what happened in the exploratory phase.

---

## 1. Why this document exists

An exploratory pass produced a leaderboard of ~30 strategies and a headline that vol targeting
beats buy-and-hold. That headline does not survive contact with statistics:

| Comparison | ΔSharpe | Memmel z | p | Bootstrap 95% CI |
|---|---|---|---|---|
| Vol target 15% vs buy-and-hold | +0.160 | +1.36 | 0.175 | [-0.06, +0.37] |
| Vol expansion + put vs buy-and-hold | +0.076 | +0.71 | 0.475 | [-0.08, +0.22] |

The standard error on a single 21-year Sharpe is 0.24, wider than any gap reported. The strategies
were selected after looking at the data, and generation 2 was bred from generation 1's winners on
the same sample. Those results are hypothesis generation. They are not findings, and they are
quarantined as such in the README.

## 2. The power problem, which drives everything else

Given the observed effect (ΔSharpe +0.160, paired SE 0.118, correlation 0.86):

| To detect it at p < 0.05 with | Years of data required |
|---|---|
| 50% power (just significant) | 44 |
| 80% power | **89** |

We have 21 years of modeled options, or 40 years of real ones. **Neither is enough to rank
strategies by Sharpe.** Any study whose primary output is "strategy X beats strategy Y" is dead on
arrival at this sample size, and pooling correlated US equity indices does not rescue it, because
four indices with 0.9 correlation are not four independent samples.

This is not a reason to give up. It is a reason to ask a question that a 40-year sample can
actually answer.

## 3. Primary hypothesis (the only one that counts)

> **H1. What forecasting precision must a discretionary bear-market call achieve before a
> protective put deployed on that call beats buy-and-hold, and how does that threshold move with
> deployment frequency, tenor and drawdown definition?**

This is a decision-theoretic estimand, not a horse race. It selects no strategy, so it cannot be
p-hacked by strategy selection: the forecaster is a hypothetical whose precision is an input, swept
across its whole range. The output is a threshold and a confidence interval around it, and the
question it answers is the one that matters to an operator: *is this bar reachable by a human with
a genuine macro read?*

**Estimand.** p\* = the smallest forecaster precision at which the hedged portfolio's Sharpe
exceeds buy-and-hold's, with a bootstrap confidence interval on p\*.

**Decision rule, fixed in advance.**
- If the lower bound of the CI on p\* sits **below 45%**, the conclusion is that conditional
  hedging is viable for a skilled discretionary forecaster, and we say so.
- If p\* exceeds **60%**, the conclusion is that it is not viable, because no published recession
  forecaster achieves 60% precision, and no signal in the exploratory phase came close.
- Between 45% and 60% the honest answer is "unresolved at this sample size", and we report that
  rather than picking a side.

**Falsification.** H1 is uninformative if p\* is not monotonically decreasing in precision (which
would mean the simulation is broken) or if the CI on p\* spans more than 30 points (which would
mean the sample cannot resolve it). Both are checked and reported.

## 4. Pre-specified parameters. No tuning, no exceptions.

Every number below is fixed now. None may be adjusted after seeing a result.

| Parameter | Values | Why these |
|---|---|---|
| Hedge instrument | CBOE PPUT (real, primary); modeled 1y 5% OTM put (secondary) | PPUT is traded prices, not my model |
| Deployment frequency | 1/4, 1/3, 1/2 of cycles | 1/3 is the operator's stated intuition; the others bracket it |
| Bear definition | 15% drawdown within horizon (primary); 10% and 20% (robustness) | 15% is the conventional threshold; the others test sensitivity |
| Precision grid | 0.20 to 1.00 in steps of 0.05 | Spans dart board to perfect foresight |
| Bootstrap | Stationary block, mean block 252d, 5,000 resamples | Block preserves vol clustering; 1y block is longer than any vol cycle |
| Risk-free | ^IRX, actual | Not a constant |
| Frictions | 1.0% of premium (commission + half-spread), applied to every option trade | Deliberately punitive; the hedge must survive it |

## 5. Data

| Series | Source | Range | Real or modeled |
|---|---|---|---|
| PPUT (5% OTM protective put index) | CBOE | 1986-06 to 2026-07, 10,080 days | **Real traded option prices** |
| CLL (collar index) | CBOE | 2008-08 onward | Real |
| SPX / SPY | yfinance, storage | 2001 onward | Real |
| VIX, VIX3M | yfinance, storage | 1990 / 2006 onward | Real |
| ^IRX (13-week bill) | yfinance, storage | 2001 onward | Real |
| Cross-market: QQQ + ^VXN | yfinance | 2001 onward | Real index, modeled option |

**Validation gate, run first.** The modeled engine (BSM + VIX + skew + term premium) is priced
against the real PPUT index over 1990-2026. If the modeled 5% OTM monthly put and PPUT disagree by
more than 1.5% annualized in return, **every modeled result in this repository is declared void**
and only PPUT-based results are reported. This gate runs before H1 and its outcome is reported
whichever way it falls.

## 6. Secondary, exploratory, and explicitly not for publication

The vol-clustering conditional hedge (the only mechanical signal that beat its random twins) is
re-tested on QQQ, which it was not developed on. This is labelled exploratory regardless of
outcome, because the sample cannot support a strategy claim (section 2). Any strategy ranking
reported at all carries a **Deflated Sharpe Ratio** adjusted for the 30 strategies already tried.
A cross-market confirmation would raise the prior; it would not constitute proof.

## 7. What will not be claimed, no matter what comes out

- That any strategy "beats" another on risk-adjusted return. The sample cannot support it.
- That any mechanical signal forecasts recessions. The exploratory phase found none that beat a
  dart board, and nothing here is designed to change that.
- That backtested results transfer to live trading. No slippage model survives contact with a
  real crash, when spreads widen exactly when you need to trade.
- Anything at all about a single-trade result. Every table reports hedge *counts*, not duty
  percentages, because a 5% duty over 21 annual cycles is one trade.

## 8. Analysis plan, in execution order

1. Fetch PPUT and CLL. Cache to `data/signals/`.
2. Run the validation gate (section 5). Report the divergence, whichever way it falls.
3. Compute the oracle bear labels on the frozen definitions.
4. Sweep precision x deployment x tenor, with the frozen friction model.
5. Bootstrap p\* and its CI.
6. Apply the section 3 decision rule. Report the verdict it gives, including "unresolved".
7. Run the secondary cross-market check. Label exploratory.

## 9. Amendments

None. Any change gets a dated entry here and demotes the affected result to exploratory.

## 10. Sign-off

- Analyst: pending
- Operator: pending
