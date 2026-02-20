from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from google.oauth2 import service_account

from .config import (
    config_path,
    ensure_config,
    load_config,
    save_config,
    set_config_value,
)
from .google_sheet import GoogleSheetClient, parse_sheet_id, to_sheet_url
from .pipeline import MintPipeline

GOOGLE_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _project_base_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def _default_service_account_path(cwd: Path) -> Path:
    return cwd / "mint-google-service-account.json"


def _as_bool(value: object, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    return default


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mint",
        description="Mint: Google Sheets multi-agent pipeline runner",
    )
    subparsers = parser.add_subparsers(dest="command_name")

    init_parser = subparsers.add_parser(
        "init",
        help="Initialize an existing Google Sheet by URL.",
    )
    init_parser.add_argument("sheet_url", help="Google Sheet URL.")

    run_parser = subparsers.add_parser(
        "run",
        help="Run pipeline against the provided sheet URL or configured default.",
    )
    run_parser.add_argument("sheet_url", nargs="?", help="Optional Google Sheet URL.")

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Validate config, Google credentials, and sheet access.",
    )
    doctor_parser.add_argument("sheet_url", nargs="?", help="Optional Google Sheet URL.")

    subparsers.add_parser(
        "config",
        help="Open the project config.json file.",
    )

    setup_parser = subparsers.add_parser(
        "setup",
        help="Store API credentials, default link, prefix, and command.",
    )
    setup_parser.add_argument(
        "target",
        choices=[
            "google",
            "prefix",
            "command",
            "auto_close",
            "sheet",
            "list",
        ],
    )
    setup_parser.add_argument("value", nargs="?", help="Value for the selected target.")
    return parser


def _print_setup_hint() -> None:
    print("Set your Google service account first:")
    print("  mint setup google")


def _load_config_or_exit(cwd: Path) -> dict:
    try:
        return load_config(base_dir=cwd)
    except ValueError as exc:
        print(str(exc))
        raise SystemExit(1)


def _read_google_json_input(value: str | None) -> str:
    if value:
        candidate = Path(value).expanduser()
        if candidate.exists():
            return candidate.read_text(encoding="utf-8").strip()
        return value.strip()

    print("Paste Google service-account JSON.")
    print("Type END on a new line when done.")
    lines: list[str] = []
    while True:
        line = input()
        if line.strip() == "END":
            break
        lines.append(line)
    return "\n".join(lines).strip()


def _setup_google_credentials(cfg: dict, cwd: Path, value: str | None) -> int:
    payload = _read_google_json_input(value=value)
    if not payload:
        print("No JSON pasted. Cancelled.")
        return 1

    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON: {exc}")
        return 1

    if not isinstance(parsed, dict) or parsed.get("type") != "service_account":
        print("This does not look like a Google service-account JSON.")
        return 1

    target_path = _default_service_account_path(cwd)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(json.dumps(parsed, indent=2), encoding="utf-8")

    set_config_value(cfg, "apis.google_service_account_json", parsed)
    set_config_value(cfg, "apis.google_service_account_file", str(target_path))
    save_config(cfg, base_dir=cwd)
    print(f"Saved Google service-account file to: {target_path}")
    print(f"Config file: {config_path(cwd)}")
    return 0


def cmd_setup(args: argparse.Namespace, cwd: Path) -> int:
    cfg = _load_config_or_exit(cwd)
    target = args.target
    value = args.value

    if target == "list":
        print("Setup targets:")
        print("  mint setup google  (paste service-account JSON; saved in project folder)")
        print("  mint setup prefix <text>")
        print("  mint setup command <cmd>")
        print("  mint setup auto_close <true|false>")
        print("  mint setup sheet <google-sheet-url>")
        return 0

    if target == "google":
        return _setup_google_credentials(cfg, cwd, value)

    if not value:
        value = input(f"Enter value for '{target}': ").strip()
    if not value:
        print("No value entered. Existing config was kept unchanged.")
        return 1

    mapping = {
        "prefix": "sheet_properties.prefix",
        "command": "sheet_properties.command",
        "auto_close": "sheet_properties.auto_close",
        "sheet": "defaults.sheet_url",
    }

    if target == "auto_close":
        normalized = value.strip().lower()
        if normalized not in {"true", "false"}:
            print("auto_close must be true or false.")
            return 1
        set_config_value(cfg, mapping[target], normalized == "true")
    else:
        set_config_value(cfg, mapping[target], value)
    save_config(cfg, base_dir=cwd)
    print(f"Saved: {mapping[target]}")
    print(f"Config file: {config_path(cwd)}")
    return 0


