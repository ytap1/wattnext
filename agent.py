"""
WattNext — "The Kill Bill Shock" Agent
DECIDE core: the ONE real agentic call (Google Gemini).

Given a customer's bill-shock context, the agent chooses exactly one resolution route,
explaining its reasoning step by step. This module is pure logic (no Streamlit import) so it
can run and be tested headless; app.py wires it into the DETECT -> DECIDE -> DELIVER UI.

Everything else in WattNext is mocked; this call is the only real AI decision.
"""

import json
import os
import pathlib
import re
import tomllib

from google import genai
from google.genai import types

# ------------------------------------------------------------------
# Config — model IDs verified live against ai.google.dev on 2026-08-23
# ------------------------------------------------------------------
PRIMARY_MODEL = "gemini-3.5-flash-lite"   # newest flash-lite; fastest free option (~1.2s), routes verified 2026-08-23
FALLBACK_MODEL = "gemini-3.7-flash"       # newest full flash — independent serving path + quality safety net

# Resolution routes the agent must choose from — constrained enum so routes can't drift.
ROUTES = {"ASSISTANCE_ENROLLMENT", "BUDGET_BILLING", "REVIEW"}


def build_client(api_key: str) -> genai.Client:
    """Create a Gemini client. Caller supplies the key (from st.secrets or env)."""
    return genai.Client(api_key=api_key)


def build_prompt(customer: dict) -> tuple[str, str]:
    """Return (system_instruction, user_content) for the DECIDE call."""
    system_instruction = (
        "You are WattNext's resolution agent for utility bill shock. "
        "Given a customer's bill-shock context, choose EXACTLY ONE route from this set: "
        f"{sorted(ROUTES)}. "
        "ASSISTANCE_ENROLLMENT = enroll in a hardship/medical-baseline assistance program "
        "(for financially vulnerable customers, especially with medical/life-support equipment). "
        "BUDGET_BILLING = level-pay plan that evens out seasonal swings (for customers who can pay "
        "but were surprised by a seasonal spike, with no hardship). "
        "REVIEW = escalate for human review when neither clearly fits. "
        "Explain your reasoning step by step as short lines a customer-service agent could read aloud. "
        "Return ONLY a JSON object, no prose, no code fences, matching this schema: "
        '{"route": "<one of the routes>", '
        '"reasoning_steps": ["step 1", "step 2", ...], '
        '"rationale": "one-sentence summary of the decision", '
        '"action_params": {"program_or_plan": "...", "note": "..."}}'
    )
    user_content = (
        "Customer bill-shock context:\n"
        f"- Name: {customer.get('name')}\n"
        f"- Income band: {customer.get('income_band')}\n"
        f"- Has medical/life-support equipment: {customer.get('medical_equipment')}\n"
        f"- Declared hardship: {customer.get('hardship')}\n"
        f"- Baseline monthly bill (USD): {customer.get('baseline_usd')}\n"
        f"- Current monthly bill (USD): {customer.get('current_usd')}\n"
        f"- Spike vs baseline: {customer.get('spike_pct')}%\n"
        f"- Likely spike cause: {customer.get('spike_cause')}\n"
    )
    return system_instruction, user_content


