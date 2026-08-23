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
    """Start the app, select Maria, run the agent. Returns the AppTest instance."""
    at = AppTest.from_file(APP, default_timeout=45)
    at.run()
    assert not at.exception, f"app raised on startup: {at.exception}"
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
    Requires a working GEMINI_API_KEY — this is the pre-pitch 'is it live?' check."""
    key = agent._load_api_key()
    assert key, "No GEMINI_API_KEY (env or .streamlit/secrets.toml) — cannot verify the live call."
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


# ---- plain-python runner (no pytest needed) --------------------------------
if __name__ == "__main__":
    import sys

    tests = [test_deliver_flow, test_debug_views, test_live_decision]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001 - surface any unexpected error clearly
            failures += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")

    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    sys.exit(1 if failures else 0)
