#!/usr/bin/env python3
"""
=============================================================
  DDoS Mitigator — Management CLI  v2
  EDUCATIONAL USE ONLY
=============================================================
  Commands:
    status              Show all currently blocked IPs and alert counts
    unblock <ip>        Remove iptables block for a specific IP
    flush               Remove ALL rules from the DDOS_MITIGATOR chain
    log                 Tail the IDS/IPS log in real time
    whitelist           Print the current whitelist from the config
    help                Show this help message
=============================================================
"""

import sys
import os
import subprocess
import ipaddress

try:
    import iptc
except ImportError:
    print("[!] python-iptables not found. Install with: sudo pip3 install python-iptables")
    sys.exit(1)

CHAIN_NAME = "DDOS_MITIGATOR"
LOG_FILE   = "/var/log/ddos_mitigator.log"


# ──────────────────────────────────────────────────────────
#  HELPERS
# ──────────────────────────────────────────────────────────

def check_root() -> None:
    if os.geteuid() != 0:
        print("[!] Requires root. Run: sudo python3 manage.py <command>")
        sys.exit(1)


def chain_exists(table: iptc.Table) -> bool:
    return CHAIN_NAME in [c.name for c in table.chains]


def validate_ip(ip: str) -> bool:
    """Return True if ip is a valid IPv4 or IPv6 address."""
    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False


# ──────────────────────────────────────────────────────────
#  COMMANDS
# ──────────────────────────────────────────────────────────

def cmd_status() -> None:
    print(f"\n{'═'*55}")
    print(f"  iptables chain : {CHAIN_NAME}")
    print(f"{'═'*55}")
    try:
        table = iptc.Table(iptc.Table.FILTER)
        if not chain_exists(table):
            print("  Chain does not exist — mitigator may not be running.")
            print()
            return

        chain = iptc.Chain(table, CHAIN_NAME)
        rules = chain.rules

        if not rules:
            print("  ✅  No IPs are currently blocked.")
        else:
            print(f"  {'#':<4} {'Source IP':<22} {'Action'}")
            print(f"  {'-'*40}")
            for idx, rule in enumerate(rules, 1):
                # Strip the /prefix that iptc appends for display clarity
                src    = (rule.src or "any").split("/")[0]
                target = rule.target.name if rule.target else "?"
                print(f"  {idx:<4} {src:<22} {target}")
        print()

        # Also check if the jump rule is in INPUT
        input_chain = iptc.Chain(table, "INPUT")
        jump_present = any(
            r.target and r.target.name == CHAIN_NAME
            for r in input_chain.rules
        )
        if not jump_present:
            print("  ⚠️  WARNING: No jump rule found in INPUT chain.")
            print("      Restart the mitigator to re-insert it.\n")

    except Exception as e:
        print(f"[!] Error reading iptables: {e}")
    print()


def cmd_unblock(ip: str) -> None:
    if not validate_ip(ip):
        print(f"[!] '{ip}' is not a valid IP address.")
        sys.exit(1)

    try:
        table = iptc.Table(iptc.Table.FILTER)
        if not chain_exists(table):
            print(f"[!] Chain {CHAIN_NAME} does not exist — nothing to unblock.")
            return

        chain   = iptc.Chain(table, CHAIN_NAME)
        removed = False

        for rule in list(chain.rules):
            rule_src = (rule.src or "").split("/")[0]
            if rule_src == ip:
                chain.delete_rule(rule)
                print(f"[+] Unblocked: {ip}")
                removed = True

        if not removed:
            print(f"[!] No rule found for IP: {ip}")

    except Exception as e:
        print(f"[!] Error: {e}")


def cmd_flush() -> None:
    print(f"  This will remove ALL rules from chain '{CHAIN_NAME}'")
    print(f"  and the jump from the INPUT chain.")
    confirm = input("[?] Are you sure? (yes/no): ")
    if confirm.strip().lower() != "yes":
        print("Aborted.")
        return

    try:
        table = iptc.Table(iptc.Table.FILTER)

        # Remove jump from INPUT
        input_chain  = iptc.Chain(table, "INPUT")
        jump_removed = False
        for rule in list(input_chain.rules):
            if rule.target and rule.target.name == CHAIN_NAME:
                input_chain.delete_rule(rule)
                jump_removed = True

        if jump_removed:
            print("[+] Removed jump rule from INPUT chain.")
        else:
            print("[!] No jump rule found in INPUT chain.")

        # Flush and delete the DDOS chain
        if chain_exists(table):
            chain = iptc.Chain(table, CHAIN_NAME)
            chain.flush()
            table.delete_chain(chain)
            print(f"[+] Chain {CHAIN_NAME} flushed and deleted.")
        else:
            print(f"[!] Chain {CHAIN_NAME} does not exist.")

    except Exception as e:
        print(f"[!] Error: {e}")


def cmd_log() -> None:
    if not os.path.exists(LOG_FILE):
        print(f"[!] Log file not found: {LOG_FILE}")
        print("    Ensure the mitigator has been run at least once.")
        return
    print(f"[*] Tailing {LOG_FILE} (Ctrl+C to stop):\n")
    try:
        subprocess.run(["tail", "-f", "-n", "50", LOG_FILE])
    except KeyboardInterrupt:
        print("\n[*] Done.")
    except FileNotFoundError:
        print("[!] 'tail' command not found. Run: sudo apt install coreutils")


def cmd_whitelist() -> None:
    """Display the WHITELIST from ddos_mitigator.py config without importing Scapy."""
    print(f"\n{'═'*50}")
    print("  Current WHITELIST (from CONFIG)")
    print(f"{'═'*50}")
    try:
        # Parse the config file with basic text search to avoid Scapy import
        script_dir  = os.path.dirname(os.path.abspath(__file__))
        mitigator   = os.path.join(script_dir, "ddos_mitigator.py")
        if not os.path.exists(mitigator):
            print("[!] ddos_mitigator.py not found in the same directory.")
            return

        in_whitelist = False
        entries      = []
        with open(mitigator) as f:
            for line in f:
                if '"WHITELIST"' in line and "[" in line:
                    in_whitelist = True
                if in_whitelist:
                    stripped = line.strip().strip('",')
                    if stripped and not stripped.startswith("#") and stripped not in ('[', ']', '{', '}'):
                        if stripped.startswith('"') or stripped.startswith("'"):
                            entries.append(stripped.strip('\'"'))
                    if "]" in line:
                        break

        if entries:
            for e in entries:
                print(f"  • {e}")
        else:
            print("  (empty or could not parse)")
    except Exception as e:
        print(f"[!] Could not read whitelist: {e}")
    print()


def usage() -> None:
    print(__doc__)


# ──────────────────────────────────────────────────────────
#  ENTRY POINT
# ──────────────────────────────────────────────────────────

def main() -> None:
    check_root()

    if len(sys.argv) < 2:
        usage()
        sys.exit(1)

    cmd = sys.argv[1].lower()

    if cmd == "status":
        cmd_status()

    elif cmd == "unblock":
        if len(sys.argv) < 3:
            print("[!] Usage: sudo python3 manage.py unblock <ip>")
            sys.exit(1)
        cmd_unblock(sys.argv[2])

    elif cmd == "flush":
        cmd_flush()

    elif cmd == "log":
        cmd_log()

    elif cmd == "whitelist":
        cmd_whitelist()

    elif cmd in ("help", "--help", "-h"):
        usage()

    else:
        print(f"[!] Unknown command: '{cmd}'")
        usage()
        sys.exit(1)


if __name__ == "__main__":
    main()
