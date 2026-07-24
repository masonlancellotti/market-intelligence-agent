"""Degrade-mode brief renderers.

When no LLM is available the brief is assembled directly from the structured context as
a data-dense, fully-cited markdown document — the "template-with-tables" fallback. Every
number carries an ``[evidence:id]`` marker so the exact same fact-checker runs on it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ..util import parse_iso

FOOTER = "\n---\n*Personal research use. Not investment advice.*"


def _pct(x) -> str:
    return f"{x:+.2f}%" if isinstance(x, int | float) else "n/a"


def _arrow(x) -> str:
    if not isinstance(x, int | float):
        return ""
    return "▲" if x > 0 else ("▼" if x < 0 else "▬")


def _num(x, prefix="") -> str:
    if not isinstance(x, int | float):
        return "n/a"
    return f"{prefix}{x:,.2f}"


def _header_line(ctx: dict) -> str:
    h = ctx["header"]
    regime = h.get("regime") or {}
    bits = []
    if regime.get("score") is not None:
        bits.append(f"Regime: {regime.get('bucket', '?')} {regime['score']:.0f}/100 {_arrow(0)}")
    for key, lbl, ev in [("es", "ES", "ES=F"), ("nq", "NQ", "NQ=F"), ("btc", "BTC", "BTC-USD")]:
        d = h.get(key)
        if d:
            bits.append(f"{lbl} {_pct(d.get('change_pct'))} [b:{ev}]")
    ten = h.get("ten_y")
    if ten:
        bits.append(f"10Y {ten['price']:.2f}% [b:^TNX]")
    vix = h.get("vix")
    if vix:
        bits.append(f"VIX {vix['price']:.1f} [b:^VIX]")
    return " · ".join(bits)


def _tldr(ctx: dict) -> list[str]:
    out = []
    regime = ctx["header"].get("regime") or {}
    if regime.get("score") is not None:
        out.append(f"Regime **{regime.get('bucket')}** at {regime['score']:.0f}/100.")
    movers = ctx.get("movers") or []
    if movers:
        m = movers[0]
        out.append(
            f"Biggest watchlist move: **{m['ticker']}** {_pct(m['change_pct'])} [b:{m['ticker']}]."
        )
    mat_news = [n for n in ctx.get("news_top", []) if n.get("materiality", 0) >= 4]
    if mat_news:
        out.append(
            f"{len(mat_news)} high-materiality stories overnight — top: {mat_news[0]['title'][:90]} [n:{mat_news[0]['id']}]."
        )
    return out[:3]


def render_morning(ctx: dict) -> str:
    date = _fmt_date(ctx.get("generated_at"))
    md = [f"# Morning Brief — {date}", f"**{_header_line(ctx)}**", ""]

    md.append("## TL;DR")
    for b in _tldr(ctx) or ["Quiet tape; nothing urgent."]:
        md.append(f"- {b}")
    md.append("")

    md.append("## Portfolio Check")
    if ctx["portfolio"]:
        md.append("| Ticker | Price | Δ% | P/L% | Dist→Invalidation | Overnight news |")
        md.append("|---|---|---|---|---|---|")
        for p in ctx["portfolio"]:
            inval = (
                f"{p['dist_to_invalidation_pct']:+.1f}% (@ {p['invalidation_level']})"
                if p.get("dist_to_invalidation_pct") is not None
                else "—"
            )
            md.append(
                f"| **{p['ticker']}** [b:{p['ticker']}] | {_num(p['price'], '$')} | {_pct(p['change_pct'])} "
                f"| {_pct(p['pl_pct'])} | {inval} | {p.get('overnight_news', 0)} |"
            )
    else:
        md.append("_No positions in portfolio.yaml._")
    md.append("")

    md.append("## Watchlist Movers & Setups")
    if ctx["movers"]:
        md.append("| Ticker | Δ% | RSI | ATR% | Vol z | 20d range |")
        md.append("|---|---|---|---|---|---|")
        for m in ctx["movers"]:
            rng = (
                f"{m['donchian20_lower']:.1f}–{m['donchian20_upper']:.1f}"
                if m.get("donchian20_upper")
                else "—"
            )
            md.append(
                f"| **{m['ticker']}** [b:{m['ticker']}] | {_pct(m['change_pct'])} "
                f"| {_fmt(m.get('rsi14'), 0)} | {_fmt(m.get('atr_pct'), 1)} | {_fmt(m.get('volume_z'), 1)} | {rng} |"
            )
    md.append("")

    md.append("## Today's Calendar")
    if ctx["calendar"]:
        for e in ctx["calendar"]:
            when = _fmt_time(e.get("scheduled_at"))
            md.append(
                f"- **{when}** {e['name']} ({e.get('importance', '')}) — cons {e.get('consensus') or '?'}, prev {e.get('previous') or '?'}"
            )
    else:
        md.append("_No scheduled releases loaded._")
    md.append("")

    md.append("## Macro Pulse")
    macro = ctx["macro"]
    for sid, lbl in [
        ("DGS10", "10Y yield"),
        ("DGS2", "2Y yield"),
        ("T10Y2Y", "10y-2y"),
        ("BAMLH0A0HYM2", "HY OAS"),
    ]:
        if sid in macro:
            md.append(f"- {lbl}: {macro[sid]['value']} [m:{sid}] (as of {macro[sid]['date']})")
    if macro.get("fed_odds"):
        f = macro["fed_odds"][0]
        md.append(f"- Fed odds — {f['question'][:80]}: {f['yes_prob'] * 100:.0f}%")
    if macro.get("crypto_fng"):
        md.append(
            f"- Crypto Fear & Greed: {macro['crypto_fng']['value']} ({macro['crypto_fng']['label']})"
        )
    md.append("")

    md.append("## Filings & Insiders")
    if ctx["filings"]:
        for f in ctx["filings"]:
            items = ", ".join(f.get("items", [])) or "—"
            md.append(
                f"- **{f['ticker']}** {f['form']} (items {items}, mat {f['materiality']}) [f:{f['id']}] — {f['filed_at']}"
            )
    else:
        md.append("_No material filings._")
    md.append("")

    md.append("## Overnight Headlines")
    for n in ctx["news_top"][:6]:
        tks = ("[" + ", ".join(n["tickers"]) + "] ") if n.get("tickers") else ""
        md.append(f"- {tks}{n['title']} [n:{n['id']}] _(m{n['materiality']}, {n['source']})_")
    md.append("")

    md.append("## Data Gaps & System Notes")
    if ctx["data_gaps"]:
        for g in ctx["data_gaps"]:
            md.append(f"- `{g['connector']}` is **{g['status']}** ({g.get('last_error') or 'n/a'})")
    else:
        md.append("- All connectors healthy.")
    md.append("- _Generated in template mode (no LLM key) — data-only, no interpretation._")
    md.append(FOOTER)
    return "\n".join(md)


def render_closing(ctx: dict) -> str:
    date = _fmt_date(ctx.get("generated_at"))
    md = [f"# Closing Wrap — {date}", f"**{_header_line(ctx)}**", ""]
    md.append("## Attribution & Movers")
    if ctx["movers"]:
        md.append("| Ticker | Close Δ% | RSI | Vol z |")
        md.append("|---|---|---|---|")
        for m in ctx["movers"]:
            md.append(
                f"| **{m['ticker']}** [b:{m['ticker']}] | {_pct(m['change_pct'])} | {_fmt(m.get('rsi14'), 0)} | {_fmt(m.get('volume_z'), 1)} |"
            )
    md.append("")
    md.append("## After-Hours & Filings")
    for f in ctx["filings"][:5]:
        md.append(f"- **{f['ticker']}** {f['form']} [f:{f['id']}]")
    md.append("")
    md.append("## Tomorrow's Calendar")
    for e in ctx["calendar"][:5]:
        md.append(f"- {_fmt_time(e.get('scheduled_at'))} {e['name']} ({e.get('importance', '')})")
    md.append(FOOTER)
    return "\n".join(md)


def render_hedge_note(hedge: dict) -> list[str]:
    md = ["## Hedge Ideas"]
    snap = hedge.get("snapshot", {})
    md.append(
        f"_Portfolio β {snap.get('portfolio_beta')} · beta-adj exposure ${snap.get('beta_adjusted_exposure', 0):,.0f} "
        f"· regime {hedge.get('regime_score')}/100 · SPY {hedge.get('spy_price')}_"
    )
    if not hedge.get("ideas"):
        md.append("_No equity/crypto exposure to hedge (or no price data)._")
        return md
    for i, idea in enumerate(hedge["ideas"], 1):
        md.append(f"\n**{i}. {idea['structure']}**")
        md.append(f"- Coverage: {idea['coverage']}")
        md.append(f"- Indicative cost: {idea['indicative_cost']}")
        md.append(f"- Trigger: {idea['trigger']}")
        md.append(f"- Exit/roll: {idea['exit_roll']}")
        md.append(f"- Does NOT protect: {idea['does_not_protect']}")
    md.append(f"\n_{hedge.get('note', '')}_")
    return md


def render_sunday(ctx: dict, hedge: dict, memos: list[dict]) -> str:
    date = _fmt_date(ctx.get("generated_at"))
    md = [f"# Sunday Setup — {date}", f"**{_header_line(ctx)}**", "", "## Week in Review"]
    regime = ctx["header"].get("regime") or {}
    md.append(
        f"- Regime closed **{regime.get('bucket')}** at {regime.get('score')}/100 (coverage {regime.get('coverage')})."
    )
    movers = ctx.get("movers") or []
    if movers:
        md.append(
            f"- Watchlist range: {movers[0]['ticker']} {_pct(movers[0]['change_pct'])} to {movers[-1]['ticker']} {_pct(movers[-1]['change_pct'])}."
        )
    md.append("")
    md.append("## This Week's Calendar")
    for e in ctx["calendar"][:8]:
        md.append(f"- {_fmt_time(e.get('scheduled_at'))} {e['name']} ({e.get('importance', '')})")
    md.append("")
    md.append("## Live Memos — Re-underwrite")
    if memos:
        for m in memos:
            rt = m.get("redteam") or {}
            md.append(
                f"- **{m['ticker']}** ({m['direction']}, gate {m.get('gate_score', '?')}/100) — red team verdict: {rt.get('verdict', '—')}"
            )
    else:
        md.append("_No Live memos._")
    md.append("")
    md.extend(render_hedge_note(hedge))
    md.append("\n## Research Questions")
    md.append("- What's the highest-conviction change in the macro regime this week?")
    md.append("- Which Live thesis is closest to its invalidation, and is the plan still right?")
    md.append("- Where is the crowd offside vs the prediction-market odds?")
    md.append(FOOTER)
    return "\n".join(md)


def render_crypto(ctx: dict, crypto: dict) -> str:
    date = _fmt_date(ctx.get("generated_at"))
    md = [f"# Crypto Weekend Pulse — {date}", "", "## Structure"]
    for sym in ("BTC-USD", "ETH-USD", "SOL-USD"):
        m = next((x for x in ctx["movers"] if x["ticker"] == sym), None)
        h = ctx["header"].get("btc") if sym == "BTC-USD" else None
        if m:
            md.append(
                f"- **{sym}** [b:{sym}] {_pct(m['change_pct'])} · RSI {_fmt(m.get('rsi14'), 0)} · range {_fmt(m.get('donchian20_lower'), 0)}–{_fmt(m.get('donchian20_upper'), 0)}"
            )
        elif h:
            md.append(f"- **{sym}** [b:{sym}] {_pct(h.get('change_pct'))}")
    fng = crypto.get("crypto_fng")
    if fng:
        md.append(f"\n## Sentiment\n- Fear & Greed: {fng['value']} ({fng['label']})")
    g = crypto.get("crypto_global")
    if g and g.get("btc_dominance"):
        md.append(f"- BTC dominance: {g['btc_dominance']:.1f}%")
    md.append("\n## Weekend-liquidity risk")
    md.append("- Thin books amplify moves; size for gaps and avoid stops in illiquid hours.")
    md.append(FOOTER)
    return "\n".join(md)


def render_event_flash(ctx: dict, event: dict) -> str:
    md = [f"# Event Flash — {event.get('title', 'event')}", f"**{_header_line(ctx)}**", ""]
    md.append(f"## What happened\n{event.get('summary', '')}")
    md.append("\n## First-order read")
    md.append(event.get("read", "_Assessing…_"))
    md.append("\n## Levels to watch")
    for m in ctx["movers"][:4]:
        md.append(f"- {m['ticker']} [b:{m['ticker']}]: {_pct(m['change_pct'])}")
    md.append(FOOTER)
    return "\n".join(md)


def _fmt(x, dp):
    return f"{x:.{dp}f}" if isinstance(x, int | float) else "—"


def _fmt_date(iso: str | None) -> str:
    dt = parse_iso(iso) or datetime.now(UTC)
    return f"{dt.strftime('%A, %B')} {dt.day}"  # avoid %-d (not Windows-safe)


def _fmt_time(iso: str | None) -> str:
    dt = parse_iso(iso)
    return f"{dt.strftime('%b')} {dt.day} {dt.strftime('%H:%M')}" if dt else (iso or "TBD")
