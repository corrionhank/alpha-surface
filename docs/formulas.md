# Quant and Volatility Formula Reference

Calculation reference for the metrics this dashboard shows or will show. Each entry gives
the formula and a short note. Math renders in the in-app docs portal (KaTeX) and on GitHub.

Every metric here is descriptive. It summarizes what has happened or what the market has
priced. None is a forecast or a signal (Principle 2).

## Notation

| Symbol | Meaning |
|--------|---------|
| $P_t$ | price (close) at time $t$ |
| $r_t$ | period return at $t$ (simple unless noted) |
| $\mu,\ \sigma$ | mean and standard deviation of returns |
| $R_f$ | risk-free rate (per period) |
| $S,\ K$ | spot and strike price |
| $T$ | time to expiry, in years |
| $r,\ q$ | risk-free rate, dividend yield (continuous, annual) |
| $\sigma$ | volatility (annualized, unless a per-period estimator) |
| $\Phi,\ \phi$ | standard normal CDF and PDF |
| $P$ | periods per year (annualization factor) |

Annualization factor $P$ (periods per year): daily $=252$, weekly $=52$, monthly $=12$,
1h RTH bars $=6.5\times252=1638$ (the value the app uses for hourly realized vol).
Volatility scales with $\sqrt{P}$, return with $P$.

---

## 1. Returns

$$r_t^{\text{simple}} = \frac{P_t}{P_{t-1}} - 1
\qquad
r_t^{\text{log}} = \ln\!\left(\frac{P_t}{P_{t-1}}\right)$$

Log returns are time-additive (used for volatility). Cumulative return over a window:
$\displaystyle \prod_t (1 + r_t^{\text{simple}}) - 1$.

CAGR (compound annual growth rate):

$$\text{CAGR} = \left(\frac{P_{\text{end}}}{P_{\text{start}}}\right)^{1/y} - 1
\qquad y = \text{years elapsed}$$

---

## 2. Historical / realized volatility (HV, RV)

Close-to-close, annualized. The standard estimator:

$$\sigma_{\text{ann}} = \sqrt{\frac{1}{N-1}\sum_{t=1}^{N}\left(r_t^{\text{log}} - \bar r\right)^2}\ \times\ \sqrt{P}$$

$n$-day HV uses the last $n$ log returns. This is the app's realized vol metric (with $P$
per the interval).

EWMA (RiskMetrics) weights recent returns more, with $\lambda = 0.94$ daily:

$$\sigma_t^2 = \lambda\,\sigma_{t-1}^2 + (1-\lambda)\,r_{t-1}^2$$

Range-based estimators use the whole bar, not just the close:

$$\sigma_{\text{Park}}^2 = \frac{1}{4N\ln 2}\sum_{i=1}^{N}\ln^2\!\frac{H_i}{L_i}$$

$$\sigma_{\text{GK}}^2 = \frac{1}{N}\sum_{i=1}^{N}\left[\tfrac{1}{2}\ln^2\!\frac{H_i}{L_i} - (2\ln 2 - 1)\,\ln^2\!\frac{C_i}{O_i}\right]$$

Parkinson (high-low) and Garman-Klass (adds open/close). Annualize by $\times\sqrt{P}$.
Yang-Zhang extends these to be drift- and gap-independent.

---

## 3. Implied volatility and option pricing

Black-Scholes-Merton (European, continuous dividend $q$):

$$d_1 = \frac{\ln(S/K) + (r - q + \tfrac{1}{2}\sigma^2)T}{\sigma\sqrt{T}}
\qquad d_2 = d_1 - \sigma\sqrt{T}$$

$$C = S e^{-qT}\Phi(d_1) - K e^{-rT}\Phi(d_2)
\qquad P = K e^{-rT}\Phi(-d_2) - S e^{-qT}\Phi(-d_1)$$

Put-call parity: $C - P = S e^{-qT} - K e^{-rT}$.

