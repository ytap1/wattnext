# WattNext v2 — Developer Handover: 3 → 5 Routes, Diagnostic-First

> 👋 New to Git/GitHub? Read `ONBOARDING_git.md` first, then `CONTRIBUTING.md`. Work on your branch
> (`v2-agent` for agent, `v2-ui` for UI) off `v2-5routes`; open your PR **into `v2-5routes`** (not `main`).

**Audience:** two developers implementing the v2 rebuild in parallel.
**Goal:** expand the agent from 3 resolution routes to **5 vetted routes**, add a **diagnostic-first
sequence**, and make **human handoff a cross-cutting safety layer** — while keeping the app demoable and the
"one real AI call" story intact. Everything stays mocked **except the single Gemini reasoning call**.

**Why:** a utilities-industry stress-test found the 3-route pitch vulnerable — the agent jumps from detecting a
spike to a financial treatment before checking whether the bill is even correct. The #1 judge objection to
pre-empt: *"What if the bill is wrong?"* v2 answers it structurally.

> Deadline context: Main event **Sep 25**. Target: this rebuild done + two ≤3-min timed dry runs with slack.

---

## 1. The 5-route model

Human handoff is **not** a 6th route — it wraps all five as a safety layer.

| Route (enum) | When | Guardrail caveat |
|---|---|---|
| `BILL_REVIEW` | Bill may be wrong (estimated→actual, wrong rate, meter error, duplicate). **First gate.** | Must run before any financial treatment |
| `PAYMENT_FLEXIBILITY` | Valid bill, needs time (extension / installment) | Distinct from Budget Billing |
| `ASSISTANCE_QUALIFICATION` | Persistent affordability; may qualify for aid | Pre-screen + prepare only — **never "enroll"/promise** (LIHEAP is agency-administered) |
| `BUDGET_BILLING` | Valid, affordable, seasonal volatility | Not debt relief, not bill reduction |
| `LOWER_FUTURE_BILLS` | Recurring high usage / wrong rate plan | Root-cause; no immediate relief |

**Operating sequence:** Detect → Diagnose (bill validity) → Screen urgency & vulnerability → Recommend ONE
route → Obtain explicit consent → Execute or escalate.

**Mandatory human-handoff triggers:** suspected billing/meter error, disputed charge, medical/vulnerable
household, imminent shutoff, failed identity, fraud/tampering, low model confidence, customer requests a
person, no compliant option.

**Autonomy boundary (encode this):** AI detects, diagnoses, screens, recommends & prepares → the **customer
authorizes** each consequential action → **humans decide** eligibility-sensitive & safety-critical cases.

---

## 2. Architecture: ONE real AI call, bracketed by deterministic rails

Do **not** add a second model call. Wrap the single Gemini call in two pure-Python gates:

```
DETECT (display)
  → screen_urgency()      [PRE-GATE, rules]  — imminent shutoff / fraud / failed-id → HUMAN_HANDOFF, NO AI call
  → decide()              [THE ONE Gemini call] — diagnose bill, assess urgency/vulnerability, pick 1 of 5
  → enforce_guardrails()  [POST-GATE, rules]  — override to human on bill_valid=False / low conf / disputed / bad route
  → Consent → Execute / Escalate
```

Pitch line this protects: *"one real reasoning call, wrapped in deterministic safety rails — emergencies and
eligibility never depend on a model."*

---

## 3. FROZEN INTERFACE CONTRACT  ← agree on Day 0, do not change unilaterally

This is the seam between Dev A (produces) and Dev B (consumes). `decide()` returns this dict:

