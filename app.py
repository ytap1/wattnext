"""
WattNext — "The Kill Bill Shock" Agent  ·  DETECT → DECIDE → DELIVER (Streamlit UI)

The FACE of WattNext. Wires agent.decide() — the ONE real Gemini call — into a live
three-stage loop:

  DETECT   read a customer's bill shock (mock usage data)
  DECIDE   one real Gemini reasoning call, revealed live in the decision-log panel
  DELIVER  a completed-action card whose route DIFFERS per customer

The differentiator: same agent, two customers, DIFFERENT routes
  Maria  (low-income, medical/life-support) → ASSISTANCE_ENROLLMENT
  James  (middle-income, seasonal AC spike) → BUDGET_BILLING

Everything is mocked EXCEPT the single agent.decide() Gemini call.
"""

import hashlib
import time
from typing import Any, Dict, Iterator

import streamlit as st

import agent


# ============================================================
# 0) PAGE SETUP + THEME
# ============================================================
st.set_page_config(
    page_title="WattNext", page_icon="⚡", layout="centered",
    initial_sidebar_state="expanded",  # keep demo controls visible on stage
)
# The two demo modes. Value shown in the sidebar toggle.
MODE_BILL = "⚡ Bill Shock"
MODE_CALL = "🚨 First Response"

# Header copy follows the active domain. The sidebar radio (key="mode") persists in
# session_state across reruns; default to Bill Shock on the first render (before the
# radio exists) so the header is never stale after a mode switch.
_active_mode = st.session_state.get("mode", MODE_BILL)
st.title("⚡ WattNext")
# Constant brand line — the flexible engine is the hero; the domain is just what it's pointed at.
st.markdown("**One flexible agent for the utility contact center — point it at a new problem, it adapts.**")
if _active_mode == MODE_CALL:
    st.subheader("First-Response Triage Agent — Detect. Decide. Deliver.")
    st.caption(
        "One real **Google Gemini** reasoning call — constrained routes, human-in-the-loop. "
        "The *same* engine that resolves bill shock is, right now, triaging an inbound gas-leak "
        "call: a severity tier, a routing decision, and a dispatch packet handed to a **human "
        "dispatcher** — never auto-dispatched. Everything else is mocked for the demo."
    )
else:
    st.subheader("The Kill Bill Shock Agent — Detect. Decide. Deliver.")
    st.caption(
        "One real **Google Gemini** reasoning call — constrained routes, human-in-the-loop. "
        "The *same* engine that triages a gas-leak call is, right now, resolving a customer's "
        "bill shock — reaching a *different* resolution per customer. Everything else is mocked "
        "for the demo."
    )

# Route → display styling (energy/utility theme).
# Two domains share this map so _render_route_badge / _render_source_badge work for both.
ROUTE_STYLE: Dict[str, Dict[str, str]] = {
    # Bill Shock domain
    "ASSISTANCE_ENROLLMENT": {"bg": "#1B5E20", "icon": "🤝", "label": "Assistance Enrollment"},
    "BUDGET_BILLING":        {"bg": "#0D47A1", "icon": "📊", "label": "Budget Billing (Level-Pay)"},
    "REVIEW":                {"bg": "#5D4037", "icon": "🔎", "label": "Escalated for Human Review"},
    # First Response domain
    "DISPATCH_NOW":          {"bg": "#B71C1C", "icon": "🚑", "label": "Dispatch Emergency Responder"},
    "SCHEDULE_TECH":         {"bg": "#0D47A1", "icon": "🔧", "label": "Schedule Technician (Non-Emergency)"},
    "ESCALATE_HUMAN":        {"bg": "#5D4037", "icon": "🧑‍✈️", "label": "Escalate to Human Dispatcher"},
}

# Per-step reveal delay for the live decision log. Trim to 0.3 if the W5
# two-branch dry run pushes the 5-min slot (see HACKATHON.md W5).
STEP_DELAY_SEC = 0.5


# ============================================================
# 1) SECRETS + CLIENT (once per session)
# ============================================================
def _resolve_api_key() -> "str | None":
    """Prefer st.secrets (works on Streamlit Community Cloud AND from a local
    .streamlit/secrets.toml); fall back to env/file for headless runs (tests)."""
    key = None
    try:
        key = st.secrets.get("GEMINI_API_KEY")
    except Exception:
        key = None
    if not key:
        key = agent._load_api_key()
    return key if key and key != "PASTE_YOUR_GEMINI_API_KEY_HERE" else None


