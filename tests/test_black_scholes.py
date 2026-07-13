"""Black-Scholes accuracy tests: textbook anchors, put-call parity, edges, and the
10 documented scenarios used to sanity-check the pricing page."""

from __future__ import annotations

import math

import pytest

from derive import black_scholes as bs

# (name, S, K, T, r, sigma, q, expected_call, expected_put)
SCENARIOS = [
    ("ATM baseline", 100, 100, 1.00, 0.05, 0.20, 0.00, 10.4506, 5.5735),
    ("Hull 6-month", 42, 40, 0.50, 0.10, 0.20, 0.00, 4.7594, 0.8086),
    ("Deep ITM call", 150, 100, 1.00, 0.05, 0.25, 0.00, 55.2781, 0.4010),
    ("Deep OTM call", 80, 120, 0.50, 0.05, 0.30, 0.00, 0.2966, 37.3337),
    ("Near expiry", 100, 100, 0.02, 0.05, 0.20, 0.00, 1.1785, 1.0785),
    ("High vol 80%", 100, 100, 1.00, 0.05, 0.80, 0.00, 32.8210, 27.9439),
    ("Zero-vol edge", 100, 90, 1.00, 0.05, 0.00, 0.00, 14.3894, 0.0000),
    ("Dividend 3%", 100, 100, 1.00, 0.05, 0.20, 0.03, 8.6525, 6.7309),
    ("High rate 15%", 100, 100, 1.00, 0.15, 0.20, 0.00, 16.3560, 2.4268),
    ("Long-dated 2y OTM", 100, 110, 2.00, 0.05, 0.25, 0.00, 14.2340, 13.7661),
]


@pytest.mark.parametrize("name,S,K,T,r,sigma,q,call,put", SCENARIOS)
def test_scenarios(name, S, K, T, r, sigma, q, call, put):
    assert bs.price(S, K, T, r, sigma, q, "call") == pytest.approx(call, abs=1e-3)
    assert bs.price(S, K, T, r, sigma, q, "put") == pytest.approx(put, abs=1e-3)


def test_textbook_anchors():
    # Hull, Options Futures and Other Derivatives: call 4.76, put 0.81.
    assert bs.price(42, 40, 0.5, 0.10, 0.20, 0.0, "call") == pytest.approx(4.76, abs=1e-2)
    assert bs.price(42, 40, 0.5, 0.10, 0.20, 0.0, "put") == pytest.approx(0.81, abs=1e-2)


@pytest.mark.parametrize(
    "S,K,T,r,sigma,q",
    [(100, 100, 1, 0.05, 0.2, 0), (120, 100, 0.5, 0.03, 0.4, 0.02), (80, 90, 2, 0.06, 0.25, 0)],
)
def test_put_call_parity(S, K, T, r, sigma, q):
    c = bs.price(S, K, T, r, sigma, q, "call")
    p = bs.price(S, K, T, r, sigma, q, "put")
    assert c - p == pytest.approx(S * math.exp(-q * T) - K * math.exp(-r * T), abs=1e-9)


def test_zero_vol_is_discounted_intrinsic():
    call = bs.price(100, 90, 1.0, 0.05, 0.0, 0.0, "call")
    assert call == pytest.approx(100 - 90 * math.exp(-0.05), abs=1e-9)
    assert bs.price(100, 90, 1.0, 0.05, 0.0, 0.0, "put") == 0.0


def test_at_expiry_is_intrinsic():
    assert bs.price(110, 100, 0.0, 0.05, 0.2, 0.0, "call") == pytest.approx(10.0)
    assert bs.price(90, 100, 0.0, 0.05, 0.2, 0.0, "put") == pytest.approx(10.0)


def test_call_delta_bounds_and_gamma_positive():
    g = bs.greeks(100, 100, 1.0, 0.05, 0.2, 0.0, "call")
    assert 0.0 < g.delta < 1.0
    assert g.gamma > 0 and g.vega > 0
