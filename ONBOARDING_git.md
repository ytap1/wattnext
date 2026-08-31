# New to collaboration? Start here (WattNext)

A gentle primer for your **first time** working on a shared repo. It explains the *concepts* so the
exact steps in **`CONTRIBUTING.md`** make sense. Read this once, then use `CONTRIBUTING.md` +
`DEV_HANDOVER_v2.md` as you work.

> `CONTRIBUTING.md` = the exact commands (setup, tests, branch/merge). This file = the "why" behind them.

---

## The 30-second mental model

- **Git** takes labeled snapshots ("commits") of the code so nothing is ever lost.
- **GitHub** is where those snapshots live online so the team shares one project.
- **A branch** is your own safe copy to edit — you can't break anyone else's work on it.
- **A Pull Request (PR)** is you saying "please review my branch and merge it in."

You never edit the shared code directly. You work on **your branch**, then open a **PR**.

## Our branches for the v2 rebuild

```
main            ← the LIVE pitch demo. Never touch directly.
  └─ v2-5routes ← the shared v2 workspace (the lead creates this)
       ├─ v2-agent  ← Dev A works here (agent.py)
       └─ v2-ui     ← Dev B works here (app.py)
```

You branch off `v2-5routes`, and your PRs go **into `v2-5routes`** (not `main`). The lead merges
`v2-5routes` → `main` only when v2 is ready for the stage. (Full steps: `CONTRIBUTING.md` →
"Current work: the v2 rebuild".)

## Easiest tool for beginners: GitHub Desktop

Prefer clicking over typing at first? Install **GitHub Desktop** (`desktop.github.com`), sign in, and
it does clone / switch branch / commit / push / open-PR with buttons — the same actions the
`CONTRIBUTING.md` commands do. Use it until the commands feel familiar.

## The rhythm of a work session

1. **Pull first** — get everyone's latest changes before you start.
2. **Edit** — follow your GitHub issue's checklist + `DEV_HANDOVER_v2.md`.
3. **Test** — run the tests; don't share red code.
4. **Commit** — save a snapshot with a clear message ("add screen_urgency pre-gate").
5. **Push** — upload your commits so the team + CI can see them.
6. **Open a PR** into `v2-5routes` when a chunk is done; fix anything CI flags; get a review; merge.

(Exact commands for each step: `CONTRIBUTING.md`.)

## Golden rules

- ✅ **Pull before you start**, and commit small with clear messages.
- 🚫 **Never commit to `main`.** Always your branch → PR.
- 🚫 **Never commit secrets** — no API keys. `.streamlit/secrets.toml` and `venv/` are gitignored; keep it so.
- 🆘 **Stuck or think you broke something? Ask the lead — don't force-push or delete to "fix" it.**
  Nothing is truly lost in git.

## Words you'll hear

| Term | Plain meaning |
|------|---------------|
| clone | download the project to your computer |
| branch | your own safe copy to edit |
| commit | a saved snapshot of your changes |
| push / pull | upload your commits / download others' |
| PR (pull request) | "please review + merge my branch" |
| CI | robot that runs the tests on your PR automatically |
| merge conflict | two people changed the same lines — ask the lead to help sort it |

---
Next: open **`CONTRIBUTING.md`** for setup + the exact commands, and your assigned **GitHub issue** for the task.
