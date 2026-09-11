"""
WattNext — Live Call Triage (PROTOTYPE)

A standalone prototype of the live-voice + danger-signal dashboard, kept separate
from app.py so the stable demo is never at risk. Flow:

  1) CAPTURE   record the caller with the mic (st.audio_input) — or pick a canned call
  2) HEAR      Gemini transcribes the audio to text  (agent.transcribe_call)
  3) SEE       live danger-signal dashboard: highlighted keywords + severity + counts
  4) DECIDE    the SAME agent.decide() triages the transcript -> route + dispatch packet

Only the Gemini calls (transcribe + decide) are real; everything else is mocked.
Run:  venv\\Scripts\\python.exe -m streamlit run live_demo.py
"""
import html
import re
import time

import streamlit as st

import agent

# ------------------------------------------------------------------
# Setup
# ------------------------------------------------------------------
st.set_page_config(page_title="WattNext — Live Triage", page_icon="🎙️", layout="centered")
# Global polish (mirrors app.py). Streamlit has no CSS layer to edit, so inject once:
# tighter top gap, higher caption contrast on the Ink surface, and inputs that read as
# intentional controls.
st.markdown(
    """<style>
  .block-container { padding-top: 2.5rem; }
  [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p { color:#A8B5C6 !important; }
  .stTextInput input,
  .stSelectbox div[data-baseweb="select"] > div {
    border: 1px solid #334155 !important;
  }
  h2, h3 { margin-top: 0.6rem !important; }
  [data-testid="stHeaderActionElements"] { display: none !important; }
</style>""",
    unsafe_allow_html=True,
)
st.title("🎙️ WattNext — Live Call Triage")
st.caption(
    "Prototype: speak the call, **Gemini hears it**, and the danger-signal dashboard "
    "reacts live before the same agent triages it. No voice biometrics — every signal is "
    "a word that was actually said."
)
# Trust signal as a visible chip, not buried in the dispatch packet.
st.markdown(
    """<div style="display:inline-block;margin:0.15rem 0 0.25rem;padding:0.3rem 0.7rem;
border-radius:999px;background:#1E293B;border:1px solid #334155;
color:#22D3EE;font-size:0.85rem;font-weight:600;">
  🔒 Human-in-the-loop · never auto-dispatched
</div>""",
    unsafe_allow_html=True,
)

ROUTE_STYLE = {
    "DISPATCH_NOW":   {"bg": "#B71C1C", "icon": "🚑", "label": "Dispatch Emergency Responder"},
    "SCHEDULE_TECH":  {"bg": "#0D47A1", "icon": "🔧", "label": "Schedule Technician (Non-Emergency)"},
    "ESCALATE_HUMAN": {"bg": "#5D4037", "icon": "🧑‍✈️", "label": "Escalate to Human Dispatcher"},
}
SEV_COLOR = {"CRITICAL": "#B71C1C", "HIGH": "#E65100", "LOW": "#0D47A1", "NEEDS_REVIEW": "#5D4037"}

# Account vulnerability flags for the live-capture dropdown (mirrors app.py). "None" is the
# empty sentinel (mapped to "" at the call site) so downstream truthiness stays unchanged.
VULN_OPTIONS = ["None", "Medical / life-support", "Elderly / mobility", "Disability"]


# ------------------------------------------------------------------
# Key + client
# ------------------------------------------------------------------
def _resolve_api_key():
    try:
        key = st.secrets.get("GEMINI_API_KEY")
    except Exception:
        key = None
    if not key:
        key = agent._load_api_key()
    return key if key and key != "PASTE_YOUR_GEMINI_API_KEY_HERE" else None


_key = _resolve_api_key()
if not _key:
    st.error("Missing **GEMINI_API_KEY** — add it to `.streamlit/secrets.toml`.")
    st.stop()
if "client" not in st.session_state:
    st.session_state.client = agent.build_client(_key)

for k, v in [("live_transcript", ""), ("live_audio_sig", None), ("live_decision", None), ("live_latency", None)]:
    st.session_state.setdefault(k, v)


# ------------------------------------------------------------------
# Danger-signal helpers
# ------------------------------------------------------------------
# Signal-tier colors — red = active danger, gold = named-but-unconfirmed hazard, orange = advisory.
_TIER_COLOR = {"danger": "#B71C1C", "ambiguous": "#CA8A04", "odor": "#E65100"}


