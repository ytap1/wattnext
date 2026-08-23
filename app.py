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
st.title("⚡ WattNext")
st.subheader("The Kill Bill Shock Agent — Detect. Decide. Deliver.")
st.caption(
    "One real **Google Gemini** reasoning call resolves a customer's utility bill shock — "
    "reaching a *different* resolution per customer. Everything else is mocked for the demo."
)

# Route → display styling (energy/utility theme).
ROUTE_STYLE: Dict[str, Dict[str, str]] = {
    "ASSISTANCE_ENROLLMENT": {"bg": "#1B5E20", "icon": "🤝", "label": "Assistance Enrollment"},
    "BUDGET_BILLING":        {"bg": "#0D47A1", "icon": "📊", "label": "Budget Billing (Level-Pay)"},
    "REVIEW":                {"bg": "#5D4037", "icon": "🔎", "label": "Escalated for Human Review"},
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
    """Pick a customer and clear any prior decision so the loop restarts clean."""
    st.session_state.selected = idx
    st.session_state.decision = None
    st.session_state.log_done = False
    st.session_state.deliver_status = "pending"


# ============================================================
# 3) SIDEBAR — one-click demo controls
# ============================================================
with st.sidebar:
    st.header("🎬 Demo Controls")
    st.caption("One-click scenarios for the live pitch.")

    if st.button("🔴 Customer A: Maria (low-income, medical)", use_container_width=True):
        _select_customer(0)
        st.rerun()

    if st.button("🟢 Customer B: James (seasonal AC)", use_container_width=True):
        _select_customer(1)
        st.rerun()

    if st.button("↺ Reset", use_container_width=True):
        st.session_state.selected = None
        st.session_state.decision = None
        st.session_state.log_done = False
        st.session_state.deliver_status = "pending"
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


# ============================================================
# 7) MAIN LAYOUT
# ============================================================
if st.session_state.selected is None:
    st.info("👈 Pick a customer from the sidebar to detect their bill shock.")
    st.stop()

cust = agent.CUSTOMERS[st.session_state.selected]

_render_detect(cust)

run = st.button("⚡ Run Agent", type="primary", use_container_width=True)

# Trigger the DECIDE call on click; persist the result across reruns.
if run:
    with st.spinner(f"Reasoning… (real Gemini call · {agent.PRIMARY_MODEL})"):
        _t0 = time.time()
        st.session_state.decision = agent.decide(st.session_state.client, cust)
        st.session_state.decision_latency = round(time.time() - _t0, 2)
    st.session_state.log_done = False            # replay the reveal for this fresh decision
    st.session_state.deliver_status = "pending"  # new decision → awaiting customer choice

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
    _render_deliver(decision, cust)


# ============================================================
# 8) DEBUG / EVIDENCE PANELS (judge toggles)
#    Proof-of-liveness (raw JSON, prompt) + guardrail (route enum) evidence.
# ============================================================
if any([show_profile, show_prompt, show_routes, show_json, show_meta]):
    st.divider()
    st.markdown("### 🧪 Debug / Evidence")

if show_profile:
    st.markdown("**🗂️ Customer profile — raw mock input (the DETECT source)**")
    st.json(cust)

if show_prompt:
    _sys_i, _user_c = agent.build_prompt(cust)
    st.markdown("**📨 Prompt sent to Gemini — the slim payload the model actually saw**")
    st.caption("System instruction")
    st.code(_sys_i, language="text")
    st.caption("User content")
    st.code(_user_c, language="text")

if show_routes:
    st.markdown("**🛡️ Allowed routes — constrained enum; the model cannot invent a route**")
    st.code("\n".join(sorted(agent.ROUTES)), language="text")

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
