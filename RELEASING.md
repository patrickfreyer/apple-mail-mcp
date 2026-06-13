# Releasing `mcp-apple-mail`

Releases are published to PyPI automatically by GitHub Actions using **PyPI
Trusted Publishing** (OIDC). No API tokens are stored anywhere.

## Background — why this exists

The `2.2.0` PyPI wheel shipped without the `apple_mail_mcp/` package (dist-info
only), so `uvx mcp-apple-mail` failed with `ModuleNotFoundError`. The fix landed
in the `3.1.x` line but was only ever **git-tagged, never uploaded** — PyPI sat
on the broken `2.2.0` for months. This automation makes "tagged but not shipped"
impossible: the same tag that marks a release also triggers the publish.

## One-time setup (do this once, on PyPI)

The release workflow can't publish until PyPI trusts it. Configure the trusted
publisher:

1. Sign in to <https://pypi.org> as the `mcp-apple-mail` project owner.
2. Go to the project: **Your projects → mcp-apple-mail → Settings → Publishing**
   (`https://pypi.org/manage/project/mcp-apple-mail/settings/publishing/`).
3. Under **Add a new trusted publisher → GitHub**, enter exactly:
   - **Owner:** `patrickfreyer`
   - **Repository name:** `apple-mail-mcp`
   - **Workflow name:** `release.yml`
   - **Environment name:** `pypi`
4. Save.

> The `environment name` must be `pypi` to match `environment: name: pypi` in
> `.github/workflows/release.yml`. Optionally add a GitHub environment protection
> rule (Settings → Environments → `pypi` → required reviewers) so a release
> pauses for manual approval before the upload step.

## Cutting a release

1. Make sure `main` is green (CI builds the wheel and runs `verify_wheel.py`).
2. Bump the version in **all** tracked files (they must agree — CI enforces it):
   - `pyproject.toml`
   - `server.json` (two places: top-level and `packages[0].version`)
   - `apple-mail-mcpb/manifest.json`
   - `plugin/apple_mail_mcp/__init__.py`

   Then confirm:
   ```bash
   python scripts/check_versions.py
   ```
3. Update `CHANGELOG.md` with the new version section.
4. Merge to `main`, then tag and push:
   ```bash
   git tag v3.1.7
   git push origin v3.1.7
   ```
5. The **Release** workflow runs automatically and does three things:
   - checks the tag matches the version, builds, runs `verify_wheel.py`, and
     **publishes to PyPI**;
   - builds the **`.mcpb` bundle** (`apple-mail-mcpb/build-mcpb.sh`), verifies it
     contains the `apple_mail_mcp` package, and **creates the GitHub Release with
     the bundle attached** (notes pulled from `CHANGELOG.md` via
     `scripts/extract_changelog.py`).
6. Confirm: `uvx mcp-apple-mail` (or `pip install -U mcp-apple-mail`) pulls the
   new version and starts cleanly, and the GitHub Release has the `.mcpb` asset.

> No manual `.mcpb` build or release upload is needed — the tag drives all of it.

## Verifying a build locally (before tagging)

```bash
python -m build
python scripts/verify_wheel.py        # structure + clean-venv install + entry point
unzip -l dist/*.whl                    # eyeball: must list apple_mail_mcp/ files
```

A healthy wheel is a few hundred KB. A ~6 KB wheel is the broken "dist-info only"
shape — do not publish it.

## Package naming (important)

This project's PyPI distribution is **`mcp-apple-mail`**. The import package is
`apple_mail_mcp` and the console script is `mcp-apple-mail`. These are correct
and consistent — do **not** rename to `apple-mail-mcp`, which is an unrelated
package by a different author already on PyPI.
