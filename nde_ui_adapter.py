import pandas as pd
from datetime import datetime
from typing import Dict, List, Any
from nde_schema import EngineContext, UISnapshot, Narrative

def safe(v):
    return str(v).replace("<", "&lt;").replace(">", "&gt;")

def safe_color(c):
    if not isinstance(c, str) or not c.startswith("#") or len(c) > 7:
        return "#8E8E93"
    return c

def format_currency_m(val: float) -> str:
    if abs(val) >= 1000.0:
        return f"{val/1000.0:.2f}B"
    return f"{val:.2f}M"

# ──────────────────────────────────────────────────────────────────────
# 1. NARRATIVE GENERATION — Deterministic Structural Bullets
# ──────────────────────────────────────────────────────────────────────

def generate_narrative(ctx: EngineContext) -> Narrative:
    """Generates the qualitative interpretation of the engine state."""
    state = ctx.state
    flow = ctx.flow

    # Action is determined by the strategy engine's execution decision
    # ctx.execution.action is set to "TRADE_READY" or "WAIT" by compile_execution_plan()
    exec_action = ctx.execution.action
    if exec_action == "TRADE_READY":
        action = "ENTER"
    elif exec_action == "EXIT":
        action = "EXIT"
    else:
        action = "WAIT"

    # ── Deterministic Reasoning (Structural, not prose) ──────────────
    reasons = []

    # 1. Gamma regime interpretation
    if flow.total_gex > 0:
        reasons.append("Deep Positive GEX absorbing all flow — dealer suppression active")
    else:
        reasons.append("Negative GEX amplifying moves — dealer hedging drives expansion")

    # 2. Vanna interpretation
    if "Bullish" in flow.vanna_bias:
        reasons.append("Vanna flow reinforcing upside — IV decline lifts spot")
    elif "Bearish" in flow.vanna_bias:
        reasons.append("Vanna flow pressuring downside — IV rise drags spot")
    else:
        reasons.append("Vanna neutral — no IV/spot reflexivity bias")

    # 3. Suppression / Expansion
    if ctx.gamma_local.suppression_strength > 0.5:
        reasons.append(f"Nearby positive gamma wall reinforcing pinning (Suppression: {ctx.gamma_local.suppression_strength:.0%})")
    elif ctx.gamma_local.collapse_risk:
        reasons.append("Gamma collapse risk detected — structural support weakening")

    # 4. RV context
    if ctx.rv.iv_rv_ratio > 1.3:
        reasons.append("RV compressing below implied expectations — premium sellers favored")
    elif ctx.rv.iv_rv_ratio < 0.8:
        reasons.append("RV exceeding implied — realized vol breakout underway")
    else:
        reasons.append(f"IV/RV ratio in equilibrium ({ctx.rv.iv_rv_ratio:.2f})")

    # 5. State machine canonical reasons
    if state.why:
        for w in state.why[:2]:  # cap at 2 from state engine
            reasons.append(w)

    # Triggers
    triggers = []
    if action == "ENTER":
        triggers.append(f"Spot sustains breach of {flow.gamma_flip_level:.0f}")
    else:
        triggers.append("Monitor for GEX expansion or flip migration.")
    if flow.call_wall > 0:
        triggers.append(f"Break above Call Wall ({flow.call_wall:,.0f})")
    if flow.put_wall > 0:
        triggers.append(f"Break below Put Wall ({flow.put_wall:,.0f})")

    conf_val = state.confidence
    conf_label = "INSTITUTIONAL" if conf_val > 0.8 else "TACTICAL" if conf_val > 0.5 else "LOW"

    # Invalidation — Regime-specific
    invalidation = _build_invalidation_text(ctx)

    # Avoid list — Structural guardrails
    avoid = []
    if state.coherence_score < 0.4:
        avoid.append("Low coherence — conflicting signals across flow/vol layers")
    if ctx.gamma_local.collapse_risk:
        avoid.append("Gamma collapse risk — avoid naked short vol")
    if ctx.rv.rv_acceleration > 2.0:
        avoid.append("Realized vol accelerating — reduce position size")

    return Narrative(
        dominant_action=action,
        dominant_state=state.state,
        confidence=conf_val,
        reasoning=reasons,
        triggers=triggers,
        next_trade=ctx.execution.strategy_code,
        invalidation=invalidation,
        avoid=avoid,
        execution_confidence={"value": conf_val, "label": conf_label}
    )


