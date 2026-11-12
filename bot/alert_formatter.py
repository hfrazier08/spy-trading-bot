from datetime import datetime, timedelta
from typing import Optional

import pytz
from bot.config import CONFIG
from bot.signal_generator import TradingSignal, BUY_CALL, BUY_PUT, EXIT_LONG, EXIT_SHORT, HOLD
from bot.trade_constructor import SingleLegTrade

ET = pytz.timezone("America/New_York")
TICKER = CONFIG.spy  # "SPY" or "QQQ" depending on which bot

SIGNAL_COLORS = {
    BUY_CALL:   0x00C851,
    BUY_PUT:    0xFF4444,
    EXIT_LONG:  0xFF8800,
    EXIT_SHORT: 0xFF8800,
    HOLD:       0x9E9E9E,
}

SIGNAL_EMOJI = {
    BUY_CALL:   "🟢",
    BUY_PUT:    "🔴",
    EXIT_LONG:  "🟠",
    EXIT_SHORT: "🟠",
    HOLD:       "⚪",
}

RISK_DISCLAIMER = (
    "⚠️ Not financial advice. Options trading carries significant risk of loss. "
    "Only risk capital you can afford to lose. Paper trade first."
)


def format_discord_embed(
    signal: TradingSignal,
    trade: Optional[SingleLegTrade],
    spy_price: float,
) -> dict:
    """Entry alert. Read top-to-bottom: WHAT to buy -> HOW to exit -> WHY. Everything else is small print."""
    emoji = SIGNAL_EMOJI.get(signal.signal, "⚪")
    color = SIGNAL_COLORS.get(signal.signal, 0x9E9E9E)
    action = {BUY_CALL: "BUY CALL", BUY_PUT: "BUY PUT"}.get(signal.signal, signal.signal.replace("_", " "))
    title = f"{emoji} {TICKER} {action} — {signal.confidence}% ({_confidence_label(signal.confidence)})"

    bd = signal.confidence_breakdown
    scores = (f"Tech {bd.get('technical', 0)}/50 · Macro {bd.get('macro', 0)}/30 · "
              f"Options {bd.get('options', 0)}/20")
    fields = []

    if trade is not None:
        today = datetime.now(ET).date()
        exp = datetime.strptime(trade.expiration, "%Y-%m-%d").date()
        stall_by = today + timedelta(days=CONFIG.time_stop_days)
        close_by = exp - timedelta(days=CONFIG.expiry_buffer_days)
        tp = trade.ask_price * 1.5
        sl = trade.ask_price * 0.5
        description = (
            f"## BUY {trade.contracts}× {TICKER} ${trade.strike:.0f} {trade.option_type}\n"
            f"**Expires:** {trade.expiration_label}  ({trade.dte} days)\n"
            f"**Limit price:** ${trade.ask_price:.2f} per share  →  **${trade.total_cost:,.0f} total** "
            f"({trade.risk_pct_used:.1f}% of account)\n"
            f"**Most you can lose:** ${trade.total_cost:,.0f} (the premium)"
        )
        fields.append({
            "name": "🚪 Exit plan — set these up now",
            "value": (
                f"✅ **Take profit:** sell if the option hits **${tp:.2f}** (+50%)\n"
                f"🛑 **Stop loss:** sell if it falls to **${sl:.2f}** (−50%)\n"
                f"⏱️ **Stalled?** if it's still within ±{CONFIG.time_stop_move_pct:.0f}% on **{stall_by.strftime('%b %-d')}**, sell\n"
                f"⌛ **Last day to hold:** **{close_by.strftime('%b %-d')}** — time decay speeds up after that"
            ),
            "inline": False,
        })
    else:
        description = f"**{signal.direction.capitalize()}** setup on {TICKER} at ${spy_price:.2f}"

    reasons = "\n".join(f"• {r}" for r in signal.signal_reasons[:3])
    fields.append({"name": "📈 Why this signal", "value": reasons[:1024] or "N/A", "inline": False})

    small = [f"**{TICKER}:** ${spy_price:.2f}", f"**Risk:** {signal.risk_level.capitalize()}", f"**Score:** {scores}"]
    if trade is not None:
        small += [f"**Breakeven:** ${trade.breakeven:.2f}", f"**Delta:** {trade.delta:.2f}",
                  f"**IV:** {trade.implied_volatility:.0f}%"]
    fields.append({"name": "Details", "value": "  ·  ".join(small), "inline": False})

    return {
        "username": f"{TICKER} Options Bot",
        "embeds": [{
            "title": title,
            "description": description,
            "color": color,
            "fields": fields,
            "footer": {"text": f"{signal.timestamp} · Paper trade first · Not financial advice"},
        }],
    }


def _code(lines) -> str:
    return "```\n" + "\n".join(lines) + "\n```"


def _money(x: float) -> str:
    return f"+${x:,.0f}" if x >= 0 else f"−${abs(x):,.0f}"


