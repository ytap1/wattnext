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
# Active-danger => a leak is likely live: emergency responder.
ACTIVE_DANGER_KEYWORDS = frozenset({
    "hiss", "hissing", "evacuat", "rotten egg", "strong smell", "strong odor",
    "strong odour", "dizzy", "dizziness", "nausea", "nauseous", "headache",
    "can't breathe", "cant breathe", "trouble breathing", "short of breath",
    "passed out", "collaps", "unconscious", "lightheaded", "light-headed",
    "loud", "confirmed leak", "gas everywhere", "filling with gas", "explos",
})
# Odor-only => a complaint with low signal: non-emergency technician visit.
ODOR_KEYWORDS = frozenset({
    "smell", "odor", "odour", "faint", "whiff", "gassy", "sulphur", "sulfur",
})


def build_call_prompt(call: dict) -> tuple[str, str]:
    """Return (system_instruction, user_content) for a first-response DECIDE call.

    Same JSON schema as build_prompt so _parse_decision handles both; only the
    domain, route set, and the safety bias differ.
    """
    system_instruction = (
        "You are WattNext's first-response triage agent for a utility contact centre. "
        "You read a raw inbound call transcript about a possible gas odor or leak and "
        "recommend ONE routing decision for a HUMAN dispatcher. You never dispatch "
        "anyone yourself. Choose EXACTLY ONE route from this set: "
        f"{sorted(CALL_ROUTES)}. "
        "DISPATCH_NOW = the transcript strongly indicates an active/confirmed leak "
        "(e.g. smell PLUS hissing, evacuation in progress, or physical symptoms like "
        "dizziness/nausea/trouble breathing). Send an emergency responder. "
        "SCHEDULE_TECH = a low-signal odor complaint with NO active-danger indicators. "
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
        "Inbound gas-odor/leak call:\n"
        f"- Caller: {call.get('caller_name')}\n"
        f"- Address: {call.get('address')}\n"
        f"- Medical-dependent household (from customer record): {call.get('medical_dependent')}\n"
        f"- Account vulnerability flag: {vuln}\n"
        "- Raw call transcript:\n"
        f"\"\"\"\n{call.get('transcript')}\n\"\"\"\n"
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
    has_odor = _mentions(transcript, ODOR_KEYWORDS)

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
        summary = "Suspected active gas leak; vulnerable occupant — emergency response."
    elif has_danger:
        route, severity = "DISPATCH_NOW", "HIGH"
        steps = [
            "Transcript contains active-danger language (leak likely live).",
            "No vulnerability flag, but the active-danger signal governs.",
            "Life-safety risk outweighs a scheduled visit.",
            "Best route: dispatch an emergency responder now.",
        ]
        rationale = "Active-danger signal in the transcript — dispatch an emergency responder."
        summary = "Suspected active gas leak — emergency response."
    elif has_odor:
        route, severity = "SCHEDULE_TECH", "LOW"
        steps = [
            "Transcript reports an odor but no active-danger indicators.",
            "No evacuation, hissing, or physical symptoms mentioned.",
            "Low-signal complaint suited to a non-emergency visit.",
            "Best route: schedule a technician.",
        ]
        rationale = "Low-signal odor complaint with no active-danger indicators — schedule a technician."
        summary = "Odor complaint, no active-danger indicators — non-emergency technician visit."
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
]


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
