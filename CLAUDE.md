# CLAUDE.md

This file provides guidance to AI assistants working with this repository.

## Repository Overview

A beginner-level JavaScript learning repository with three standalone scripts demonstrating core JavaScript concepts. There are no build tools, package managers, frameworks, or dependencies.

## File Structure

```
playground/
├── hello.js.    # Hello World - console output demo (note the trailing dot in filename)
├── math.js      # Function definition and arithmetic
├── todo.js      # Array manipulation and string operations
└── CLAUDE.md    # This file
```

## Source Files

### `hello.js.` (note trailing dot)
Single-line script printing "Hello, world!" to stdout. The trailing dot in the filename is intentional — do not rename it.

### `math.js`
Defines an `add(a, b)` function and logs the result of `add(23, 56)`. Demonstrates basic function declaration and invocation.

### `todo.js`
Demonstrates array operations:
- Array literal initialization
- `Array.push()` to append items
- Index assignment to mutate items
- `console.log()` for output

## Running the Code

No installation required. Run any file directly with Node.js:

```bash
node hello.js.
node math.js
node todo.js
```

## Development Conventions

- **Language**: Vanilla JavaScript (no TypeScript, no transpilation)
- **Runtime**: Node.js (no browser-specific APIs used)
- **Style**: No linter or formatter is configured; follow the existing style in each file (2-space indentation, no semicolons in `math.js`, semicolons present in `todo.js`)
- **No dependencies**: Do not add `package.json` or npm packages unless explicitly requested
- **No framework**: Keep scripts standalone and self-contained

## Git Workflow

- Default branch: `main` (remote), `master` (local alias)
- Feature branches follow the pattern: `claude/<description>-<id>`
- Commit messages are short and descriptive (e.g., "Added celebration todo", "Initial commit with hello, math, todo files")
- There are no pre-commit hooks, CI checks, or required reviewers

## Testing

No test framework is configured. To verify a script works, run it with `node <filename>` and inspect stdout.

## What Not to Do

- Do not rename `hello.js.` — the trailing dot is part of the filename as committed
- Do not add a build step, bundler, or transpiler unless explicitly asked
- Do not create a `package.json` unless explicitly asked
- Do not add linting or formatting config unless explicitly asked