```python
{
  "route": "<one of the 5 ROUTES, or 'HUMAN_HANDOFF'>",   # canonical outcome key the UI switches on
  "diagnosis": "<plain-language read of what's driving the bill>",
  "bill_valid": True | False,                 # diagnostic gate result
  "urgency_flags": ["imminent_shutoff", ...], # [] if none
  "vulnerability_flags": ["medical_equipment", ...],
  "confidence": 0.0-1.0,                       # model self-rated
  "recommended_route": "<one of 5 ROUTES>",   # model's pick BEFORE post-gate (for "leaned toward X" display)
  "requires_human": True | False,             # True after any gate forces handoff
  "handoff_reason": "<str or None>",          # populated when requires_human
  "reasoning_steps": ["step 1", "step 2", ...],   # what STREAMS live in the decision log
  "rationale": "<one sentence>",
  "action_params": {"program_or_plan": "...", "forecast": "...", "note": "..."},  # forecast feeds consent
  "source": "live" | "fallback" | "pre_gate", # provenance for the badge
  "model_used": "gemini-3.5-flash-lite" | "gemini-3.7-flash" | "none"
}
```

Rules:
- `route` is the single field the UI switches on. For handoff it equals `"HUMAN_HANDOFF"`; otherwise one of the 5.
- Pre-gate path: `source="pre_gate"`, `model_used="none"` (honest — no AI call was made).
- Only an invalid `recommended_route` is fatal to parsing; every other key gets a safe `setdefault`.

**Route constants (Dev A owns, in `agent.py`):**
```python
ROUTES = {"BILL_REVIEW", "PAYMENT_FLEXIBILITY", "ASSISTANCE_QUALIFICATION",
          "BUDGET_BILLING", "LOWER_FUTURE_BILLS"}
HUMAN_HANDOFF = "HUMAN_HANDOFF"   # cross-cutting outcome, NOT in ROUTES
```

**Persona schema (Dev A owns):** existing fields `name, income_band, medical_equipment, hardship,
baseline_usd, current_usd, spike_pct, spike_cause` **+ new** `shutoff_hours (int|None)`,
`bill_anomaly (str|None)`, `rate_plan (str)`, `disputed_charge (bool)`, `past_due_usd (float)`.

---

## 4. Ownership & task split

Clean seam: `agent.py` (pure logic, no Streamlit) ↔ `app.py` (UI). The two devs touch different files.
Current anchors are from the v1 code (line numbers approximate — confirm as you edit).

### Dev A — Agent / Logic  (`agent.py` + new `test_agent.py`)
- [ ] Replace `ROUTES` (~line 27) with the 5-set; add `HUMAN_HANDOFF` constant. Delete old `REVIEW` route.
- [ ] Rename `ASSISTANCE_ENROLLMENT → ASSISTANCE_QUALIFICATION` everywhere.
- [ ] `build_prompt()` (~35-64): keep `sorted(ROUTES)` injection; rewrite the 5 route-meaning lines (with
      caveats from §1); add the explicit operating sequence; extend the demanded JSON to the §3 contract;
      pass the new persona fields into `user_content`.
- [ ] `_parse_decision()` (~76-87): validate `recommended_route` ∈ ROUTES; `setdefault` all new keys.
- [ ] NEW `screen_urgency(customer)` — pure pre-gate; returns a `HUMAN_HANDOFF` dict (canned reasoning +
      `handoff_reason`) on `shutoff_hours ≤ 48` / fraud / identity-fail, else `None`.
- [ ] NEW `enforce_guardrails(decision, customer)` — pure post-gate; set `requires_human=True` +
      `handoff_reason` + `route="HUMAN_HANDOFF"` on `bill_valid False` / `confidence < 0.5` / disputed / bad route.
- [ ] `decide()` (~123-162): orchestrate pre-gate → Gemini loop (unchanged mechanics: temp 0, JSON mime,
      10 s timeout, primary→fallback) → post-gate → deterministic fallback. Set `source`/`model_used` honestly.
- [ ] `_deterministic_decision()` (~90-120): expand to reach each of the 5 routes + handoff
      (`bill_anomaly`→BILL_REVIEW; low `shutoff_hours`→HUMAN_HANDOFF; medical+low→ASSISTANCE_QUALIFICATION;
      `past_due>0` & no hardship→PAYMENT_FLEXIBILITY; suboptimal `rate_plan`→LOWER_FUTURE_BILLS; else BUDGET).
      Keep canned `reasoning_steps` per branch so offline demo still narrates.
