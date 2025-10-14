# Changelog

All notable changes to the Apple Mail MCP Server will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

- **v1.3.0** - Major feature expansion (8 new tools: search, status, trash, forward, threads, drafts, statistics, export)
- **v1.2.0** - Enhanced overview with email preview
- **v1.1.0** - Added inbox overview dashboard
- **v1.0.0** - Initial release with core functionality

## Upgrade Notes

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