def _strip_code_fences(text: str) -> str:
    """Remove ```json ... ``` fences a model may wrap JSON in."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1] if "\n" in t else t
        t = t.rsplit("```", 1)[0] if "```" in t else t
    return t.strip()


def _parse_decision(text: str, valid_routes: set) -> dict | None:
    """Parse the model's JSON; return None if invalid or route not in valid_routes.

    valid_routes is passed in (not hardcoded) so the same parser serves every
    domain's route enum — bill-shock ROUTES, first-response CALL_ROUTES, etc.
    """
    try:
        obj = json.loads(_strip_code_fences(text))
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(obj, dict) or obj.get("route") not in valid_routes:
        return None
    obj.setdefault("reasoning_steps", [])
    obj.setdefault("rationale", "")
    obj.setdefault("action_params", {})
    return obj


def _deterministic_decision(customer: dict) -> dict:
    """Rule-based fallback so the stage demo always completes if the live call/parse fails."""
    if customer.get("medical_equipment") and customer.get("income_band") == "low":
        return {
            "route": "ASSISTANCE_ENROLLMENT",
            "reasoning_steps": [
                f"Bill jumped {customer.get('spike_pct')}% — a real shock for this household.",
                "Customer is low-income and relies on medical/life-support equipment.",
                "Cutting usage is not a safe option; this is a hardship case.",
                "Best route: enroll in a medical-baseline assistance program.",
            ],
            "rationale": "Low-income, medical-equipment household with a large spike qualifies for assistance.",
            "action_params": {
                "program_or_plan": "Medical Baseline Assistance Program",
                "note": "Deterministic fallback decision.",
            },
        }
    return {
        "route": "BUDGET_BILLING",
        "reasoning_steps": [
            f"Bill rose {customer.get('spike_pct')}%, driven by a seasonal cause.",
            "Customer has capacity to pay and declared no hardship.",
            "Smoothing the seasonal swing solves the shock without assistance.",
            "Best route: enroll in a budget (level-pay) billing plan.",
        ],
        "rationale": "Seasonal spike with no hardship is best solved by level-pay budget billing.",
        "action_params": {
            "program_or_plan": "Budget Billing (level-pay) plan",
            "note": "Deterministic fallback decision.",
        },
    }


def decide(
    client: genai.Client,
    customer: dict,
    build_prompt_fn=build_prompt,
    deterministic_fn=_deterministic_decision,
    valid_routes: set = ROUTES,
) -> dict:
    """
    The ONE agentic call. Domain-agnostic: the domain supplies its prompt builder,
    deterministic fallback, and valid-route set; the primary->fallback model switch
    and JSON-parse-with-fallback logic below are identical for every domain.

    Defaults reproduce the original bill-shock behaviour, so decide(client, customer)
    keeps working unchanged. Returns:
      {route, reasoning_steps, rationale, action_params, model_used, source}
    source is "live" (from Gemini) or "fallback" (deterministic rule-based).
    reasoning_steps is what the live decision-log panel renders line by line.
    """
    system_instruction, user_content = build_prompt_fn(customer)
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=0.0,
        response_mime_type="application/json",
        # Per-request timeout (milliseconds): a slow/hung call on conference wifi
        # raises, is caught below, and falls through to the next model then the
        # deterministic path — instead of hanging the live demo. 10000ms is the
        # API's minimum allowed deadline (it rejects <10s with 400 INVALID_ARGUMENT);
        # arg verified live against google-genai 2.19.0 (HttpOptions.timeout, ms).
        http_options=types.HttpOptions(timeout=10000),
    )

    # Primary -> fallback model switch on API exception.
    for model in (PRIMARY_MODEL, FALLBACK_MODEL):
        try:
            response = client.models.generate_content(
                model=model, contents=user_content, config=config
            )
        except Exception:
            continue  # try the fallback model
        parsed = _parse_decision(getattr(response, "text", "") or "", valid_routes)
        if parsed is not None:
            parsed["model_used"] = model
            parsed["source"] = "live"
            return parsed
        # Live call succeeded but output was unparseable/invalid — try next model once.

    # Both models failed (or produced invalid output): deterministic fallback.
    decision = deterministic_fn(customer)
    decision["model_used"] = "none"
    decision["source"] = "fallback"
    return decision


# ==================================================================
# SECOND DOMAIN — Gas-leak first-response call triage.
# Reuses the DETECT -> DECIDE -> DELIVER engine above (same decide(),
# same _parse_decision) with its own routes, prompt, and fallback.
# Output is handed to a HUMAN dispatcher — never auto-dispatched.
# ==================================================================

# First-response routes — a SEPARATE enum; bill-shock ROUTES is untouched.
CALL_ROUTES = {"DISPATCH_NOW", "SCHEDULE_TECH", "ESCALATE_HUMAN"}

# Fallback keyword signals (matched against the lowercased transcript).
# The taxonomy is hazard-AGNOSTIC on purpose: WattNext triages any utility
# emergency, not only gas. Active-danger => a hazard is likely live now.
ACTIVE_DANGER_KEYWORDS = frozenset({
    # Gas
    "hiss", "hissing", "rotten egg", "strong smell", "strong odor", "strong odour",
    "gas everywhere", "filling with gas", "confirmed leak",
    # Electrical
    "spark", "sparks", "sparking", "arcing", "electric shock", "electrocut",
    "exposed wire", "bare wire", "live wire", "downed line", "downed power line",
    "power line down", "downed wire",
    # Fire / thermal (common to gas and electrical)
    "smoke", "fire", "flame", "burning", "burning smell", "melting", "scorch", "sizzl",
    # Physical symptoms (hazard-agnostic)
    "dizzy", "dizziness", "nausea", "nauseous", "headache", "can't breathe",
    "cant breathe", "trouble breathing", "short of breath", "passed out",
    "collaps", "unconscious", "lightheaded", "light-headed",
    # Escalators
    "evacuat", "explos", "trapped", "loud",
})
# Low-signal => an advisory complaint with no active-danger indicators: schedule a tech.
LOW_SIGNAL_KEYWORDS = frozenset({
    # Gas
    "smell", "odor", "odour", "faint", "whiff", "gassy", "sulphur", "sulfur",
    # Electrical
    "flicker", "flickering", "buzzing", "warm outlet", "warm plug", "tripping",
    "keeps tripping", "intermittent", "dimming", "crackle", "crackling",
    # General
    "slight", "occasional",
})
# Ambiguous-hazard => a hazard is NAMED (a leak, gas, a hazard) but with NO active-danger
# indicator to confirm it and NO way to safely downgrade it to a scheduled visit. The honest
# outcome is human escalation, not a guess in either direction. This tier exists so the
# danger-signal dashboard shows WHY an under-specified hazard call escalates, instead of
# reading as "detector found nothing" on a literal "gas leak".
AMBIGUOUS_HAZARD_KEYWORDS = frozenset({
    "gas leak", "leak", "leaking", "smell of gas", "smells like gas", "smell gas",
    "gas smell", "possible leak", "might be a leak", "think there's a leak",
})


def build_call_prompt(call: dict, cluster: dict | None = None) -> tuple[str, str]:
    """Return (system_instruction, user_content) for a first-response DECIDE call.

    Same JSON schema as build_prompt so _parse_decision handles both; only the
    domain, route set, and the safety bias differ.

    cluster is an OPTIONAL cross-incident context dict from detect_cluster(). When
    present and clustered, a short platform-detected summary is appended to the
    prompt so the ONE real decision can reference the systemic pattern. This is
    purely additive — cluster=None reproduces the original prompt byte-for-byte,
    it adds no model call, and it only extends the input (never the output schema),
    so _parse_decision is unaffected.
    """
    system_instruction = (
        "You are WattNext's first-response triage agent for a utility contact centre. "
        "You read a raw inbound call transcript about a possible utility hazard — a gas "
        "leak, an electrical hazard (sparks, exposed or downed wires), smoke or burning, "
        "or similar — and recommend ONE routing decision for a HUMAN dispatcher. You never "
        "dispatch anyone yourself. Choose EXACTLY ONE route from this set: "
        f"{sorted(CALL_ROUTES)}. "
        "DISPATCH_NOW = the transcript strongly indicates an active/confirmed hazard "
        "(e.g. gas smell PLUS hissing, sparks or exposed/downed wires, smoke or burning, "
        "evacuation in progress, or physical symptoms like dizziness/nausea/trouble "
        "breathing). Send an emergency responder. "
        "SCHEDULE_TECH = a low-signal advisory complaint with NO active-danger indicators "
        "(e.g. a faint odor, a flickering light, an occasional buzz). "
        "Book a non-emergency technician visit. "
        "ESCALATE_HUMAN = signals are ambiguous, conflicting, or a safety-critical "
        "detail is missing. Route to a human dispatcher to decide. "
        "SAFETY RULE: this is a life-safety call. When the transcript is ambiguous or a "
        "safety-critical detail is missing, choose ESCALATE_HUMAN — bias toward human "
        "review. Never guess DISPATCH_NOW or SCHEDULE_TECH on incomplete information. "
        "Explain your reasoning step by step as short lines a dispatcher could read aloud. "
        "Return ONLY a JSON object, no prose, no code fences, matching this schema: "
        '{"route": "<one of the routes>", '
        '"reasoning_steps": ["step 1", "step 2", ...], '
        '"rationale": "one-sentence summary of the decision", '
        '"action_params": {"dispatch_packet": {'
        '"severity_tier": "<CRITICAL|HIGH|LOW|NEEDS_REVIEW>", '
        '"address": "<caller address>", '
        '"vulnerability_flags": "<vulnerability notes or none>", '
        '"responder_summary": "<one-line brief for the responder>"}}}'
    )
    vuln = call.get("account_vulnerability_flag") or "none on file"
    user_content = (
        "Inbound utility-hazard call:\n"
        f"- Caller: {call.get('caller_name')}\n"
        f"- Address: {call.get('address')}\n"
        f"- Medical-dependent household (from customer record): {call.get('medical_dependent')}\n"
        f"- Account vulnerability flag: {vuln}\n"
        "- Raw call transcript:\n"
        f"\"\"\"\n{call.get('transcript')}\n\"\"\"\n"
    )
    if cluster and cluster.get("clustered"):
        user_content += (
            "\nCROSS-INCIDENT CONTEXT (platform-detected across recent calls, "
            "deterministic — NOT stated in this call's transcript):\n"
            f"- {cluster.get('summary', '')}\n"
        )
        system_instruction += (
            " If a CROSS-INCIDENT CONTEXT section is present indicating a probable "
            "systemic event, you MAY reference it in your reasoning steps; it does NOT "
            "change the route enum or the required JSON schema."
        )
    return system_instruction, user_content


_NEGATOR_RE = re.compile(r"\b(no|not|n't|without|never)\s*$")


def _mentions(transcript: str, keywords) -> bool:
    """True if the transcript contains any keyword NOT under a nearby negator.

    Substring matching alone misfires on 'No hissing' / 'not dizzy' — so an
    occurrence immediately preceded (within ~8 chars) by no/not/n't/without/never
    is treated as negated and skipped. Keeps the fallback honest without a parser.
    """
    for kw in keywords:
        for m in re.finditer(re.escape(kw), transcript):
            prefix = transcript[max(0, m.start() - 8):m.start()]
            if _NEGATOR_RE.search(prefix):
                continue
            return True
    return False


def _deterministic_call_decision(call: dict) -> dict:
    """Rule-based fallback for first-response, so the demo always completes.

    Rules (per spec):
      vulnerable AND active-danger keyword -> DISPATCH_NOW (CRITICAL)
      active-danger keyword                -> DISPATCH_NOW (HIGH)
      odor-only language                   -> SCHEDULE_TECH (LOW)
      otherwise                            -> ESCALATE_HUMAN (NEEDS_REVIEW)
    """
    transcript = (call.get("transcript") or "").lower()
    vuln_flag = call.get("account_vulnerability_flag")
    vulnerable = bool(call.get("medical_dependent")) or bool(vuln_flag)
    has_danger = _mentions(transcript, ACTIVE_DANGER_KEYWORDS)
    has_ambiguous = _mentions(transcript, AMBIGUOUS_HAZARD_KEYWORDS)
    has_low_signal = _mentions(transcript, LOW_SIGNAL_KEYWORDS)

    vuln_flags = vuln_flag if vuln_flag else ("medical-dependent household" if call.get("medical_dependent") else "none")

    if has_danger and vulnerable:
        route, severity = "DISPATCH_NOW", "CRITICAL"
        steps = [
            "Transcript contains active-danger language (leak likely live).",
            "Household is medical-dependent or flagged vulnerable — highest priority.",
            "Life-safety risk; do not wait for a technician window.",
            "Best route: dispatch an emergency responder now.",
        ]
        rationale = "Active-danger signal in a vulnerable household — dispatch an emergency responder immediately."
        summary = "Suspected active hazard; vulnerable occupant — emergency response."
    elif has_danger:
        route, severity = "DISPATCH_NOW", "HIGH"
        steps = [
            "Transcript contains active-danger language (leak likely live).",
            "No vulnerability flag, but the active-danger signal governs.",
            "Life-safety risk outweighs a scheduled visit.",
            "Best route: dispatch an emergency responder now.",
        ]
        rationale = "Active-danger signal in the transcript — dispatch an emergency responder."
        summary = "Suspected active hazard — emergency response."
    elif has_ambiguous:
        route, severity = "ESCALATE_HUMAN", "NEEDS_REVIEW"
        steps = [
            "Transcript names a hazard (e.g. a gas leak) but gives no confirming detail.",
            "No active-danger indicator — no hissing, symptoms, or confirmed leak — yet the hazard can't be ruled out.",
            "Too ambiguous to auto-dispatch, too risky to downgrade to a scheduled visit.",
            "Best route: escalate to a human dispatcher to decide.",
        ]
        rationale = "A hazard is named but under-specified — escalate to a human dispatcher rather than guess."
        summary = "Named hazard with no confirming detail — needs a human dispatcher to decide."
    elif has_low_signal:
        route, severity = "SCHEDULE_TECH", "LOW"
        steps = [
            "Transcript reports a low-signal advisory but no active-danger indicators.",
            "No evacuation, active-hazard language, or physical symptoms mentioned.",
            "Low-signal complaint suited to a non-emergency visit.",
            "Best route: schedule a technician.",
        ]
        rationale = "Low-signal advisory complaint with no active-danger indicators — schedule a technician."
        summary = "Low-signal utility complaint, no active-danger indicators — non-emergency technician visit."
    else:
        route, severity = "ESCALATE_HUMAN", "NEEDS_REVIEW"
        steps = [
            "Transcript signals are ambiguous or a safety-critical detail is missing.",
            "Cannot safely confirm or rule out an active leak from this text.",
            "Life-safety call — do not guess.",
            "Best route: escalate to a human dispatcher to decide.",
        ]
        rationale = "Ambiguous or incomplete signals on a life-safety call — escalate to a human dispatcher."
        summary = "Ambiguous gas-odor call — needs a human dispatcher to decide."

    return {
        "route": route,
        "reasoning_steps": steps,
        "rationale": rationale,
        "action_params": {
            "dispatch_packet": {
                "severity_tier": severity,
                "address": call.get("address"),
                "vulnerability_flags": vuln_flags,
                "responder_summary": summary,
            },
        },
    }


# Public alias — the two demo calls, consumed by app.py's First Response DETECT panel.
# Routes MUST differ: Call A -> DISPATCH_NOW, Call B -> SCHEDULE_TECH.
CALLS = [
    {
        "caller_name": "Rosa Delgado",
        "address": "418 Maple Street, Apt 2B",
        "transcript": (
            "Caller: There's a really strong smell of gas in my kitchen and I can hear "
            "a hissing sound near the stove. I'm feeling dizzy so I stepped out onto the "
            "porch. My husband is on oxygen and still inside — please hurry."
        ),
        "medical_dependent": True,
        "account_vulnerability_flag": "elderly, oxygen-dependent",
    },
    {
        "caller_name": "Trevor Nash",
        "address": "77 Birchwood Lane",
        "transcript": (
            "Caller: I think I catch a faint odor near the water heater every now and "
            "then. It's very slight, nothing right now. No hissing, everyone's fine — I "
            "just wanted someone to take a look when it's convenient."
        ),
        "medical_dependent": False,
        "account_vulnerability_flag": None,
    },
    {
        # Electrical hazard — proves the engine is not gas-only. Routes DISPATCH_NOW.
        "caller_name": "Marcus Bell",
        "address": "92 Cedar Avenue",
        "transcript": (
            "Caller: There's a downed power line across my driveway after the storm — "
            "it's sparking and arcing on the wet ground and there's a burning smell. My "
            "kids are inside and I've kept everyone away from it. Please send someone."
        ),
        "medical_dependent": False,
        "account_vulnerability_flag": None,
    },
]


# Fallback transcript for the bundled demo video (assets/demo-call.mp4), captured from a
# live Gemini transcription of that file. The Demo-video path transcribes the file LIVE on
# stage; if the live call fails (wifi), the UI falls back to this so the beat still completes.
DEMO_VIDEO_TRANSCRIPT = (
    "Agent: Thank you for calling, my name is Faye — are you experiencing a gas emergency? "
    "Caller: Yeah, I'm a passer-by and I want to report a strong odor of gas. It's like rotten eggs. "
    "Agent: Aside from smelling the gas, can you also see, feel, or hear it? "
    "Caller: No, just a smell. "
    "Agent: Okay, may I have the full address, please? Please stay at least 100 feet from the gas "
    "odor. Do not operate any gas or electrical devices that can cause a spark — no open fires, flames, "
    "smoking, or use of the telephone within the area. Let me call gas dispatch to confirm the ticket, "
    "stay on the line, please."
)


def transcribe_call(client: genai.Client, audio_bytes: bytes, mime_type: str = "audio/wav",
                    timeout_ms: int = 10000) -> str:
    """Transcribe a recorded call with Gemini (multimodal audio/video -> text).

    A SUPPORTING call, separate from decide(): the mic (or a demo video) gives us media,
    this turns it into the transcript that decide() then triages. Same primary->fallback
    model resilience; returns "" on failure so the caller can fall back to a canned/typed
    transcript instead of hanging the demo.

    timeout_ms is the per-request deadline (API minimum 10000). A short mic clip is fine at
    the default; a video file is larger to upload + process, so the Demo-video path passes a
    larger value (~45s) to give the LIVE transcription margin before it falls back on stage.
    """
    prompt = (
        "Transcribe this emergency utility phone call verbatim. "
        "Return ONLY the spoken words as plain text — no speaker labels, no commentary, no timestamps."
    )
    audio_part = types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)
    config = types.GenerateContentConfig(
        temperature=0.0,
        http_options=types.HttpOptions(timeout=max(timeout_ms, 10000)),
    )
    for model in (PRIMARY_MODEL, FALLBACK_MODEL):
        try:
            response = client.models.generate_content(
                model=model, contents=[audio_part, prompt], config=config
            )
        except Exception:
            continue
        text = (getattr(response, "text", "") or "").strip()
        if text:
            return text
    return ""


def find_signals(transcript: str) -> dict:
    """Return the danger / low-signal / ambiguous-hazard keywords present (negation-aware).

    Powers the live danger-signal dashboard: which words made the agent escalate, and how
    many. Three tiers, mirroring decide()'s deterministic precedence:
      - danger     : an active-hazard indicator (governs the routing decision)
      - low_signal : an advisory complaint with no active-danger indicator
      - ambiguous  : a hazard is named but unconfirmed — only surfaced when NO active
                     danger is present, since danger short-circuits the routing anyway
    Hazard-agnostic (gas, electrical, fire, symptoms). Uses the same _mentions() logic
    decide()'s fallback uses, so on-screen signals match the routing rationale — nothing
    negated (e.g. "no hissing") is counted or shown.
    """
    t = (transcript or "").lower()
    danger = sorted({k for k in ACTIVE_DANGER_KEYWORDS if _mentions(t, [k])})
    low_signal = sorted({k for k in LOW_SIGNAL_KEYWORDS if _mentions(t, [k])})
    # Ambiguous cues are decision-relevant only when there's no active danger (danger is
    # matched first and governs). Suppressing them under danger also stops the dashboard
    # from showing an "ambiguous" chip with no matching transcript highlight on a clear
    # active-danger call (e.g. "smell of gas" beside "strong smell").
    ambiguous = sorted({k for k in AMBIGUOUS_HAZARD_KEYWORDS if _mentions(t, [k])}) if not danger else []
    # Drop cues subsumed by a longer matched cue — e.g. bare "leak" inside "gas leak" —
    # so the tier shows only genuinely under-specified hazards, not redundant fragments.
    ambiguous = [k for k in ambiguous if not any(k != o and k in o for o in ambiguous)]
    return {"danger": danger, "low_signal": low_signal, "ambiguous": ambiguous}


# ==================================================================
# CROSS-INCIDENT INTELLIGENCE — emerging-incident cluster detection.
# Pure, deterministic Python (NO model call): correlates the current hazard call
# against other recent reports on the same street/main. When >= CLUSTER_MIN_PRIOR
# prior reports cluster on one main inside the window, WattNext flags a probable
# SYSTEMIC event (a gas-main rupture, not isolated leaks) and surfaces vulnerable
# households on that main for proactive outreach. This is the differentiator no
# transcription tool can produce: no single call reveals it.
# Offline/demo-safe: the panel reads THIS (never model output), so it renders
# identically live or on the deterministic fallback.
# ==================================================================

CLUSTER_WINDOW_MIN = 120          # 2-hour correlation window
CLUSTER_MIN_PRIOR = 2             # >= 2 prior reports on the main (this call = 3rd) tips a cluster
MANUAL_CORRELATION_LAG_MIN = 30   # ASSUMPTION: a supervisor spots the cross-call pattern ~30 min later than the platform
EMERGENCY_TRUCK_ROLL_USD = 1200   # ASSUMPTION: loaded cost of one emergency field dispatch (crew + vehicle + OT)

# Recent utility-hazard reports the contact centre has already logged — mock data,
# inline like CALLS/CUSTOMERS. Each row is one prior call. `street_key` is the
# normalized main, stored explicitly as a HEDGE so a normalize_street() regression
# can't silently kill the cluster on stage (matching falls back to it). `minutes_ago`
# is relative (not wall-clock) so detection is deterministic and offline-reproducible.
INCIDENTS = [
    # Maple Street seeds — Rosa (CALLS[0]) becomes the 3rd report -> cluster fires.
    {"id": "INC-4021", "address": "402 Maple Street", "street_key": "maple st",
     "hazard_type": "gas", "minutes_ago": 47, "status": "unresolved",
     "medical_dependent": False, "vulnerability_flag": None,
     "summary": "Strong gas odor + hissing near the street-side meter."},
    {"id": "INC-4024", "address": "431 Maple Street, Apt 5C", "street_key": "maple st",
     "hazard_type": "gas", "minutes_ago": 22, "status": "crew_enroute",
     "medical_dependent": True, "vulnerability_flag": "elderly, oxygen-dependent",
     "summary": "Gas smell in stairwell; oxygen-dependent resident in unit."},
    # Distractors on OTHER mains — prove NO false cluster for Trevor / Marcus.
    {"id": "INC-3987", "address": "15 Birchwood Lane", "street_key": "birchwood ln",
     "hazard_type": "gas", "minutes_ago": 33, "status": "resolved",
     "medical_dependent": False, "vulnerability_flag": None,
     "summary": "Single faint-odor report; crew found nothing, resolved."},
    {"id": "INC-3921", "address": "88 Cedar Avenue", "street_key": "cedar ave",
     "hazard_type": "electrical", "minutes_ago": 15, "status": "unresolved",
     "medical_dependent": False, "vulnerability_flag": None,
     "summary": "Downed-line report after the storm; isolated to one pole."},
]

# Street-type suffixes canonicalized so spelling variants collide (Street/St -> st).
_STREET_SUFFIXES = {
    "street": "st", "st": "st", "avenue": "ave", "ave": "ave", "av": "ave",
    "lane": "ln", "ln": "ln", "road": "rd", "rd": "rd", "boulevard": "blvd",
    "blvd": "blvd", "drive": "dr", "dr": "dr", "court": "ct", "ct": "ct",
    "place": "pl", "pl": "pl", "way": "way",
}

# A leading house number or hyphenated range: "418", "12B", "1200-1210".
_HOUSE_NUM_RE = re.compile(r"\d+[a-z]?(-\d+[a-z]?)?$")


def normalize_street(address: str) -> str:
    """Reduce a free-text address to a canonical street key.

    "418 Maple Street, Apt 2B" -> "maple st". Drops the unit (everything after the
    first comma), the leading house number/range, and canonicalizes the street-type
    suffix so spelling variants collide. Returns "" for an empty address.
    Known limitation (out of demo scope): directional prefixes like "N Maple" are
    not stripped, so "N Maple St" and "Maple St" would not collide.
    """
    if not address:
        return ""
    head = address.split(",")[0].strip().lower()      # drop ", Apt 2B"
    head = re.sub(r"[^a-z0-9\s]", " ", head)           # punctuation -> space
    tokens = head.split()
    while tokens and _HOUSE_NUM_RE.fullmatch(tokens[0]):
        tokens.pop(0)                                  # drop house number / range
    if tokens and tokens[-1] in _STREET_SUFFIXES:
        tokens[-1] = _STREET_SUFFIXES[tokens[-1]]      # canonicalize suffix
    return " ".join(tokens).strip()


def _street_label(address: str) -> str:
    """Human-readable street name for banners: "418 Maple Street, Apt 2B" ->
    "Maple Street". Drops a leading house number; falls back to the raw head."""
    if not address:
        return "this area"
    head = address.split(",")[0].strip()
    tokens = head.split()
    while tokens and _HOUSE_NUM_RE.fullmatch(tokens[0].lower()):
        tokens.pop(0)
    return " ".join(tokens) if tokens else head


def compute_cluster_value(total_reports: int, vuln_count: int, first_report_min_ago: int) -> dict:
    """Emergency-framing value of catching a systemic event early.

    Deliberately conservative and honest: the safety benefit is shown as
    exposure-minutes and the flagged vulnerable household, NOT dollarized. Only the
    avoidable field-dispatch cost is priced. Assumptions travel with the numbers so
    the pitch can defend every figure under Shark Q&A.
    """
    trucks_without = total_reports          # one emergency roll per uncorrelated report
    trucks_with = 1                         # correlated: one coordinated response to the main
    trucks_saved = max(trucks_without - trucks_with, 0)
    return {
        "detection_lead_min": MANUAL_CORRELATION_LAG_MIN,
        "first_report_min_ago": first_report_min_ago,
        "affected_households": total_reports,
        "vulnerable_household_count": vuln_count,
        "exposure_minutes_avoided": MANUAL_CORRELATION_LAG_MIN * total_reports,
        "trucks_without": trucks_without,
        "trucks_with": trucks_with,
        "trucks_saved": trucks_saved,
        "dollars_saved": trucks_saved * EMERGENCY_TRUCK_ROLL_USD,
        "assumptions": [
            f"Platform correlates the pattern ~{MANUAL_CORRELATION_LAG_MIN} min before a supervisor would spot it manually.",
            f"One emergency field dispatch (crew + vehicle + OT) is approximately ${EMERGENCY_TRUCK_ROLL_USD:,}.",
            "Safety/exposure benefit shown as exposure-minutes and the flagged vulnerable household — deliberately not dollarized.",
        ],
    }


def _cluster_summary(street_label: str, total_reports: int, dominant_hazard: str,
                     first_report_min_ago: int, vuln_count: int) -> str:
    """One-line systemic-event summary — human-readable and reused for prompt injection."""
    vuln_clause = (
        f" {vuln_count} vulnerable household{'s' if vuln_count != 1 else ''} on the same main."
        if vuln_count else ""
    )
    return (
        f"PROBABLE SYSTEMIC EVENT: {total_reports} {dominant_hazard} reports on {street_label} "
        f"within {first_report_min_ago} min ({total_reports - 1} prior + this call)."
        f"{vuln_clause} Treat as a possible {dominant_hazard}-main event, not an isolated incident."
    )


def detect_cluster(call: dict, incidents=INCIDENTS,
                   window_min: int = CLUSTER_WINDOW_MIN, min_prior: int = CLUSTER_MIN_PRIOR) -> dict:
    """Correlate the current call against prior reports on the same street/main.

    Pure and deterministic — no model call. ALWAYS returns a dict (clustered True or
    False) so the UI has a clean isolated-incident state; every field access is
    .get()-guarded so a missing key can never raise mid-render on stage.
    """
    key = normalize_street(call.get("address", ""))
    matched = [
        i for i in incidents
        if key and (i.get("street_key") or normalize_street(i.get("address", ""))) == key
        and i.get("minutes_ago", 10 ** 9) <= window_min
    ]
    matched.sort(key=lambda i: i.get("minutes_ago", 0))          # most recent first
    prior = len(matched)
    total = prior + 1                                            # + the current call
    clustered = prior >= min_prior
    vuln = [i for i in matched if i.get("medical_dependent") or i.get("vulnerability_flag")]
    hazards = [i.get("hazard_type", "unknown") for i in matched]
    # sorted() before max() gives a stable tie-break (set iteration order is not
    # deterministic), so a mixed-hazard main always labels the same way run to run.
    dominant = max(sorted(set(hazards)), key=hazards.count) if hazards else "unknown"
    first_min = max((i.get("minutes_ago", 0) for i in matched), default=0)  # earliest report
    label = _street_label(call.get("address", ""))
    value = compute_cluster_value(total, len(vuln), first_min) if clustered else {}
    summary = _cluster_summary(label, total, dominant, first_min, len(vuln)) if clustered else ""
    return {
        "clustered": clustered,
        "systemic_event": clustered,
        "street_key": key,
        "street_label": label,
        "matched_incidents": matched,
        "prior_count": prior,
        "total_reports": total,
        "dominant_hazard": dominant,
        "vulnerable_neighbors": vuln,
        "window_min": window_min,
        "first_report_min_ago": first_min,
        "value": value,
        "summary": summary,
    }


# ==================================================================
# QUEUE INTELLIGENCE — proactive action on callers still waiting.
# When a systemic cluster fires, the queue fills with callers from the SAME main
# who are waiting one-by-one while the hazard is live. triage_queue() finds them,
# orders them vulnerable-first, and prepares ONE broadcast safety alert so N waiting
# callers are reached in seconds and the queue for that main collapses to a single
# coordinated response. Pure/deterministic (no model call); reuses normalize_street.
# ==================================================================

QUEUE_AVG_HANDLE_MIN = 6   # ASSUMPTION: avg agent handle time for one emergency-info call

# Callers currently holding in the contact-centre queue — mock data, inline like
# CALLS/INCIDENTS. During Rosa's Maple St cluster, the Maple callers here are the ones
# WattNext can act on proactively; the off-main callers prove it targets only the event.
QUEUE = [
    {"id": "Q-1", "caller_name": "Maria Alvarez", "address": "455 Maple Street",
     "waiting_min": 4, "medical_dependent": True, "vulnerability_flag": "mobility-impaired",
     "reason": "smells gas, can't get downstairs quickly"},
    {"id": "Q-2", "caller_name": "Dan Whitfield", "address": "410 Maple Street, Apt 1A",
     "waiting_min": 7, "medical_dependent": False, "vulnerability_flag": None,
     "reason": "wants to know what's happening on the street"},
    {"id": "Q-3", "caller_name": "Priya Nair", "address": "421 Maple Street",
     "waiting_min": 2, "medical_dependent": False, "vulnerability_flag": "infant at home",
     "reason": "gas smell in the hallway"},
    {"id": "Q-4", "caller_name": "Greg Han", "address": "437 Maple Street",
     "waiting_min": 5, "medical_dependent": False, "vulnerability_flag": None,
     "reason": "is it safe to stay inside?"},
    # Off-main callers — must NOT be swept into the Maple St action.
    {"id": "Q-5", "caller_name": "Tom Becker", "address": "8 Oakdale Road",
     "waiting_min": 9, "medical_dependent": False, "vulnerability_flag": None,
     "reason": "billing question"},
    {"id": "Q-6", "caller_name": "Susan Lee", "address": "63 Birchwood Lane",
     "waiting_min": 3, "medical_dependent": False, "vulnerability_flag": None,
     "reason": "faint odor, non-urgent"},
]


def _queue_is_vulnerable(rec: dict) -> bool:
    return bool(rec.get("medical_dependent")) or bool(rec.get("vulnerability_flag"))


def triage_queue(queue=QUEUE, cluster: "dict | None" = None) -> dict:
    """Given the waiting queue and a detected cluster, find callers on the SAME main and
    prepare the proactive action. Returns an empty/no-op result unless a cluster fired.

    Ordering: vulnerable first, then longest-waiting. Deterministic — no model call.
    'reached' = everyone on the affected main gets the broadcast; 'prioritized' = the
    vulnerable ones also bumped for a live agent; 'deflected' = info-only callers the
    broadcast answers without an agent (conservatively, the non-vulnerable same-main ones).
    """
    empty = {
        "active": False, "street_label": "", "same_main": [], "others": list(queue),
        "reached": 0, "prioritized_count": 0, "deflected": 0, "longest_wait_min": 0,
        "agent_minutes_freed": 0, "vulnerable": [],
    }
    if not cluster or not cluster.get("clustered"):
        return empty
    key = cluster.get("street_key") or ""
    same_main = [q for q in queue if normalize_street(q.get("address", "")) == key and key]
    if not same_main:
        return empty
    same_main.sort(key=lambda q: (not _queue_is_vulnerable(q), -q.get("waiting_min", 0)))
    vulnerable = [q for q in same_main if _queue_is_vulnerable(q)]
    deflected = len(same_main) - len(vulnerable)
    return {
        "active": True,
        "street_label": cluster.get("street_label", "this main"),
        "same_main": same_main,
        "others": [q for q in queue if q not in same_main],
        "reached": len(same_main),
        "prioritized_count": len(vulnerable),
        "deflected": deflected,
        "longest_wait_min": max((q.get("waiting_min", 0) for q in same_main), default=0),
        "agent_minutes_freed": deflected * QUEUE_AVG_HANDLE_MIN,
        "vulnerable": vulnerable,
    }


# ------------------------------------------------------------------
# Headless smoke test — the checkpoint artifact.
#   GEMINI_API_KEY=... python agent.py
# Expect: Maria -> ASSISTANCE_ENROLLMENT, James -> BUDGET_BILLING (routes MUST differ).
# With no key set, it exercises the deterministic-fallback path so the module still demos offline.
# ------------------------------------------------------------------
_SMOKE_CUSTOMERS = [
    {
        "name": "Maria Santos",
        "income_band": "low",
        "medical_equipment": True,
        "hardship": True,
        "baseline_usd": 120.0,
        "current_usd": 168.0,
        "spike_pct": 40,
        "spike_cause": "increased use of home medical/life-support equipment",
    },
    {
        "name": "James Carter",
        "income_band": "middle",
        "medical_equipment": False,
        "hardship": False,
        "baseline_usd": 210.0,
        "current_usd": 273.0,
        "spike_pct": 30,
        "spike_cause": "seasonal air-conditioning usage during a heat wave",
    },
]


# Public alias — the two demo customers, consumed by app.py's DETECT panel.
CUSTOMERS = _SMOKE_CUSTOMERS


_PLACEHOLDER_KEY = "PASTE_YOUR_GEMINI_API_KEY_HERE"


def _load_api_key() -> str | None:
    """Read the key from GEMINI_API_KEY env var, else .streamlit/secrets.toml. None if absent/placeholder."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        secrets = pathlib.Path(__file__).parent / ".streamlit" / "secrets.toml"
        if secrets.exists():
            try:
                key = tomllib.loads(secrets.read_text(encoding="utf-8")).get("GEMINI_API_KEY")
            except (tomllib.TOMLDecodeError, OSError):
                key = None
    return key if key and key != _PLACEHOLDER_KEY else None


