# AGENTS.md

You are working inside this project.

## Project context

This project prefers a modular architecture and a clear module-based folder structure.

Before making non-trivial changes, read the relevant project documents under `docs/`:

- `docs/project_structure.md`: current project folder structure
- `docs/project_progress.md`: current implementation progress
- `docs/project_diary.md`: short record of previous architecture/design mistakes
- `docs/project_overview.md`: main project overview
- module-specific documents under `docs/`

Use these documents as the main source of project context. Do not guess architecture details if the docs already define them.

## Working principles

- Prefer small, modular changes.
- Keep module boundaries clear.
- Avoid large rewrites unless explicitly requested.
- Preserve existing project conventions.
- Do not modify unrelated files.
- Do not hardcode secrets or environment-specific paths.
- Keep implementation, tests, and documentation consistent.

## Testing workflow

For large or medium module changes, design the test plan before implementation.

The main agent is responsible for:
- understanding the change
- designing the test cases
- deciding what should be tested
- giving a clear testing task to the `Tester` subagent

The `Tester` subagent is responsible only for:
- writing test programs/files
- running the relevant tests
- reporting the results

Do not ask `Tester` to design the testing strategy from scratch.

For small one-off checks, the main agent may run quick commands directly.

## Documentation workflow

For every large or medium change that affects architecture, design, module behavior, API behavior, folder structure, or project progress, call the `doc-writer` subagent after implementation.

Use `doc-writer` to update the relevant documents under `docs/`.

Do not call `doc-writer` for:
- tiny code fixes
- typo fixes
- changes that only affect comments
- changes that only affect documentation
- temporary experiments
- small local-only changes

## Before implementation

For large or medium changes:

1. Read the relevant docs.
2. Summarize the affected modules.
3. Propose a short implementation plan.
4. Design test cases.
5. Implement the change.
6. Give the test plan to `Tester`.
7. Fix issues found by tests.
8. Call `doc-writer` if project docs need updating.

## Final response format

When finishing a task, report:

- files changed
- behavior implemented
- tests run and result
- docs updated, if any
- known limitations or next steps
