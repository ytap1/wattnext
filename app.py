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
import html
import re
import time
from functools import partial
from pathlib import Path
from typing import Any, Dict, Iterator, Sequence

import streamlit as st

import agent


# ============================================================
# 0) PAGE SETUP + THEME
# ============================================================
# Brand assets (see brand/brand-spec.md). Resolved from this file's location so
# paths hold no matter the working directory `streamlit run` is launched from.
_BRAND = Path(__file__).parent / "brand"
_FAVICON = str(_BRAND / "favicons" / "icon-192.png")
_LOGO_CHROME = str(_BRAND / "wattnext-lockup-mono-white.svg")  # top-left chrome lockup (dark surface)
_MARK = str(_BRAND / "wattnext-mark.svg")  # pulse symbol only (transparent) — hero side mark

st.set_page_config(
    page_title="WattNext", page_icon=_FAVICON, layout="centered",
    initial_sidebar_state="expanded",  # keep demo controls visible on stage
)
# Brand mark in the top-left chrome (app + sidebar corner).
st.logo(_LOGO_CHROME, icon_image=_MARK)
# Global polish. Streamlit has no CSS layer to edit, so inject once: tighter top gap,
# higher caption contrast on the Ink surface, and inputs that read as intentional controls.
st.markdown(
    """<style>
  .block-container { padding-top: 2.5rem; }
  /* Caption text — lift off Streamlit's muted default for readability on dark Ink. */
  [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p { color:#A8B5C6 !important; }
  /* Inputs/selects — a visible slate border so empty fields don't read as voids. */
  .stTextInput input,
  .stSelectbox div[data-baseweb="select"] > div {
    border: 1px solid #334155 !important;
  }
  /* Trim heading top-margins so the hero stack sits tighter. */
  h2, h3 { margin-top: 0.6rem !important; }
  /* Hide Streamlit's hover anchor-link icon next to headers (visual clutter on stage). */
  [data-testid="stHeaderActionElements"] { display: none !important; }
</style>""",
    unsafe_allow_html=True,
)
# The two demo modes. Value shown in the sidebar toggle.
MODE_BILL = "⚡ Bill Shock"
MODE_CALL = "🚨 First Response"

# First Response call sources — a canned demo call, or a live mic recording.
SOURCE_CANNED = "📼 Canned call"
SOURCE_LIVE = "🎙️ Live mic"

# Account vulnerability flags for the live-capture dropdown. "None" is the empty sentinel
# (mapped to "" at the call site) so downstream truthiness checks stay unchanged.
VULN_OPTIONS = ["None", "Medical / life-support", "Elderly / mobility", "Disability"]

# Header copy follows the active domain. The sidebar radio (key="mode") persists in
# session_state across reruns; default to First Response (the hero domain) on the first
# render (before the radio exists) so the header is never stale after a mode switch.
_active_mode = st.session_state.get("mode", MODE_CALL)
# Hero = pulse mark on the side + a large wordmark and tagline (brand colors on dark).
_hero_mark, _hero_word = st.columns([1, 3.4], vertical_alignment="center")
with _hero_mark:
    st.image(_MARK, width=130)
with _hero_word:
    st.markdown(
        """<div style="display:inline-block;line-height:1;">
  <div style="font-size:3.6rem;font-weight:800;letter-spacing:-1px;">
    <span style="color:#F8FAFC;">Watt</span><span style="color:#22D3EE;">Next</span>
  </div>
  <div style="font-size:1.02rem;font-weight:600;color:#38BDF8;margin-top:0.5rem;
              text-align:justify;text-align-last:justify;">
    DETECT · DECIDE · DELIVER
  </div>
</div>""",
        unsafe_allow_html=True,
    )
# Constant brand line — the flexible engine is the hero; the domain is just what it's pointed at.
st.markdown("**One flexible agent for the utility contact center — point it at a new problem, it adapts.**")
if _active_mode == MODE_CALL:
    st.subheader("Live-Call Copilot — First Response")
    st.caption(
        "A copilot for the contact-center **agent**: it listens as the caller speaks, analyzes "
        "in the background, and hands the agent a verified-ready decision — severity tier, routing, "
        "and a dispatch packet. The *same* engine that resolves bill shock, pointed at a hazard call."
    )
else:
    st.subheader("The Kill Bill Shock Agent")
    st.caption(
        "One real **Google Gemini** reasoning call — a *different* resolution per customer. "
        "The *same* engine that triages a hazard call, pointed at bill shock."
    )
