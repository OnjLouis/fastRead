# FastRead

FastRead is an NVDA add-on for text that changes frequently and needs to be heard immediately.
It is useful for browser dashboards, upload or download speeds, CPU meters, status fields,
terminal output, progress text, and similar live readouts.

Press `NVDA+Y` to toggle monitoring. When FastRead detects a change, it cancels the previous
FastRead message and speaks the newest text straight away.

## Behaviour

- Browsers and browse mode: speaks the full changed value from the current line.
- Terminals and command output: speaks newly added text where possible.
- Focused controls: watches the focused control when no browse-mode document is active.

FastRead monitors one active item at a time and avoids reading entire browser documents.

## Updates

FastRead checks GitHub releases for updates while it is not distributed through the NVDA Add-on Store.

Repository: <https://github.com/OnjLouis/fastRead>