_api_key = _resolve_api_key()
if not _api_key:
    st.error(
        "Missing **GEMINI_API_KEY**. Locally: add it to `.streamlit/secrets.toml`. "
        "On Streamlit Cloud: add it under **App settings → Secrets** in TOML form "
        "(`GEMINI_API_KEY = \"...\"`), then rerun."
    )
    st.stop()

if "client" not in st.session_state:
    st.session_state.client = agent.build_client(_api_key)


# ============================================================
# 2) SESSION STATE INIT
# ============================================================
for _key, _default in [
    ("selected", None),      # index into agent.CUSTOMERS, or None
    ("decision", None),      # last decision dict, or None
    ("log_done", False),            # whether the staged reveal has already played
    ("deliver_status", "pending"),  # pending | accepted | declined
    ("decision_latency", None),     # seconds the live DECIDE call took
]:
    if _key not in st.session_state:
        st.session_state[_key] = _default


def _select_customer(idx: int) -> None:
    """Pick a record and clear any prior decision so the loop restarts clean."""
    st.session_state.selected = idx
    st.session_state.decision = None
    st.session_state.log_done = False
    st.session_state.deliver_status = "pending"


def _reset_loop() -> None:
    """Clear the whole loop back to the empty state (used by Reset and mode switch)."""
    st.session_state.selected = None
    st.session_state.decision = None
    st.session_state.log_done = False
    st.session_state.deliver_status = "pending"


# ============================================================
# 3) SIDEBAR — one-click demo controls
# ============================================================
with st.sidebar:
    st.header("🎬 Demo Controls")

    # Domain toggle — same DETECT→DECIDE→DELIVER engine, two triage domains.
    # Switching modes clears the loop so the two demos never bleed into each other.
    mode = st.radio(
        "Triage domain",
        [MODE_BILL, MODE_CALL],
        key="mode",
        on_change=_reset_loop,
        help="Same agent engine, two domains. Bill Shock resolves billing; "
             "First Response triages inbound gas-odor/leak calls.",
    )
    st.caption("One-click scenarios for the live pitch.")

    if mode == MODE_BILL:
        if st.button("🔴 Customer A: Maria (low-income, medical)", use_container_width=True):
            _select_customer(0)
            st.rerun()
        if st.button("🟢 Customer B: James (seasonal AC)", use_container_width=True):
            _select_customer(1)
            st.rerun()
    else:
        if st.button("🔴 Call A: Rosa (active leak, oxygen-dependent)", use_container_width=True):
            _select_customer(0)
            st.rerun()
        if st.button("🟢 Call B: Trevor (faint odor, no danger)", use_container_width=True):
            _select_customer(1)
            st.rerun()

    if st.button("↺ Reset", use_container_width=True):
        _reset_loop()
        st.rerun()

    st.divider()
    st.caption(f"Primary model: `{agent.PRIMARY_MODEL}`")
    st.caption(f"Fallback model: `{agent.FALLBACK_MODEL}`")

    st.divider()
    st.subheader("🧪 Debug / Evidence")
    st.caption("_Toggle on to inspect what the agent saw and returned._")
    show_profile = st.checkbox("Show customer profile (raw input)", value=False)
    show_prompt = st.checkbox("Show prompt sent to Gemini", value=False)
    show_routes = st.checkbox("Show allowed routes (guardrail)", value=False)
    show_json = st.checkbox("Show structured decision JSON", value=False)
    show_meta = st.checkbox("Show call metadata (model · source · latency)", value=False)


# ============================================================
# 4) DETECT — bill-shock banner
# ============================================================
def _render_detect(cust: Dict[str, Any]) -> None:
    spike = cust.get("spike_pct")
    baseline = cust.get("baseline_usd")
    current = cust.get("current_usd")
    # Amber for a moderate spike, red for a large one — visual "shock" cue.
    bg = "#B71C1C" if (spike or 0) >= 35 else "#E65100"
    st.markdown(
        f"""<div style="padding:1rem 1.15rem;border-radius:0.6rem;background:{bg};
color:#FFFFFF;margin-bottom:0.5rem;">
  <div style="font-size:1.15rem;font-weight:800;">⚠️ BILL SHOCK DETECTED — {cust.get('name')}</div>
  <div style="font-size:1.9rem;font-weight:800;margin:0.15rem 0;">+{spike}% <span style="font-size:1rem;font-weight:600;opacity:0.9;">vs baseline</span></div>
  <div style="font-weight:600;">${baseline:,.0f}/mo → ${current:,.0f}/mo</div>
  <div style="margin-top:0.35rem;font-weight:500;opacity:0.95;">Cause: {cust.get('spike_cause')}</div>
</div>""",
        unsafe_allow_html=True,
    )
    c1, c2, c3 = st.columns(3)
    c1.metric("Income band", str(cust.get("income_band")).title())
    c2.metric("Medical equipment", "Yes" if cust.get("medical_equipment") else "No")
    c3.metric("Declared hardship", "Yes" if cust.get("hardship") else "No")


