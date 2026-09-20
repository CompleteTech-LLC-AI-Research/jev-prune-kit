# Repository Guidelines

## Project Structure & Module Organization

`jev_prune/` contains the Python runtime: snapshot selection and projection in `core.py`, bounded transport in `client.py`, the stdio worker, decision gate, installer, and filesystem utilities. `adapters/` holds Pi/OpenCode JavaScript modules, their shared bridge, and the Hermes Python adapter. Tests and fixtures live in `tests/`; offline examples live in `examples/`. Read `docs/` for compatibility, security, validation limits, and the native contract. `install.py` and `runner.py` are local entry points.

## Build, Test, and Development Commands

Use Python 3.10+ and Node.js; runtime code needs no third-party dependencies. Run from the repository root:

- `python3 -m unittest discover -s tests -v` — run Python tests.
- `node --test tests/native.test.mjs` — test adapters and the real Python worker. Set `PYTHON_BINARY` to the desired interpreter if needed.
- `python3 runner.py inspect examples/pi-snapshot.json` — inspect fabricated data without network calls.
- `python3 examples/gate_demo.py --choice prune` — exercise the offline decision-gate demo.
- `python3 install.py --all` — preview installation without writes.
- `python3 build_release.py` — generate the self-contained installer and source ZIP in the repository's parent directory.

On Windows, substitute `py -3` for `python3`.

## Coding Style & Naming Conventions

Follow surrounding code: four-space Python indentation, two-space JavaScript indentation, Python `snake_case` functions, `PascalCase` classes, and JavaScript `camelCase` functions. Use `.mjs` ES modules and Node built-ins. Preserve the dependency-free runtime. No formatter or linter is configured; avoid unrelated formatting changes.

## Testing Guidelines

Python uses `unittest` with `test_*.py` files and `test_*` methods; JavaScript uses `node:test`. Add regression coverage for changed behavior, especially stale receipts, transcript preservation, installer ownership, and adapter failures. Keep routine tests offline with deterministic evaluator fixtures and isolated installation directories. No numeric coverage threshold is configured. Report platform and live-service validation limits explicitly.

## Commit & Pull Request Guidelines

History currently contains only `Initial commit: Jev Prune Kit 0.1.0`; no recurring commit convention is established. Use concise, imperative subjects. PRs should explain the behavior change, link relevant issues, list validation commands/results, and update affected compatibility or security documentation.

## Safety & Configuration

Preserve original transcripts and revalidate receipt proofs before projection. Keep credentials out of source, fixtures, and logs. Remote assessment requires explicit consent and environment configuration described in `docs/SECURITY.md`. Never shut down or terminate the shared WSL VM.
