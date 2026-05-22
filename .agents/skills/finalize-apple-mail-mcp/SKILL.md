---
name: finalize-apple-mail-mcp
description: Final codebase review and doc/manifest sync for apple-mail-mcp after feature work. Runs pytest and validate_manifests, updates CLAUDE.md hubs, README, docs, plugin skills, and MCPB manifests, then commits and pushes when the user asks. Use when finishing a change, before release, when the user says finalize, sync docs, update manifests, or ship the branch.
---

# Finalize apple-mail-mcp

Run this **after implementation is done** and before calling the branch finished. Orchestrate with subagents; do not solo large doc/manifest sweeps.

## When to use

- User finished a feature/fix and wants docs, guides, and manifests aligned
- User says: finalize, ship, sync docs, update CLAUDE.md, validate manifests, pre-release check
- Before opening a PR or tagging a release

## Out of scope

- New feature implementation
- Version bump across five files unless user explicitly requests a release
- Force push or amending pushed commits

## Workflow

Copy and track:

```
Finalize progress:
- [ ] 1. Understand the diff (what changed, why)
- [ ] 2. Code + tests verified
- [ ] 3. Docs, CLAUDE.md, skills, manifests synced
- [ ] 4. Expert validation (plugin-validator, skill-reviewer if skills touched)
- [ ] 5. Commit (only if user asked)
- [ ] 6. Push (only if user asked)
```

### 1. Scope the change

```bash
git status
git log --oneline -5
git diff main...HEAD --stat
```

Identify touched areas: `plugin/apple_mail_mcp/tools/`, `plugin/skills/`, `tests/`, manifests, `README.md`, `docs/`.

### 2. Verify code (delegate to `shell` subagent)

From repo root with `.venv/`:

```bash
.venv/bin/pytest tests/ -q
bash tools/validate_manifests.sh
.venv/bin/pytest tests/test_validate_manifests.py tests/test_wrapper_surface.py -q
```

Optional when tools or CLI changed:

```bash
bash tools/pre-commit-validate.sh
.venv/bin/apple-mail quick-check --json   # live Mail smoke (~30s)
```

All must pass before doc/manifest claims are updated.

### 3. Sync documentation (delegate to `generalPurpose` subagent)

Update **only** what the code change affects. Do not rewrite unrelated files.

| If you changed… | Update |
|-----------------|--------|
| MCP tools (`@mcp.tool`, params, defaults) | `plugin/apple_mail_mcp/tools/CLAUDE.md`, tool docstrings, `README.md` tool table, `docs/CLAUDE-conventions.md`, `apple-mail-mcpb/manifest.json` `tools[].description` |
| Plugin wiring / flags | `plugin/CLAUDE.md`, `plugin/apple_mail_mcp/CLAUDE.md`, `README.md` Configuration |
| Agent workflows | `plugin/skills/*/SKILL.md`, `plugin/skills/CLAUDE.md`, `docs/CLAUDE.md` skill map |
| Test count | Root `CLAUDE.md`, `README.md`, any doc citing test totals — run `pytest tests/ --collect-only -q` for count |
| Tool count | Five version files only on release; always sync **claims**: `grep -c '^@mcp.tool' plugin/apple_mail_mcp/tools/*.py` vs `plugin.json`, marketplace, MCPB `tools[]` |

**CLAUDE.md hubs to spot-check** (stale cross-links or wrong counts):

- `CLAUDE.md` (root)
- `plugin/CLAUDE.md`, `plugin/apple_mail_mcp/CLAUDE.md`, `plugin/apple_mail_mcp/tools/CLAUDE.md`
- `plugin/skills/CLAUDE.md`, `tests/CLAUDE.md`, `tools/CLAUDE.md`, `docs/CLAUDE.md`
- `.claude-plugin/CLAUDE.md`, `apple-mail-mcpb/CLAUDE.md`, `tasks/CLAUDE.md`

**Manifest rules** (see `tools/CLAUDE.md`):

- Versions: `pyproject.toml`, `plugin/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` `plugins[0].version`, `server.json`, `apple-mail-mcpb/manifest.json`
- Do **not** bump `metadata.version` in marketplace.json
- MCPB `tools[]` names must match registered tool function names

### 4. Expert passes (required for plugin work)

| Expert | When |
|--------|------|
| `plugin-dev:plugin-validator` | Any manifest, tool count, marketplace, or MCPB change |
| `plugin-dev:skill-reviewer` | Any `plugin/skills/*/SKILL.md` edit |

Fix blockers before commit.

### 5. Final review checklist

- [ ] Behavior described in docs matches `compose.py` / other tool defaults
- [ ] No stale "open by default" or subject-matching guidance where `message_id` is preferred
- [ ] `email-drafting` and `apple-mail-operator` skills agree with README draft-safe section
- [ ] No secrets or local paths committed
- [ ] Unrelated dirty files left unstaged

### 6. Commit and push (user must ask)

**Commit** only when the user explicitly requests it. Stage focused paths; do not sweep unrelated WIP.

```bash
git add <relevant paths>
git commit -m "$(cat <<'EOF'
<1-2 sentences: why, not what>

EOF
)"
```

**Push** only when the user explicitly requests it:

```bash
git push -u origin HEAD
```

Use `gh pr create` only when the user asks for a PR.

## Release note

If shipping a version bump, bump all five version files together (root `CLAUDE.md` § Version bump), re-run `validate_manifests.sh`, rebuild MCPB if needed (`apple-mail-mcpb/CLAUDE.md`).

## Additional resources

- Deep conventions: [docs/CLAUDE-conventions.md](../../docs/CLAUDE-conventions.md)
- Live verification: [docs/AGENT_LIVE_TESTING.md](../../docs/AGENT_LIVE_TESTING.md)