def _render_detect_call(call: Dict[str, Any]) -> None:
    """DETECT for the First Response domain — the raw inbound gas-odor/leak call."""
    vuln = call.get("account_vulnerability_flag")
    # Red banner: every inbound gas-odor call is treated as potentially life-safety
    # until the agent triages it.
    st.markdown(
        f"""<div style="padding:1rem 1.15rem;border-radius:0.6rem;background:#B71C1C;
color:#FFFFFF;margin-bottom:0.5rem;">
  <div style="font-size:1.15rem;font-weight:800;">📞 INCOMING GAS-ODOR CALL — {call.get('caller_name')}</div>
  <div style="font-size:1.05rem;font-weight:700;margin:0.15rem 0;">📍 {call.get('address')}</div>
  <div style="margin-top:0.35rem;font-weight:500;opacity:0.95;">Awaiting triage — nothing dispatched until a human dispatcher confirms.</div>
</div>""",
        unsafe_allow_html=True,
    )
    st.markdown("**📝 Call transcript (raw)**")
    st.markdown(
        f"""<div style="padding:0.75rem 1rem;border-radius:0.5rem;border-left:4px solid #B71C1C;
background:rgba(0,0,0,0.03);font-style:italic;">{call.get('transcript')}</div>""",
        unsafe_allow_html=True,
    )
    c1, c2 = st.columns(2)
    c1.metric("Medical-dependent household", "Yes" if call.get("medical_dependent") else "No")
    c2.metric("Vulnerability flag", vuln if vuln else "None")


# ============================================================
# 5) DECIDE — live decision-log (staged reveal of REAL model output)
# ============================================================
def _render_source_badge(decision: Dict[str, Any]) -> None:
    """Unmissable proof-of-liveness badge — the answer to the Shark question
    'how do I know it's really the AI?'. LIVE vs FALLBACK, front and centre."""
    if decision.get("source") == "live":
        bg, icon, label = "#00897B", "⚡", "LIVE GEMINI"
        sub = f"model {decision.get('model_used')}"
    else:
        bg, icon, label = "#E65100", "🛟", "FALLBACK (rules-based)"
        sub = "live call unavailable — loop still completes"
    st.markdown(
        f"""<div style="display:inline-block;padding:0.45rem 0.9rem;border-radius:0.5rem;
background:{bg};color:#FFFFFF;font-weight:800;font-size:1.1rem;letter-spacing:0.3px;margin:0.2rem 0 0.4rem;">
  {icon} {label}<span style="font-weight:500;opacity:0.9;font-size:0.9rem;"> · {sub}</span>
</div>""",
        unsafe_allow_html=True,
    )


def _stream_steps(steps: list) -> Iterator[str]:
    """Yield each reasoning step as a markdown line, paced for a live reveal.
    The content is the real model output; only the pacing is staged."""
    for step in steps:
        yield f"- {step}\n"
        time.sleep(STEP_DELAY_SEC)


def _render_route_badge(decision: Dict[str, Any]) -> None:
    style = ROUTE_STYLE.get(decision["route"], ROUTE_STYLE["REVIEW"])
    st.markdown(
        f"""<div style="padding:0.8rem 1rem;border-radius:0.6rem;background:{style['bg']};
color:#FFFFFF;font-weight:800;margin:0.5rem 0;">
  {style['icon']} DECISION: {style['label']}
  <div style="font-weight:500;opacity:0.95;margin-top:0.2rem;">{decision.get('rationale','')}</div>
</div>""",
        unsafe_allow_html=True,
    )


# ============================================================
# 6) DELIVER — prepared action → customer acceptance → completed
#    Human-in-the-loop: WattNext never changes an account without consent.
# ============================================================
def _confirmation_number(route: str, cust: Dict[str, Any]) -> str:
    """Deterministic mock confirmation # — stable across process restarts
    (unlike hash(), which is per-process randomized)."""
    seed = f"{route}:{cust.get('name', '')}".encode("utf-8")
    n = int(hashlib.sha1(seed).hexdigest()[:6], 16) % 90000 + 10000
    return f"WN-{route[:3]}-{n}"


