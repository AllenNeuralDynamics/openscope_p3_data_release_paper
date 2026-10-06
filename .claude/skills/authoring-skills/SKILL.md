---
name: authoring-skills
description: Use when creating or editing a project-local skill in this repo — to get the SKILL.md format, the directory convention, and a template to copy, and to decide skill vs. CLAUDE.md.
---

# Authoring Project-Local Skills

A **skill** is a small, on-demand instruction file Claude Code loads when a task matches its
description. Project skills live in this repo so the conventions travel with the code. This
guide is self-contained and does not require the superpowers plugin.

## Where skills live

```
.claude/skills/<skill-name>/SKILL.md
```

One directory per skill, named in `lower-kebab-case`. The directory may hold supporting files
(reference docs, templates, scripts) that the SKILL.md points to.

## SKILL.md format

YAML frontmatter, then a Markdown body:

```markdown
---
name: my-skill
description: Use when <triggering situation> — to <what it helps the reader do>.
---

# My Skill

<short framing: what this is for>

## <section>
<concrete, actionable guidance — commands, tables, examples>
```

- **`name`** matches the directory name.
- **`description`** is the most important line: it's all Claude sees when deciding whether to
  load the skill. Write it as **"Use when … — to …"**, naming concrete triggers (the kind of
  task, files, or symptoms). Avoid vague descriptions like "helps with code."

## Skill vs. CLAUDE.md — which one?

| Put it in… | When |
|---|---|
| **CLAUDE.md** | A short rule that should apply to *every* task (always-on, low cost). |
| **A skill** | Procedural / deep guidance only needed for a *specific kind* of task. |

If it's more than a couple of lines and only matters sometimes, make it a skill and add a
one-line pointer to it in CLAUDE.md's skill index.

## Writing a good skill

- **Actionable over abstract.** Prefer exact commands, file paths, and tables to prose.
- **Short.** A skill is a checklist, not an essay. Link to longer references beside the
  SKILL.md instead of inlining them.
- **One purpose.** If a skill is trying to cover two unrelated jobs, split it.
- **Match the repo.** Point at real paths and patterns that exist here.

## Checklist for a new skill

1. Create `.claude/skills/<name>/SKILL.md` with the frontmatter above.
2. Write a trigger-focused `description`.
3. Keep the body concrete and short.
4. Add a one-line entry under "Available project skills" in `CLAUDE.md`.
5. Sanity-check: would Claude know *when* to load this from the description alone?

## Copy-paste template

```markdown
---
name: <kebab-name>
description: Use when <trigger> — to <outcome>.
---

# <Title>

<one-line purpose>

## Steps
1.
2.
```
