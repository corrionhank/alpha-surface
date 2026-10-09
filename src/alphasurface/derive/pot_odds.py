"""Pot odds for defined-risk trades.

Poker: you call C to win a pot of P, so you need C/(P+C) equity to break even. A trade risking
R to make W is the same bet laid at W-to-R odds, and the breakeven win rate falls out of the
payoff alone: p* = R/(R+W). Nothing about the market enters that number.

Whether the bet is worth taking is a separate question, and it turns entirely on how your
estimate of the true win probability p compares to p*. See docs/formulas.md section 11.

Amounts are per share. An option contract covers 100, so scale at the display layer.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Odds:
    risk: float  # R, max loss
    reward: float  # W, max gain
    ratio: float  # b = W/R, the odds you are laid
    breakeven: float  # p*, the win rate that makes EV zero


def from_payoff(risk: float, reward: float) -> Odds:
    if risk <= 0 or reward <= 0:
        raise ValueError("risk and reward must both be positive")
    return Odds(risk, reward, reward / risk, risk / (risk + reward))


def from_credit_vertical(width: float, credit: float) -> Odds:
    """Short vertical: keep the credit, or lose the rest of the width.

    p* = (width - credit) / width, so the credit as a fraction of the width is exactly the
    market's quoted price of the spread finishing at max loss.
    """
    if not 0 < credit < width:
        raise ValueError("credit must be between 0 and width")
    return from_payoff(width - credit, credit)


def from_debit_vertical(width: float, debit: float) -> Odds:
    """Long vertical: pay the debit to win the rest of the width."""
    if not 0 < debit < width:
        raise ValueError("debit must be between 0 and width")
    return from_payoff(debit, width - debit)


def expected_value(p: float, odds: Odds) -> float:
    """EV = p*W - (1-p)*R. Equivalently (R + W) * edge, which is the identity tested."""
    return p * odds.reward - (1 - p) * odds.risk


def edge(p: float, odds: Odds) -> float:
    """How far your win probability clears the breakeven. Positive edge means positive EV."""
    return p - odds.breakeven


def kelly(p: float, odds: Odds) -> float:
    """Log-growth-maximizing stake, f* = p - (1-p)/b. Zero when there is no edge.

    Full Kelly assumes p is exactly right and is brutal when it is not, so it is an upper
    bound on sizing rather than a target.
    """
    return max(p - (1 - p) / odds.ratio, 0.0)