def _deliver_figure(route: str, cust: Dict[str, Any]) -> tuple[str, str]:
    """Route → (label, value). Credit shown positive — a credit lowers the bill."""
    if route == "ASSISTANCE_ENROLLMENT":
        credit = cust.get("current_usd", 0) - cust.get("baseline_usd", 0)
        return "Est. monthly credit", f"${credit:,.0f}/mo"
    if route == "BUDGET_BILLING":
        leveled = (cust.get("baseline_usd", 0) + cust.get("current_usd", 0)) / 2
        return "Leveled monthly amount", f"${leveled:,.0f}/mo"
    return "Next step", "Human review queued"


def _render_deliver(decision: Dict[str, Any], cust: Dict[str, Any]) -> None:
    route = decision["route"]
    style = ROUTE_STYLE.get(route, ROUTE_STYLE["REVIEW"])
    params = decision.get("action_params", {}) or {}
    plan = params.get("program_or_plan", "—")
    figure_label, figure_val = _deliver_figure(route, cust)

    st.markdown("### 📦 Deliver")
    status = st.session_state.deliver_status

    if status == "pending":
        # Prepared, awaiting the customer's CHOICE — real consent means a real option to decline.
        st.markdown(
            f"""<div style="padding:1rem 1.15rem;border-radius:0.6rem;border:2px dashed {style['bg']};
background:rgba(0,0,0,0.02);">
  <div style="font-size:1.05rem;font-weight:800;color:{style['bg']};">{style['icon']} {plan}</div>
  <div style="margin-top:0.4rem;"><b>{figure_label}:</b> {figure_val}</div>
  <div style="margin-top:0.2rem;opacity:0.8;">{params.get('note','')}</div>
  <div style="margin-top:0.55rem;font-weight:800;color:{style['bg']};">🧾 Prepared — your choice</div>
</div>""",
            unsafe_allow_html=True,
        )
        st.caption("The agent prepared everything, but nothing changes without your say-so.")
        col_accept, col_decline = st.columns(2)
        if col_accept.button("✅ Accept & Enroll", type="primary", use_container_width=True, key="accept_action"):
            st.session_state.deliver_status = "accepted"
            st.rerun()
        if col_decline.button("💬 Not now — talk to a specialist", use_container_width=True, key="decline_action"):
            st.session_state.deliver_status = "declined"
            st.rerun()

    elif status == "accepted":
        # Accepted → action completed, confirmation issued.
        st.markdown(
            f"""<div style="padding:1rem 1.15rem;border-radius:0.6rem;border:2px solid {style['bg']};
background:rgba(0,0,0,0.03);">
  <div style="font-size:1.05rem;font-weight:800;color:{style['bg']};">{style['icon']} {plan}</div>
  <div style="margin-top:0.4rem;"><b>{figure_label}:</b> {figure_val}</div>
  <div style="margin-top:0.2rem;"><b>Confirmation #:</b> <code>{_confirmation_number(route, cust)}</code></div>
  <div style="margin-top:0.55rem;font-weight:800;color:{style['bg']};">✅ Accepted &amp; enrolled — action completed</div>
</div>""",
            unsafe_allow_html=True,
        )
        st.caption("DELIVER is mocked — in production, acceptance triggers the real enrollment/plan change.")

    else:  # declined → human handoff (surfaces the REVIEW route in the enum)
        review = ROUTE_STYLE["REVIEW"]
        st.markdown(
            f"""<div style="padding:1rem 1.15rem;border-radius:0.6rem;border:2px solid {review['bg']};
background:rgba(0,0,0,0.03);">
  <div style="font-size:1.05rem;font-weight:800;color:{review['bg']};">{review['icon']} Handed off to a WattNext specialist</div>
  <div style="margin-top:0.4rem;">No account changes were made. A specialist will review your options with you.</div>
  <div style="margin-top:0.2rem;"><b>Reference #:</b> <code>{_confirmation_number('REVIEW', cust)}</code></div>
  <div style="margin-top:0.2rem;"><b>Callback:</b> within 24 hours</div>
  <div style="margin-top:0.55rem;font-weight:800;color:{review['bg']};">💬 Escalated for human review</div>
</div>""",
            unsafe_allow_html=True,
        )
        st.caption("The customer is never trapped — declining routes to a human, with nothing changed.")
        if st.button("↩ Reconsider options", use_container_width=True, key="reconsider_action"):
            st.session_state.deliver_status = "pending"
            st.rerun()


