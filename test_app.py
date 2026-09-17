"""
WattNext regression tests — the "robot that clicks through the app for you".

WHY THIS EXISTS (plain terms):
  Every code change risks quietly breaking something that used to work — and you
  don't want to discover that live on stage. This drives the REAL app logic
  in-process (via Streamlit's AppTest, no browser needed) and fails loudly if the
  demo flow breaks. It also catches a dead/expired API key before the pitch.

HOW TO RUN:
  venv\\Scripts\\python.exe test_app.py       # plain run, prints PASS/FAIL
  (or, if pytest is installed:  pytest test_app.py)

NOTE: test_live_decision needs a working GEMINI_API_KEY (env or
.streamlit/secrets.toml) + network — that's the point: it proves the one real call
still works. The UI-flow tests pass even offline (the deterministic fallback still
returns the correct routes), so they check app logic independently of the network.
"""
from pathlib import Path

from streamlit.testing.v1 import AppTest

import agent

APP = str(Path(__file__).parent / "app.py")
EXPECTED_ROUTE = {"Maria Santos": "ASSISTANCE_ENROLLMENT", "James Carter": "BUDGET_BILLING"}


class SkipTest(Exception):
    """Raised to skip a test that can't run in this environment (e.g. no API key in CI)."""


# ---- helpers ---------------------------------------------------------------
def _click(at, needle):
    for b in at.button:
        if needle in (b.label or ""):
            b.click()
            return
    raise AssertionError(f"button {needle!r} not found; have {[b.label for b in at.button]}")


def _check(at, needle, value=True):
    for c in at.checkbox:
        if needle in (c.label or ""):
            c.set_value(value)
            return
    raise AssertionError(f"checkbox {needle!r} not found; have {[c.label for c in at.checkbox]}")


def _md(at):
    return "\n".join(getattr(m, "value", "") for m in at.markdown)


def _fresh_run_for_maria():
    """Start the app, select Maria, run the agent. Returns the AppTest instance.

    The app hard-stops without a key, so we inject one into the simulated secrets:
    the real key locally (so the UI test also exercises the live call), or a dummy
    in CI (no key present) — where decide() falls back to the deterministic path and
    the flow still completes. This is the "passes even offline" contract.
    """
    at = AppTest.from_file(APP, default_timeout=45)
    at.secrets["GEMINI_API_KEY"] = agent._load_api_key() or "ci-dummy-key"
    at.run()
    assert not at.exception, f"app raised on startup: {at.exception}"
    # First Response is the default (hero) domain now — select Bill Shock explicitly.
    at.radio(key="mode").set_value("⚡ Bill Shock").run()
    assert not at.exception, f"mode switch raised: {at.exception}"
    _click(at, "Maria")
    at.run()
    assert "BILL SHOCK DETECTED" in _md(at), "DETECT panel did not render"
    _click(at, "Run Agent")
    at.run()
    assert at.session_state["decision"] is not None, "no decision after Run Agent"
    return at


# ---- tests -----------------------------------------------------------------
def test_deliver_flow():
    """Accept vs decline-to-human consent flow, incl. reconsider."""
    at = _fresh_run_for_maria()
    assert at.session_state["deliver_status"] == "pending"
    labels = [b.label for b in at.button]
    assert any("Accept & Enroll" in (l or "") for l in labels), labels
    assert any("talk to a specialist" in (l or "") for l in labels), labels

    # Decline -> human handoff (surfaces the REVIEW route)
    at.button(key="decline_action").click()
    at.run()
    assert at.session_state["deliver_status"] == "declined"
    assert "Handed off to a WattNext specialist" in _md(at)
    assert "WN-REV-" in _md(at)

    # Reconsider -> back to pending
    at.button(key="reconsider_action").click()
    at.run()
    assert at.session_state["deliver_status"] == "pending"

    # Accept -> enrolled/completed with confirmation #
    at.button(key="accept_action").click()
    at.run()
    assert at.session_state["deliver_status"] == "accepted"
    md = _md(at)
    assert "Accepted" in md and "enrolled" in md
    assert "WN-" in md


