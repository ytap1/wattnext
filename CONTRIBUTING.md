# Contributing to WattNext

Welcome to the team! WattNext is a Streamlit + Google Gemini demo for the Americas
Agentic AI Hackathon 2026. `main` auto-deploys to the **live demo**
(https://wattnext-ai.streamlit.app), so treat `main` as the release branch — see the
merge workflow below.

## First-time setup

1. **Accept the GitHub invite** from `ytap1` (email invite → Accept), then clone:
   ```bash
   git clone https://github.com/ytap1/wattnext.git
   cd wattnext
   ```
2. **Create a virtual environment + install deps** (Python 3.11+; we build on 3.14):
   ```bash
   python -m venv venv
   venv\Scripts\python.exe -m pip install -r requirements.txt
   ```
3. **Add your OWN Gemini key** — never use or commit someone else's:
   - Get a free key at https://aistudio.google.com/apikey
   - Create `.streamlit/secrets.toml`:
     ```toml
     GEMINI_API_KEY = "your-key-here"
     ```
   - This file is **gitignored** — a key must never be pushed.
4. **Run it:**
   ```bash
   venv\Scripts\python.exe -m streamlit run app.py
   ```

## Before EVERY push — run the tests

```bash
venv\Scripts\python.exe test_app.py
```

Must print **`3/3 passed`**. This checks the accept/decline flow, the debug panels, and that
the **live Gemini call still works** — catching a broken flow or a dead key *before* it reaches
the live demo. Do not push on a red test.

## Branch & merge workflow (main = the live demo)

`main` auto-deploys to the pitch app, so it is the release gate. **Do not commit directly to `main`.**

1. Branch off `main` (prefixes: `feat/`, `fix/`, `docs/`, `chore/`):
   ```bash
   git switch main
   git pull
   git switch -c feat/<short-topic>
   ```
2. Do the work, run `test_app.py`, commit, and push the branch:
   ```bash
   git push -u origin feat/<short-topic>
   ```
3. Open a **Pull Request** into `main` on GitHub.
4. **@ytap1 (Chris) reviews and merges.** This is **enforced** by branch protection on `main`:
   a PR with **1 approval** is required before merging, and direct pushes to `main` are blocked
   for collaborators. Nobody merges their own PR — the repo owner is the merge gate for the live demo.
5. **CI runs automatically on your PR.** A GitHub Actions check (`tests`) runs `test_app.py`
   (flow + debug views + the live Gemini call). Wait for the green check before requesting review;
   a red check blocks the merge.
6. After merge, confirm the Streamlit app redeployed and still works
   (open the app; check a Run Agent still returns `⚡ LIVE GEMINI`).

## Commit messages

Conventional prefixes: `feat:`, `fix:`, `docs:`, `chore:`, `test:`.
Example: `feat: add third customer profile to DETECT panel`.

## Never commit

- API keys / `.streamlit/secrets.toml` (gitignored)
- `venv/`, `__pycache__/`

## Project map

| File | What it is |
|------|------------|
| `agent.py` | The DECIDE core — the one real Gemini call, guardrails, deterministic fallback |
| `app.py` | The Streamlit UI — DETECT → DECIDE → DELIVER, sidebar, debug toggles |
| `test_app.py` | Regression tests — run before every push |
| `requirements.txt` | Pinned deps (keep pinned for reproducible Cloud builds) |
