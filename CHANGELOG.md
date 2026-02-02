# Changelog

## [Unreleased]

### Added
- Settings UI presets plus show-only-overrides toggle and group reset controls in the web UI.
- Settings schema endpoint now emits defaults/current/groupings and field metadata for UI use.
- Deterministic tests for privacy-excluded gating, idle GPU concurrency, settings schema/UI contract, capture status payload, status banner, and SST persistence contracts.
- ADRs for no-holes capture, storage pressure state machine, and foreground gating.

### Changed
- Idle processing now skips derived work for privacy-excluded records and disables VLM when GPU concurrency is set to 0.
- UX facade/schema parity adjustments and blueprint spec updates.
- Removed outdated redteam plan/spec text docs from active docs.

### Fixed
- Preset and quick-toggle config patches now validate `/api/config` responses and surface failures to the UI.
