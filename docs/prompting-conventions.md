# Prompting Conventions for Coding Agents

How to frame a task for an LLM coding agent so it does the right thing the first time. This is
the full reference; the `prompting-conventions` skill is the short version.

## Why framing matters

A coding agent can't see your intent, can't infer your repo's conventions, and doesn't know when
a task is "done" unless you say so. It acts confidently on whatever you give it — so a vague
prompt produces a confident, wrong result. A couple of minutes framing the task up front saves a
round-trip of rework. The flip side: don't over-specify a one-line fix.

Works both ways: **humans** use these to write better prompts; the **agent** uses them to notice
what a task is missing and ask before guessing.

## Quick checklist

Before sending a non-trivial prompt:

- [ ] Started with a plan (plan mode) for non-trivial work
- [ ] 2–3 approaches with trade-offs + a recommendation (when multiple reasonable ways)
- [ ] Goal stated as an outcome (what should be true when done)
- [ ] Context + file paths the agent can't infer
- [ ] Acceptance criteria / definition of done
- [ ] Out-of-scope / don't-touch noted
- [ ] Verification method specified
- [ ] Task small enough, or decomposed
- [ ] Example / reference pattern if style matters

## The principles

Each principle shows a **weak** prompt and a **stronger** version.

### 1. Start in plan mode

For any non-trivial task, have the agent plan or design first and approve the plan before it
writes code. Planning surfaces wrong assumptions while they're cheap to fix; jumping straight to
code bakes them in. Truly trivial edits (a typo, a one-line fix) can skip it.

```text
Weak:   Add caching to the API.
Strong: We want to cache the /search endpoint. First plan it: which cache (in-memory vs Redis),
        where it lives, and how it's invalidated — show me the approach before coding.
```

### 2. Propose 2-3 approaches with trade-offs and a recommendation

When a task can reasonably be solved more than one way, lay out 2-3 options with their trade-offs
and lead with the one you'd choose and why — before committing to an implementation. This makes
the decision reviewable and often surfaces a better option than the first idea. Don't silently
pick one, and don't dump every possibility without a recommendation.

```text
Weak:   Add a background job queue, you decide how.
Strong: Propose 2-3 ways to add a background job queue (e.g. a thread pool, RQ/Redis, Celery)
        with trade-offs for our single-box scale, and recommend one — then we'll build it.
```

### 3. Goal as an outcome, not just an action

Say what should be *true* when the task is done, not only the action to take. Outcomes are
checkable; bare actions leave the target ambiguous.

```text
Weak:   Refactor the auth module.
Strong: Split auth.py so the token logic and the HTTP handlers live in separate modules, with
        no change in behavior and all existing tests still passing.
```

### 4. Give context the agent can't see

Point at the files, the relevant code, the constraints, and the reason behind the task. The
agent can read the repo, but telling it where to look (and why) avoids wrong guesses.

```text
Weak:   The parser is slow, fix it.
Strong: parse_events() in src/pkg/parser.py is O(n^2) — it re-scans `seen` each loop (~line 80).
        Make it linear; inputs can be ~1e6 rows. Keep the public signature unchanged.
```

### 5. Acceptance criteria / definition of done

State how success is judged, including edge cases. This is the agent's target and your review
rubric.

```text
Weak:   Validate the email field.
Strong: Reject input without a single @ and a dot in the domain; trim whitespace; empty input
        shows "required". Done when tests cover valid, missing-@, and empty cases.
```

### 6. Bound the scope

Say what *not* to touch. Agents otherwise "helpfully" refactor adjacent code, widening the diff
and the risk.

```text
Weak:   Clean up the dashboard component.
Strong: Only extract the chart legend into its own component. Don't touch data fetching,
        styling, or any other component.
```

### 7. Specify verification — evidence over assertions

Say how the change should be checked, and ask for the evidence (test output, run logs), not a
claim that it works.

```text
Weak:   Make sure it works.
Strong: Add a test in tests/test_parser.py and run `pytest -k parser`; paste the output. Then
        run `python -m pkg.main` on sample.csv and show the result.
```

### 8. Right-size the task

Keep a prompt to one coherent change; break big asks into ordered steps. A giant prompt yields a
giant, hard-to-review diff.

```text
Weak:   Build the whole user system: auth, profiles, settings, and billing.
Strong: Step 1 only: email/password signup + login with sessions. Profiles come next. Plan
        step 1 first.
```

### 9. Show examples / desired patterns

Give a similar existing function, a preferred style, or sample input/output. Examples pin down
intent faster than prose.

```text
Weak:   Add a retry helper.
Strong: Add retry() mirroring the backoff in src/pkg/net.py (same logging style). e.g.
        retry(fetch, attempts=3) returns fetch()'s result, or raises after 3 failures.
```

### 10. Iterate with checkpoints

For larger work, review a plan or a small first slice before the agent goes big. Cheap course
corrections beat one large wrong turn.

```text
Weak:   Migrate the codebase to async.
Strong: Convert just the db layer to async and stop; show the diff. Once it looks right we'll
        do the callers.
```

### 11. Give feedback on specifics

When correcting, point to the exact behavior, file, or line, and state expected vs. actual.
"That's wrong" gives the agent nothing to act on.

```text
Weak:   No, that's not right, try again.
Strong: handle_login() returns 200 on a bad password (should be 401). The check at line 42
        compares the hash to the raw input — compare against the stored hash instead.
```

## Anti-patterns

- **"Fix it" with no context** — no file, no symptom, no expected behavior.
- **Everything at once** — many unrelated changes in one prompt; impossible to review or verify.
- **No acceptance criteria** — neither you nor the agent can tell when it's done.
- **No verification** — accepting "it works" without running anything.
- **Over-constraining trivial tasks** — a paragraph of ceremony for a one-line typo fix.

## Iterating and giving feedback

- Prefer a **plan or a small first step** over a big bang; review at boundaries.
- When something's off, give **specific, located** feedback (file/line, expected vs. actual) and
  re-state the acceptance criteria if they've drifted.
- Ask for **evidence** at each checkpoint (test output, a run) rather than assurances.
- If the agent is guessing, that's a signal the prompt is missing an outcome, criteria, or
  scope — add it rather than re-rolling the same prompt.

## Optional: in Claude Code

"Start in plan mode" maps directly to Claude Code's **plan mode** — the agent proposes a plan
and waits for approval before editing. If the **superpowers** plugin is installed, its
`brainstorming` skill does the same for design-heavy work and `writing-plans` turns a spec into
a step-by-step plan. None of that is required; the principles above stand on their own.
