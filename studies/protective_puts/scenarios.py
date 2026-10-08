"""The experiments.

Scenario 1, the ladder: does the strike you buy change the answer?
Scenario 2, the cadence: is the bleed coming from how often you roll?
Scenario 3, the crises: what did the protection actually buy when it mattered?
Scenario 4, the skew sweep: how much of the conclusion rests on the pricing assumption?
"""

from __future__ import annotations

from studies.protective_puts.engine import ROLLS, Strategy

BUY_AND_HOLD = Strategy("Buy and hold SPY", hedged=False)

LADDER = [
    BUY_AND_HOLD,
    Strategy("Put ATM, monthly", moneyness=0.00, roll_days=ROLLS["monthly"]),
    Strategy("Put 5% OTM, monthly", moneyness=0.05, roll_days=ROLLS["monthly"]),
    Strategy("Put 10% OTM, monthly", moneyness=0.10, roll_days=ROLLS["monthly"]),
]

CADENCE = [
    BUY_AND_HOLD,
    Strategy("Put 5% OTM, monthly", moneyness=0.05, roll_days=ROLLS["monthly"]),
    Strategy("Put 5% OTM, quarterly", moneyness=0.05, roll_days=ROLLS["quarterly"]),
    Strategy("Put 5% OTM, annual", moneyness=0.05, roll_days=ROLLS["annual"]),
]

# Peak-to-trough windows, the tails the hedge is bought for.
CRISES = {
    "GFC 2008": ("2007-10-09", "2009-03-09"),
    "COVID 2020": ("2020-02-19", "2020-03-23"),
    "Bear 2022": ("2022-01-03", "2022-10-12"),
}

# Vol points per 1% OTM. 0 is flat VIX (the flattering assumption), 0.5 is roughly what SPX
# 30-day skew has actually traded at, 1.0 is a stressed surface.
SKEW_SWEEP = [0.0, 0.25, 0.5, 0.75, 1.0]