Implied volatility is the $\sigma$ that makes the BS price equal the market price. No closed
form, so solve numerically (Newton-Raphson using vega, or bisection).

Greeks:

$$\Delta_{\text{call}} = e^{-qT}\Phi(d_1)
\qquad
\Gamma = \frac{e^{-qT}\phi(d_1)}{S\,\sigma\sqrt{T}}
\qquad
\mathcal{V} = S e^{-qT}\phi(d_1)\sqrt{T}$$

$$\Theta_{\text{call}} = -\frac{S e^{-qT}\phi(d_1)\sigma}{2\sqrt{T}} - rKe^{-rT}\Phi(d_2) + qSe^{-qT}\Phi(d_1)
\qquad
\rho_{\text{call}} = KTe^{-rT}\Phi(d_2)$$

Vega is per $1.00$ of vol (divide by 100 for per vol-point). Theta per year (divide by 365 for per day).

IVx / VIX-style index: model-free 30-day implied variance from a strip of OTM options:

$$\sigma^2 = \frac{2}{T}\sum_i \frac{\Delta K_i}{K_i^2}\,e^{rT}\,Q(K_i)\ -\ \frac{1}{T}\left(\frac{F}{K_0} - 1\right)^2$$

$Q(K_i)$ is the mid price of the OTM option at strike $K_i$, $F$ the forward, $K_0$ the first
strike below $F$. $\text{IVx} = 100\,\sigma$, interpolated to a constant 30-day maturity.

Delta as probability (premium-selling shortcut): $\lvert\Delta\rvert \approx P(\text{ITM at expiry})$,
$16\Delta \approx 1\sigma$, $5\Delta \approx 2\sigma$, probability of touch $\approx 2\lvert\Delta\rvert$.

---

## 4. IV context metrics

IV Rank, where current IV sits in its 52-week range:

$$\text{IVR} = \frac{\text{IV} - \text{IV}^{52w}_{\min}}{\text{IV}^{52w}_{\max} - \text{IV}^{52w}_{\min}}$$

IV Percentile, fraction of the last year spent below current IV (steadier than IVR after a spike):