def progress_bar(frac: float, n: int = 10) -> str:
    frac = max(0.0, min(1.0, frac))
    return "▓" * round(frac * n) + "░" * (n - round(frac * n))


def format_spread_embed(spread, spot: float, ma200: float, timestamp: str) -> dict:
    """Entry alert: a copy-ready order ticket, then exactly when to take profit / get out."""
    from bot.spread_strategy import SL_PCT
    exp = datetime.strptime(spread.expiration, "%Y-%m-%d").date()
    close_by = exp - timedelta(days=CONFIG.expiry_buffer_days)
    n, debit = spread.contracts, spread.ask_price
    max_gain = spread.max_profit_per_share * 100 * n
    tp_gain = (spread.tp_value - debit) * 100 * n
    stop_loss = (spread.stop_value - debit) * 100 * n

    ticket = _code([
        f"{TICKER}  ·  Call Debit Spread  ·  {n} spread{'s' if n > 1 else ''}",
        f"Expiration:    {spread.expiration_label}",
        f"BUY  to open:  ${spread.strike:.0f} Call   (long)",
        f"SELL to open:  ${spread.short_strike:.0f} Call   (short)",
        f"Order type:    LIMIT  ·  NET DEBIT ${debit:.2f}",
        f"Don't pay more than ${spread.max_price:.2f}",
    ])
    description = (
        f"**1) Place this order** — in Robinhood choose *Call Debit Spread* (tap the box to copy):\n{ticket}\n"
        f"**Cost:** ${spread.total_cost:,.0f}  ({debit:.2f} × 100"
        + (f" × {n}" if n > 1 else "") + f")  ·  **Most you can lose:** ${spread.total_cost:,.0f}  ·  "
        f"**Most you can make:** ${max_gain:,.0f} (if {TICKER} is at or above ${spread.short_strike:.0f} at expiry)"
    )

    if spread.tp_value > 0:
        profit_text = (
            f"**Close the whole spread when its price reaches ${spread.tp_value:.2f}** → about **{_money(tp_gain)}**.\n"
            f"That's the *spread price* Robinhood shows for your position (you paid ${debit:.2f}). "
            f"It's {int(CONFIG.tp_fraction * 100)}% of the most you can make; in backtests this gave up some profit versus "
            f"waiting longer, in exchange for a clear exit.")
    else:
        profit_text = "No profit target is set — hold until the stop or the last day below."
    fields = [
        {"name": "2) 🎯 When to take profit", "value": profit_text, "inline": False},
        {"name": "3) 🛑 When to get out", "value": (
            f"• **Stop:** close if the spread's price falls to **${spread.stop_value:.2f}** → about **{_money(stop_loss)}**\n"
            f"• **Time:** close on **{close_by.strftime('%b %-d')}** at the latest (decay speeds up near expiry)\n"
            f"• You'll get a **CLOSE NOW** alert with a copy-ready order when any of these hit."), "inline": False},
        {"name": "Prices right now", "value": _code([
            f"Long  ${spread.strike:.0f} call:   bid {spread.long_bid:.2f} / ask {spread.long_ask:.2f}",
            f"Short ${spread.short_strike:.0f} call:  bid {spread.short_bid:.2f} / ask {spread.short_ask:.2f}",
            f"{TICKER} ${spot:.2f}   ·   breakeven at expiry ${spread.breakeven:.2f}"]), "inline": False},
        {"name": "📈 Why now", "value": (
            f"{TICKER} is **above its 200-day average** (${spot:.2f} vs ${ma200:.2f}, {(spot / ma200 - 1) * 100:+.1f}%). "
            f"The rule: hold a bullish spread whenever the trend is up and no trade is open. "
            f"This is market exposure, not a prediction — about half of these trades lose. Paper only."), "inline": False},
    ]
    return {"username": f"{TICKER} Options Bot", "embeds": [{
        "title": f"🟢 {TICKER} — NEW TRADE: Bull Call Spread", "description": description,
        "color": 0x00C851, "fields": fields,
        "footer": {"text": f"{timestamp} · Paper trade only · Not financial advice"}}]}


