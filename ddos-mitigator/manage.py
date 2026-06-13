#!/usr/bin/env python3
"""
manage.py — DDoS Mitigator Management CLI  v2
EDUCATIONAL USE ONLY

Commands:
  status              Show all currently blocked IPs
  unblock <ip>        Remove iptables block for an IP
  flush               Remove ALL rules and chains
  log                 Tail the log in real time
  whitelist           Print current whitelist
  help                Show this help message
"""

import sys
import os
import subprocess
import ipaddress
import re as _re

# ──────────────────────────────────────────────────────────
#  TERMINAL UI  — shared with ddos_mitigator.py
# ──────────────────────────────────────────────────────────

class C:
    RED     = '\033[91m'
    ORANGE  = '\033[38;5;208m'
    YELLOW  = '\033[93m'
    GREEN   = '\033[92m'
    CYAN    = '\033[96m'
    BLUE    = '\033[94m'
    MAGENTA = '\033[95m'
    WHITE   = '\033[97m'
    GREY    = '\033[90m'
    BOLD    = '\033[1m'
    DIM     = '\033[2m'
    RESET   = '\033[0m'

UI_W = 70

def _strip(s: str) -> str:
    return _re.sub(r'\033\[[^m]*m', '', s)

def _box_top(title: str = "", w: int = UI_W) -> str:
    if title:
        pad   = w - len(title) - 4
        left  = max(1, pad // 2)
        right = max(1, pad - left)
        return f"{C.GREY}╔{'═'*left} {C.WHITE}{C.BOLD}{title}{C.RESET}{C.GREY} {'═'*right}╗{C.RESET}"
    return f"{C.GREY}╔{'═'*(w-2)}╗{C.RESET}"

def _box_bot(w: int = UI_W) -> str:
    return f"{C.GREY}╚{'═'*(w-2)}╝{C.RESET}"

def _box_sep(w: int = UI_W) -> str:
    return f"{C.GREY}╠{'═'*(w-2)}╣{C.RESET}"

def _box_row(content: str, w: int = UI_W) -> str:
    pad = w - 2 - len(_strip(content))
    return f"{C.GREY}║{C.RESET} {content}{' '*max(0, pad-1)}{C.GREY}║{C.RESET}"

def _box_blank(w: int = UI_W) -> str:
    return f"{C.GREY}║{' '*(w-2)}║{C.RESET}"

def _ok(msg: str) -> None:
    print(f"  {C.GREEN}✔{C.RESET}  {msg}")

def _warn(msg: str) -> None:
    print(f"  {C.YELLOW}⚠{C.RESET}  {msg}")

def _err(msg: str) -> None:
    print(f"  {C.RED}✘{C.RESET}  {msg}")

def print_manage_banner() -> None:
    print()
    print(_box_top("DDoS MITIGATOR  ·  MANAGE  v2"))
    print(_box_row(f"  {C.GREY}Use: {C.WHITE}sudo python3 manage.py <command>{C.RESET}"))
    print(_box_row(f"  {C.GREY}Commands: status  unblock  flush  log  whitelist  help{C.RESET}"))
    print(_box_bot())
    print()

# ──────────────────────────────────────────────────────────
#  DEPENDENCIES
# ──────────────────────────────────────────────────────────

try:
    import iptc
except ImportError:
    print(_box_top("MISSING DEPENDENCY"))
    _err("python-iptables not found.")
    print(f"     Install: {C.WHITE}sudo pip3 install python-iptables{C.RESET}")
    print(_box_bot())
    sys.exit(1)

CHAIN_NAME = "DDOS_MITIGATOR"
LOG_FILE   = "/var/log/ddos_mitigator.log"

# ──────────────────────────────────────────────────────────
#  HELPERS
# ──────────────────────────────────────────────────────────

def check_root() -> None:
    if os.geteuid() != 0:
        print()
        print(_box_top("PERMISSION ERROR"))
        _err(f"Root required.  Run: {C.WHITE}sudo python3 manage.py <command>{C.RESET}")
        print(_box_bot())
        sys.exit(1)

def chain_exists(table: iptc.Table) -> bool:
    return CHAIN_NAME in [c.name for c in table.chains]

def validate_ip(ip: str) -> bool:
    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False

# ──────────────────────────────────────────────────────────
#  COMMANDS
# ──────────────────────────────────────────────────────────

def cmd_status() -> None:
    import time
    print()
    print(_box_top(f"STATUS  ·  {CHAIN_NAME}"))
    try:
        table = iptc.Table(iptc.Table.FILTER)
        if not chain_exists(table):
            _warn("Chain does not exist — mitigator may not be running.")
            print(_box_bot())
            print()
            return

        chain = iptc.Chain(table, CHAIN_NAME)
        rules = chain.rules

        if not rules:
            print(_box_row(f"  {C.GREEN}No IPs are currently blocked.  ✔{C.RESET}"))
        else:
            print(_box_row(f"  {C.BOLD}{'#':<4} {'Source IP':<24} Action{C.RESET}"))
            print(_box_row(f"  {C.GREY}{'─'*4} {'─'*24} {'─'*8}{C.RESET}"))
            for idx, rule in enumerate(rules, 1):
                src    = (rule.src or "any").split("/")[0]
                target = rule.target.name if rule.target else "?"
                tcolor = C.RED if target == "DROP" else C.YELLOW
                print(_box_row(f"  {C.GREY}{idx:<4}{C.RESET} {C.RED}{src:<24}{C.RESET} {tcolor}{target}{C.RESET}"))

        print(_box_sep())
        input_chain  = iptc.Chain(table, "INPUT")
        jump_present = any(r.target and r.target.name == CHAIN_NAME for r in input_chain.rules)
        if jump_present:
            print(_box_row(f"  {C.GREEN}INPUT → {CHAIN_NAME} jump  ✔{C.RESET}"))
        else:
            print(_box_row(f"  {C.YELLOW}⚠  No jump rule in INPUT chain — restart mitigator.{C.RESET}"))

    except Exception as e:
        _err(f"Error reading iptables: {e}")

    print(_box_bot())
    print()

def cmd_unblock(ip: str) -> None:
    if not validate_ip(ip):
        print()
        print(_box_top("UNBLOCK"))
        _err(f"'{ip}' is not a valid IP address.")
        print(_box_bot())
        sys.exit(1)

    print()
    print(_box_top(f"UNBLOCK  ·  {ip}"))
    try:
        table = iptc.Table(iptc.Table.FILTER)
        if not chain_exists(table):
            _warn(f"Chain {CHAIN_NAME} does not exist — nothing to unblock.")
            print(_box_bot())
            return

        chain   = iptc.Chain(table, CHAIN_NAME)
        removed = False
        for rule in list(chain.rules):
            rule_src = (rule.src or "").split("/")[0]
            if rule_src == ip:
                chain.delete_rule(rule)
                _ok(f"Unblocked: {C.WHITE}{ip}{C.RESET}")
                removed = True

        if not removed:
            _warn(f"No rule found for IP: {C.WHITE}{ip}{C.RESET}")

    except Exception as e:
        _err(f"Error: {e}")

    print(_box_bot())
    print()

def cmd_flush() -> None:
    print()
    print(_box_top("FLUSH  ·  ALL RULES"))
    print(_box_row(f"  {C.YELLOW}This removes ALL rules from chain '{CHAIN_NAME}'{C.RESET}"))
    print(_box_row(f"  {C.YELLOW}and the jump from the INPUT chain.{C.RESET}"))
    print(_box_bot())
    confirm = input(f"\n  {C.BOLD}[?] Are you sure? (yes / no): {C.RESET}")
    if confirm.strip().lower() != "yes":
        print(f"\n  {C.GREY}Aborted.{C.RESET}\n")
        return

    print()
    print(_box_top("FLUSHING"))
    try:
        table       = iptc.Table(iptc.Table.FILTER)
        input_chain = iptc.Chain(table, "INPUT")
        removed_jump = False
        for rule in list(input_chain.rules):
            if rule.target and rule.target.name == CHAIN_NAME:
                input_chain.delete_rule(rule)
                removed_jump = True

        if removed_jump:
            _ok("Removed jump rule from INPUT chain.")
        else:
            _warn("No jump rule found in INPUT chain.")

        if chain_exists(table):
            chain = iptc.Chain(table, CHAIN_NAME)
            chain.flush()
            table.delete_chain(chain)
            _ok(f"Chain {CHAIN_NAME} flushed and deleted.")
        else:
            _warn(f"Chain {CHAIN_NAME} does not exist.")

    except Exception as e:
        _err(f"Error: {e}")

    print(_box_bot())
    print()

def cmd_log() -> None:
    if not os.path.exists(LOG_FILE):
        print()
        print(_box_top("LOG"))
        _err(f"Log file not found: {LOG_FILE}")
        print(_box_row("  Run the mitigator at least once to create it."))
        print(_box_bot())
        return

    print()
    print(_box_top(f"LOG  ·  {LOG_FILE}"))
    print(_box_row(f"  {C.GREY}Ctrl+C to stop{C.RESET}"))
    print(_box_bot())
    print()
    try:
        subprocess.run(["tail", "-f", "-n", "50", LOG_FILE])
    except KeyboardInterrupt:
        print(f"\n  {C.GREEN}Done.{C.RESET}\n")
    except FileNotFoundError:
        _err("'tail' command not found.")

def cmd_whitelist() -> None:
    print()
    print(_box_top("WHITELIST"))

    # Import CONFIG directly instead of parsing source text
    script_dir = os.path.dirname(os.path.abspath(__file__))
    mitigator  = os.path.join(script_dir, "ddos_mitigator.py")

    if not os.path.exists(mitigator):
        _err("ddos_mitigator.py not found in the same directory.")
        print(_box_bot())
        return

    try:
        # Safely load only CONFIG from the mitigator module
        import importlib.util
        spec   = importlib.util.spec_from_file_location("_mitigator_cfg", mitigator)
        mod    = importlib.util.module_from_spec(spec)
        # Stub out heavy imports so we can read CONFIG without side effects
        import unittest.mock as _mock
        with _mock.patch.dict("sys.modules", {
            "scapy":       _mock.MagicMock(),
            "scapy.all":   _mock.MagicMock(),
            "iptc":        _mock.MagicMock(),
        }):
            spec.loader.exec_module(mod)
        entries = getattr(mod, "CONFIG", {}).get("WHITELIST", [])
        if entries:
            for e in entries:
                print(_box_row(f"  {C.GREEN}•{C.RESET}  {e}"))
        else:
            print(_box_row(f"  {C.YELLOW}(empty){C.RESET}"))
    except Exception as e:
        _err(f"Could not load whitelist: {e}")

    print(_box_bot())
    print()

def cmd_help() -> None:
    print()
    print(_box_top("HELP"))
    cmds = [
        ("status",        "Show all currently blocked IPs"),
        ("unblock <ip>",  "Remove iptables block for an IP"),
        ("flush",         "Remove ALL rules and chains"),
        ("log",           "Tail the log in real time"),
        ("whitelist",     "Print current whitelist"),
        ("help",          "Show this help message"),
    ]
    for cmd, desc in cmds:
        print(_box_row(f"  {C.CYAN}{cmd:<18}{C.RESET}  {desc}"))
    print(_box_sep())
    print(_box_row(f"  {C.GREY}Usage: sudo python3 manage.py <command>{C.RESET}"))
    print(_box_bot())
    print()

# ──────────────────────────────────────────────────────────
#  ENTRY POINT
# ──────────────────────────────────────────────────────────

def main() -> None:
    check_root()
    print_manage_banner()

    if len(sys.argv) < 2:
        cmd_help()
        sys.exit(1)

    cmd = sys.argv[1].lower()

    if cmd == "status":
        cmd_status()
    elif cmd == "unblock":
        if len(sys.argv) < 3:
            _err(f"Usage: {C.WHITE}sudo python3 manage.py unblock <ip>{C.RESET}")
            sys.exit(1)
        cmd_unblock(sys.argv[2])
    elif cmd == "flush":
        cmd_flush()
    elif cmd == "log":
        cmd_log()
    elif cmd == "whitelist":
        cmd_whitelist()
    elif cmd in ("help", "--help", "-h"):
        cmd_help()
    else:
        print()
        print(_box_top("UNKNOWN COMMAND"))
        _err(f"'{cmd}' is not a valid command.")
        print(_box_bot())
        cmd_help()
        sys.exit(1)

if __name__ == "__main__":
    main()
