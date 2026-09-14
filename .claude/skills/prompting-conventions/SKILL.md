---
name: prompting-conventions
description: Use when writing or refining a prompt/task for a coding agent, or when you receive an underspecified coding task — to plan before implementing and frame it well (clear outcome, context, acceptance criteria, scope, verification) and ask before guessing.
---

# Prompting Conventions

How to frame a task for a coding agent so it does the right thing the first time. Works both
ways: **humans** use it to write better task prompts; the **agent** uses it to spot what a task
is missing and ask instead of guessing.

## Principles

1. **Start in plan mode.** For any non-trivial task, plan/design and get the plan approved
   before writing code — don't jump straight to implementation. (Trivial edits can skip it.)
2. **Propose 2-3 approaches with trade-offs and a recommendation.** When a task has more than
   one reasonable approach, lay out 2-3 options with their trade-offs and lead with the one
   you'd pick and why — before committing. Don't silently choose, and don't dump every option
   without a recommendation.
3. **State the goal as an outcome**, not just an action — what should be *true* when done.
4. **Give context the agent can't see** — file paths, the relevant code, constraints, the "why."
5. **Make acceptance criteria explicit** — how success is judged, including edge cases.
6. **Bound the scope** — say what *not* to touch, to prevent unwanted changes.
7. **Specify verification** — how the change is checked (tests, run it, expected output);
   evidence over assertions.
8. **Right-size the task** — small and single-purpose; decompose big asks into steps.
9. **Show examples / desired patterns** — a similar function, preferred style, sample I/O.
10. **Iterate with checkpoints** — review a plan or a small first step before a big change.
11. **Give feedback on specifics** — point to the exact behavior/line, expected vs. actual.

## Before sending a prompt — checklist

- [ ] Non-trivial? → started with a plan / plan mode
- [ ] Multiple valid approaches? → 2–3 options with trade-offs + a recommendation
- [ ] Goal stated as an outcome
- [ ] Context + file paths the agent can't infer
- [ ] Acceptance criteria / definition of done
- [ ] Out-of-scope / don't-touch noted
- [ ] Verification method specified
- [ ] Task small enough (or decomposed)
- [ ] Example or reference pattern (if style matters)

## When you're the agent and the task is underspecified

Don't guess. Name the 1–3 things that are missing (usually the outcome, acceptance criteria, or
scope) and ask — or, for non-trivial work, enter plan mode and propose 2-3 approaches (with
trade-offs and a recommendation) for approval before implementing.

## Full reference

See [`docs/prompting-conventions.md`](../../../docs/prompting-conventions.md) for each principle
with weak-vs-strong examples, anti-patterns, and how to give feedback while iterating.
