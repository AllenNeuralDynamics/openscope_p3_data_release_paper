---
name: bash-safety
description: Use before running destructive or surprising bash commands — rm/rm -rf, glob (*), redirection (>), mv/cp overwrites, chmod -R, git reset/clean/push --force, sudo, or curl|bash — to avoid data loss.
---

# Bash Safety

Read a destructive command the way the shell will execute it, not the way it looks. Before
running anything that deletes, overwrites, or forces, work through the rules below.

## Core rules

- **Preview first.** Use the read-only/dry-run form before the destructive one:
  `ls <glob>`, `echo <glob>`, `--dry-run`, `-n`, `git status`, `git clean -ndx`.
- **Quote and guard variables.** Always `"$VAR"`; for required paths use
  `${VAR:?refusing to run on empty}` so an unset/empty value fails loudly instead of widening
  the target (the `rm -rf "$DIR/"` → `rm -rf /` trap).
- **Check your location.** Confirm `pwd` before any path-relative `rm`/`mv`/`cp`. Chain
  dependent steps with `&&`, never `;` (`cd x && rm …`, so a failed `cd` can't run `rm` in the
  wrong place).
- **Avoid `-f`/`-r` unless truly needed.** Prefer moving to a temp dir over deleting.
- **Use `--`** before globs/paths to stop option parsing (`rm -rf -- *`).
- **Make it reversible.** Commit or back up before risky operations.
- **Scripts:** start with `set -euo pipefail`.

## Highest-risk commands to slow down on

`rm -rf` · `rm *` · `> file` (truncates, even on failure) · `mv`/`cp` (silent overwrite) ·
`git reset --hard` · `git clean -fdx` · `git push --force` (use `--force-with-lease`) ·
`chmod -R 777` · `sudo` · `curl … | bash` · `find … -exec rm` · unquoted `$VAR` · `dd`.

## Before approving a command

1. Destructive? (deletes / overwrites / `-f` / `-r`)
2. Variables quoted **and** guaranteed non-empty?
3. Right `pwd` and path? No stray spaces?
4. Previewed with a dry-run?
5. Reversible (git / backup)?

If any answer is "not sure," stop and verify.

## Full reference

See [`docs/bash-safety.md`](../../../docs/bash-safety.md) for the complete cheat-sheet and
worked examples of each footgun.