def _build_invalidation_text(ctx: EngineContext) -> str:
    """Produces regime-specific thesis invalidation text."""
    state = ctx.state.state
    flow = ctx.flow

    if "PINNED" in state:
        return f"Spot sustains beyond structural walls ({flow.put_wall:,.0f}–{flow.call_wall:,.0f}) or suppression collapses"
    elif "EXPANSIVE" in state:
        return "Volatility crush (IV < RV shift) or mean reversion below flip level"
    elif "SUPPRESSED" in state:
        return "Structural drift reversal or GEX flip polarity change"
    elif "VACUUM" in state or "LIQUIDITY" in state:
        return "Velocity reversal or wall recapture — momentum exhaustion"
    elif "TRANSITION" in state:
        return "Wait for structural pivot confirmation — avoid premature entry"
    else:
        return f"Regime shift from {state} or coherence breakdown below 40%"


# ──────────────────────────────────────────────────────────────────────
# 2. UI SNAPSHOT GENERATION — Full Operator Cockpit
# ──────────────────────────────────────────────────────────────────────

def generate_ui_snapshot(ctx: EngineContext, narrative: Narrative) -> UISnapshot:
    """Produces the pre-formatted visual state for the rendering layer."""
    flow = ctx.flow

    # ── 1. Colors & Branding ─────────────────────────────────────────
    action_colors = {"ENTER": "#00C805", "EXIT": "#FF3B30", "WAIT": "#FF9500", "STAND ASIDE": "#8E8E93"}
    action_color = safe_color(action_colors.get(narrative.dominant_action, "#8E8E93"))
    conf_color = safe_color("#FF3B30" if narrative.confidence < 0.4 else "#007AFF" if narrative.confidence < 0.7 else "#00C805")

    # ── 2. Why This Action (HTML) ────────────────────────────────────
    reasons_html = "".join([
        f'<div style="color: #E0E0E0; font-size: 1.05em; font-weight: 600; margin-bottom: 10px; display: flex; gap: 10px; line-height: 1.4;">'
        f'<span>✅</span> {safe(r)}</div>'
        for r in narrative.reasoning
    ])

    # ── 3. Dealer Behavior Panel (5 Greeks) ──────────────────────────
    beh_html = _build_behavior_html(flow)

    # ── 4. Key Trading Levels (5 entries incl Max Pain) ──────────────
    levels_html = _build_levels_html(ctx)

    # ── 5. Execution Summary ─────────────────────────────────────────
    exec_html = ""
    if narrative.dominant_action != "WAIT" and ctx.execution.legs:
        legs_text = " | ".join([f"**{leg['type']}**: `{int(leg['strike'])}`" for leg in ctx.execution.legs])
        exec_html = f"""
        <div style="background: rgba(0,200,5,0.05); border: 1px solid rgba(0,200,5,0.2); padding: 12px 20px; border-radius: 12px; margin-bottom: 30px; display: flex; justify-content: space-between; align-items: center;">
            <div style="display: flex; gap: 25px; align-items: center;">
                <span style="color: #00C805; font-weight: 900; font-size: 0.8em; text-transform: uppercase;">⚡ Execution Summary</span>
                <div style="display: flex; gap: 15px; font-size: 1.1em;">{legs_text}</div>
            </div>
            <div style="font-weight: 800; font-size: 0.9em; color: #8E8E93;">TARGET SIZE: <span style="color: #00C805; font-size: 1.2em;">{ctx.execution.confidence:.1f}x</span></div>
        </div>
        """

    # ── 6. Greek Snapshot (6 metrics with behavioral interpretation) ──
    greeks_html = _build_greeks_html(flow)

    # ── 7. Threat Invalidation HTML ──────────────────────────────────
    threat_html = _build_threat_html(ctx, narrative)

    # ── 8. Derived Display Values ────────────────────────────────────
    iq = flow.intelligence or {}
    max_pain = iq.get("max_pain", 0)
    pcr_oi = flow.pcr_oi if flow.pcr_oi > 0 else iq.get("pcr_oi", 0)
    expected_move = iq.get("expected_move", {})
    em_pts = expected_move.get("points", 0) if isinstance(expected_move, dict) else 0

    suppression = ctx.gamma_local.suppression_strength
    if suppression > 0.7:
        supp_label = f"{suppression:.2f} (STRONG)"
    elif suppression > 0.4:
        supp_label = f"{suppression:.2f} (MODERATE)"
    elif suppression > 0.1:
        supp_label = f"{suppression:.2f} (WEAK)"
    else:
        supp_label = f"{suppression:.2f} (NONE)"

    return UISnapshot(
        hero_action=narrative.dominant_action,
        hero_state=narrative.dominant_state,
        action_color=action_color,
        confidence_label=narrative.execution_confidence.get("label", "NORMAL"),
        confidence_color=conf_color,
        reasons_html=reasons_html,
        triggers_text=" | ".join(narrative.triggers),
        is_tradeable=narrative.dominant_action != "WAIT",
        quality_score=narrative.confidence,
        execution_summary=exec_html,
        behavior_html=beh_html,
        greeks_html=greeks_html,
        levels_html=levels_html,
        threat_html=threat_html,
        pcr_display=f"{pcr_oi:.2f}" if isinstance(pcr_oi, (int, float)) else str(pcr_oi),
        suppression_display=supp_label,
        max_pain_display=f"{int(max_pain):,}" if max_pain else "N/A",
        expected_move_display=f"±{em_pts:,.0f} pts" if em_pts else "N/A",
        audit_score=ctx.state.coherence_score
    )


