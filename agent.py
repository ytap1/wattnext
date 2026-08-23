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


def _parse_decision(text: str) -> dict | None:
    """Parse the model's JSON; return None if invalid or route not in ROUTES."""
    try:
        obj = json.loads(_strip_code_fences(text))
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(obj, dict) or obj.get("route") not in ROUTES:
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


def decide(client: genai.Client, customer: dict) -> dict:
    """
    The ONE agentic call. Returns:
      {route, reasoning_steps, rationale, action_params, model_used, source}
    source is "live" (from Gemini) or "fallback" (deterministic rule-based).
    reasoning_steps is what the live decision-log panel renders line by line.
    """
    system_instruction, user_content = build_prompt(customer)
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
        parsed = _parse_decision(getattr(response, "text", "") or "")
        if parsed is not None:
            parsed["model_used"] = model
            parsed["source"] = "live"
            return parsed
        # Live call succeeded but output was unparseable/invalid — try next model once.

    # Both models failed (or produced invalid output): deterministic fallback.
    decision = _deterministic_decision(customer)
    decision["model_used"] = "none"
    decision["source"] = "fallback"
    return decision


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
        for cust in _SMOKE_CUSTOMERS:
            result = decide(client, cust)
            print(
                f"{cust['name']:<14} -> route={result['route']:<22} "
                f"source={result['source']:<8} model={result['model_used']}"
            )
            for step in result["reasoning_steps"]:
                print(f"    • {step}")
            print()
    else:
        print("No API key (env or .streamlit/secrets.toml) — exercising deterministic fallback path:\n")
        for cust in _SMOKE_CUSTOMERS:
            result = _deterministic_decision(cust)
            print(f"{cust['name']:<14} -> route={result['route']} (deterministic fallback)")