$$\text{IVP} = \frac{\#\{d \in \text{last }252 : \text{IV}_d < \text{IV}_{\text{now}}\}}{252}$$

Variance risk premium (VRP), implied minus realized. The premium sellers harvest:

$$\text{VRP} = \sigma_{\text{IV}} - \sigma_{\text{HV}}$$

Shown in context via its own percentile over trailing history.

---

## 5. Expected move

1-standard-deviation move to a horizon (the cone's half-width):

$$\text{EM}_{1\sigma} = S \cdot \sigma \cdot \sqrt{T}, \qquad T = \frac{\text{DTE}}{365}$$

ATM-straddle approximation: $\text{EM}_{1\sigma} \approx 0.85 \times \text{ATM straddle price}$.

Daily shortcut (why traders eyeball $\text{VIX}/16$): $\sqrt{252}\approx 15.87$, so the SPX
1-day expected move $\approx \dfrac{\text{VIX}}{16}\%$.

---

## 6. Skew and term structure

25-delta skew (put richness, crash insurance demand):

$$\text{skew}_{25\Delta} = \text{IV}(25\Delta\ \text{put}) - \text{IV}(25\Delta\ \text{call})$$

Risk reversal $= \text{IV}(25\Delta\ \text{call}) - \text{IV}(25\Delta\ \text{put})$ (sign-flipped convention).

Term-structure slope, contango (normal) vs. backwardation (fear):

$$\text{slope} = \text{IV}_{\text{back}} - \text{IV}_{\text{front}}
\qquad
\text{contango}\% = \frac{F_2 - F_1}{F_1}\times 100$$

For the VIX complex, $\text{VIX3M} - \text{VIX} > 0$ is contango.

---

## 7. Moving averages and technicals

Simple (SMA) and exponential (EMA):

$$\text{SMA}_n = \frac{1}{n}\sum_{i=0}^{n-1} P_{t-i}
\qquad
\text{EMA}_t = \alpha P_t + (1-\alpha)\,\text{EMA}_{t-1},\quad \alpha = \frac{2}{n+1}$$

Distance from an MA (regime/stretch): $\dfrac{P_t - \text{MA}_n}{\text{MA}_n}\times 100$ (e.g. price vs. 50/200-DMA).

Bollinger Bands: $\text{SMA}_n \pm k\,\sigma_n$ (typically $n=20,\ k=2$).

MACD: $\text{EMA}_{12} - \text{EMA}_{26}$, signal $= \text{EMA}_9(\text{MACD})$, histogram $= \text{MACD} - \text{signal}$.

RSI (Wilder, $n=14$): $\text{RSI} = 100 - \dfrac{100}{1 + \text{RS}}$, where $\text{RS} = \dfrac{\text{avg gain}}{\text{avg loss}}$.

ATR (average true range): $\text{TR}_t = \max\big(H_t - L_t,\ \lvert H_t - C_{t-1}\rvert,\ \lvert L_t - C_{t-1}\rvert\big)$, ATR is the Wilder MA of TR.

---

## 8. Risk-adjusted performance

Sharpe ratio (annualized), excess return per unit total vol:

$$\text{Sharpe} = \frac{\bar r - R_f}{\sigma_r}\,\sqrt{P}$$

Sortino ratio penalizes only downside deviation $\sigma_d$:

$$\text{Sortino} = \frac{\bar r - \text{MAR}}{\sigma_d}\sqrt{P}
\qquad
\sigma_d = \sqrt{\frac{1}{N}\sum_t \min(r_t - \text{MAR},\,0)^2}$$

Calmar $= \dfrac{\text{CAGR}}{\lvert\text{MaxDD}\rvert}$. Information ratio $= \dfrac{\bar r_p - \bar r_b}{\sigma(r_p - r_b)}\sqrt{P}$. Treynor $= \dfrac{\bar r_p - R_f}{\beta}$.

Maximum drawdown:

$$\text{MaxDD} = \min_{t}\left(\frac{P_t}{\max_{s\le t} P_s} - 1\right)$$

---

## 9. Cross-asset and statistics

Beta and CAPM alpha (vs. a benchmark $m$):

$$\beta = \frac{\operatorname{Cov}(r_a, r_m)}{\operatorname{Var}(r_m)}
\qquad
\alpha = \bar r_a - \big[R_f + \beta(\bar r_m - R_f)\big]$$

Correlation $\rho = \dfrac{\operatorname{Cov}(X,Y)}{\sigma_X\sigma_Y}$. Z-score $z = \dfrac{x - \mu}{\sigma}$.

Percentile rank (context for any raw number): $\dfrac{\#\{x_i < x\}}{N}$.

Skewness and excess kurtosis (tail shape):

$$\text{skew} = \frac{\tfrac{1}{N}\sum (x_i - \mu)^3}{\sigma^3}
\qquad
\text{kurt} = \frac{\tfrac{1}{N}\sum (x_i - \mu)^4}{\sigma^4} - 3$$

---

## 10. Tail risk and risk-neutral density (Phase 2)

Historical VaR at confidence $\alpha$ is the $(1-\alpha)$ quantile of the return distribution
(a loss threshold). CVaR / Expected Shortfall is the mean loss beyond VaR:

$$\text{CVaR}_\alpha = \mathbb{E}\big[\,L \mid L \ge \text{VaR}_\alpha\,\big]$$

Project rule: no Gaussian parametric VaR. Phase 2 uses empirical/historical VaR and EVT
(peaks-over-threshold plus Generalized Pareto) for the tail.

Risk-neutral density (Breeden-Litzenberger), what the option surface implies about the
terminal price distribution:

$$f(K) = e^{rT}\,\frac{\partial^2 C}{\partial K^2}$$

Smooth the IV surface before differentiating twice (raw prices are too noisy).

---

## 11. Pot odds and edge

A defined-risk trade risking $R$ to make $W$ is a bet laid at $b = W/R$. The win rate that makes
it a coin flip in expectation depends on the payoff alone:

$$p^* = \frac{R}{R + W} = \frac{1}{1 + b}$$

This is the poker calculation: call $C$ to win a pot of $P$ and you need $C/(P+C)$ equity. Nothing
about the market or the underlying enters $p^*$. Expected value and edge follow:

$$\text{EV} = pW - (1-p)R \qquad \text{edge} = p - p^*$$

The two collapse into one identity, so a positive edge and a positive EV are the same statement:

$$\text{EV} = (R + W)\,(p - p^*)$$

Options quote the odds directly. A vertical of width $X$ sold for credit $c$ keeps $W = c$ and
risks $R = X - c$:

$$p^*_{\text{credit}} = \frac{X - c}{X} \qquad p^*_{\text{debit}} = \frac{d}{X}$$

So the credit as a fraction of the width is the market's own price of the spread finishing at max
loss. Bought instead for debit $d$, the payoff flips: $R = d$, $W = X - d$.

**The equity side.** $p^*$ is free, but $p$ has to be estimated, and Black-Scholes already supplies
one under the risk-neutral measure (section 3):

$$P(S_T > K) = \Phi(d_2) \qquad P(S_T < K) = \Phi(-d_2)$$

Evaluate it at implied vol and you recover the market's odds, which is why a fairly priced spread
has $p \approx p^*$ and no edge. Evaluate the same expression at realized vol instead and you get the
odds under the historical distribution. The gap between the two is the variance risk premium
(section 4): when $\sigma_{\text{IV}} > \sigma_{\text{RV}}$, the seller is laid better odds than the
risk warrants. Pot odds is the decision rule that VRP feeds.

Kelly gives the log-growth-maximizing stake for an edge:

$$f^* = \frac{pb - (1-p)}{b} = p - \frac{1-p}{b}$$

Full Kelly assumes $p$ is exactly right and punishes overestimation hard, so treat it as a ceiling
on size, not a target. Half-Kelly is the usual concession to the fact that $p$ is a guess.

---

## 12. Regime flag

Shorthand for the state strip, not a signal. The VIX level picks the base bucket:

$$\text{VIX} < 14:\ \text{low\_vol} \qquad 14\text{--}20:\ \text{normal} \qquad
20\text{--}28:\ \text{elevated} \qquad \ge 28:\ \text{stress}$$

Backwardation ($\text{VIX3M} < \text{VIX}$, section 6) and negative VRP
($\sigma_{\text{RV21}} > \text{VIX}$, section 4) each escalate one bucket, capped at stress.
Both mean the market is being repriced faster than the back end or the option premium admits.

---

## 13. Single-contract metrics

What the options chain page shows for one selected contract. Spot $S$, strike $K$, calendar days
to expiry $D$, $T = D/365$. Everything is per share; one contract is 100 shares.

**Mark.** The mid of a two-sided market, else the last print (flagged stale):

$$m = \tfrac{1}{2}(b + a) \quad \text{if } b > 0 \text{ and } a > b, \qquad m = \text{last otherwise}$$

**Intrinsic and extrinsic.** Intrinsic is spot-based, what exercising now is worth:

$$\text{intrinsic}_{\text{call}} = \max(S - K, 0) \qquad \text{intrinsic}_{\text{put}} = \max(K - S, 0)$$

$$\text{extrinsic} = m - \text{intrinsic} \qquad \text{extrinsic per day} = \frac{m - \text{intrinsic}}{D}$$

Extrinsic per day is the straight-line decay to expiry. Black-Scholes theta at the contract's IV
(section 3, divided by 365) is shown beside it; near expiry the two diverge because time value
does not decay in a straight line. Extrinsic can be negative: a European-style price sits below
spot intrinsic when carry is large (the strike is paid later, discounted), and on a listed American
option a negative value usually means a stale or crossed quote. It is shown, not hidden.

**Breakeven and odds.** For the buyer at expiry:

$$\text{BE}_{\text{call}} = K + m \qquad \text{BE}_{\text{put}} = K - m \qquad
\text{move} = \frac{\text{BE}}{S} - 1$$

Probability ITM is $\Phi(d_2)$ for a call and $\Phi(-d_2)$ for a put at the contract's IV
(section 11): risk-neutral odds, not a forecast. IV and Greeks are solved from $m$ (section 3).

**Versus realized vol.** Price the same contract at trailing realized vol $\sigma_{\text{RV}}$
(section 2, close-to-close over 10, 21 or 63 sessions):

$$V_{\text{RV}} = \text{BS}(S, K, T, r, q, \sigma_{\text{RV}}) \qquad
\text{gap} = m - V_{\text{RV}} \qquad \Delta\sigma = 100\,(\sigma_{\text{IV}} - \sigma_{\text{RV}})$$

Price rises with vol, so $\text{sign}(\text{gap}) = \text{sign}(\Delta\sigma)$. The label uses vol
points so one tolerance means the same thing across strikes, where the dollar gap shrinks with vega:

$$\Delta\sigma > 1:\ \text{overpriced vs realized} \qquad \Delta\sigma < -1:\ \text{underpriced vs realized}
\qquad \text{else in line}$$

Realized vol is backward-looking and the market prices the vol it expects ahead, so this is the
variance risk premium for one contract (section 4), not a signal.

**Seller yield.** With fill $p$ (the bid by default, the mark on request), return on the cash at
work. Covered call, cash at work $S - p$:

$$r_{\text{unchanged}} = \frac{p - \text{intrinsic}}{S - p} \qquad r_{\text{called}} = \frac{p + K - S}{S - p}$$

Cash-secured put, cash at work $K - p$:

$$r_{\text{unchanged}} = \frac{p - \text{intrinsic}}{K - p} \qquad r_{\text{not assigned}} = \frac{p}{K - p}$$

If unchanged keeps only the time value: an in-the-money option is exercised and hands its
intrinsic back, so counting intrinsic as yield overstates it. For an out-of-the-money contract the
two rows of a put coincide. Annualized two ways:

$$r_{\text{simple}} = r \cdot \frac{365}{D} \qquad \text{APY} = (1 + r)^{365/D} - 1$$

APY compounds the same trade back to back for a year, which no one can do at the same price, so
read it as a ceiling. Commissions, dividends and early assignment are ignored.

---

## 14. Simulation and scenarios

What the scenarios page computes. Time steps are trading days, $\Delta t = 1/252$; $\mu$ is the
annual price drift (risk-neutral default $r - q$), $\sigma$ the annual vol, $Z \sim N(0, 1)$.

**Geometric Brownian motion**, stepped exactly in log space:

$$\ln S_{t+\Delta t} = \ln S_t + \left(\mu - \tfrac{1}{2}\sigma^2\right)\Delta t + \sigma\sqrt{\Delta t}\,Z$$

$$E[S_T] = S_0 e^{\mu T} \qquad \text{median}(S_T) = S_0 e^{(\mu - \sigma^2/2)T}$$

The gap between the two is volatility drag: the average grows at $\mu$, the typical path at
$\mu - \sigma^2/2$.

**Jump diffusion** (Merton). Jumps arrive at rate $\lambda$ a year with log size
$Y \sim N(m_J, s_J^2)$; the compensator keeps the mean at $S_0 e^{\mu T}$:

$$k = e^{m_J + s_J^2/2} - 1 \qquad
\ln \frac{S_{t+\Delta t}}{S_t} = \left(\mu - \lambda k - \tfrac{1}{2}\sigma^2\right)\Delta t
+ \sigma\sqrt{\Delta t}\,Z + \sum_{j=1}^{N_t} Y_j, \quad N_t \sim \text{Poisson}(\lambda\Delta t)$$

**Historical bootstrap.** Standardize stored daily log returns, $z_i = (r_i - \bar r)/s_r$,
resample them in blocks of $b$ consecutive sessions, and rescale to the chosen drift and vol:

$$\ln \frac{S_{t+\Delta t}}{S_t} = \left(\mu - \tfrac{1}{2}\sigma^2\right)\Delta t + \sigma\sqrt{\Delta t}\,z^*$$

History supplies the shape (skew, fat tails, short-range clustering); the inputs supply the level.

**Reading the paths.** Percentile bands per step; $P(\text{finish up}) = \frac{1}{N}\sum
\mathbb{1}[S_T > S_0]$; touch probability $\frac{1}{N}\sum \mathbb{1}[\max_t S_t \ge L]$ (or $\min$
for a level below spot), roughly twice the probability of finishing beyond $L$ (reflection
principle); worst drawdown per path $\min_t \left(S_t / \max_{u \le t} S_u - 1\right)$.

**Position P&L.** Legs are priced with section 3 at implied vol $\sigma_{\text{IV}}$ and marked at
the horizon $h$ with $D - h$ sessions left, $T = (D - h)/252$:

$$\text{P\&L} = \sum_{\text{legs}} q_\ell \cdot 100 \cdot \left[V_\ell(S_h, T) - V_\ell(S_0, D/252)\right]$$

**Value at risk and expected shortfall**, read straight off the simulated outcomes, no normal
approximation (the project rule in section 10):

$$\text{VaR}_\alpha = -Q_{1-\alpha}(\text{P\&L}) \qquad
\text{ES}_\alpha = -E\left[\text{P\&L} \mid \text{P\&L} \le Q_{1-\alpha}\right]$$

**Fair-game check.** Simulate with $\sigma = \sigma_{\text{IV}}$ and $\mu = r - q$ and the
expected P&L is close to zero, the carry on the premium aside. The difference from the expected
P&L at the chosen model and realized vol is the edge from vol, drift or tail shape, before costs.

**Delta-hedged option.** Buy ($s = 1$) or sell ($s = -1$) one option at $\sigma_{\text{IV}}$ and
hold $-s\,\Delta_i$ shares, $\Delta_i$ the Black-Scholes delta at $\sigma_{\text{IV}}$, rebalanced
every $k$ sessions. Each holding earns its price change less carry, compounded to expiry:

$$\text{P\&L} = s\left[\text{payoff}(S_T) - V_0 e^{rT}\right]
+ \sum_i h_i\left[S_{i+1} - S_i e^{(r-q)\Delta t}\right] e^{r(T - t_{i+1})}$$

In the limit of continuous hedging the mean is approximately

$$E[\text{P\&L}] \approx s \cdot \tfrac{1}{2}\sum_i \Gamma_i S_i^2 \left(\sigma_{\text{RV}}^2 - \sigma_{\text{IV}}^2\right)\Delta t$$

so a hedged option is a position in variance: it breaks even where realized equals implied.

**Sizing.** A bet that wins $b$ per 1 staked with probability $p$, staking fraction $f$:

$$W_{n+1} = W_n(1 + f b) \text{ or } W_n(1 - f) \qquad
g(f) = p\ln(1 + f b) + (1 - p)\ln(1 - f) \qquad f^* = p - \frac{1 - p}{b}$$

$g$ is the growth of the median bankroll. It peaks at Kelly $f^*$ and turns negative near
$2f^*$, while the mean bankroll keeps rising with $f$, carried by a few lucky paths.

**Replay.** A historical window rescaled to today's spot,
$S_t^{\text{replay}} = S_0 \cdot P_{t_0 + t}/P_{t_0}$, with implied vol scaled by VIX over the same
window, $\sigma_t = \sigma_{\text{IV}} \cdot \text{VIX}_{t_0+t}/\text{VIX}_{t_0}$.


---

*2026-07-10: initial formula reference.*
*2026-07-13: section 11, pot odds.*
*2026-08-09: section 12, regime flag.*
*2026-10-07: section 13, single-contract metrics.*
*2026-10-07: section 14, simulation and scenarios.*