def _highlight(transcript: str, danger: list, odor: list, ambiguous: list = ()) -> str:
    """Wrap detected (non-negated) keywords in colored spans; escape everything else."""
    spans = (
        [(k, "danger") for k in danger]
        + [(k, "ambiguous") for k in ambiguous]
        + [(k, "odor") for k in odor]
    )
    if not spans:
        return html.escape(transcript)
    spans.sort(key=lambda kv: len(kv[0]), reverse=True)  # longest first: "strong smell" before "smell"
    kind_of = {k.lower(): kind for k, kind in spans}
    pattern = re.compile("|".join(re.escape(k) for k, _ in spans), re.IGNORECASE)
    out, last = [], 0
    for m in pattern.finditer(transcript):
        out.append(html.escape(transcript[last:m.start()]))
        bg = _TIER_COLOR.get(kind_of.get(m.group(0).lower()), "#E65100")
        out.append(
            f'<span style="background:{bg};color:#fff;padding:0 4px;border-radius:4px;'
            f'font-weight:700;">{html.escape(m.group(0))}</span>'
        )
        last = m.end()
    out.append(html.escape(transcript[last:]))
    return "".join(out)


def _preview_severity(danger: list, odor: list, vulnerable: bool, ambiguous: list = ()) -> str:
    """Signal-only severity preview — mirrors decide()'s deterministic tiering."""
    if danger and vulnerable:
        return "CRITICAL"
    if danger:
        return "HIGH"
    if ambiguous:  # named hazard, no confirming detail -> human review, never a guess
        return "NEEDS_REVIEW"
    if odor:
        return "LOW"
    return "NEEDS_REVIEW"


def _chips(items: list, bg: str) -> str:
    if not items:
        return '<span style="opacity:0.6;">none detected</span>'
    return " ".join(
        f'<span style="display:inline-block;background:{bg};color:#fff;padding:2px 8px;'
        f'border-radius:10px;font-size:0.8rem;font-weight:600;margin:2px;">{html.escape(c)}</span>'
        for c in items
    )


# ------------------------------------------------------------------
# 1) CAPTURE — mic or canned
# ------------------------------------------------------------------
st.markdown("### 1 · Capture the call")
source = st.radio("Call source", ["🎙️ Live mic", "📼 Canned call"], horizontal=True)

transcript = ""
call_record = None

if source == "🎙️ Live mic":
    st.caption("Tap to record the caller, then stop. Gemini transcribes what it heard.")
    audio = st.audio_input("Record the caller", help="Mic needs localhost or HTTPS.")
    c1, c2 = st.columns(2)
    address = c1.text_input("Address (from caller ID / account)", value="418 Maple Street, Apt 2B")
    # A flag is a fixed set, not free text — a dropdown improves data quality. "None" maps to
    # "" so the downstream truthiness (bool(vuln) / vuln or None) is unchanged.
    vuln_choice = c2.selectbox("Account vulnerability flag (optional)", VULN_OPTIONS)
    vuln = "" if vuln_choice == "None" else vuln_choice
    if audio is not None:
        data = audio.getvalue()
        sig = hash(data)
        if sig != st.session_state.live_audio_sig:  # only transcribe a fresh recording
            with st.spinner("Gemini is transcribing the call…"):
                st.session_state.live_transcript = agent.transcribe_call(st.session_state.client, data)
                st.session_state.live_audio_sig = sig
                st.session_state.live_decision = None  # new call -> clear old triage
        transcript = st.session_state.live_transcript
        if not transcript:
            st.warning("Transcription failed (audio/network). Try again, or use a canned call.")
    if transcript:
        call_record = {
            "caller_name": "Live caller",
            "address": address,
            "transcript": transcript,
            "medical_dependent": bool(vuln),
            "account_vulnerability_flag": vuln or None,
        }
else:
    names = [c["caller_name"] for c in agent.CALLS]
    pick = st.selectbox("Pick a canned call", names)
    call_record = next(c for c in agent.CALLS if c["caller_name"] == pick)
    transcript = call_record["transcript"]
    st.session_state.live_decision = None if st.session_state.get("_picked") != pick else st.session_state.live_decision
    st.session_state["_picked"] = pick