if __name__ == "__main__":
    api_key = _load_api_key()
    if api_key:
        client = build_client(api_key)
        print("=== Bill Shock ===")
        for cust in _SMOKE_CUSTOMERS:
            result = decide(client, cust)
            print(
                f"{cust['name']:<14} -> route={result['route']:<22} "
                f"source={result['source']:<8} model={result['model_used']}"
            )
            for step in result["reasoning_steps"]:
                print(f"    • {step}")
            print()
        print("=== First Response ===")
        for call in CALLS:
            result = decide(
                client, call,
                build_prompt_fn=build_call_prompt,
                deterministic_fn=_deterministic_call_decision,
                valid_routes=CALL_ROUTES,
            )
            print(
                f"{call['caller_name']:<14} -> route={result['route']:<14} "
                f"source={result['source']:<8} model={result['model_used']}"
            )
            for step in result["reasoning_steps"]:
                print(f"    • {step}")
            print()
    else:
        print("No API key (env or .streamlit/secrets.toml) — exercising deterministic fallback path:\n")
        print("=== Bill Shock ===")
        for cust in _SMOKE_CUSTOMERS:
            result = _deterministic_decision(cust)
            print(f"{cust['name']:<14} -> route={result['route']} (deterministic fallback)")
        print("\n=== First Response ===")
        for call in CALLS:
            result = _deterministic_call_decision(call)
            print(f"{call['caller_name']:<14} -> route={result['route']} (deterministic fallback)")

    # Cross-incident cluster smoke — deterministic, no key needed. Expect Rosa (Maple
    # St) to CLUSTER; Trevor (Birchwood) and Marcus (Cedar) to stay isolated.
    print("\n=== Cross-Incident Clusters ===")
    for call in CALLS:
        c = detect_cluster(call)
        verdict = "CLUSTER" if c["clustered"] else "isolated"
        print(
            f"{call['caller_name']:<14} @ {c['street_label']:<16} -> {verdict:<8} "
            f"(prior={c['prior_count']}, total={c['total_reports']}, "
            f"vuln={len(c['vulnerable_neighbors'])})"
        )

    # Queue intelligence smoke — for Rosa's Maple St cluster, expect the Maple callers
    # swept in and the off-main callers left alone.
    print("\n=== Queue Intelligence (Rosa's cluster) ===")
    qr = triage_queue(QUEUE, detect_cluster(CALLS[0]))
    print(
        f"active={qr['active']} reached={qr['reached']} prioritized={qr['prioritized_count']} "
        f"deflected={qr['deflected']} agent_min_freed={qr['agent_minutes_freed']}"
    )
    for q in qr["same_main"]:
        tag = "VULN" if _queue_is_vulnerable(q) else "info"
        print(f"    [{tag}] {q['caller_name']:<14} {q['address']:<24} waited {q['waiting_min']}m")
