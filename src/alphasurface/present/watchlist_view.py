"""The watchlist as a native list: click a row to open it, right-click (or the row's menu button,
or Shift+F10) for open, replace, move and remove, and an add row at the bottom that appends.

A Streamlit v2 component: plain HTML, CSS and JS mounted in the page (no iframe), so it inherits
the theme's CSS variables and fonts. It only reports what the user did; the caller applies it to
the stored list (present.watchlist) and passes the new rows back in.
"""

from __future__ import annotations

import math
from typing import TypedDict

import pandas as pd
import streamlit as st


class Row(TypedDict):
    sym: str  # stored symbol, e.g. ^VIX
    label: str  # shown, e.g. VIX
    last: float | None
    chg: float | None  # fraction, e.g. 0.0042
    spark: list[float]  # recent closes, oldest first


CSS = """
:host { display: block; }
.wl { font-variant-numeric: tabular-nums; color: var(--fg); }
ul { list-style: none; margin: 0; padding: 0; }
.row { position: relative; display: grid; grid-template-columns: 1fr 64px 76px 22px; align-items: center;
  gap: 10px; padding: 9px 4px 9px 10px; margin: 0 -10px; border-radius: 4px; cursor: pointer;
  outline: none; user-select: none; }
.row:hover, .row.menu-open { background: var(--surface-raised); }
.row:focus-visible { box-shadow: inset 0 0 0 2px var(--accent); }
.row.sel { background: var(--surface-raised); box-shadow: inset 2px 0 0 var(--accent); }
.row.sel:focus-visible { box-shadow: inset 2px 0 0 var(--accent), inset 0 0 0 2px var(--accent); }
.sym { font-size: 13.5px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.px { display: flex; flex-direction: column; align-items: flex-end; line-height: 1.25; }
.px b { font-size: 13px; font-weight: 600; }
.px small { font-size: 12px; font-weight: 500; }
.up { color: var(--good); }
.down { color: var(--risk); }
.flat { color: var(--fg-subtle); }
svg.spark { display: block; }
.more { visibility: hidden; display: grid; place-items: center; width: 22px; height: 22px; padding: 0;
  border: 0; border-radius: 4px; background: transparent; color: var(--fg-subtle); cursor: pointer; }
.row:hover .more, .row.menu-open .more, .row:focus-visible .more { visibility: visible; }
.more:hover { background: var(--line); color: var(--fg); }
.add { display: flex; align-items: center; gap: 8px; width: calc(100% + 20px); margin: 4px -10px 0;
  padding: 9px 10px; border: 0; border-radius: 4px; background: transparent; color: var(--fg-muted);
  font: inherit; font-size: 13px; font-weight: 500; text-align: left; cursor: pointer; }
.add:hover { background: var(--surface-raised); color: var(--fg); }
.add:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
.add .plus { font-size: 16px; line-height: 1; width: 14px; text-align: center; }
.edit { margin: 4px -10px 0; padding: 4px 6px; }
li.edit { margin: 0 -10px; }
input { box-sizing: border-box; width: 100%; height: 34px; padding: 0 10px; border: 1px solid var(--line-strong);
  border-radius: 4px; background: var(--surface); color: var(--fg); font: inherit; font-size: 13px;
  font-weight: 600; text-transform: uppercase; outline: none; }
input:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-tint); }
input::placeholder { text-transform: none; font-weight: 400; color: var(--fg-subtle); }
.hint { margin: 4px 0 0; font-size: 12px; color: var(--fg-subtle); }
.err { margin: 6px 0 0; font-size: 12px; color: var(--risk); }
.menu { position: fixed; z-index: 1000; min-width: 168px; padding: 4px; border: 1px solid var(--line);
  border-radius: 6px; background: var(--surface); box-shadow: 0 8px 24px -8px rgba(0,0,0,0.18); }
.menu button { display: block; width: 100%; padding: 7px 10px; border: 0; border-radius: 4px;
  background: transparent; color: var(--fg); font: inherit; font-size: 13px; text-align: left; cursor: pointer; }
.menu button:hover:not(:disabled), .menu button:focus-visible { background: var(--surface-raised); outline: none; }
.menu button:disabled { color: var(--fg-subtle); cursor: default; }
.menu button.danger { color: var(--risk); }
.menu hr { margin: 4px 0; border: 0; border-top: 1px solid var(--line); }
"""