# ------------------------------------------------------------------
# 2) SEE — live danger-signal dashboard
# ------------------------------------------------------------------
if transcript:
    signals = agent.find_signals(transcript)
    danger, odor = signals["danger"], signals["low_signal"]
    ambiguous = signals.get("ambiguous", [])
    vulnerable = bool(call_record.get("account_vulnerability_flag")) or bool(call_record.get("medical_dependent"))
    sev = _preview_severity(danger, odor, vulnerable, ambiguous)

    st.markdown("### 2 · Danger-signal dashboard")
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Active-danger signals", len(danger))
    m2.metric("Ambiguous hazard", len(ambiguous))
    m3.metric("Advisory signals", len(odor))
    m4.metric("Vulnerable occupant", "Yes" if vulnerable else "No")
    lat = st.session_state.live_latency
    m5.metric("Time-to-triage", f"{lat:.2f}s" if lat else "—")

    st.markdown(
        f"""<div style="display:inline-block;padding:0.35rem 0.8rem;border-radius:0.5rem;
background:{SEV_COLOR.get(sev)};color:#fff;font-weight:800;margin:0.2rem 0 0.6rem;">
SIGNAL SEVERITY (preview): {sev}</div>""",
        unsafe_allow_html=True,
    )

    st.markdown("**Transcript — active-danger in red, ambiguous hazard in gold, advisory in orange**")
    st.markdown(
        f"""<div style="padding:0.8rem 1rem;border-radius:0.5rem;border-left:4px solid #B71C1C;
background:rgba(255,255,255,0.05);line-height:1.7;">{_highlight(transcript, danger, odor, ambiguous)}</div>""",
        unsafe_allow_html=True,
    )
    st.markdown(f"**Active-danger:** {_chips(danger, '#B71C1C')}", unsafe_allow_html=True)
    st.markdown(f"**Ambiguous hazard:** {_chips(ambiguous, '#CA8A04')}", unsafe_allow_html=True)
    st.markdown(f"**Advisory:** {_chips(odor, '#E65100')}", unsafe_allow_html=True)
    if ambiguous and not danger:
        st.caption(
            "A hazard is named but unconfirmed — no active-danger signal to dispatch on, "
            "yet too risky to downgrade. The agent escalates to a human rather than guess."
        )

    # --------------------------------------------------------------
    # 3) DECIDE — same agent.decide()
    # --------------------------------------------------------------
    st.markdown("### 3 · Triage")
    if st.button("⚡ Run triage", type="primary", use_container_width=True):
        with st.spinner(f"Reasoning… (real Gemini call · {agent.PRIMARY_MODEL})"):
            t0 = time.time()
            st.session_state.live_decision = agent.decide(
                st.session_state.client, call_record,
                build_prompt_fn=agent.build_call_prompt,
                deterministic_fn=agent._deterministic_call_decision,
                valid_routes=agent.CALL_ROUTES,
            )
            st.session_state.live_latency = round(time.time() - t0, 2)
        st.rerun()

    decision = st.session_state.live_decision
    if decision:
        style = ROUTE_STYLE.get(decision["route"], ROUTE_STYLE["ESCALATE_HUMAN"])
        packet = (decision.get("action_params", {}) or {}).get("dispatch_packet", {}) or {}
        badge = "⚡ LIVE GEMINI" if decision.get("source") == "live" else "🛟 FALLBACK (rules-based)"
        st.markdown(
            f"""<div style="padding:0.9rem 1.1rem;border-radius:0.6rem;background:{style['bg']};color:#fff;">
  <div style="font-size:0.85rem;opacity:0.85;">{badge} · model {decision.get('model_used')}</div>
  <div style="font-size:1.1rem;font-weight:800;margin-top:0.2rem;">{style['icon']} {style['label']}</div>
  <div style="margin-top:0.3rem;opacity:0.95;">{decision.get('rationale','')}</div>
  <div style="margin-top:0.5rem;"><b>Severity:</b> {packet.get('severity_tier','—')}
     &nbsp;·&nbsp; <b>Address:</b> {packet.get('address','—')}</div>
  <div style="margin-top:0.2rem;"><b>Vulnerability:</b> {packet.get('vulnerability_flags','none')}</div>
  <div style="margin-top:0.2rem;"><b>Responder brief:</b> {packet.get('responder_summary','—')}</div>
  <div style="margin-top:0.55rem;font-weight:800;">🧾 Prepared for a human dispatcher — never auto-dispatched.</div>
</div>""",
            unsafe_allow_html=True,
        )
        st.caption("Reasoning steps: " + " → ".join(decision.get("reasoning_steps", [])))
else:
    st.markdown(
        """<div style="padding:0.85rem 1.1rem;border-radius:0.6rem;background:#1E293B;
border-left:4px solid #22D3EE;color:#E2E8F0;font-weight:600;">
  ↑ Record a call or pick a canned one to see the danger-signal dashboard.
</div>""",
        unsafe_allow_html=True,
    )