def format_spread_update(trade: dict, value: float, quote: Optional[dict], spot: float, status: str,
                         days_left, close_by: str) -> str:
    """Hourly status for an open spread: says what to do, shows both legs, and how far from the target."""
    entry, n = trade["entry_price"], trade["contracts"]
    pnl = (value - entry) * 100 * n
    pct = (value / entry - 1) * 100
    tp, stop = trade.get("tp_value"), trade.get("stop_value") or entry * 0.5
    head = {"hold": "✅ HOLD — nothing to do", "near": "⏳ CLOSE TO TARGET — get your sell order ready",
            "warn": "⚠️ WATCH — getting close to your stop"}[status]
    lines = [f"**{head}**",
             f"**{TICKER} ${trade['strike']:.0f} / ${trade['short_strike']:.0f} Call Debit Spread**  "
             f"(long ${trade['strike']:.0f} call, short ${trade['short_strike']:.0f} call)",
             f"Spread price now **${value:.2f}**  (you paid ${entry:.2f})  →  **{_money(pnl)} ({pct:+.0f}%)**"]
    if tp:
        prog = (value - entry) / (tp - entry) if tp > entry else 0
        lines.append(f"Toward profit target: `{progress_bar(prog)}` {max(prog, 0) * 100:.0f}%  "
                     f"(close at **${tp:.2f}**, stop at **${stop:.2f}**)")
    else:
        lines.append(f"Stop at **${stop:.2f}**")
    if quote:
        lines.append(_code([f"Long  ${trade['strike']:.0f} call:   {quote['long_bid']:.2f} / {quote['long_ask']:.2f}",
                            f"Short ${trade['short_strike']:.0f} call:  {quote['short_bid']:.2f} / {quote['short_ask']:.2f}"]))
    lines.append(f"{TICKER} ${spot:.2f}  ·  expires {trade['expiration']} ({days_left} days)  ·  last day to hold **{close_by}**")
    return "\n".join(lines)


def format_spread_exit(kind: str, trade: dict, value: float, pnl: float, pct: float) -> str:
    """Sell alert: why, the result, and a copy-ready closing order."""
    why = {"take_profit": "🎯 **TAKE PROFIT — your target was hit**",
           "stop_loss": "🛑 **STOP HIT — get out**",
           "expiry_buffer": f"⌛ **TIME TO CLOSE — under {CONFIG.expiry_buffer_days} days left**",
           "expiration": "⌛ **EXPIRING — close it now**",
           "signal_exit": "🔔 **EXIT SIGNAL — close it**"}.get(kind, "🔔 **CLOSE NOW**")
    n = trade["contracts"]
    order = _code([
        f"{TICKER}  ·  Call Debit Spread  ·  CLOSE {n} spread{'s' if n > 1 else ''}",
        f"Expiration:     {trade['expiration']}",
        f"SELL to close:  ${trade['strike']:.0f} Call   (your long)",
        f"BUY  to close:  ${trade['short_strike']:.0f} Call   (your short)",
        f"Order type:     LIMIT  ·  NET CREDIT ${value:.2f} or better",
    ])
    result = "WIN" if pnl > 0 else "LOSS" if pnl < 0 else "FLAT"
    return (f"{why}\n**{result}: {_money(pnl)} ({pct:+.0f}%)**  ·  paid ${trade['entry_price']:.2f} → "
            f"closing near ${value:.2f}\n\n**Place this order** (in Robinhood open your {TICKER} spread → *Close*):\n{order}")


def format_whatsapp_message(
    signal: TradingSignal,
    trade: Optional[SingleLegTrade],
    spy_price: float,
) -> str:
    emoji = SIGNAL_EMOJI.get(signal.signal, "⚪")
    lines = [
        f"{emoji} *{TICKER} BOT — {signal.signal}*",
        f"Price: ${spy_price:.2f} | Conf: {signal.confidence}%",
        "",
    ]
    if trade:
        lines += [
            f"*Buy {trade.option_type}: ${trade.strike:.0f} Strike*",
            f"Exp: {trade.expiration_label} ({trade.dte} DTE)",
            f"Ask: ${trade.ask_price:.2f} | Cost: ${trade.total_cost:,.0f}",
            f"Breakeven: ${trade.breakeven:.2f}",
            f"Target: ${trade.profit_target:.2f} | Stop: ${trade.stop_loss_price:.2f}",
            "",
        ]
    lines.append("*Why:*")
    for r in signal.signal_reasons[:3]:
        lines.append(f"• {r}")
    lines.append("")
    lines.append("Not financial advice.")
    return "\n".join(lines)


def _confidence_label(conf: int) -> str:
    if conf >= 90: return "VERY HIGH"
    if conf >= 80: return "HIGH"
    if conf >= 70: return "MODERATE"
    return "LOW"


def _robinhood_steps(trade: SingleLegTrade) -> str:
    return (
        f"1️⃣ Open Robinhood → Search **{TICKER}**\n"
        f"2️⃣ Tap **Trade** → **{trade.option_type}**\n"
        f"3️⃣ Select expiration: **{trade.expiration_label}**\n"
        f"4️⃣ Find strike: **${trade.strike:.0f}**\n"
        f"5️⃣ Tap **Buy** → set quantity: **{trade.contracts} contract(s)**\n"
        f"6️⃣ Order type: **Limit** → enter **${trade.ask_price:.2f}**\n"
        f"7️⃣ Review cost: **${trade.total_cost:,.0f} total**\n"
        f"8️⃣ Tap **Review** → **Submit**\n"
        f"9️⃣ Set alert: notify if {TICKER} hits **${trade.breakeven:.2f}**"
    )[:1024]
