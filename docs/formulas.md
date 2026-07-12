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

*2026-07-10: initial formula reference.*