# ──────────────────────────────────────────────────────────────────────
# 3. HTML BUILDERS — Operator Cockpit Components
# ──────────────────────────────────────────────────────────────────────

def _build_behavior_html(flow) -> str:
    """5-row Dealer Behavior Panel with behavioral interpretations."""
    behaviors = [
        {
            "label": "GEX",
            "state": "POSITIVE" if flow.total_gex > 0 else "NEGATIVE",
            "behavior": "Dealer Gamma Supports Range" if flow.total_gex > 0 else "Dealer Gamma Expands Volatility"
        },
        {
            "label": "VANNA",
            "state": flow.vanna_bias.split()[0].upper() if flow.vanna_bias else "NEUTRAL",
            "behavior": f"IV/Spot Reflexivity — {flow.vanna_bias}"
        },
        {
            "label": "CHARM",
            "state": "BULLISH" if flow.total_charm > 0 else "BEARISH" if flow.total_charm < 0 else "NEUTRAL",
            "behavior": f"Hedging Decay — {flow.charm_flow}"
        },
        {
            "label": "DELTA",
            "state": "LONG" if flow.total_delta > 0 else "SHORT",
            "behavior": f"Directional Imbalance {'(Bullish Tilt)' if flow.total_delta > 0 else '(Bearish Tilt)'}"
        },
        {
            "label": "THETA",
            "state": "DECAY" if flow.total_theta < 0 else "ACCRUAL",
            "behavior": f"Time Regime — {flow.tv_label}"
        }
    ]

    beh_html = ""
    for b in behaviors:
        positive_states = {"LONG", "POSITIVE", "BULLISH", "STRONG", "ACCRUAL"}
        negative_states = {"SHORT", "NEGATIVE", "BEARISH", "MILD", "DECAY"}
        s_color = "#00C805" if b["state"] in positive_states else "#FF3B30" if b["state"] in negative_states else "#8E8E93"

        beh_html += f'<div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.05); border-radius: 12px; padding: 14px; margin-bottom: 8px; display: flex; align-items: center; gap: 15px;">'
        beh_html += f'<div style="flex: 0 0 80px; text-align: center; border-right: 1px solid rgba(255,255,255,0.1); padding-right: 10px;">'
        beh_html += f'<span style="font-size: 0.7em; color: #8E8E93; text-transform: uppercase; font-weight: 800;">{safe(b["label"])}</span><br>'
        beh_html += f'<span style="font-size: 0.95em; font-weight: 900; color: {s_color};">{safe(b["state"])}</span></div>'
        beh_html += f'<div style="flex: 1; color: #5AC8FA; font-size: 0.95em; font-weight: 700;">{safe(b["behavior"])}</div></div>'

    return beh_html