# ------------------------------------------------------------------
# First Response DELIVER — the dispatch packet, handed to a HUMAN
# dispatcher. Never auto-dispatched: that human-in-the-loop step is
# the deliberate safety story for a life-safety call.
# ------------------------------------------------------------------
_SEVERITY_COLOR = {
    "CRITICAL": "#B71C1C", "HIGH": "#E65100", "LOW": "#0D47A1", "NEEDS_REVIEW": "#5D4037",
}


def _render_deliver_call(decision: Dict[str, Any], call: Dict[str, Any]) -> None:
    route = decision["route"]
    style = ROUTE_STYLE.get(route, ROUTE_STYLE["ESCALATE_HUMAN"])
    packet = (decision.get("action_params", {}) or {}).get("dispatch_packet", {}) or {}
    severity = packet.get("severity_tier", "NEEDS_REVIEW")
    sev_color = _SEVERITY_COLOR.get(severity, "#5D4037")
    ref = _confirmation_number(route, {"name": call.get("caller_name", "")})

    st.markdown("### 📦 Deliver — dispatch packet")
    status = st.session_state.deliver_status

    packet_rows = f"""
  <div style="margin-top:0.5rem;"><b>Severity tier:</b>
    <span style="background:{sev_color};color:#FFF;padding:0.1rem 0.5rem;border-radius:0.4rem;font-weight:800;">{severity}</span></div>
  <div style="margin-top:0.3rem;"><b>Address:</b> {packet.get('address','—')}</div>
  <div style="margin-top:0.3rem;"><b>Vulnerability flags:</b> {packet.get('vulnerability_flags','none')}</div>
  <div style="margin-top:0.3rem;"><b>Responder brief:</b> {packet.get('responder_summary','—')}</div>"""

    if status == "pending":
        # Triaged and prepared, awaiting the dispatcher's decision.
        st.markdown(
            f"""<div style="padding:1rem 1.15rem;border-radius:0.6rem;border:2px dashed {style['bg']};
background:rgba(0,0,0,0.02);">
  <div style="font-size:1.05rem;font-weight:800;color:{style['bg']};">{style['icon']} {style['label']}</div>
  <div style="margin-top:0.2rem;opacity:0.9;">{decision.get('rationale','')}</div>
  {packet_rows}
  <div style="margin-top:0.55rem;font-weight:800;color:{style['bg']};">🧾 Packet prepared — dispatcher's call</div>
</div>""",
            unsafe_allow_html=True,
        )
        st.caption("The agent triaged the call and prepared the packet. **Nothing is dispatched until a human dispatcher confirms.**")
        col_go, col_hold = st.columns(2)
        if col_go.button("🚑 Dispatch responder", type="primary", use_container_width=True, key="dispatch_action"):
            st.session_state.deliver_status = "dispatched"
            st.rerun()
        if col_hold.button("✋ Hold & review", use_container_width=True, key="hold_action"):
            st.session_state.deliver_status = "held"
            st.rerun()

    elif status == "dispatched":
        st.markdown(
            f"""<div style="padding:1rem 1.15rem;border-radius:0.6rem;border:2px solid {style['bg']};
background:rgba(0,0,0,0.03);">
  <div style="font-size:1.05rem;font-weight:800;color:{style['bg']};">{style['icon']} {style['label']}</div>
  {packet_rows}
  <div style="margin-top:0.3rem;"><b>Dispatch ref #:</b> <code>{ref}</code></div>
  <div style="margin-top:0.55rem;font-weight:800;color:{style['bg']};">✅ Dispatcher confirmed — packet sent to responder</div>
</div>""",
            unsafe_allow_html=True,
        )
        st.caption("DELIVER is mocked — in production, confirmation pages the on-call responder with this packet.")

    else:  # held → nothing dispatched, dispatcher will review
        review = ROUTE_STYLE["ESCALATE_HUMAN"]
        st.markdown(
            f"""<div style="padding:1rem 1.15rem;border-radius:0.6rem;border:2px solid {review['bg']};
background:rgba(0,0,0,0.03);">
  <div style="font-size:1.05rem;font-weight:800;color:{review['bg']};">{review['icon']} Held for dispatcher review</div>
  <div style="margin-top:0.4rem;">No responder was dispatched. A dispatcher will review the packet before any action.</div>
  <div style="margin-top:0.2rem;"><b>Reference #:</b> <code>{ref}</code></div>
  <div style="margin-top:0.55rem;font-weight:800;color:{review['bg']};">✋ Awaiting human dispatcher</div>
</div>""",
            unsafe_allow_html=True,
        )
        st.caption("A held call is never dropped — it waits on a human, with nothing dispatched.")
        if st.button("↩ Reconsider", use_container_width=True, key="reconsider_call_action"):
            st.session_state.deliver_status = "pending"
            st.rerun()