# Surface the trust signal as a visible chip, not buried gray text — it's the strongest
# credibility point for a utility-hazard use case.
_trust_line = (
    "Human-in-the-loop · never auto-dispatched" if _active_mode == MODE_CALL
    else "Human-in-the-loop · human approves every resolution"
)
st.markdown(
    f"""<div style="display:inline-block;margin:0.15rem 0 0.25rem;padding:0.3rem 0.7rem;
border-radius:999px;background:#1E293B;border:1px solid #334155;
color:#22D3EE;font-size:0.85rem;font-weight:600;">
  🔒 {_trust_line}
</div>""",
    unsafe_allow_html=True,
)
# The flexibility/scalability proof, made visible: the engine is CONSTANT across domains —
# only the prompt + route list change. Rendered in BOTH modes so "same engine, retargeted"
# is an on-screen fact, not just a spoken claim. The domain pill tracks the sidebar toggle.
st.markdown(
    f"""<div style="margin:0.4rem 0 0.3rem;padding:0.7rem 0.95rem;border-radius:0.6rem;
background:#111C31;border:1px solid #334155;border-left:4px solid #22D3EE;">
  <div style="display:flex;flex-wrap:wrap;align-items:center;gap:0.5rem;
              font-size:0.95rem;font-weight:700;color:#E2E8F0;">
    <span>⚙️ One engine · <code style="color:#22D3EE;background:transparent;padding:0;">agent.decide()</code></span>
    <span style="color:#64748B;">→ now pointed at</span>
    <span style="padding:0.1rem 0.55rem;border-radius:999px;background:#1E293B;
                 border:1px solid #334155;color:#38BDF8;font-size:0.85rem;font-weight:600;">{_active_mode}</span>
  </div>
  <div style="margin-top:0.35rem;font-size:0.82rem;color:#94A3B8;">
    Retarget to a new problem = swap the prompt + route list. No new model, no new pipeline.
  </div>
</div>""",
    unsafe_allow_html=True,
)

# Route → display styling (energy/utility theme). `bg` = solid badge fill (white text on
# it); `fg` = a brightened tint of the same hue for text/borders that must read on the
# dark Ink surface. Two domains share this map so the render helpers work for both.
ROUTE_STYLE: Dict[str, Dict[str, str]] = {
    # Bill Shock domain
    "ASSISTANCE_ENROLLMENT": {"bg": "#1B5E20", "fg": "#4ADE80", "icon": "🤝", "label": "Assistance Enrollment"},
    "BUDGET_BILLING":        {"bg": "#0D47A1", "fg": "#60A5FA", "icon": "📊", "label": "Budget Billing (Level-Pay)"},
    "REVIEW":                {"bg": "#5D4037", "fg": "#D6B08C", "icon": "🔎", "label": "Escalated for Human Review"},
    # First Response domain
    "DISPATCH_NOW":          {"bg": "#B71C1C", "fg": "#F87171", "icon": "🚑", "label": "Dispatch Emergency Responder"},
    "SCHEDULE_TECH":         {"bg": "#0D47A1", "fg": "#60A5FA", "icon": "🔧", "label": "Schedule Technician (Non-Emergency)"},
    "ESCALATE_HUMAN":        {"bg": "#5D4037", "fg": "#D6B08C", "icon": "🧑‍✈️", "label": "Escalate to Human Dispatcher"},
}

# Per-step reveal delay for the live decision log. Trim to 0.3 if the W5
# two-branch dry run pushes the 5-min slot (see HACKATHON.md W5).
STEP_DELAY_SEC = 0.5

# Per-chunk delay for the live-call replay (First Response hero). The transcript
# reveals a chunk at a time while the danger-signal dashboard re-populates in sync,
# so the copilot visibly keeps pace with the caller. Trim alongside STEP_DELAY_SEC.
PLAY_DELAY_SEC = 0.7
PLAY_MAX_CHUNKS = 5  # cap reveal steps so a long live transcript can't overrun the slot

# Kill-switch for cross-incident prompt injection. When True, a detected systemic
# cluster is threaded into the single real decision's prompt so its reasoning can cite
# the pattern. Flip to False to ship the intelligence PANEL untouched while leaving the
# live prompt exactly as-is — a safety valve if the model misbehaves off-stage. The
# panel itself is deterministic and never depends on this flag.
CLUSTER_PROMPT_INJECTION = True


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
    ("selected", None),      # index into agent.CUSTOMERS/CALLS, or None
    ("decision", None),      # last decision dict, or None
    ("call_played", False),         # whether the live-call replay has run for this record
    ("log_done", False),            # whether the staged reveal has already played
    ("deliver_status", "pending"),  # pending | accepted | declined
    ("decision_latency", None),     # seconds the live DECIDE call took
    ("live_transcript", ""),        # Gemini transcription of the recorded call
    ("live_audio_sig", None),       # hash of the last transcribed audio (avoid re-calling)
    ("cluster", None),              # cross-incident cluster dict for the active call, or None
]:
    if _key not in st.session_state:
        st.session_state[_key] = _default


