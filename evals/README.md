# Evals

Regression checks for the tools. Each case is a question, the tool calls a
good agent should make for it, and text the results must (or must not)
contain. Most cases come from real mistakes: when the agent gets something
wrong in a chat, add a case so it stays fixed.

| File | In git | Contents |
|---|---|---|
| `cases.example.json` | yes | Generic cases that work on any workspace made from the template |
| `cases.local.json` | no (ignored) | Your cases, with your real data (names, IDs, dates) |

## Run

```bash
uv run agent eval                      # your cases (falls back to the example file)
uv run agent eval -k person -v         # only matching cases, show all output
uv run agent eval --file evals/cases.example.json
uv run agent eval --questions          # questions to try by hand in a chat
```

The command exits with status 1 if any case fails, so it can run in CI or a
pre-commit hook.

## Two levels of testing

1. **Tools** (`agent eval`): do the tools return what a correct answer needs?
   Deterministic, free, runs in seconds.
2. **The model** (`agent eval --questions`): ask each question in a new chat
   and check it used the expected tools and mentioned the expected items.
   Manual for now; can be automated later with a local model.

## Writing a case

```json
{
  "name": "weekly-update-not-cvpr-call",
  "question": "What came out of my weekly internship update?",
  "calls": [{"tool": "find", "args": {"database": "Interactions",
                                      "where": {"Category": "periodical-check-in"}}}],
  "expect": ["INT-14"],
  "expect_not": ["CVPR call"],
  "why": "An agent once picked the CVPR call for this question."
}
```

Tips: match on IDs (`INT-14`) and fixed values rather than titles, which you
may rename. Use fixed dates, not `today`, so cases don't drift.