def cmd_config(cwd: Path) -> int:
    try:
        path = ensure_config(base_dir=cwd, open_in_editor=True)
    except ValueError as exc:
        print(str(exc))
        return 1
    print(f"Opened config: {path}")
    return 0


def _service_account_info_from_config(cfg: dict, cwd: Path) -> dict:
    embedded = cfg.get("apis", {}).get("google_service_account_json")
    if isinstance(embedded, dict) and embedded.get("type") == "service_account":
        return embedded

    configured_path = cfg.get("apis", {}).get("google_service_account_file", "").strip()
    if configured_path:
        candidate = Path(configured_path).expanduser()
    else:
        candidate = _default_service_account_path(cwd)

    if candidate.exists():
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("type") == "service_account":
                # Backfill into config for consistency.
                set_config_value(cfg, "apis.google_service_account_json", data)
                set_config_value(cfg, "apis.google_service_account_file", str(candidate))
                save_config(cfg, base_dir=cwd)
                return data
        except json.JSONDecodeError:
            pass

    raise ValueError("Missing Google service-account JSON. Run: mint setup google")


def _sheet_client_from_service_account(cfg: dict, cwd: Path) -> GoogleSheetClient:
    info = _service_account_info_from_config(cfg, cwd)
    creds = service_account.Credentials.from_service_account_info(info, scopes=GOOGLE_SCOPES)
    return GoogleSheetClient(credentials=creds)


def _sync_sheet_properties_to_local_config(cfg: dict, sheet_properties: dict[str, str]) -> bool:
    local_props = cfg.setdefault("sheet_properties", {})
    changed = False

    for key, incoming in sheet_properties.items():
        if key == "auto_close":
            current = _as_bool(local_props.get(key, True), default=True)
            normalized = _as_bool(incoming, default=current)
        else:
            normalized = str(incoming or "")

        if local_props.get(key) != normalized:
            local_props[key] = normalized
            changed = True

    return changed


def cmd_init(args: argparse.Namespace, cwd: Path) -> int:
    try:
        cfg_path = ensure_config(base_dir=cwd, open_in_editor=False)
    except ValueError as exc:
        print(str(exc))
        return 1
    print(f"Config ready: {cfg_path}")
    cfg = _load_config_or_exit(cwd)

    try:
        client = _sheet_client_from_service_account(cfg, cwd)
    except ValueError:
        _print_setup_hint()
        return 1

    prefix = cfg["sheet_properties"].get("prefix", "")
    command = cfg["sheet_properties"].get("command", "")
    auto_close = _as_bool(cfg["sheet_properties"].get("auto_close", True), default=True)
    property_values = {
        "prefix": prefix,
        "command": command,
        "auto_close": auto_close,
    }

    spreadsheet_id = parse_sheet_id(args.sheet_url)
    try:
        client.verify_access(spreadsheet_id)
        client.initialize_layout(
            spreadsheet_id=spreadsheet_id,
            property_values=property_values,
        )
    except Exception as exc:
        print(str(exc))
        return 1
    cfg["defaults"]["sheet_url"] = to_sheet_url(spreadsheet_id)
    save_config(cfg, base_dir=cwd)
    print(f"Initialized existing sheet: {to_sheet_url(spreadsheet_id)}")
    return 0


