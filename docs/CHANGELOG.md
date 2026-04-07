# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Phase 2 – Safe Improvements] — 2026-03-05

### Added
- `notes/nse_holidays.json` — 15 official NSE 2026 holidays; powers `trading_calendar.py` business-day logic.
- `make_page_diag_block()` factory in `utils.py` — canonical page diagnostics context manager.

### Changed
- `data_fetch.py`: Removed `logging.basicConfig()` that overrode app-level logging.
- `config.py`: Converted remaining 4 `print()` statements to `_log.warning()` / `_log.info()`.
- `NSE_Config.py`: Converted 5 `print()` statements to `_log.info()` / `_log.warning()`.
- `README.md`: Full rewrite — now documents all 16 pages, current project structure, all data sources.
- `pages/5_Trading_Journal.py`: Replaced local `page_diag_block` with canonical `make_page_diag_block` import.
- `pages/7_Portfolio_Risk.py`: Same — replaced local `page_diag_block` with canonical import.

### Removed
- `qodana.yaml` — unused placeholder file.
- `venv/` — redundant 12MB empty venv alongside active `.venv/` (492MB).

## [Phase 1 – Cleanup] — 2026-03-05

### Added
- `responsive_cols()` canonical helper in `utils.py` — replaces 11 page-local duplicates.
- `compact_table()` canonical helper in `utils.py` — replaces 2 page-local duplicates.
- `docs/CODE_MANIFEST.md` — full file-by-file inventory of the project.
- `docs/DECISIONS.md` — 8 Architecture Decision Records.
- `docs/HANDOVER.md` — onboarding guide for new developers.
- This `docs/CHANGELOG.md`.

### Changed
- `config.py`: Replaced bare `print()` on import with `logging.warning()`.
- `watchlist_manager.py`: Removed `logging.basicConfig()` that overrode app-level logging.
- `requirements.txt`: Populated with actual project dependencies (was only `python-dotenv`).
- Moved `CHANGELOG.md`, `CODE_MANIFEST.md`, `DECISIONS.md`, `HANDOVER.md` from root → `docs/`.

### Removed
- Duplicate `_responsive_cols` definitions from 11 page files (2, 4, 6, 8, 9, 10, 11, 12, 13, 15).
- Duplicate `_compact_table` definitions from 2 page files (9, 11).
- 3 orphaned debug scripts: `scripts/check_vwap.py`, `scripts/check_yf_columns.py`, `scripts/diagnose.py`.

### Fixed
- `config.py` no longer prints to stdout on import.
- `watchlist_manager.py` no longer overrides root logger configuration.

