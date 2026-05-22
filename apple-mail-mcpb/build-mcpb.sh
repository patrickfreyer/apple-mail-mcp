#!/bin/bash

# Build script for creating Apple Mail MCP Bundle (.mcpb)
# This creates a distributable package for Claude Desktop installation

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
SOURCE_DIR="${SCRIPT_DIR}/../plugin"
BUILD_DIR="${SCRIPT_DIR}/build"
OUTPUT_DIR="${SCRIPT_DIR}/../"
PACKAGE_NAME="apple-mail-mcp"
VERSION=$(grep '"version"' "${SCRIPT_DIR}/manifest.json" | sed -E 's/.*"version": "([^"]+)".*/\1/')

echo -e "${GREEN}Building Apple Mail MCP Bundle v${VERSION}${NC}"
echo "========================================="

# Step 1: Clean build directory
echo -e "\n${YELLOW}Step 1: Cleaning build directory...${NC}"
rm -rf "${BUILD_DIR}"
mkdir -p "${BUILD_DIR}"

# Step 2: Copy manifest.json
echo -e "\n${YELLOW}Step 2: Copying manifest.json...${NC}"
cp "${SCRIPT_DIR}/manifest.json" "${BUILD_DIR}/"

# Step 3: Copy Python source files
echo -e "\n${YELLOW}Step 3: Copying Python source files...${NC}"

# Check if source directory exists
if [ ! -d "${SOURCE_DIR}" ]; then
    echo -e "  ${RED}✗${NC} Source directory not found: ${SOURCE_DIR}"
    exit 1
fi

# Copy the main Python script
if [ ! -f "${SOURCE_DIR}/apple_mail_mcp.py" ]; then
    echo -e "  ${RED}✗${NC} Python script not found: ${SOURCE_DIR}/apple_mail_mcp.py"
    exit 1
fi
cp "${SOURCE_DIR}/apple_mail_mcp.py" "${BUILD_DIR}/"
chmod +x "${BUILD_DIR}/apple_mail_mcp.py"

# Copy requirements.txt
if [ ! -f "${SOURCE_DIR}/requirements.txt" ]; then
    echo -e "  ${RED}✗${NC} requirements.txt not found: ${SOURCE_DIR}/requirements.txt"
    exit 1
fi
cp "${SOURCE_DIR}/requirements.txt" "${BUILD_DIR}/"

# Copy startup wrapper script
echo -e "\n${YELLOW}Step 4: Copying startup wrapper script...${NC}"
if [ ! -f "${SOURCE_DIR}/start_mcp.sh" ]; then
    echo -e "  ${RED}✗${NC} Startup script not found: ${SOURCE_DIR}/start_mcp.sh"
    exit 1
fi
cp "${SOURCE_DIR}/start_mcp.sh" "${BUILD_DIR}/"
chmod +x "${BUILD_DIR}/start_mcp.sh"

# Copy Claude Code workflow skills (mirror plugin/skills for manual install)
echo -e "\n${YELLOW}Step 5: Copying Claude Code workflow skills...${NC}"
if [ -d "${SOURCE_DIR}/skills" ]; then
  mkdir -p "${BUILD_DIR}/skills"
  cp -a "${SOURCE_DIR}/skills/." "${BUILD_DIR}/skills/"
  SKILL_MD_COUNT="$(find "${BUILD_DIR}/skills" -name "SKILL.md" | wc -l | tr -d ' ')"
  echo -e "  ${GREEN}✓${NC} skills/ mirrored (${SKILL_MD_COUNT} SKILL.md files)"
else
  echo -e "  ${YELLOW}⚠${NC} Skills directory missing at ${SOURCE_DIR}/skills — skipping skill bundle"
fi

# Copy MCP Package Directory
echo -e "\n${YELLOW}Step 5b: Copying MCP package directory...${NC}"
if [ -d "${SOURCE_DIR}/apple_mail_mcp" ]; then
    cp -r "${SOURCE_DIR}/apple_mail_mcp" "${BUILD_DIR}/"
    # Remove __pycache__ directories
    find "${BUILD_DIR}/apple_mail_mcp" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    echo -e "  ${GREEN}✓${NC} MCP package directory included"
else
    echo -e "  ${RED}✗${NC} MCP package directory not found: ${SOURCE_DIR}/apple_mail_mcp"
    exit 1
fi

# Copy UI Module
echo -e "\n${YELLOW}Step 5c: Copying UI Module...${NC}"
if [ -d "${SOURCE_DIR}/ui" ]; then
    cp -r "${SOURCE_DIR}/ui" "${BUILD_DIR}/"
    # Remove __pycache__ if exists
    rm -rf "${BUILD_DIR}/ui/__pycache__"
    echo -e "  ${GREEN}✓${NC} UI Module included (MCP Apps dashboard support)"
else
    echo -e "  ${YELLOW}⚠${NC} UI directory not found (optional, skipping)"
fi

# Note: Virtual environment will be created on user's machine during first run
echo -e "\n${YELLOW}Step 6: Skipping venv creation (will be created on user's machine)...${NC}"
echo -e "  ${GREEN}✓${NC} Venv will be initialized automatically on first run using user's Python installation"

# Step 7: Create README
echo -e "\n${YELLOW}Step 7: Creating README...${NC}"
cat > "${BUILD_DIR}/README.md" << 'EOF'
# Apple Mail MCP bundle