def _clear_decision() -> None:
    """Reset just the DECIDE/DELIVER state (a fresh record → replay the loop)."""
    st.session_state.decision = None
    st.session_state.call_played = False
    st.session_state.log_done = False
    st.session_state.deliver_status = "pending"
    st.session_state.cluster = None


def _select_customer(idx: int) -> None:
    """Pick a record and clear any prior decision so the loop restarts clean."""
    st.session_state.selected = idx
    _clear_decision()


def _reset_loop() -> None:
    """Clear the whole loop back to the empty state (used by Reset, mode/source switch)."""
    st.session_state.selected = None
    st.session_state.live_transcript = ""
    st.session_state.live_audio_sig = None
    _clear_decision()


# ============================================================
# 3) SIDEBAR — one-click demo controls
# ============================================================
with st.sidebar:
    st.header("🎬 Demo Controls")

    # Domain toggle — same DETECT→DECIDE→DELIVER engine, two triage domains.
    # Switching modes clears the loop so the two demos never bleed into each other.
    mode = st.radio(
        "Triage domain",
        [MODE_CALL, MODE_BILL],  # First Response first — it's the hero domain / default
        key="mode",
        on_change=_reset_loop,
        help="Same agent engine, two domains. First Response triages inbound "
             "utility-hazard calls (gas, electrical, and more); Bill Shock resolves billing.",
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
        # Canned demo call, or a live recording transcribed by Gemini.
        call_source = st.radio(
            "Call source", [SOURCE_CANNED, SOURCE_LIVE],
            key="call_source", on_change=_reset_loop, horizontal=True,
        )
        if call_source == SOURCE_CANNED:
            if st.button("🔴 Call A: Rosa (active leak, oxygen-dependent)", use_container_width=True):
                _select_customer(0)
                st.rerun()
            if st.button("🟢 Call B: Trevor (faint odor, no danger)", use_container_width=True):
                _select_customer(1)
                st.rerun()
            if st.button("🟠 Call C: Marcus (downed power line, sparks)", use_container_width=True):
                _select_customer(2)
                st.rerun()
        else:
            st.caption("🎙️ Record the caller in the main panel →")

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
    """DETECT for the First Response domain — the raw inbound utility-hazard call."""
    vuln = call.get("account_vulnerability_flag")
    # Red banner: every inbound hazard call is treated as potentially life-safety
    # until the agent triages it.
    st.markdown(
        f"""<div style="padding:1rem 1.15rem;border-radius:0.6rem;background:#B71C1C;
color:#FFFFFF;margin-bottom:0.5rem;">
  <div style="font-size:1.15rem;font-weight:800;">📞 INCOMING HAZARD CALL — {call.get('caller_name')}</div>
  <div style="font-size:1.05rem;font-weight:700;margin:0.15rem 0;">📍 {call.get('address')}</div>
  <div style="margin-top:0.35rem;font-weight:500;opacity:0.95;">Awaiting triage — nothing dispatched until a human agent confirms.</div>
</div>""",
        unsafe_allow_html=True,
    )
    c1, c2 = st.columns(2)
    c1.metric("Medical-dependent household", "Yes" if call.get("medical_dependent") else "No")
    c2.metric("Vulnerability flag", vuln if vuln else "None")


# ------------------------------------------------------------------
# First Response — live-voice capture + danger-signal dashboard.
# No voice biometrics: every metric traces to a word actually said.
# ------------------------------------------------------------------
_SIGNAL_SEVERITY_COLOR = {
    "CRITICAL": "#B71C1C", "HIGH": "#E65100", "LOW": "#0D47A1", "NEEDS_REVIEW": "#5D4037",
}


# Signal-tier colors — red = active danger, gold = named-but-unconfirmed hazard, orange = advisory.
_SIGNAL_TIER_COLOR = {"danger": "#B71C1C", "ambiguous": "#CA8A04", "advisory": "#E65100"}


def _preview_severity(danger: list, advisory: list, vulnerable: bool, ambiguous: Sequence[str] = ()) -> str:
    """Signal-only severity preview — mirrors decide()'s deterministic tiering."""
    if danger and vulnerable:
        return "CRITICAL"
    if danger:
        return "HIGH"
    if ambiguous:  # named hazard, no confirming detail -> human review, never a guess
        return "NEEDS_REVIEW"
    if advisory:
        return "LOW"
    return "NEEDS_REVIEW"


def _highlight(transcript: str, danger: list, advisory: list, ambiguous: Sequence[str] = ()) -> str:
    """Wrap detected (non-negated) keywords in colored spans; escape everything else."""
    spans = (
        [(k, "danger") for k in danger]
        + [(k, "ambiguous") for k in ambiguous]
        + [(k, "advisory") for k in advisory]
    )
    if not spans:
        return html.escape(transcript)
    spans.sort(key=lambda kv: len(kv[0]), reverse=True)  # longest first: "strong smell" before "smell"
    kind_of = {k.lower(): kind for k, kind in spans}
    pattern = re.compile("|".join(re.escape(k) for k, _ in spans), re.IGNORECASE)
    out, last = [], 0
    for m in pattern.finditer(transcript):
        out.append(html.escape(transcript[last:m.start()]))
        bg = _SIGNAL_TIER_COLOR.get(kind_of.get(m.group(0).lower()), "#E65100")
        out.append(
            f'<span style="background:{bg};color:#fff;padding:0 4px;border-radius:4px;'
            f'font-weight:700;">{html.escape(m.group(0))}</span>'
        )
        last = m.end()
    out.append(html.escape(transcript[last:]))
    return "".join(out)


def _chips(items: list, bg: str) -> str:
    if not items:
        return '<span style="opacity:0.6;">none detected</span>'
    return " ".join(
        f'<span style="display:inline-block;background:{bg};color:#fff;padding:2px 8px;'
        f'border-radius:10px;font-size:0.8rem;font-weight:600;margin:2px;">{html.escape(c)}</span>'
        for c in items
    )


def _render_signal_dashboard(call: Dict[str, Any]) -> None:
    """Live danger-signal dashboard — the transcript with signals highlighted, plus
    counts, a severity preview, and (once triaged) the real time-to-decision."""
    transcript = call.get("transcript") or ""
    signals = agent.find_signals(transcript)
    danger, advisory = signals["danger"], signals["low_signal"]
    ambiguous = signals.get("ambiguous", [])
    vulnerable = bool(call.get("account_vulnerability_flag")) or bool(call.get("medical_dependent"))
    sev = _preview_severity(danger, advisory, vulnerable, ambiguous)

    # Once triaged, show the DECIDED severity (from the real decision) rather than the
    # keyword-only preview — otherwise the preview could contradict the decision log below
    # (e.g. preview "NEEDS_REVIEW" over a decision that dispatched).
    decided = st.session_state.decision
    if decided:
        sev = (decided.get("action_params", {}) or {}).get("dispatch_packet", {}).get("severity_tier", sev)
        sev_label = "SIGNAL SEVERITY"
    else:
        sev_label = "SIGNAL SEVERITY (preview)"

    st.markdown("### 📡 Danger-signal dashboard")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Active-danger signals", len(danger))
    m2.metric("Ambiguous hazard", len(ambiguous))
    m3.metric("Advisory signals", len(advisory))
    lat = st.session_state.decision_latency
    m4.metric("Time-to-triage", f"{lat:.2f}s" if (lat and decided) else "—")

    st.markdown(
        f"""<div style="display:inline-block;padding:0.35rem 0.8rem;border-radius:0.5rem;
background:{_SIGNAL_SEVERITY_COLOR.get(sev)};color:#fff;font-weight:800;margin:0.1rem 0 0.5rem;">
{sev_label}: {sev}</div>""",
        unsafe_allow_html=True,
    )
    st.markdown("**📝 Transcript — active-danger in red, ambiguous hazard in gold, advisory in orange**")
    st.markdown(
        f"""<div style="padding:0.8rem 1rem;border-radius:0.5rem;border-left:4px solid #B71C1C;
background:rgba(255,255,255,0.05);line-height:1.7;">{_highlight(transcript, danger, advisory, ambiguous)}</div>""",
        unsafe_allow_html=True,
    )
    st.markdown(f"**Active-danger:** {_chips(danger, '#B71C1C')}", unsafe_allow_html=True)
    st.markdown(f"**Ambiguous hazard:** {_chips(ambiguous, '#CA8A04')}", unsafe_allow_html=True)
    st.markdown(f"**Advisory:** {_chips(advisory, '#E65100')}", unsafe_allow_html=True)
    if ambiguous and not danger:
        st.caption(
            "A hazard is named but unconfirmed — no active-danger signal to dispatch on, "
            "yet too risky to downgrade. The agent escalates to a human rather than guess."
        )


def _render_incident_intelligence(call: Dict[str, Any], cluster: "Dict[str, Any] | None") -> None:
    """Cross-incident intelligence panel — the WattNext differentiator.

    Correlates this call against recent reports on the same main and, when a systemic
    pattern emerges, flags a probable main event + vulnerable households for proactive
    outreach, with a quantified value strip. Reads detect_cluster() output ONLY (never
    model output), so it renders identically live or on the deterministic fallback.
    """
    if not cluster:
        return
    st.markdown("### 🛰️ Cross-incident intelligence")

    if not cluster.get("clustered"):
        prior = cluster.get("prior_count", 0)
        label = cluster.get("street_label", "this area")
        hours = max(cluster.get("window_min", 120) // 60, 1)
        rpt = f"{prior} prior report{'s' if prior != 1 else ''}"
        st.markdown(
            f"""<div style="padding:0.9rem 1.1rem;border-radius:0.6rem;background:#111C31;
border:1px solid #334155;border-left:4px solid #22D3EE;color:#E2E8F0;">
  <div style="font-weight:800;color:#38BDF8;">🛰️ No systemic pattern — isolated incident</div>
  <div style="margin-top:0.3rem;font-size:0.92rem;color:#94A3B8;">
    {rpt} on {html.escape(label)} in the last {hours}h — below the cluster threshold.
    Handled as a single call. <b>No false alarm raised.</b>
  </div>
</div>""",
            unsafe_allow_html=True,
        )
        st.caption("Proof it doesn't cry wolf: one main, one report, no manufactured pattern.")
        return

    # --- Clustered: a probable systemic event ---
    label = cluster.get("street_label", "this area")
    hazard = cluster.get("dominant_hazard", "utility")
    val = cluster.get("value", {}) or {}
    st.markdown(
        f"""<div style="padding:1rem 1.15rem;border-radius:0.6rem;
background:linear-gradient(90deg,#B71C1C 0%,#CA8A04 100%);color:#FFFFFF;margin-bottom:0.5rem;">
  <div style="font-size:1.15rem;font-weight:800;">⚠️ PROBABLE SYSTEMIC EVENT</div>
  <div style="font-size:1rem;font-weight:700;margin-top:0.15rem;">
    Possible {html.escape(hazard)}-main event on {html.escape(label)} — not an isolated leak
  </div>
</div>""",
        unsafe_allow_html=True,
    )

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Reports on this main", cluster.get("total_reports", 0))
    m2.metric("Within", f"{cluster.get('first_report_min_ago', 0)} min")
    m3.metric("Vulnerable households", len(cluster.get("vulnerable_neighbors", [])))
    m4.metric("Detected earlier", f"~{val.get('detection_lead_min', 0)} min")

    st.markdown("**📍 Correlated reports on this main**")
    rows = []
    for inc in cluster.get("matched_incidents", []):
        vflag = inc.get("vulnerability_flag")
        chip = (
            f' <span style="background:#CA8A04;color:#fff;padding:1px 7px;border-radius:10px;'
            f'font-size:0.72rem;font-weight:700;">{html.escape(vflag)}</span>' if vflag else ""
        )
        status = html.escape(str(inc.get("status", "")).replace("_", " "))
        rows.append(
            f"""<div style="padding:0.4rem 0.7rem;border-left:3px solid #B71C1C;margin:0.25rem 0;
background:rgba(255,255,255,0.04);border-radius:0.35rem;">
  <b>{html.escape(inc.get('id',''))}</b> · {html.escape(inc.get('address',''))}
  · {inc.get('minutes_ago','?')} min ago · <i>{status}</i>{chip}
  <div style="font-size:0.82rem;color:#94A3B8;margin-top:0.1rem;">{html.escape(inc.get('summary',''))}</div>
</div>"""
        )
    st.markdown("".join(rows), unsafe_allow_html=True)

    # Proactive vulnerable-household outreach — the life-safety differentiator.
    vuln = cluster.get("vulnerable_neighbors", [])
    if vuln:
        names = "; ".join(
            f"{html.escape(v.get('address',''))} "
            f"({html.escape(v.get('vulnerability_flag') or 'vulnerable')})"
            for v in vuln
        )
        st.markdown(
            f"""<div style="padding:0.85rem 1.1rem;border-radius:0.6rem;background:#3B2A00;
border:1px solid #CA8A04;border-left:4px solid #FACC15;color:#FDE68A;margin-top:0.4rem;">
  <div style="font-weight:800;">📞 Proactive outreach — vulnerable household on this main</div>
  <div style="margin-top:0.25rem;color:#FEF3C7;">{names}</div>
  <div style="font-size:0.82rem;color:#D6B08C;margin-top:0.2rem;">
    Flagged for a wellness call <b>before they dial in</b> — the platform knows they're on the affected main.
  </div>
</div>""",
            unsafe_allow_html=True,
        )

    # Quantified value strip — emergency framing, conservative + labeled.
    st.markdown(
        f"""<div style="margin-top:0.5rem;padding:0.8rem 1rem;border-radius:0.6rem;
background:#052E2B;border:1px solid #0D9488;border-left:4px solid #22D3EE;">
  <div style="font-weight:800;color:#5EEAD4;">💡 Value of catching it early</div>
  <div style="display:flex;flex-wrap:wrap;gap:1.4rem;margin-top:0.4rem;color:#E2E8F0;">
    <div><b style="color:#22D3EE;font-size:1.25rem;">{val.get('exposure_minutes_avoided',0)}</b><br>
      <span style="font-size:0.8rem;color:#94A3B8;">exposure-minutes acted on sooner</span></div>
    <div><b style="color:#22D3EE;font-size:1.25rem;">{val.get('trucks_without',0)} &rarr; {val.get('trucks_with',0)}</b><br>
      <span style="font-size:0.8rem;color:#94A3B8;">emergency truck-rolls (consolidated)</span></div>
    <div><b style="color:#22D3EE;font-size:1.25rem;">${val.get('dollars_saved',0):,}</b><br>
      <span style="font-size:0.8rem;color:#94A3B8;">avoidable dispatch cost, this event</span></div>
  </div>
</div>""",
        unsafe_allow_html=True,
    )
    st.caption(
        "Cross-incident intelligence — deterministic, no extra AI call. No single call "
        "transcript reveals this. The dollar figure prices only avoidable dispatches; the "
        "safety benefit is shown as exposure-minutes and the flagged household — deliberately not dollarized."
    )


def _capture_live_call() -> "Dict[str, Any] | None":
    """Render the mic + caller inputs, transcribe a fresh recording with Gemini, and
    return a call record. Returns None while waiting for audio or on transcription failure."""
    st.markdown("### 🎙️ Live call capture")
    st.caption("Record the caller, then stop — Gemini transcribes what it heard.")
    audio = st.audio_input("Record the caller", help="Mic needs localhost or HTTPS.")
    c1, c2 = st.columns(2)
    address = c1.text_input("Address (from caller ID / account)", value="418 Maple Street, Apt 2B", key="live_addr")
    # A flag is a fixed set, not free text — a dropdown improves data quality. "None" maps to
    # "" so the downstream truthiness (bool(vuln) / vuln or None) is unchanged.
    vuln_choice = c2.selectbox(
        "Account vulnerability flag (optional)", VULN_OPTIONS, key="live_vuln",
    )
    vuln = "" if vuln_choice == "None" else vuln_choice

    if audio is None:
        st.markdown(
            """<div style="padding:0.85rem 1.1rem;border-radius:0.6rem;background:#1E293B;
border-left:4px solid #22D3EE;color:#E2E8F0;font-weight:600;">
  ↑ Record a call above to triage it.
</div>""",
            unsafe_allow_html=True,
        )
        return None

    data = audio.getvalue()
    sig = hash(data)
    if sig != st.session_state.live_audio_sig:  # only transcribe a genuinely new recording
        with st.spinner("Gemini is transcribing the call…"):
            st.session_state.live_transcript = agent.transcribe_call(st.session_state.client, data)
            st.session_state.live_audio_sig = sig
            _clear_decision()  # new call → replay the loop

    transcript = st.session_state.live_transcript
    if not transcript:
        st.warning("Transcription failed (audio or network). Try again, or switch to a canned call.")
        return None

    return {
        "caller_name": "Live caller",
        "address": address,
        "transcript": transcript,
        "medical_dependent": bool(vuln),
        "account_vulnerability_flag": vuln or None,
    }


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
            f"""<div style="padding:1rem 1.15rem;border-radius:0.6rem;border:2px dashed {style['fg']};
background:rgba(255,255,255,0.05);">
  <div style="font-size:1.05rem;font-weight:800;color:{style['fg']};">{style['icon']} {plan}</div>
  <div style="margin-top:0.4rem;"><b>{figure_label}:</b> {figure_val}</div>
  <div style="margin-top:0.2rem;opacity:0.8;">{params.get('note','')}</div>
  <div style="margin-top:0.55rem;font-weight:800;color:{style['fg']};">🧾 Prepared — your choice</div>
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
            f"""<div style="padding:1rem 1.15rem;border-radius:0.6rem;border:2px solid {style['fg']};
background:rgba(255,255,255,0.05);">
  <div style="font-size:1.05rem;font-weight:800;color:{style['fg']};">{style['icon']} {plan}</div>
  <div style="margin-top:0.4rem;"><b>{figure_label}:</b> {figure_val}</div>
  <div style="margin-top:0.2rem;"><b>Confirmation #:</b> <code>{_confirmation_number(route, cust)}</code></div>
  <div style="margin-top:0.55rem;font-weight:800;color:{style['fg']};">✅ Accepted &amp; enrolled — action completed</div>
</div>""",
            unsafe_allow_html=True,
        )
        st.caption("DELIVER is mocked — in production, acceptance triggers the real enrollment/plan change.")

    else:  # declined → human handoff (surfaces the REVIEW route in the enum)
        review = ROUTE_STYLE["REVIEW"]
        st.markdown(
            f"""<div style="padding:1rem 1.15rem;border-radius:0.6rem;border:2px solid {review['fg']};
background:rgba(255,255,255,0.05);">
  <div style="font-size:1.05rem;font-weight:800;color:{review['fg']};">{review['icon']} Handed off to a WattNext specialist</div>
  <div style="margin-top:0.4rem;">No account changes were made. A specialist will review your options with you.</div>
  <div style="margin-top:0.2rem;"><b>Reference #:</b> <code>{_confirmation_number('REVIEW', cust)}</code></div>
  <div style="margin-top:0.2rem;"><b>Callback:</b> within 24 hours</div>
  <div style="margin-top:0.55rem;font-weight:800;color:{review['fg']};">💬 Escalated for human review</div>
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
            f"""<div style="padding:1rem 1.15rem;border-radius:0.6rem;border:2px dashed {style['fg']};
background:rgba(255,255,255,0.05);">
  <div style="font-size:1.05rem;font-weight:800;color:{style['fg']};">{style['icon']} {style['label']}</div>
  <div style="margin-top:0.2rem;opacity:0.9;">{decision.get('rationale','')}</div>
  {packet_rows}
  <div style="margin-top:0.55rem;font-weight:800;color:{style['fg']};">🧾 Packet prepared — agent's call</div>
</div>""",
            unsafe_allow_html=True,
        )
        st.caption("The copilot triaged the call and prepared the packet. **Nothing is dispatched until the human agent confirms.**")
        col_go, col_hold = st.columns(2)
        if col_go.button("🚑 Dispatch responder", type="primary", use_container_width=True, key="dispatch_action"):
            st.session_state.deliver_status = "dispatched"
            st.rerun()
        if col_hold.button("✋ Hold & review", use_container_width=True, key="hold_action"):
            st.session_state.deliver_status = "held"
            st.rerun()

    elif status == "dispatched":
        st.markdown(
            f"""<div style="padding:1rem 1.15rem;border-radius:0.6rem;border:2px solid {style['fg']};
background:rgba(255,255,255,0.05);">
  <div style="font-size:1.05rem;font-weight:800;color:{style['fg']};">{style['icon']} {style['label']}</div>
  {packet_rows}
  <div style="margin-top:0.3rem;"><b>Dispatch ref #:</b> <code>{ref}</code></div>
  <div style="margin-top:0.55rem;font-weight:800;color:{style['fg']};">✅ Agent confirmed — packet sent to responder</div>
</div>""",
            unsafe_allow_html=True,
        )
        st.caption("DELIVER is mocked — in production, confirmation pages the on-call responder with this packet.")

    else:  # held → nothing dispatched, dispatcher will review
        review = ROUTE_STYLE["ESCALATE_HUMAN"]
        st.markdown(
            f"""<div style="padding:1rem 1.15rem;border-radius:0.6rem;border:2px solid {review['fg']};
background:rgba(255,255,255,0.05);">
  <div style="font-size:1.05rem;font-weight:800;color:{review['fg']};">{review['icon']} Held for agent review</div>
  <div style="margin-top:0.4rem;">No responder was dispatched. The agent will review the packet before any action.</div>
  <div style="margin-top:0.2rem;"><b>Reference #:</b> <code>{ref}</code></div>
  <div style="margin-top:0.55rem;font-weight:800;color:{review['fg']};">✋ Awaiting human agent</div>
</div>""",
            unsafe_allow_html=True,
        )
        st.caption("A held call is never dropped — it waits on a human, with nothing dispatched.")
        if st.button("↩ Reconsider", use_container_width=True, key="reconsider_call_action"):
            st.session_state.deliver_status = "pending"
            st.rerun()


# ============================================================
# 6b) LIVE-CALL REPLAY
#     The hero interaction: one "▶ Play call" click reveals the transcript a
#     chunk at a time while the danger-signal dashboard populates in sync, so the
#     copilot is SEEN keeping pace with the caller — then the one real decision lands.
# ============================================================
def _split_sentences(text: str) -> list:
    """Split a transcript into sentence-ish chunks for progressive reveal."""
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    return [p for p in parts if p]


def _play_chunks(text: str, max_chunks: int = PLAY_MAX_CHUNKS) -> list:
    """Sentences for reveal, merged into at most `max_chunks` groups so a long
    (e.g. live-mic) transcript can't overrun the demo slot."""
    sents = _split_sentences(text)
    if len(sents) <= max_chunks:
        return sents
    size = -(-len(sents) // max_chunks)  # ceil division
    return [" ".join(sents[i:i + size]) for i in range(0, len(sents), size)]


def _play_call(call: Dict[str, Any]) -> None:
    """Reveal the transcript chunk-by-chunk, re-rendering the danger-signal
    dashboard on the accumulated text each step (decision is still None here, so
    the dashboard shows its preview severity). Blocking — plays during the click
    run, exactly like the decision-log staged reveal already does."""
    chunks = _play_chunks(call.get("transcript") or "")
    if not chunks:
        return
    ph = st.empty()
    acc = ""
    for i, chunk in enumerate(chunks, start=1):
        acc = f"{acc} {chunk}".strip()
        with ph.container():
            st.caption(f"🔴 Live call in progress — copilot analyzing… ({i}/{len(chunks)})")
            _render_signal_dashboard({**call, "transcript": acc})
        time.sleep(PLAY_DELAY_SEC)


def _run_decision(rec: Dict[str, Any], is_call: bool) -> None:
    """Fire the ONE real Gemini decision call and record its latency."""
    with st.spinner(f"Copilot reasoning… (real Gemini call · {agent.PRIMARY_MODEL})"):
        _t0 = time.time()
        if is_call:
            # Cross-incident cluster — deterministic, NO extra model call. Optionally
            # thread a clustered summary into THIS one call's prompt via functools.partial
            # so the reasoning can cite the systemic pattern; decide() stays untouched.
            cluster = agent.detect_cluster(rec)
            st.session_state.cluster = cluster
            build_fn = (
                partial(agent.build_call_prompt, cluster=cluster)
                if (CLUSTER_PROMPT_INJECTION and cluster.get("clustered"))
                else agent.build_call_prompt
            )
            st.session_state.decision = agent.decide(
                st.session_state.client, rec,
                build_prompt_fn=build_fn,
                deterministic_fn=agent._deterministic_call_decision,
                valid_routes=agent.CALL_ROUTES,
            )
        else:
            st.session_state.decision = agent.decide(st.session_state.client, rec)
        st.session_state.decision_latency = round(time.time() - _t0, 2)


# ============================================================
# 7) MAIN LAYOUT
# ============================================================
# Branch on the active domain. The DECIDE stage (decision log) is shared; only the
# record source, DETECT card, DELIVER card, and decide() bindings differ.
is_call = st.session_state.mode == MODE_CALL

if is_call:
    # Live-mic source builds a record on the fly; canned source uses the sidebar pick.
    is_live = st.session_state.get("call_source", SOURCE_CANNED) == SOURCE_LIVE
    if is_live:
        rec = _capture_live_call()
        if rec is None:
            st.stop()  # waiting for a recording + transcript
    else:
        if st.session_state.selected is None:
            st.info("👈 Pick a call from the sidebar — or switch Call source to 🎙️ Live mic.")
            st.stop()
        rec = agent.CALLS[st.session_state.selected]
    _render_detect_call(rec)

    # HERO reveal. Canned calls wait for a "▶ Play call" click (a scripted, on-cue
    # demo moment). The live-mic path AUTO-RUNS the instant the recording stops —
    # the browser only hands us the audio on stop, so this is the honest "the call
    # ends, the copilot already has the answer" moment, no separate click. Both paths
    # then share the same replay + one-real-decision code below.
    if not st.session_state.call_played:
        if not is_live:
            st.caption("▶ Press play — the copilot analyzes the call as the caller speaks.")
            if not st.button("▶ Play call", type="primary", use_container_width=True):
                st.stop()  # canned: wait for the on-cue click
        _play_call(rec)                   # progressive transcript + signal dashboard
        _run_decision(rec, is_call=True)  # the ONE real Gemini call (free-tier model)
        st.session_state.call_played = True
        st.session_state.log_done = False            # decision log reveals post-rerun
        st.session_state.deliver_status = "pending"  # awaiting the agent's verify
        st.rerun()
    # Settled: full dashboard (shows the DECIDED severity + real time-to-triage).
    _render_signal_dashboard(rec)
    # Cross-incident intelligence — the systemic pattern recognized BEFORE the decision
    # log, so the narrative reads: signals -> pattern -> agent decides -> dispatch.
    _render_incident_intelligence(rec, st.session_state.cluster)
else:
    if st.session_state.selected is None:
        st.info("👈 Pick a customer from the sidebar to detect their bill shock.")
        st.stop()
    rec = agent.CUSTOMERS[st.session_state.selected]
    _render_detect(rec)

    # Bill Shock (scalability retarget) keeps the one-click Run Agent trigger.
    if st.button("⚡ Run Agent", type="primary", use_container_width=True):
        _run_decision(rec, is_call=False)
        st.session_state.log_done = False            # replay the reveal for this fresh decision
        st.session_state.deliver_status = "pending"  # new decision → awaiting the human decision
        st.rerun()

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
        # Show the ACTUAL prompt sent — including injected cross-incident context when a
        # cluster fired and injection is on, so judges see the intelligence reach the model.
        _clu = st.session_state.cluster
        if CLUSTER_PROMPT_INJECTION and _clu and _clu.get("clustered"):
            _sys_i, _user_c = agent.build_call_prompt(rec, cluster=_clu)
        else:
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
