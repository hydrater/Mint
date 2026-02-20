# Mint

Mint is a Python CLI for running a Google Sheets-driven task pipeline.

It reads tasks from a sheet, runs your configured agent command, writes status/output back to the sheet, and archives approved work.

---

## Features

- Google Sheets as the single task board
- CLI-first workflow (`mint`, `mint run`, `mint init`, `mint setup`, `mint doctor`)
- Configurable command and prompt prefix from sheet or local config
- Resume support for ongoing tasks using stored session id
- Automatic archiving of approved tasks (J/K/L)
- Runtime sheet formatting enforcement:
  - B, F wrap
  - J, K, L clip (no spill)
  - A, F top-aligned
  - L normalized to one line for archived output
- Local config sync from sheet config block when running `mint`

---

## Requirements

- Python 3.10+
- An installed AI agent CLI command (configured in A5 / `sheet_properties.command`)
- A Google Cloud service account JSON key with Sheets API access
- A Google Sheet shared with that service account email

---

## Installation

```cmd
cd C:\path\to\Mint
pip install -e .
```

After installation, `mint` is available from CMD.

---

## Quick Start

### 1) Configure credentials

```cmd
mint setup google
```

Paste your service-account JSON, then type `END` on a new line.

### 2) Initialize your sheet

```cmd
mint init https://docs.google.com/spreadsheets/d/<ID>/edit
```

`init` creates `config.json` if it does not exist, writes the sheet layout, and sets the default sheet URL.

### 3) Set runtime properties in the sheet

In Column A:

- A3 = Prefix
- A5 = Command
- A7 = Auto Close (`true`/`false`)

You can still use `mint setup prefix|command|auto_close` if you prefer CLI editing.

### 4) Run

```cmd
mint
```

When you run `mint`, it also reads A3/A5/A7 from the spreadsheet and saves them into local `config.json`.

---

## Command Reference

### `mint` (no args)

Equivalent to `mint run`.

### `mint run [sheet_url]`

- Uses provided URL, else `defaults.sheet_url` from `config.json`
- Syncs config properties from sheet (Column A block) into local config
- Enforces runtime sheet formatting rules
- Processes tasks from row 2 downward
- Stops when Column B is empty

### `mint init <sheet_url>`

Initializes an existing sheet:
- writes headers (A1:L1)
- freezes row 1
- writes config block in Column A
- applies status dropdown in Column D
- applies formatting rules

Also creates `config.json` if missing and updates `defaults.sheet_url` in local config.

### `mint setup <target> [value]`

Targets:

- `google` – paste service-account JSON
- `prefix` – text prepended to prompts
- `command` – executable command used for task runs
- `auto_close` – `true` / `false`
- `sheet` – default Google Sheet URL
- `list` – print targets

Examples:

```cmd
mint setup list
mint setup prefix "[Mint] "
mint setup command "your-agent-command"
mint setup auto_close false
```

### `mint doctor [sheet_url]`

Checks:
- config file presence/validity
- service-account availability
- credential usability
- sheet accessibility (if URL is available)
- configured command and auto_close state

### `mint config`

Opens project `config.json`.

---

## Google Sheet Layout

### Headers (Row 1)

- A: Configs
- B: User Prompt
- C: Ticket Summary
- D: Status
- E: User Input
- F: AI Thoughts / Output
- G: Session ID
- J: Approved Tickets
- K: Original Prompt
- L: Final Thoughts

### Column ownership matrix

| Column | Meaning | Updated by |
|---|---|---|
| A | Config labels + values (Prefix, Command, Auto Close) | User and Mint (`init`, config sync on `mint`) |
| B | User prompt/task request | User |
| C | Ticket summary | Mint |
| D | Task status (`Ongoing`, `Testing`, `Blocked`, `Completed`, `Approved`) | Mint and User |
| E | Extra user input for resume/follow-up | User |
| F | Latest AI thoughts/output | Mint |
| G | Session ID for resume | Mint |
| J | Archived ticket summary | Mint (when status becomes `Approved`) |
| K | Archived original prompt (from B) | Mint (when status becomes `Approved`) |
| L | Archived final thoughts (from F, single-line) | Mint (when status becomes `Approved`) |

### Config Block (Column A)

- A2: `Prefix`
- A3: value
- A4: `Command`
- A5: value
- A6: `Auto Close`
- A7: `true` / `false`

### Status values (Column D dropdown)

- Ongoing
- Testing
- Blocked
- Completed
- Approved

### Row status lifecycle

Each task row is controlled by Column D:

- **Ongoing**
  - Used when a task is actively being worked on.
  - New tasks are automatically set to `Ongoing` after Mint writes a summary to Column C.
  - On the next run, Mint can continue the row using Column G (session id) and Column E (user input).

- **Testing**
  - Means the task needs user testing/verification.
  - Row remains in place and can be updated by the user.

- **Blocked**
  - Means user intervention is needed (missing input, environment issue, permission issue, etc.).
  - Row remains in place until unblocked.

- **Completed**
  - Means implementation is done.
  - Row remains in place until explicitly approved.

- **Approved**
  - Signals that the ticket is ready to archive.
  - On the next `mint` run, Mint archives it automatically (see below).

---

## Processing Rules

For each row starting at 2:

1. If Column B is empty: stop scanning.
2. If status is `Approved`: archive the row and shift queue rows upward.
3. If Column C is empty:
   - generate summary into C
   - set D to `Ongoing`
   - run command with prefixed prompt from B
   - write status/thoughts/session to D/F/G.
4. If status is `Ongoing`:
   - resume using G (session id)
   - use Column E as resume prompt (fallback to B if E is empty)
   - write status/thoughts/session to D/F/G.
5. Rows in `Testing`, `Blocked`, or `Completed` are preserved and not auto-archived.

### Archiving behavior

To archive a task:

1. Set Column D to `Approved`.
2. Run `mint`.

Mint will:

- move Column C (ticket summary) to Column J
- move Column B (original prompt) to Column K
- move Column F (final thoughts/output) to Column L
- flatten Column L into a single line
- clear B:G for the approved row
- shift subsequent B:G rows up by one (queue compaction), stopping at the first empty row

---

## Configuration File (`config.json`)

Default shape:

```json
{
  "apis": {
    "google_service_account_file": "",
    "google_service_account_json": {}
  },
  "sheet_properties": {
    "prefix": "",
    "command": "",
    "auto_close": true
  },
  "defaults": {
    "sheet_url": ""
  }
}
```

When running `mint`, sheet properties are synced from Column A into `sheet_properties`.

---

## Development

```cmd
python -m compileall mint
```

Optional health check:

```cmd
mint doctor
```

---

## License

This project is licensed under the **MIT License**. See [LICENSE](LICENSE).
