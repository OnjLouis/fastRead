# FastRead

FastRead is an NVDA add-on for text that changes frequently and needs to be heard immediately.
It is useful for browser dashboards, upload or download speeds, CPU meters, status fields,
terminal output, progress text, and similar live readouts.

Press `NVDA+Y` to toggle monitoring. When FastRead detects a change, it cancels the previous
FastRead message and speaks the newest text straight away.

## Behaviour

- Browsers and browse mode: follows the current line exposed by NVDA's browse/application cursor and speaks the useful changed text.
- Terminals and command output: speaks newly added text where possible, including interrupting live output in NVDA live-text terminals such as PuTTY.
- Focused controls: watches the focused control when no browse-mode document is active.

FastRead monitors one active item at a time and avoids reading entire browser documents.

## Watcher Slots

FastRead can also pin up to three watched items or lines in the same window.
This is useful when a value changes somewhere else while you move focus, such as a price
changing while you alter options on a web page.

- `NVDA+8`: read watcher 1. Press twice quickly to set it if empty, or clear it if already set.
- `NVDA+9`: read watcher 2. Press twice quickly to set it if empty, or clear it if already set.
- `NVDA+0`: read watcher 3. Press twice quickly to set it if empty, or clear it if already set.

Watchers can be set, read, or cleared while FastRead is off. They only speak automatically
while FastRead is on, and automatic watcher speech is queued politely after FastRead's own
change announcement.

## Updates and Source Code

FastRead uses NVDA's add-on update channel for store-compatible updates.
Repository: <https://github.com/OnjLouis/fastRead>

## Changes

- 1.0.3: Added three watcher slots with `NVDA+8`, `NVDA+9`, and `NVDA+0` for pinned values in the current window.
- 1.0.2: Aligned update handling with NVDA Add-on Store distribution.
- 1.0.1: Improved support for NVDA live-text terminals such as PuTTY.
- 1.0.0: Initial release.
