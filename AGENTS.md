# Agent instructions

- Static browser app: laboratory, configuration, installation and bilingual guides.
- Source guides live in docs/en and docs/it; shared assets in docs/assets.
- Build with python build_site.py; public output is _site/ only.
- English default, reversible EN/IT UI translation in i18n/. Never translate data,
  protocol payloads, input values, technical logs or user-entered recordings.
- Preserve acquisition/reception times and signal/upstream-filter metadata.
- Keep numerical filtering and audio independent from plotting and translation.
- Run python verify.py for functional changes. Tests are host/API doubles unless stated.
- Device access, firmware writes and Pages deployment require explicit user actions.
- Never publish private captures, device bonds, credentials, backups or personal paths.
- Live/Record and experiment-panel redesign are deferred in ROADMAP.md.
