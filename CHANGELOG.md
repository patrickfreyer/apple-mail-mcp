# Changelog

All notable changes to the Apple Mail MCP Server will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.5.1] - 2026-02-07

### Changed
- **search_emails**: Replaced per-message iteration with AppleScript `whose` clause for app-level filtering
- **search_by_sender**: Replaced per-message iteration and `lowercase()` shell handler with `whose` clause
- **get_recent_from_sender**: Replaced per-message iteration and `lowercase()` shell handler with `whose` clause
- **get_newsletters**: Replaced per-message iteration and `lowercase()` shell handler with `whose date received` pre-filter
- **get_statistics**: Added `whose` clause pre-filtering for `account_overview` and `sender_stats` scopes

### Fixed
- **get_newsletters**: Fixed timeout on large mailboxes by adding `whose date received > cutoffDate` pre-filter instead of iterating all messages
- **get_statistics**: Fixed "missing value" error by adding per-mailbox `try/on error` and skipping system folders (Trash, Junk, Sent, Drafts, etc.)
- **get_statistics**: Added division-by-zero guard for percentage calculations when no emails match

### Performance
- Eliminated `do shell script` subprocess spawning per message for case-insensitive sender matching (`lowercase()` via `tr`) — AppleScript's `contains` is already case-insensitive
- Search filtering now happens at the Mail.app level instead of iterating every message in Python/AppleScript loops
- Date filtering in `search_emails` uses programmatic date construction (locale-independent) instead of string-based date parsing
- `get_newsletters` now pre-filters by date at the Mail.app level, reducing iteration from ~25K messages to ~200 (last 7 days)
- `get_statistics` scopes skip system folders and use `whose` clause date/sender pre-filtering

### Technical
- Added per-mailbox `try/on error` blocks to gracefully skip smart mailboxes and missing-value errors
- `has_attachments` filter retained as post-filter (not supported in `whose` clauses)
- Newsletter sender pattern matching (17 OR conditions) retained as post-filter — too complex for a single `whose` clause
- No tool signature changes — fully backward compatible

## [1.5.0] - 2026-02-01

### Added
- **search_by_sender**: Find emails from a specific sender across mailboxes
  - Search by sender email address or name
  - Configurable mailbox scope (specific or all)
  - Returns matching emails with subject, date, and read status

- **search_all_accounts**: Cross-account search with advanced filtering
  - Search across all configured email accounts
  - Date range filtering support
  - Configurable sorting options
  - Unified results from multiple accounts

- **search_email_content**: Full-text search in email bodies
  - Search within email message content
  - Find emails containing specific text or phrases
  - Searches both plain text and HTML content

- **get_newsletters**: Find newsletter and subscription emails
  - Identifies newsletter/subscription patterns
  - Filters promotional and mailing list emails
  - Helps manage subscriptions and bulk mail

### Changed
- Updated manifest to include 4 new search tools (total: 24 tools)
- Enhanced search capabilities across the server

### Technical
- Improved search performance for large mailboxes
- Added missing value error handling for mailbox searches

## [1.4.0] - 2025-10-14

### Added
- **User Preferences Configuration**: New configurable preference string in MCPB user_config
  - Allows users to set personal email preferences (default account, max emails, preferred folders, etc.)
  - Preferences automatically injected into all tool descriptions
  - Helps Claude understand user workflow and make context-aware decisions
  - Configurable via Claude Desktop UI for .mcpb installations
  - Environment variable support for manual installations (USER_EMAIL_PREFERENCES)

### Changed
- Updated manifest.json to include user_config section (version 1.4.0)
- Enhanced all 20 tool functions with @inject_preferences decorator
- Updated README.md with comprehensive configuration documentation

### Technical
- Added environment variable loading at server startup
- Implemented decorator pattern for dynamic docstring injection
- Zero-config default behavior maintained (preferences optional)

## [1.3.0] - 2025-10-14

### Added
- **search_emails**: Advanced unified search tool with multi-criteria filtering
  - Search by subject keyword, sender, attachment presence, read status
  - Date range filtering (date_from, date_to)
  - Search across all mailboxes or specific mailbox
  - Optional content preview with configurable max results

- **update_email_status**: Batch email status management
  - Actions: mark_read, mark_unread, flag, unflag
  - Search by subject keyword or sender
  - Safety limit on updates (default: 10)