def _build_greeks_html(flow) -> str:
    """6-row Greek snapshot with 'So what?' behavioral labels."""
    greek_metrics = [
        {"label": "Net GEX",     "value": format_currency_m(flow.total_gex),    "color": "#00C805" if flow.total_gex > 0 else "#FF3B30",   "meaning": "Dealer Suppression" if flow.total_gex > 0 else "Dealer Amplification"},
        {"label": "Net Delta",   "value": format_currency_m(flow.total_delta),   "color": "#00C805" if flow.total_delta > 0 else "#FF3B30",  "meaning": "Directional Pressure"},
        {"label": "Vanna Flow",  "value": format_currency_m(flow.total_vanna),   "color": "#007AFF",                                         "meaning": "IV/Spot Reflexivity"},
        {"label": "Charm Drift", "value": format_currency_m(flow.total_charm),   "color": "#FF9500",                                         "meaning": "Hedging Decay Pressure"},
        {"label": "Net Theta",   "value": format_currency_m(flow.total_theta),   "color": "#E040FB",                                         "meaning": "Time Decay Regime"},
        {"label": "Net Vega",    "value": format_currency_m(flow.total_vega),    "color": "#00BCD4",                                         "meaning": "Volatility Sensitivity"},
    ]

    html = '<div style="background: rgba(255,255,255,0.03); border-radius: 12px; padding: 20px; border: 1px solid rgba(255,255,255,0.05);">'
    for g in greek_metrics:
        html += f'<div style="display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-bottom: 1px solid rgba(255,255,255,0.05);">'
        html += f'<span style="color: #8E8E93; font-weight: 600; font-size: 0.9em;">{safe(g["label"])}</span>'
        html += f'<div style="text-align: right;"><span style="color: {g["color"]}; font-weight: 900; font-size: 1.1em;">{safe(g["value"])}</span><br>'
        html += f'<span style="color: #666; font-size: 0.7em; text-transform: uppercase; font-weight: 800;">{safe(g["meaning"])}</span></div></div>'
    html += '</div>'
    return html


def _build_levels_html(ctx: EngineContext) -> str:
    """5-entry Key Trading Levels ribbon: Spot, Flip, Pain, Call Wall, Put Wall."""
    flow = ctx.flow
    spot = ctx.spot
    iq = flow.intelligence or {}
    max_pain = iq.get("max_pain", 0)

    levels = [
        {"val": flow.put_wall,   "label": "PUT WALL",  "color": "#00C805", "type": "Global Wall"},
        {"val": spot,            "label": "SPOT",       "color": "#2979ff", "type": "Reference"},
        {"val": flow.gamma_flip_level, "label": "FLIP", "color": "#ffd600", "type": "Regime Pivot"},
        {"val": flow.call_wall,  "label": "CALL WALL",  "color": "#ff1744", "type": "Global Wall"},
    ]
    if max_pain and max_pain > 0:
        levels.append({"val": max_pain, "label": "MAX PAIN", "color": "#E040FB", "type": "Dealer Neutral"})

    levels = [l for l in levels if l["val"] is not None and not (isinstance(l["val"], float) and l["val"] != l["val"]) and l["val"] > 0]
    levels.sort(key=lambda x: x["val"])

    html = '<div style="display: flex; width: 100%; gap: 6px; margin: 30px 0; align-items: stretch;">'
    for l in levels:
        is_spot = (l["label"] == "SPOT")
        dist_pct = ((l["val"] / (spot or 1)) - 1) * 100
        dist_label = f"{dist_pct:+.1f}%" if not is_spot else "REF"
        l_color = safe_color(l["color"])

        # Text colors for readability
        if l["label"] in ("CALL WALL", "PUT WALL", "SPOT"):
            t_color = "#FFFFFF"
        elif l["label"] == "MAX PAIN":
            t_color = "#FFFFFF"
        else:
            t_color = "#121212"

        html += f'<div style="flex: 1; background: {l_color}; padding: 14px 5px; border-radius: 6px; text-align: center; box-shadow: 0 4px 15px rgba(0,0,0,0.3); position: relative; min-width: 70px;">'
        html += f'<div style="font-size: 0.6em; font-weight: 900; color: {t_color}; opacity: 0.8; text-transform: uppercase; letter-spacing: 1px;">{safe(l["label"])}</div>'
        html += f'<div style="font-size: 1.1em; font-weight: 900; color: {t_color}; font-family: monospace; margin-top: 3px;">{l["val"]:,.0f}</div>'
        html += f'<div style="font-size: 0.55em; font-weight: 800; color: {t_color}; opacity: 0.6; margin-top: 2px;">{dist_label}</div>'
        html += f'<div style="font-size: 0.5em; font-weight: 700; color: {t_color}; opacity: 0.5; margin-top: 1px; font-style: italic;">{safe(l["type"])}</div>'
        html += '</div>'
    html += '</div>'
    return html


