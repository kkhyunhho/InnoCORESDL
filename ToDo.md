# ToDo.md

Append-only task log per CommonClaude §4 Task Management. Never delete or
rewrite past entries; only add new tasks below and flip checkboxes.

---

## 2026-07-03 — Add vendor submodules & apply CommonClaude repo-wide

- [x] Add `vendor/CommonClaude`, `vendor/HotplateController`,
      `vendor/SmartPlugController` as git submodules.
- [x] Copy CommonClaude hooks + `settings.json` into `.claude/`
      (added a `vendor/` skip to the ruff post-write hook).
- [x] Update `CLAUDE.md`: Conventions section now defers to
      `vendor/CommonClaude`, new Hooks section, Files table rows.
- [x] Scaffold `ToDo.md` and `claude_test/README.md`.
- [ ] Register a GitHub issue via `gh issue create` (pending user
      confirmation / gh auth).

## 2026-07-03 — Register CommonClaude §7 MCP servers

- [x] Install runtimes in the container: `uv`/`uvx` 0.11.26
      (symlinked into `/usr/local/bin`), Node 18.19 + npm (apt).
- [x] Write project-scope `.mcp.json` with **serena**, **context7**,
      and **fetch**, per CommonClaude §7.3.
- [x] Handshake-test each server over stdio (JSON-RPC `initialize`).
- [ ] Persist `jq`, `ruff`, `uv`, and Node into the container image /
      setup script so they survive a rebuild.

## 2026-07-03 — demo_scenario: motor + hotplate/plug + syringe demo

- [x] Create `demo_scenario/` package: `main.py` holds only the
      scenario flow; `devices.py` holds all open/cleanup plumbing
      (context managers) over the vendored drivers.
- [x] Scenario order (user-specified): motor home → down
      `MOTOR_DOWN_MM`; plug ON + hotplate 30 °C for 1 min; syringe
      5 µL dispense (valve ports 2→1, M05 90° rule); motor to origin;
      heater + plug OFF together.
- [x] Add `ika>=2.0` and `python-kasa>=0.7` to `requirements.txt`.
- [x] `ruff check` / `ruff format --check` pass on `demo_scenario/`
      (and all non-vendor code).
- [x] Register a GitHub issue via `gh issue create` — issue #1
      (user authenticated gh; repo Issues feature was disabled,
      enabled via `gh api`).
- [ ] Bench validation on real devices: confirm single-motor "down"
      direction (flip `coord_invert` if reversed), plug credentials
      in `vendor/SmartPlugController/secure.env`.