Portable Apple Mail MCP server for Claude Desktop **plus** a mirrored **`skills/`** tree copied from [`plugin/skills`](https://github.com/patrickfreyer/apple-mail-mcp/tree/main/plugin/skills) for Claude Code workflows.

## What is inside this archive

| Path | Role |
|------|------|
| `apple_mail_mcp/` + `apple_mail_mcp.py` | FastMCP tool implementation (**27 tools**) |
| `start_mcp.sh` | Creates `venv/`, installs `requirements.txt`, execs Python entry |
| `requirements.txt` | Runtime Python dependencies |
| `ui/` *(optional)* | MCP Apps dashboard helpers for `inbox_dashboard` |
| `skills/` | Bundled Claude Code skills (`SKILL.md` per subdirectory) |

For grouped tool summaries, see the upstream [`README`](https://github.com/patrickfreyer/apple-mail-mcp#readme).

## Claude Desktop install (.mcpb)

1. Claude Desktop → **Settings → Developer → MCP Servers → Install from file** → choose this `.mcpb`.
2. Approve Automation + Mail Data Access prompts when macOS asks.
3. Populate **Default Mail Account** / **Email Preferences** in the MCP inspector when available.

Prefer **`--draft-safe`** for shared/agent hosts; manifests typically enable it by default — override only deliberately.

## Claude Code skills (manual sync)

Mirror the bundle's `skills/` directory into Claude Code (`~/.claude/skills`):

```
mkdir -p ~/.claude/skills
cp -a skills/. ~/.claude/skills/
```

Skills included (each subfolder owns a `SKILL.md`):

- `apple-mail-operator` — MCP + Mail navigation bootstrap
- `inbox-triage` — 5–10 minute read-first scan
- `email-management` — sustained Inbox Zero umbrella
- `mailbox-taxonomy` — folder taxonomy + noise diagnosis
- `email-archive-cleanup` — staged archive / bulk move / trash with dry runs
- `mail-rules-advisor` — Mail rule/filter proposals (**Mail UI apply only** — no MCP rule API)
- `email-drafting` — compose/reply drafts (`--draft-safe` aware)
- `email-style-profile` — derive voice prefs from Sent mail + `USER_EMAIL_PREFERENCES`
- `email-attachments` — list/save attachments with path safeguards

Also copies `skills/CLAUDE.md` authoring notes — safe to ignore for runtime.

## Operational notes

- Keep **`DEFAULT_MAIL_ACCOUNT`** set when multiple accounts fan out slowly.
- Use narrow `recent_days` / caps before escalating cross-account AppleScript workloads.
- `export_emails`, `save_email_attachment`, compose send paths imply disk or dispatch risk — preview + confirm.

Support & source: https://github.com/patrickfreyer/apple-mail-mcp
EOF

# Step 7: Create the MCPB package
echo -e "\n${YELLOW}Step 7: Creating MCPB package...${NC}"
cd "${BUILD_DIR}"
OUTPUT_FILE="${OUTPUT_DIR}/${PACKAGE_NAME}-v${VERSION}.mcpb"

# Create zip archive with .mcpb extension
zip -r -q "${OUTPUT_FILE}" . -x "*.DS_Store" "*__MACOSX*" "*.git*"

# Step 8: Verify package
echo -e "\n${YELLOW}Step 8: Verifying package...${NC}"
if [ -f "${OUTPUT_FILE}" ]; then
    FILE_SIZE=$(du -h "${OUTPUT_FILE}" | cut -f1)
    echo -e "  ${GREEN}✓${NC} Package created successfully"
    echo -e "  ${GREEN}✓${NC} Size: ${FILE_SIZE}"
    echo -e "  ${GREEN}✓${NC} Location: ${OUTPUT_FILE}"

    # List contents summary
    echo -e "\n  Package contents:"
    unzip -l "${OUTPUT_FILE}" | head -20
else
    echo -e "  ${RED}✗${NC} Failed to create package"
    exit 1
fi

# Step 9: Clean up
echo -e "\n${YELLOW}Step 9: Cleaning up...${NC}"
rm -rf "${BUILD_DIR}"

echo -e "\n${GREEN}=========================================${NC}"
echo -e "${GREEN}Build completed successfully!${NC}"
echo -e "\nPackage created: ${GREEN}${OUTPUT_FILE}${NC}"
echo -e "\n${YELLOW}Installation Instructions:${NC}"
echo -e "\n${GREEN}Step 1: Install MCP in Claude Desktop${NC}"
echo -e "  1. Open Claude Desktop settings"
echo -e "  2. Navigate to Developer > MCP Servers"
echo -e "  3. Click 'Install from file' and select the .mcpb file"
echo -e "  4. Grant Mail.app permissions when prompted"
echo -e "  5. Restart Claude Desktop"
echo -e "\n${GREEN}Step 2: Copy bundled skills to Claude Code (optional)${NC}"
echo -e "  ${YELLOW}unzip -q \"${OUTPUT_FILE}\" -d /tmp/am-mcp${NC}"
echo -e "  ${YELLOW}mkdir -p \"$HOME/.claude/skills\"${NC}"
echo -e "  ${YELLOW}cp -a /tmp/am-mcp/skills/. \"$HOME/.claude/skills/\"${NC}"
echo -e "\n${GREEN}What ships:${NC}"
echo -e "  FastMCP server with ${GREEN}27${NC} tools + mirrored plugin workflow skills/"
echo -e "\nUpstream docs: https://github.com/patrickfreyer/apple-mail-mcp#readme"