- **manage_trash**: Comprehensive deletion operations
  - Three actions: move_to_trash, delete_permanent, empty_trash
  - Search by subject or sender
  - Safety limits on deletions (default: 5)

- **forward_email**: Email forwarding capability
  - Forward by subject keyword
  - Optional custom message prepended to forwarded content

- **get_email_thread**: Conversation thread view
  - Groups related messages by subject
  - Strips Re:, Fwd: prefixes for proper threading
  - Searches across all mailboxes

- **manage_drafts**: Complete draft lifecycle management
  - Four actions: list, create, send, delete
  - Full composition parameters support (TO, CC, BCC)

- **get_statistics**: Email analytics dashboard
  - Three scopes: account_overview, sender_stats, mailbox_breakdown
  - Metrics: total emails, read/unread ratios, flagged count, top senders
  - Configurable time range

- **export_emails**: Email export functionality
  - Two scopes: single_email, entire_mailbox
  - Export formats: TXT, HTML
  - Configurable save directory

### Changed
- Updated manifest to include all 8 new tools (total: 20 tools)
- Enhanced error handling across all new tools
- Improved AppleScript safety with proper escaping

### Technical
- Added comprehensive tool descriptions in manifest.json
- Implemented safety limits for batch operations
- Added support for nested mailbox paths with "/" separator

## [1.2.0] - 2025-10-14

### Added
- **get_inbox_overview**: Email preview section
  - Shows 10 most recent emails across all accounts
  - Includes subject, sender, date, and read status
  - Provides quick snapshot of recent activity

### Changed
- Enhanced inbox overview to be more comprehensive
- Improved formatting of overview output

## [1.1.0] - 2025-10-14

### Added
- **get_inbox_overview**: Comprehensive inbox dashboard
  - Unread counts by account
  - Mailbox structure with unread indicators
  - AI-driven action suggestions
  - Identifies emails needing action or response

### Changed
- Updated description to highlight overview tool as primary entry point

## [1.0.0] - 2025-10-14

### Added
- Initial release of Apple Mail MCP Server
- Core email reading tools:
  - `list_inbox_emails`: List emails with filtering
  - `get_email_with_content`: Search with content preview
  - `get_unread_count`: Quick unread counts
  - `list_accounts`: List Mail accounts
  - `get_recent_emails`: Recent messages

- Email organization tools:
  - `list_mailboxes`: View folder structure
  - `move_email`: Move between folders

- Email composition tools:
  - `compose_email`: Send new emails
  - `reply_to_email`: Reply to messages

- Attachment management:
  - `list_email_attachments`: View attachments
  - `save_email_attachment`: Download attachments

- MCP Bundle (.mcpb) support with build script
- FastMCP-based implementation
- AppleScript automation for Mail.app
- Comprehensive README documentation
- Example Claude Desktop configuration

### Technical
- Python 3.7+ support
- Virtual environment setup
- Requirements: fastmcp
- MIT License

---

## Version History Summary

- **v1.5.1** - Search performance: whose clause filtering replaces per-message iteration
- **v1.5.0** - Advanced search tools (4 new tools: search_by_sender, search_all_accounts, search_email_content, get_newsletters)
- **v1.4.0** - User preferences configuration
- **v1.3.0** - Major feature expansion (8 new tools: search, status, trash, forward, threads, drafts, statistics, export)
- **v1.2.0** - Enhanced overview with email preview
- **v1.1.0** - Added inbox overview dashboard
- **v1.0.0** - Initial release with core functionality

## Upgrade Notes

### Upgrading to 1.5.0
- No breaking changes
- All existing tools remain compatible
- New search tools available immediately after update
- Rebuild .mcpb bundle to include new tools

### Upgrading to 1.4.0
- No breaking changes
- Optional user preferences configuration available
- Set USER_EMAIL_PREFERENCES environment variable for customization

### Upgrading to 1.3.0
- No breaking changes
- All existing tools remain compatible
- New tools available immediately after update
- Rebuild .mcpb bundle to include new tools

### Upgrading to 1.2.0
- No breaking changes
- Overview tool enhanced with email preview
- No configuration changes required

### Upgrading to 1.1.0
- No breaking changes
- New overview tool recommended as first interaction
- No configuration changes required
