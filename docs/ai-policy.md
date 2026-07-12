# AI Contribution Policy

Rules for anyone (AI or human) writing code or docs in this repo. Read before contributing.
These extend `.claude/Development-Principles.md`.

## Style

- Direct, high signal, low noise. Write the least code that solves the problem.
- No em dashes. Use periods, commas, colons, or parentheses.
- No emojis in code, UI, docs, or commit messages.
- No marketing or filler phrasing ("first working slice", "the spine of", "seamlessly", "robust").
- Comments explain non-obvious intent, not what the code plainly does.
- Docstrings are one line unless more is genuinely needed.
- No decorative symbols or arrows in prose.
- Match the surrounding naming, structure, and terseness.

## Structure

- No abstraction, library, or layer you cannot justify from the task in front of you.
- Delete dead code and stale comments rather than leaving them.
- Update the relevant doc when behavior changes, with a one-line dated log.

## Before committing

- Cut every sentence that does not add signal.
- Remove comments that restate the obvious.
- Check for em dashes and emojis, and remove them.
- Names say what the thing is, not how it feels.