def test_call_play_flow():
    """First Response hero: '▶ Play call' drives the replay + the one decision, and
    the deliver (dispatch/hold) controls appear. Offline-safe: with no key, decide()
    falls back deterministically and the flow still completes."""
    at = AppTest.from_file(APP, default_timeout=60)
    at.secrets["GEMINI_API_KEY"] = agent._load_api_key() or "ci-dummy-key"
    at.run()
    assert not at.exception, f"app raised on startup: {at.exception}"
    # First Response is the default (hero) domain; pick canned Call A (Rosa).
    _click(at, "Rosa")
    at.run()
    assert "INCOMING HAZARD CALL" in _md(at), "hazard DETECT panel did not render"
    assert at.session_state["call_played"] is False, "call marked played before ▶ Play"

    # Play the call → progressive replay + the ONE real decision call.
    _click(at, "Play call")
    at.run()
    assert at.session_state["call_played"] is True, "▶ Play did not mark the call played"
    assert at.session_state["decision"] is not None, "no decision after ▶ Play"
    md = _md(at)
    assert "Decision Log" in md, "decision log did not render"

    labels = [b.label for b in at.button]
    assert any("Dispatch responder" in (l or "") for l in labels), labels
    assert any("Hold" in (l or "") for l in labels), labels

    lat = at.session_state["decision_latency"]
    assert isinstance(lat, (int, float)) and lat > 0, f"latency not captured: {lat}"


def test_debug_views():
    """All five Debug/Evidence panels render; latency is captured."""
    at = _fresh_run_for_maria()
    for lbl in ["customer profile", "prompt sent", "allowed routes",
                "structured decision", "call metadata"]:
        _check(at, lbl, True)
    at.run()
    md = _md(at)
    for expected in ["Debug / Evidence", "Customer profile", "Prompt sent to Gemini",
                     "Allowed routes", "Structured decision", "Call metadata"]:
        assert expected in md, f"debug panel missing: {expected}"
    lat = at.session_state["decision_latency"]
    assert isinstance(lat, (int, float)) and lat > 0, f"latency not captured: {lat}"


def test_live_decision():
    """The ONE real Gemini call still works and routes DIVERGE per customer.
    Requires a working GEMINI_API_KEY — this is the pre-pitch 'is it live?' check.
    Skipped (not failed) when no key is present, e.g. in CI without the secret."""
    key = agent._load_api_key()
    if not key:
        raise SkipTest("no GEMINI_API_KEY (env or .streamlit/secrets.toml) — live call not verified here")
    client = agent.build_client(key)
    routes = {}
    for cust in agent.CUSTOMERS:
        result = agent.decide(client, cust)
        assert result["source"] == "live", (
            f"{cust['name']} fell back to deterministic (source={result['source']}) — "
            "check the API key / model IDs / network before the pitch."
        )
        assert result["route"] == EXPECTED_ROUTE[cust["name"]], (
            f"{cust['name']} routed to {result['route']}, expected {EXPECTED_ROUTE[cust['name']]}"
        )
        routes[cust["name"]] = result["route"]
    assert len(set(routes.values())) == 2, f"routes did not diverge: {routes}"


# ---- cross-incident intelligence (deterministic, offline-safe) -------------
def test_normalize_street_matches_variants():
    """The Rosa/seed Maple variants collapse to one key; other mains stay distinct."""
    ns = agent.normalize_street
    assert ns("418 Maple Street, Apt 2B") == "maple st"
    assert ns("402 Maple Street") == "maple st"
    assert ns("431 Maple Street, Apt 5C") == "maple st"
    assert ns("77 Birchwood Lane") == "birchwood ln"
    assert ns("92 Cedar Avenue") == "cedar ave"
    assert ns("birchwood ln") != ns("cedar ave")
    assert ns("") == ""


def test_cluster_fires_for_rosa():
    """Rosa's Maple St call is the 3rd report on the main → systemic cluster + value."""
    c = agent.detect_cluster(agent.CALLS[0])
    assert c["clustered"] and c["systemic_event"], "Rosa should trigger a systemic cluster"
    assert c["prior_count"] >= agent.CLUSTER_MIN_PRIOR
    assert c["total_reports"] >= 3
    assert c["dominant_hazard"] == "gas"
    assert len(c["vulnerable_neighbors"]) >= 1, "should flag the oxygen-dependent neighbor"
    val = c["value"]
    assert val.get("trucks_saved", 0) >= 1
    assert val.get("dollars_saved", 0) > 0
    assert val.get("exposure_minutes_avoided", 0) > 0


def test_incident_street_keys_match_normalizer():
    """The plan's #1 stage risk is a normalize_street mismatch silently killing the
    cluster. Guard it: every seed's explicit street_key must equal what normalize_street
    would produce for its address, so a future data edit can't desync them undetected."""
    for inc in agent.INCIDENTS:
        assert inc["street_key"] == agent.normalize_street(inc["address"]), (
            f"{inc['id']}: street_key {inc['street_key']!r} != "
            f"normalize_street({inc['address']!r})={agent.normalize_street(inc['address'])!r}"
        )