JS = r"""
const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ESC[c]);
const num = (x) => (x == null || Number.isNaN(x) ? "" :
  x.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const DOTS = '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">' +
  '<circle cx="12" cy="5" r="1.8"/><circle cx="12" cy="12" r="1.8"/><circle cx="12" cy="19" r="1.8"/></svg>';

function spark(points, up) {
  const W = 64, H = 22;
  if (!points || points.length < 2) return `<svg class="spark" width="${W}" height="${H}"></svg>`;
  const lo = Math.min(...points), hi = Math.max(...points), span = hi - lo || 1, step = W / (points.length - 1);
  const pts = points.map((v, i) => `${(i * step).toFixed(1)},${(H - 2 - ((v - lo) / span) * (H - 4)).toFixed(1)}`);
  return `<svg class="spark" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" aria-hidden="true">` +
    `<polyline points="${pts.join(" ")}" fill="none" stroke="var(--${up ? "good" : "risk"})" ` +
    `stroke-width="1.25" stroke-linejoin="round"/></svg>`;
}

export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  let root = parentElement.querySelector(".wl");
  if (!root) {
    root = document.createElement("div");
    root.className = "wl";
    parentElement.appendChild(root);
    root.__state = { draft: null, menu: null };
  }
  const state = root.__state;
  const rows = data.rows || [];
  const send = (type, sym, extra = {}) => setTriggerValue("action", { type, sym, ...extra, t: Date.now() });

  function closeMenu() {
    if (!state.menu) return;
    state.menu.el.remove();
    root.querySelector(".row.menu-open")?.classList.remove("menu-open");
    const sym = state.menu.sym;
    state.menu = null;
    return sym;
  }

  function startDraft(draft) {
    closeMenu();
    state.draft = draft;
    render();
  }

  function act(action, sym) {
    closeMenu();
    if (action === "replace") {
      const row = rows.find((r) => r.sym === sym);
      startDraft({ mode: "replace", sym, value: row ? row.label : sym });
    } else {
      send(action, sym);
    }
  }

  function openMenu(sym, x, y) {
    closeMenu();
    const i = rows.findIndex((r) => r.sym === sym);
    const last = rows.length - 1;
    const items = [
      ["open", "Open chart", false], ["replace", "Replace symbol", false], null,
      ["top", "Move to top", i <= 0], ["up", "Move up", i <= 0], ["down", "Move down", i >= last], null,
      ["remove", "Remove", false, true],
    ];
    const el = document.createElement("div");
    el.className = "menu";
    el.setAttribute("role", "menu");
    el.innerHTML = items.map((it) => it === null ? "<hr>" :
      `<button type="button" role="menuitem" data-a="${it[0]}" ${it[2] ? "disabled" : ""} ` +
      `class="${it[3] ? "danger" : ""}">${it[1]}</button>`).join("");
    root.appendChild(el);
    const r = el.getBoundingClientRect();
    el.style.left = `${Math.max(8, Math.min(x, window.innerWidth - r.width - 8))}px`;
    el.style.top = `${Math.max(8, Math.min(y, window.innerHeight - r.height - 8))}px`;
    root.querySelector(`.row[data-i="${i}"]`)?.classList.add("menu-open");
    state.menu = { el, sym };
    el.addEventListener("click", (e) => {
      const b = e.target.closest("button[data-a]");
      if (b && !b.disabled) act(b.dataset.a, sym);
    });
    el.addEventListener("keydown", (e) => {
      const buttons = [...el.querySelectorAll("button:not([disabled])")];
      const at = buttons.indexOf(el.getRootNode().activeElement);
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        const step = e.key === "ArrowDown" ? 1 : -1;
        buttons[(at + step + buttons.length) % buttons.length]?.focus();
      } else if (e.key === "Escape" || e.key === "Tab") {
        e.preventDefault();
        closeMenu();
        root.querySelector(`.row[data-i="${i}"]`)?.focus();
      }
    });
    el.querySelector("button:not([disabled])")?.focus();
  }

  function submitDraft(value) {
    const draft = state.draft;
    state.draft = null;
    const sym = value.trim().toUpperCase();
    if (!sym || (draft.mode === "replace" && sym === draft.value.toUpperCase())) return render();
    if (draft.mode === "add") send("add", sym);
    else send("replace", draft.sym, { to: sym });
    render();
  }

  function render() {
    const d = state.draft;
    let html = '<ul role="listbox" aria-label="Watchlist">';
    rows.forEach((r, i) => {
      if (d && d.mode === "replace" && d.sym === r.sym) {
        html += `<li class="edit"><input value="${esc(d.value)}" aria-label="Replace ${esc(r.label)}" ` +
          'spellcheck="false" autocomplete="off"></li>';
        return;
      }
      const sel = r.sym === data.selected;
      const flat = r.chg != null && Math.abs(r.chg) < 0.00005;  // shows as 0.00%: no color, no sign
      const up = !(r.chg < 0);
      const chg = r.chg == null ? "" : flat ? '<small class="flat">0.00%</small>' :
        `<small class="${up ? "up" : "down"}">${up ? "+" : ""}${(r.chg * 100).toFixed(2)}%</small>`;
      html += `<li class="row${sel ? " sel" : ""}" role="option" aria-selected="${sel}" tabindex="0" ` +
        `data-i="${i}" title="${esc(r.label)}"><span class="sym">${esc(r.label)}</span>${spark(r.spark, up)}` +
        `<span class="px"><b>${num(r.last)}</b>${chg}</span>` +
        `<button type="button" class="more" tabindex="-1" aria-label="Options for ${esc(r.label)}">${DOTS}</button></li>`;
    });
    html += "</ul>";
    if (d && d.mode === "add") {
      html += `<div class="edit"><input value="${esc(d.value)}" placeholder="Symbol, e.g. AAPL" ` +
        'aria-label="Add symbol" spellcheck="false" autocomplete="off">' +
        '<p class="hint">Enter to add, Esc to cancel</p></div>';
    } else {
      html += '<button type="button" class="add"><span class="plus">+</span>Add symbol</button>';
    }
    if (data.error) html += `<p class="err" role="alert">${esc(data.error)}</p>`;
    root.querySelectorAll(":scope > :not(.menu)").forEach((n) => n.remove());
    root.insertAdjacentHTML("afterbegin", html);
    bind();
  }

  function bind() {
    root.querySelectorAll(".row").forEach((li) => {
      const sym = rows[+li.dataset.i].sym;
      li.addEventListener("click", (e) => {
        if (e.target.closest(".more")) {
          const b = e.target.closest(".more").getBoundingClientRect();
          openMenu(sym, b.right - 168, b.bottom + 4);
        } else {
          send("open", sym);
        }
      });
      li.addEventListener("contextmenu", (e) => {
        e.preventDefault();
        openMenu(sym, e.clientX, e.clientY);
      });
      li.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          send("open", sym);
        } else if (e.key === "ContextMenu" || (e.shiftKey && e.key === "F10")) {
          e.preventDefault();
          const b = li.getBoundingClientRect();
          openMenu(sym, b.left + 24, b.bottom);
        } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
          e.preventDefault();
          (e.key === "ArrowDown" ? li.nextElementSibling : li.previousElementSibling)?.focus();
        }
      });
    });
    root.querySelector(".add")?.addEventListener("click", () => startDraft({ mode: "add", value: "" }));
    const input = root.querySelector("input");
    if (input) {
      input.focus();
      input.setSelectionRange(input.value.length, input.value.length);
      input.addEventListener("input", () => { if (state.draft) state.draft.value = input.value; });
      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); submitDraft(input.value); }
        else if (e.key === "Escape") { e.preventDefault(); state.draft = null; render(); }
      });
      input.addEventListener("blur", () => {
        setTimeout(() => {
          if (state.draft && !input.value.trim() && root.getRootNode().activeElement !== input) {
            state.draft = null;
            render();
          }
        }, 120);
      });
    }
  }

  if (!root.__outside) {
    // One set of document listeners per mount, closing the menu on any click, scroll or resize
    // outside it. They read the menu from root.__state, so they never hold stale rows.
    root.__outside = (e) => {
      const m = root.__state.menu;
      if (m && !e.composedPath().includes(m.el)) {
        m.el.remove();
        root.querySelector(".row.menu-open")?.classList.remove("menu-open");
        root.__state.menu = null;
      }
    };
    root.__close = () => root.__outside({ composedPath: () => [] });
    document.addEventListener("mousedown", root.__outside, true);
    window.addEventListener("scroll", root.__close, true);
    window.addEventListener("resize", root.__close);
  }

  closeMenu();
  render();
  return () => {
    document.removeEventListener("mousedown", root.__outside, true);
    window.removeEventListener("scroll", root.__close, true);
    window.removeEventListener("resize", root.__close);
    root.__outside = null;
  };
}
"""

_component = st.components.v2.component("alpha_watchlist", css=CSS, js=JS)


def _clean(x: float | None) -> float | None:
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else float(x)


def row(sym: str, last: float | None, chg: float | None, closes: pd.Series) -> Row:
    return {
        "sym": sym,
        "label": sym.lstrip("^"),
        "last": _clean(last),
        "chg": _clean(chg),
        "spark": [round(float(v), 4) for v in closes.dropna().tolist()],
    }


def render(
    rows: list[Row], selected: str, error: str = "", key: str = "watchlist_view"
) -> dict | None:
    """Draw the list. Returns the user's action, if any, as {"type", "sym"[, "to"]}: type is one
    of open, replace, top, up, down, remove, add."""
    result = _component(
        key=key,
        data={"rows": rows, "selected": selected, "error": error},
        on_action_change=lambda: None,
    )
    return getattr(result, "action", None) if result is not None else None