def cmd_run(args: argparse.Namespace, cwd: Path) -> int:
    cfg = _load_config_or_exit(cwd)
    sheet_url = args.sheet_url or cfg["defaults"].get("sheet_url", "")
    if not sheet_url:
        print("No sheet URL provided.")
        print("Use: mint <sheet-url> or set one with: mint setup sheet <url>")
        return 1

    print("Mint starting...")

    try:
        client = _sheet_client_from_service_account(cfg, cwd)
    except ValueError:
        _print_setup_hint()
        return 1

    try:
        spreadsheet_id = parse_sheet_id(sheet_url)
        print(f"Using sheet: {to_sheet_url(spreadsheet_id)}")
        sheet_properties = client.get_properties(spreadsheet_id)
        if _sync_sheet_properties_to_local_config(cfg, sheet_properties):
            save_config(cfg, base_dir=cwd)
            print("Synced sheet properties into local config.json.")
        else:
            print("Local config already matches sheet properties.")
        client.enforce_runtime_layout(spreadsheet_id)
        client.normalize_column_l_single_line(spreadsheet_id)
        print("Applied runtime layout rules.")
    except Exception as exc:
        print(str(exc))
        return 1

    pipeline = MintPipeline(sheet_client=client, config=cfg)
    summary = pipeline.run(sheet_url=sheet_url)

    if summary.executed_rows == 0 and summary.archived_rows == 0:
        if summary.stopped_at_row <= 2:
            print("Mint finished: no rows found (Column B is empty at row 2).")
        else:
            print("Mint finished: no runnable rows found.")
        return 0

    print("Mint finished successfully.")
    print(f"- Executed rows: {summary.executed_rows}")
    print(f"- Archived rows: {summary.archived_rows}")
    return 0


def _doctor_check(label: str, passed: bool, details: str) -> None:
    icon = "OK" if passed else "FAIL"
    print(f"[{icon}] {label} - {details}")


def cmd_doctor(args: argparse.Namespace, cwd: Path) -> int:
    cfg = _load_config_or_exit(cwd)
    failures = 0

    cfg_file = config_path(cwd)
    _doctor_check("config", cfg_file.exists(), str(cfg_file))
    if not cfg_file.exists():
        failures += 1

    service_account_json = cfg.get("apis", {}).get("google_service_account_json")
    if isinstance(service_account_json, dict) and service_account_json.get("type") == "service_account":
        _doctor_check("google service account", True, "loaded from config.json")
    else:
        path_hint = cfg.get("apis", {}).get("google_service_account_file", "") or str(
            _default_service_account_path(cwd)
        )
        _doctor_check(
            "google service account",
            False,
            f"missing/invalid in config. Expected service_account JSON. Path hint: {path_hint}",
        )
        failures += 1

    try:
        client = _sheet_client_from_service_account(cfg, cwd)
        _doctor_check("google credentials", True, "service account key is usable")
    except Exception as exc:
        _doctor_check("google credentials", False, str(exc))
        failures += 1
        client = None

    sheet_url = args.sheet_url or cfg["defaults"].get("sheet_url", "")
    if not sheet_url:
        _doctor_check("sheet access", True, "skipped (no sheet URL provided)")
    elif client is None:
        _doctor_check("sheet access", False, "skipped because credential checks failed")
        failures += 1
    else:
        try:
            spreadsheet_id = parse_sheet_id(sheet_url)
            client.verify_access(spreadsheet_id)
            _doctor_check("sheet access", True, to_sheet_url(spreadsheet_id))
        except Exception as exc:
            _doctor_check("sheet access", False, str(exc))
            failures += 1

    configured_command = cfg["sheet_properties"].get("command", "").strip()
    if configured_command:
        _doctor_check("command", True, configured_command)
    else:
        _doctor_check("command", True, "empty (set with: mint setup command \"<cmd>\")")

    configured_auto_close = _as_bool(cfg["sheet_properties"].get("auto_close", True), default=True)
    _doctor_check("auto_close", True, str(configured_auto_close).lower())

    if failures:
        print(f"Doctor found {failures} issue(s).")
        return 1
    print("Doctor check passed.")
    return 0


def main(argv: list[str] | None = None) -> None:
    argv = list(argv if argv is not None else sys.argv[1:])
    parser = build_parser()

    if not argv:
        argv = ["run"]
    elif argv[0] not in {"init", "run", "setup", "doctor", "config", "-h", "--help"}:
        argv = ["run", *argv]

    args = parser.parse_args(argv)
    cwd = _project_base_dir()

    if args.command_name == "setup":
        raise SystemExit(cmd_setup(args, cwd))
    if args.command_name == "init":
        raise SystemExit(cmd_init(args, cwd))
    if args.command_name == "run":
        raise SystemExit(cmd_run(args, cwd))
    if args.command_name == "doctor":
        raise SystemExit(cmd_doctor(args, cwd))
    if args.command_name == "config":
        raise SystemExit(cmd_config(cwd))

    parser.print_help()


if __name__ == "__main__":
    main()
