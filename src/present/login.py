"""Sign-in and create-account page. Mock only: any email and password get you in, and nothing is
checked, sent or stored (present.auth). Forwards to ?next= when it names a real page."""

from __future__ import annotations

import streamlit as st

from present import auth, routes, theme

nxt = st.query_params.get("next", routes.DEFAULT)
target = f"{nxt if nxt in routes.STEMS else routes.DEFAULT}.py"
if auth.user():
    st.switch_page(target)

st.markdown(
    """
<style>
header[data-testid="stHeader"] { display: none !important; }
[data-testid="stSidebar"], [data-testid="stExpandSidebarButton"] { display: none !important; }
[data-testid="stMainBlockContainer"] { max-width: none !important; padding: 0 !important; }
[data-testid="stMainBlockContainer"] [data-testid="stHorizontalBlock"] { gap: 0; }
.st-key-auth-left { min-height: 100vh; padding: 32px 24px; }
@media (min-width: 640px) { .st-key-auth-left { padding: 32px 48px; } }
[data-testid="stLayoutWrapper"]:has(> .st-key-auth-form) { flex: 1; display: flex; }
.st-key-auth-form { flex: 1; justify-content: center; width: 100%; max-width: 448px;
  margin: 0 auto; padding: 48px 0; }
.auth-logo { display: inline-flex; align-items: center; gap: 10px; font-size: 15px; font-weight: 600;
  letter-spacing: -0.025em; color: var(--fg) !important; text-decoration: none; }
.auth-logo-mark { display: grid; place-items: center; width: 32px; height: 32px; border-radius: 6px;
  background: var(--fg); color: #fff; }
.auth-title { margin: 32px 0 0; font-family: var(--serif); font-weight: 400; font-size: 2.25rem;
  letter-spacing: -0.025em; color: var(--fg); }
.auth-sub { margin: 12px 0 8px; color: var(--fg-muted); line-height: 1.625; }
.auth-panel { min-height: 100vh; box-sizing: border-box; background: var(--fg); color: #fff;
  padding: 48px; display: flex; flex-direction: column; justify-content: space-between; }
.auth-panel h2 { margin: 0; max-width: 34rem; font-family: var(--serif); font-weight: 400; font-size: 3rem;
  line-height: 1.08; letter-spacing: -0.025em; color: #fff; text-wrap: balance; }
.auth-panel p { margin: 24px 0 0; max-width: 24rem; font-size: 1.125rem; line-height: 1.625;
  color: rgba(255,255,255,0.7); }
.auth-panel .auth-small { margin: 0; font-size: 0.875rem; color: rgba(255,255,255,0.6); }
@media (max-width: 1023px) { .auth-panel { display: none; } }
</style>
""",
    unsafe_allow_html=True,
)

left, right = st.columns(2, gap=None)

with left, st.container(key="auth-left"):
    st.markdown(
        f'<a class="auth-logo" href="/" target="_self"><span class="auth-logo-mark">'
        f"{theme.icon(theme.MARK, 18)}</span>Derivative-Implied Pricing</a>",
        unsafe_allow_html=True,
    )
    with st.container(key="auth-form"):
        start = "Create account" if st.query_params.get("mode") == "signup" else "Sign in"
        mode = st.segmented_control(
            "Mode", ["Sign in", "Create account"], default=start, key="auth_mode",
            label_visibility="collapsed", width="stretch",
        ) or start
        signup = mode == "Create account"
        st.html(
            f'<h1 class="auth-title">{"Create your account" if signup else "Sign in"}</h1>'
            f'<p class="auth-sub">{"Set up access to the dashboard." if signup else "Welcome back. Pick up where the market left off."}</p>'
        )
        with st.form("auth", border=False):
            if signup:
                st.text_input("Name", placeholder="Your name")
            email = st.text_input("Email", placeholder="you@example.com")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button(
                "Create account" if signup else "Sign in", type="primary", width="stretch",
                icon=":material/arrow_forward:", icon_position="right",
            )
        if submitted:
            if "@" not in email or not password:
                st.error("Enter an email address and a password.")
            else:
                auth.sign_in(email)
                st.switch_page(target)
        if st.button("Continue with the demo account", width="stretch"):
            auth.sign_in("demo@example.com")
            st.switch_page(target)
        st.caption("Mock sign-in. Any email and password work. Nothing is verified, sent or stored.")

with right:
    st.html(
        '<div class="auth-panel">'
        '<p class="auth-small">Derivative-Implied Pricing &middot; Dashboard</p>'
        "<div><h2>Every expiry. Every strike. One view of what is priced.</h2>"
        "<p>Live market and derivatives analysis for options and futures traders.</p></div>"
        '<p class="auth-small">Context, not a forecast. Not investment advice.</p>'
        "</div>"
    )