# ============================================================
# 7) MAIN LAYOUT
# ============================================================
# Branch on the active domain. The DECIDE stage (decision log) is shared; only the
# record source, DETECT card, DELIVER card, and decide() bindings differ.
is_call = st.session_state.mode == MODE_CALL

if st.session_state.selected is None:
    hint = ("👈 Pick a call from the sidebar to triage it."
            if is_call else
            "👈 Pick a customer from the sidebar to detect their bill shock.")
    st.info(hint)
    st.stop()

if is_call:
    rec = agent.CALLS[st.session_state.selected]
    _render_detect_call(rec)
else:
    rec = agent.CUSTOMERS[st.session_state.selected]
    _render_detect(rec)

run = st.button("⚡ Run Agent", type="primary", use_container_width=True)

# Trigger the DECIDE call on click; persist the result across reruns.
if run:
    with st.spinner(f"Reasoning… (real Gemini call · {agent.PRIMARY_MODEL})"):
        _t0 = time.time()
        if is_call:
            st.session_state.decision = agent.decide(
                st.session_state.client, rec,
                build_prompt_fn=agent.build_call_prompt,
                deterministic_fn=agent._deterministic_call_decision,
                valid_routes=agent.CALL_ROUTES,
            )
        else:
            st.session_state.decision = agent.decide(st.session_state.client, rec)
        st.session_state.decision_latency = round(time.time() - _t0, 2)
    st.session_state.log_done = False            # replay the reveal for this fresh decision
    st.session_state.deliver_status = "pending"  # new decision → awaiting the human decision

decision = st.session_state.decision
if decision:
    st.markdown("### 🧠 Decision Log — live agent reasoning")
    _render_source_badge(decision)

    if not st.session_state.log_done:
        # First render after a run → stage the reveal of the REAL reasoning lines.
        st.write_stream(_stream_steps(decision.get("reasoning_steps", [])))
        st.session_state.log_done = True
    else:
        # Subsequent reruns (e.g. widget interaction) → show instantly, no re-delay.
        for step in decision.get("reasoning_steps", []):
            st.markdown(f"- {step}")

    _render_route_badge(decision)
    if is_call:
        _render_deliver_call(decision, rec)
    else:
        _render_deliver(decision, rec)


# ============================================================
# 8) DEBUG / EVIDENCE PANELS (judge toggles)
#    Proof-of-liveness (raw JSON, prompt) + guardrail (route enum) evidence.
# ============================================================
if any([show_profile, show_prompt, show_routes, show_json, show_meta]):
    st.divider()
    st.markdown("### 🧪 Debug / Evidence")

if show_profile:
    label = "Call record" if is_call else "Customer profile"
    st.markdown(f"**🗂️ {label} — raw mock input (the DETECT source)**")
    st.json(rec)

if show_prompt:
    if is_call:
        _sys_i, _user_c = agent.build_call_prompt(rec)
    else:
        _sys_i, _user_c = agent.build_prompt(rec)
    st.markdown("**📨 Prompt sent to Gemini — the slim payload the model actually saw**")
    st.caption("System instruction")
    st.code(_sys_i, language="text")
    st.caption("User content")
    st.code(_user_c, language="text")

if show_routes:
    _routes = agent.CALL_ROUTES if is_call else agent.ROUTES
    st.markdown("**🛡️ Allowed routes — constrained enum; the model cannot invent a route**")
    st.code("\n".join(sorted(_routes)), language="text")

if show_json:
    if decision:
        st.markdown("**🧾 Structured decision — parsed from the model's JSON output**")
        st.json(decision)
    else:
        st.info("Run the agent to see the structured decision JSON.")

if show_meta:
    if decision:
        st.markdown("**📊 Call metadata**")
        st.write({
            "model_used": decision.get("model_used"),
            "source": decision.get("source"),
            "latency_seconds": st.session_state.get("decision_latency"),
        })
    else:
        st.info("Run the agent to see call metadata.")