- [ ] Personas (~171-196): the 6 in §5; update `__main__` smoke to print `route` + `requires_human` + `source`.
- [ ] `test_agent.py` (NEW): routing per persona, pre-gate (no AI call for Earl), guardrail overrides,
      malformed-JSON fallback. All offline-safe (mock the client).

### Dev B — UI / Experience  (`app.py` + `test_app.py`)
- [ ] `ROUTE_STYLE` (~42-46): 5 entries on the **brand palette** (Electric Blue `#2563EB`, Cyan `#06B6D4`,
      Ink `#0F172A`; see `brand/brand-spec.md`). Add a separate `HANDOFF_STYLE`. Icons:
      BILL_REVIEW 🔎 · PAYMENT_FLEXIBILITY 🗓️ · ASSISTANCE_QUALIFICATION 🤝 · BUDGET_BILLING 📊 ·
      LOWER_FUTURE_BILLS 📉 · HUMAN_HANDOFF 🧑‍💼.
- [ ] Session state (~85-94): add `diagnosis`, `urgency_cleared`, `authorized_actions`; reset in
      `_select_customer()` (~96-102).
- [ ] Sidebar (~107-137): 6-way persona selector (radio/selectbox) over `agent.CUSTOMERS`; keep Reset +
      debug toggles; add a "diagnostic + urgency screen" evidence toggle.
- [ ] NEW `_render_diagnose()` + `_render_urgency()` — two compact panels between decision log and route
      badge, rendered from the single call's JSON (**zero added latency**). `bill_valid` chip (green
      "verified" / red "possible billing error — needs human") + flag chips.