def _build_threat_html(ctx: EngineContext, narrative: Narrative) -> str:
    """Structured Threat Invalidation block with regime-specific triggers."""
    threats = []

    # 1. Wall breach
    if ctx.flow.call_wall > 0:
        threats.append(f"Spot sustains above Call Wall ({ctx.flow.call_wall:,.0f})")
    if ctx.flow.put_wall > 0:
        threats.append(f"Spot breaks below Put Wall ({ctx.flow.put_wall:,.0f})")

    # 2. Suppression collapse
    if ctx.gamma_local.suppression_strength > 0.3:
        threats.append(f"Gamma suppression collapses (currently {ctx.gamma_local.suppression_strength:.0%})")

    # 3. RV acceleration
    if ctx.rv.rv_acceleration > 0:
        threats.append(f"Realized vol accelerates beyond implied ({ctx.rv.iv_rv_ratio:.2f} IV/RV)")

    # 4. Flip rejection
    if ctx.flow.gamma_flip_level > 0:
        threats.append(f"Spot crosses Gamma Flip ({ctx.flow.gamma_flip_level:,.0f}) and sustains")

    # 5. Coherence breakdown
    threats.append(f"Signal coherence drops below 40% (currently {ctx.state.coherence_score:.0%})")

    html = f'<div style="background: rgba(255,59,48,0.05); border: 1px solid rgba(255,59,48,0.2); border-radius: 12px; padding: 20px; margin-bottom: 20px;">'
    html += f'<div style="font-size: 0.8em; color: #FF3B30; text-transform: uppercase; font-weight: 900; letter-spacing: 1px; margin-bottom: 15px;">⚠️ THESIS INVALIDATES IF:</div>'
    html += f'<div style="font-size: 1.05em; color: #FF9500; font-weight: 700; margin-bottom: 15px; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 10px;">{safe(narrative.invalidation)}</div>'
    for t in threats:
        html += f'<div style="color: #E0E0E0; font-size: 0.9em; font-weight: 600; margin-bottom: 6px; display: flex; gap: 8px;"><span style="color: #FF3B30;">🔺</span> {safe(t)}</div>'
    html += '</div>'
    return html


# ──────────────────────────────────────────────────────────────────────
# 4. ENTRY POINT
# ──────────────────────────────────────────────────────────────────────

def adapt_context_for_ui(ctx: EngineContext) -> EngineContext:
    """Updates the context with pre-computed narratives and UI snapshots."""
    narrative = generate_narrative(ctx)
    ui = generate_ui_snapshot(ctx, narrative)

    from dataclasses import replace
    return replace(ctx, narrative=narrative, ui=ui)