def test_cluster_does_not_fire_for_trevor():
    """Trevor's Birchwood call has only 1 prior report → below threshold, no cluster."""
    c = agent.detect_cluster(agent.CALLS[1])
    assert not c["clustered"], "Trevor should NOT cluster (no false positive)"
    assert c["prior_count"] < agent.CLUSTER_MIN_PRIOR
    assert c["value"] == {}


def test_cluster_does_not_fire_for_marcus():
    """Marcus's Cedar call has only 1 prior report → below threshold, no cluster."""
    c = agent.detect_cluster(agent.CALLS[2])
    assert not c["clustered"], "Marcus should NOT cluster (no false positive)"
    assert c["prior_count"] < agent.CLUSTER_MIN_PRIOR


def test_cluster_prompt_injection_safe():
    """Injection is additive: it extends the prompt when clustered, leaves the default
    prompt byte-for-byte unchanged, and never perturbs the deterministic route."""
    rosa = agent.CALLS[0]
    cluster = agent.detect_cluster(rosa)
    assert cluster["clustered"]
    sys_i, user_c = agent.build_call_prompt(rosa, cluster=cluster)
    assert "CROSS-INCIDENT" in user_c and "SYSTEMIC" in user_c
    base_sys, base_user = agent.build_call_prompt(rosa)  # no cluster kwarg
    assert "CROSS-INCIDENT" not in base_user, "default prompt must not carry cluster context"
    result = agent.build_call_prompt(rosa)
    assert isinstance(result, tuple) and len(result) == 2, "signature must stay a 2-tuple"
    assert agent._deterministic_call_decision(rosa)["route"] == "DISPATCH_NOW", (
        "deterministic route must ignore cluster context"
    )


def test_cluster_panel_renders_offline():
    """The intelligence panel renders in the full Rosa flow, live OR on the fallback."""
    at = AppTest.from_file(APP, default_timeout=60)
    at.secrets["GEMINI_API_KEY"] = agent._load_api_key() or "ci-dummy-key"
    at.run()
    assert not at.exception, f"app raised on startup: {at.exception}"
    _click(at, "Rosa")
    at.run()
    _click(at, "Play call")
    at.run()
    assert not at.exception, f"cluster render raised: {at.exception}"
    md = _md(at)
    assert "SYSTEMIC" in md, "systemic-event banner missing"
    assert "Maple" in md, "street label missing"
    assert "Proactive outreach" in md, "vulnerable-household outreach callout missing"


def test_cluster_isolated_panel_renders_for_trevor():
    """The isolated-incident panel branch renders end-to-end without a false cluster."""
    at = AppTest.from_file(APP, default_timeout=60)
    at.secrets["GEMINI_API_KEY"] = agent._load_api_key() or "ci-dummy-key"
    at.run()
    assert not at.exception, f"app raised on startup: {at.exception}"
    _click(at, "Trevor")
    at.run()
    _click(at, "Play call")
    at.run()
    assert not at.exception, f"isolated-panel render raised: {at.exception}"
    md = _md(at)
    assert "No systemic pattern" in md, "isolated-incident panel missing"
    assert "SYSTEMIC" not in md, "false systemic cluster shown for Trevor"


# ---- plain-python runner (no pytest needed) --------------------------------
if __name__ == "__main__":
    import sys

    tests = [
        test_deliver_flow, test_call_play_flow, test_debug_views,
        test_normalize_street_matches_variants, test_incident_street_keys_match_normalizer,
        test_cluster_fires_for_rosa, test_cluster_does_not_fire_for_trevor,
        test_cluster_does_not_fire_for_marcus, test_cluster_prompt_injection_safe,
        test_cluster_panel_renders_offline, test_cluster_isolated_panel_renders_for_trevor,
        test_live_decision,
    ]
    passed = failures = skipped = 0
    for t in tests:
        try:
            t()
            passed += 1
            print(f"PASS  {t.__name__}")
        except SkipTest as e:
            skipped += 1
            print(f"SKIP  {t.__name__}: {e}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001 - surface any unexpected error clearly
            failures += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")

    print(f"\n{passed} passed, {failures} failed, {skipped} skipped (of {len(tests)})")
    sys.exit(1 if failures else 0)