- [ ] Pre-gate emergency card (~line 315): branch first on `route == "HUMAN_HANDOFF"` / `requires_human`
      → dedicated red emergency card (`handoff_reason`, ref #, "no automated action taken"); skip consent/deliver.
- [ ] Consent upgrade (`_render_deliver`, ~229-290): show `action_params.forecast`; per-route accept labels
      ("Authorize application" / "Authorize due-date change") recorded in `authorized_actions`; keep Accept /
      decline→specialist, and **relabel** the customer-initiated handoff to distinguish it from the
      safety/eligibility handoff. Extend `_deliver_figure` (~218-226) + `_confirmation_number` (~215;
      `route[:3]` → BIL/PAY/ASS/BUD/LOW/HUM, all distinct).
- [ ] LIVE/FALLBACK badge (~168-183): add a third state **"PRE-GATE (no AI needed — safety rule)"** so
      Earl's no-AI-call path never shows a misleading FALLBACK.
- [ ] ≤3-min guard: one "Run Agent" click drives Detect→…→Consent; auto-render diagnose/urgency in the same
      rerun; **no** second inter-stage button; keep `STEP_DELAY_SEC` trimmable (~line 50).
- [ ] `test_app.py`: keep the AppTest UI tests; add the new diagnostic toggle + emergency-card + forecast checks.

### Shared / coordination
- **Personas** live in `agent.py` (Dev A owns). Dev B imports `agent.CUSTOMERS` read-only.
- **Split the test files** so you never edit the same file: Dev A → `test_agent.py`; Dev B → `test_app.py`.
- **Two handoff notions reconciled:** rule/AI-forced handoff flows through `route="HUMAN_HANDOFF"` /
  `requires_human` (Dev A); the UI "decline → talk to a specialist" stays a separate *customer-initiated*
  path (Dev B) — label them distinctly on screen.

---

## 5. Personas (6: one per route + mandatory handoff)

| Name | Route | Key fields |
|---|---|---|
| Dwayne Okafor | `BILL_REVIEW` | `bill_anomaly="estimated_read_then_actual"`, spike ~85%, `bill_valid`→False |
| James Carter | `BUDGET_BILLING` | KEEP; middle income, seasonal AC, valid bill, capacity to pay |
| Maria Santos | `ASSISTANCE_QUALIFICATION` | KEEP; low income, medical, hardship, **`shutoff_hours=None`** (qualify, not handoff) |
| Rosa Delgado | `PAYMENT_FLEXIBILITY` | valid bill, `past_due_usd`>0, temporary cash-flow gap, no hardship |
| Priya Nair | `LOWER_FUTURE_BILLS` | `rate_plan="flat_but_TOU_eligible"`, higher usage, valid bill |
| Earl Jackson | `HUMAN_HANDOFF` | `shutoff_hours=18`, medical, low income → pre-gate fires, **no AI call** |

Invariant to keep: **5 distinct routes + 1 emergency handoff from one agent.**

---

## 6. Git / PR / CI workflow

Repo `github.com/ytap1/wattnext` (private); `main` auto-deploys to `wattnext-ai.streamlit.app`.

1. Cut integration branch `v2-5routes` off `main`.
2. **Day 0 together:** commit this contract (§3) + route constants + persona schema; **Dev A lands a stub
   `decide()`** on `v2-5routes` that returns a hardcoded §3-shaped dict per persona — so Dev B can build the
   whole UI immediately, without waiting for the model wiring.
3. Sub-branches: `v2-agent` (Dev A), `v2-ui` (Dev B). PR → `v2-5routes`; `.github/workflows/test.yml` must be
   green. Merge Dev A's contract/stub first, then Dev B rebases.
4. Keep `main` deployable throughout. Fast-forward `v2-5routes` → `main` **only after** the timed dry run passes.

**Two-week shape:** Wk1 — Day-0 freeze+stub; Dev A: enum/prompt/parse + personas + fallback + gates; Dev B:
styles + selector + diagnose/urgency panels + emergency card against the stub → merge: all routes demoable
**offline**. Wk2 — Dev A: wire real enriched call + guardrail tuning; Dev B: consent-forecast + badge polish →
joint full test pass, brand polish, two ≤3-min dry runs, lock the 3 scripted personas (Dwayne/Maria/Earl).

---

## 7. Acceptance checks (definition of done)

- `venv\Scripts\python.exe -m streamlit run app.py` runs; each of the 6 personas goes end-to-end
  (Detect → Diagnose → route → consent → deliver/escalate).
- Dwayne → `bill_valid=False` → BILL_REVIEW (offers no financial plan first). Earl → `HUMAN_HANDOFF` with
  **no AI call** (`source="pre_gate"`, badge shows PRE-GATE). Maria → `ASSISTANCE_QUALIFICATION` (not handoff).
- ≥5 distinct routes demonstrable; live personas show `source="live"`.
- Consent shows a forecast; nothing changes without an explicit authorize click.
- `test_agent.py` + `test_app.py` green in CI.
- One "Run Agent" click drives the whole loop; a scripted 3-persona run lands **under 3 minutes**.

## 8. Risks (read before starting)

- **Maria drifting to HUMAN_HANDOFF** (highest-probability bug) once vulnerability flags are first-class. Keep
  `shutoff_hours=None`; in the prompt separate "vulnerability + emergency → handoff" from "vulnerability + no
  emergency → qualify"; verify at temp 0 across **both** models off-stage.
- **"One real call" story:** never add a 2nd model call; the gates are Python. Narrate Earl's zero-call path as
  a strength.
- **Enriched JSON = more parse-failure surface:** generous `setdefault`s; only an invalid route is fatal.
- **Contract drift:** freeze §3 on Day 0 + land the stub before parallel work.
- **Scope fence:** this supersedes the old "exactly two customer branches" fence in `../HACKATHON.md` — update
  that file's scope fence + scorecard when you start.

---
*Source of truth for the pitch narrative: `pitch/WattNext_Pitch.pptx` (5-route model, slides 3–7).*
