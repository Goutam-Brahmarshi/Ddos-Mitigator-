#!/usr/bin/env python3
"""
=============================================================
  DDoS Mitigation Tool with Built-in IDS/IPS
  Author: Goutam
  Purpose: EDUCATIONAL USE ONLY - Cybersecurity Research
  Platform: Ubuntu Server 26.04
=============================================================
"""

import sys
import os
import time
import signal
import logging
import threading
import ipaddress
from datetime import datetime
from collections import defaultdict, deque

# ──────────────────────────────────────────────────────────
#  TERMINAL UI  — Colors, glyphs, box-drawing
# ──────────────────────────────────────────────────────────

class C:
    # Foreground colors
    RED      = '\033[91m'
    ORANGE   = '\033[38;5;208m'
    YELLOW   = '\033[93m'
    GREEN    = '\033[92m'
    CYAN     = '\033[96m'
    BLUE     = '\033[94m'
    MAGENTA  = '\033[95m'
    WHITE    = '\033[97m'
    GREY     = '\033[90m'
    # Styles
    BOLD     = '\033[1m'
    DIM      = '\033[2m'
    RESET    = '\033[0m'

# Keep a Colors alias so existing references still work
Colors = C

# Width of all UI panels
UI_W = 70

def _box_top(title: str = "", w: int = UI_W) -> str:
    if title:
        pad   = w - len(title) - 4
        left  = pad // 2
        right = pad - left
        return f"{C.GREY}╔{'═'*left} {C.WHITE}{C.BOLD}{title}{C.RESET}{C.GREY} {'═'*right}╗{C.RESET}"
    return f"{C.GREY}╔{'═'*(w-2)}╗{C.RESET}"

def _box_bot(w: int = UI_W) -> str:
    return f"{C.GREY}╚{'═'*(w-2)}╝{C.RESET}"

def _box_sep(w: int = UI_W) -> str:
    return f"{C.GREY}╠{'═'*(w-2)}╣{C.RESET}"

def _box_row(content: str, w: int = UI_W) -> str:
    # Strip ANSI for length calculation
    import re
    plain = re.sub(r'\033\[[^m]*m', '', content)
    pad   = w - 2 - len(plain)
    return f"{C.GREY}║{C.RESET} {content}{' '*max(0,pad-1)}{C.GREY}║{C.RESET}"

def _box_blank(w: int = UI_W) -> str:
    return f"{C.GREY}║{' '*(w-2)}║{C.RESET}"

def print_banner() -> None:
    art = rf"""
{C.RED}{C.BOLD}INITIALIZING MITIGATION{C.RESET}"""
    print(art)
    print(_box_top("IDS / IPS ENGINE  v2"))
    print(_box_row(f"{C.GREY}  Author & Scode  {C.RESET}       Goutam Achary                             "))
    print(_box_row(f"{C.GREY}  Purpose {C.RESET}{C.YELLOW}LAB USE ONLY{C.RESET} — Security Research  "))
    print(_box_row(f"{C.GREY}  Platform{C.RESET}               Ubuntu Server 26.04                       "))
    print(_box_bot())
    print()

def print_config_summary(iface: str) -> None:
    print(_box_top("CONFIGURATION"))
    print(_box_row(f"  {C.CYAN}Interface{C.RESET}          {C.WHITE}{iface}{C.RESET}"))
    print(_box_row(f"  {C.CYAN}IPS Mode{C.RESET}           {C.GREEN+'ACTIVE  ✔' if CONFIG['IPS_ENABLED'] else C.YELLOW+'IDS ONLY ✘'}{C.RESET}"))
    print(_box_row(f"  {C.CYAN}Block Duration{C.RESET}     {'permanent' if CONFIG['BLOCK_DURATION']==-1 else str(CONFIG['BLOCK_DURATION'])+'s'}"))
    print(_box_sep())
    print(_box_row(f"  {C.GREY}THRESHOLDS (packets/sec){C.RESET}"))
    print(_box_row(f"  {'SYN':<10} {C.RED}{CONFIG['SYN_FLOOD_THRESHOLD']:<6}{C.RESET}  "
                   f"{'UDP':<10} {C.ORANGE}{CONFIG['UDP_FLOOD_THRESHOLD']:<6}{C.RESET}  "
                   f"{'ICMP':<10} {C.YELLOW}{CONFIG['ICMP_FLOOD_THRESHOLD']}{C.RESET}"))
    print(_box_row(f"  {'GENERAL':<10} {C.CYAN}{CONFIG['GENERAL_PKT_THRESHOLD']:<6}{C.RESET}  "
                   f"{'GLOBAL':<10} {C.MAGENTA}{CONFIG['GLOBAL_PKT_THRESHOLD']:<6}{C.RESET}  "
                   f"{'ALERT→BLK':<10} {C.WHITE}{CONFIG['IPS_BLOCK_THRESHOLD']}{C.RESET}"))
    print(_box_bot())
    print()

# ── "Bananas !" ASCII art — printed on successful block ───

BANANAS_ART = rf"""
{C.YELLOW}{C.BOLD}
  ██████╗  █████╗ ███╗   ██╗ █████╗ ███╗   ██╗ █████╗ ███████╗    ██╗
  ██╔══██╗██╔══██╗████╗  ██║██╔══██╗████╗  ██║██╔══██╗██╔════╝    ██║
  ██████╔╝███████║██╔██╗ ██║███████║██╔██╗ ██║███████║███████╗    ██║
  ██╔══██╗██╔══██║██║╚██╗██║██╔══██║██║╚██╗██║██╔══██║╚════██║    ╚═╝
  ██████╔╝██║  ██║██║ ╚████║██║  ██║██║ ╚████║██║  ██║███████║    ██╗
  ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝╚══════╝    ╚═╝
{C.RESET}"""

def print_block_event(ip: str, alert_count: int) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(BANANAS_ART)
    print(_box_top("  ▶  IP BLOCKED  ◀"))
    print(_box_blank())
    print(_box_row(f"  {C.RED}{C.BOLD}  🚫  {ip:<22}{C.RESET}  dropped via iptables"))
    print(_box_row(f"  {C.GREY}  Alerts triggered : {C.WHITE}{alert_count}{C.RESET}   "
                   f"{C.GREY}Time : {C.WHITE}{ts}{C.RESET}"))
    print(_box_blank())
    print(_box_bot())
    print()

def print_ids_alert(ip: str, attack_type: str, rate: float, count: int) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    # Color-code by attack type
    acolor = {
        "SYN Flood":    C.RED,
        "UDP Flood":    C.ORANGE,
        "ICMP Flood":   C.YELLOW,
        "Packet Flood": C.CYAN,
    }.get(attack_type, C.RED)

    badge = f"{acolor}{C.BOLD} {attack_type.upper()} {C.RESET}"
    print(_box_top("IDS  ALERT"))
    print(_box_row(f"  {badge}   {C.WHITE}{ip:<22}{C.RESET}  {C.GREY}{ts}{C.RESET}"))
    print(_box_row(f"  {C.GREY}  Rate : {acolor}{rate:.1f} pkt/s{C.RESET}"
                   f"   {C.GREY}Alerts : {C.WHITE}{count}{C.RESET}"
                   f"   {C.GREY}Threshold : {C.WHITE}{CONFIG['IPS_BLOCK_THRESHOLD']}{C.RESET}"))
    print(_box_bot())

def print_distributed_alert(proto: str, rate: float, last_src: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(_box_top("⚠  DISTRIBUTED / SPOOFED FLOOD"))
    print(_box_row(f"  {C.MAGENTA}{C.BOLD}  GLOBAL RATE EXCEEDED{C.RESET}"))
    print(_box_row(f"  {C.GREY}  Proto : {C.WHITE}{proto:<6}{C.RESET}"
                   f"  {C.GREY}Rate : {C.MAGENTA}{rate:.1f} pkt/s{C.RESET}"
                   f"  {C.GREY}Last src : {C.WHITE}{last_src}{C.RESET}"
                   f"  {C.GREY}{ts}{C.RESET}"))
    print(_box_bot())

def print_dashboard(snap: dict) -> None:
    blocked = snap["blocked_ips"]
    alerts  = snap["alert_counts"]
    ts      = datetime.now().strftime("%H:%M:%S")

    print()
    print(_box_top(f"STATUS  {ts}"))
    print(_box_row(f"  {C.GREY}Total packets{C.RESET}    {C.WHITE}{C.BOLD}{snap['total_packets']}{C.RESET}"))
    print(_box_row(f"  {C.GREY}IPS mode{C.RESET}         "
                   f"{'  '+C.GREEN+C.BOLD+'ACTIVE'+C.RESET if CONFIG['IPS_ENABLED'] else C.YELLOW+'IDS ONLY'+C.RESET}"))
    print(_box_row(f"  {C.GREY}Blocked IPs{C.RESET}      {C.RED}{C.BOLD}{len(blocked)}{C.RESET}"))
    if blocked:
        print(_box_sep())
        print(_box_row(f"  {C.BOLD}{'IP':<20}  {'ALERTS':>6}  {'EXPIRES IN':>12}{C.RESET}"))
        print(_box_row(f"  {C.GREY}{'─'*20}  {'──────':>6}  {'──────────':>12}{C.RESET}"))
        for ip, ts_block in blocked.items():
            elapsed   = int(time.time() - ts_block)
            remaining = "permanent" if CONFIG["BLOCK_DURATION"] == -1 else \
                        f"{max(0, CONFIG['BLOCK_DURATION'] - elapsed)}s"
            alc = alerts.get(ip, 0)
            print(_box_row(f"  {C.RED}{ip:<20}{C.RESET}  {C.WHITE}{alc:>6}{C.RESET}  {C.YELLOW}{remaining:>12}{C.RESET}"))
    print(_box_bot())
    print()

def print_unblock_event(ip: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(_box_top("IP UNBLOCKED"))
    print(_box_row(f"  {C.GREEN}✔  {ip:<22}{C.RESET}  block expired — rule removed  {C.GREY}{ts}{C.RESET}"))
    print(_box_bot())
    print()

def print_shutdown() -> None:
    print()
    print(_box_top("SHUTDOWN"))
    print(_box_row(f"  {C.YELLOW}Flushing iptables rules …{C.RESET}"))
    print(_box_bot())
    print()

# ── Dependency checks ──────────────────────────────────────
try:
    from scapy.all import sniff, IP, TCP, UDP, ICMP, get_if_list
except ImportError:
    print(f"{C.RED}[!] Scapy not found. Install: sudo pip3 install scapy{C.RESET}")
    sys.exit(1)

try:
    import iptc
except ImportError:
    print(f"{C.RED}[!] python-iptables not found. Install: sudo pip3 install python-iptables{C.RESET}")
    sys.exit(1)

# ──────────────────────────────────────────────────────────
#  CONFIGURATION
# ──────────────────────────────────────────────────────────

CONFIG = {
    "SYN_FLOOD_THRESHOLD":    10,
    "UDP_FLOOD_THRESHOLD":    50,
    "ICMP_FLOOD_THRESHOLD":   5,
    "GENERAL_PKT_THRESHOLD":  200,
    "GLOBAL_PKT_THRESHOLD":   1000,
    "RATE_WINDOW":            5,
    "IPS_BLOCK_THRESHOLD":    2,
    "BLOCK_DURATION":         60,
    "WHITELIST": [
        "127.0.0.1",
        "::1",
        "192.168.179.133",
        "192.168.179.1",
        "192.168.179.2",
        "192.168.56.1",
    ],
    "INTERFACE": "ens34",
    "LOG_FILE": "/var/log/ddos_mitigator.log",
    "IPS_ENABLED": True,
    "LOG_LEVEL": logging.INFO,
    "UNBLOCK_CHECK_INTERVAL": 30,
}

# ──────────────────────────────────────────────────────────
#  CONFIG VALIDATION
# ──────────────────────────────────────────────────────────

def validate_config() -> None:
    errors = []
    for key in ("SYN_FLOOD_THRESHOLD", "UDP_FLOOD_THRESHOLD",
                "ICMP_FLOOD_THRESHOLD", "GENERAL_PKT_THRESHOLD",
                "GLOBAL_PKT_THRESHOLD"):
        if CONFIG[key] <= 0:
            errors.append(f"  {key} must be > 0 (got {CONFIG[key]})")

    if CONFIG["RATE_WINDOW"] <= 0:
        errors.append(f"  RATE_WINDOW must be > 0 (got {CONFIG['RATE_WINDOW']})")
    if CONFIG["IPS_BLOCK_THRESHOLD"] <= 0:
        errors.append("  IPS_BLOCK_THRESHOLD must be > 0")
    if CONFIG["BLOCK_DURATION"] != -1 and CONFIG["BLOCK_DURATION"] <= 0:
        errors.append("  BLOCK_DURATION must be > 0 or -1 for permanent")

    for entry in CONFIG["WHITELIST"]:
        try:
            ipaddress.ip_network(entry, strict=False)
        except ValueError:
            errors.append(f"  Invalid WHITELIST entry: '{entry}'")

    if errors:
        print(_box_top("CONFIG ERRORS"))
        for e in errors:
            print(_box_row(f"  {C.RED}{e}{C.RESET}"))
        print(_box_bot())
        sys.exit(1)

# ──────────────────────────────────────────────────────────
#  LOGGING — ANSI stripped for file handler
# ──────────────────────────────────────────────────────────

import re as _re

class _StripAnsiFormatter(logging.Formatter):
    _ansi = _re.compile(r'\033\[[^m]*m')
    def format(self, record: logging.LogRecord) -> str:
        record.msg  = self._ansi.sub('', str(record.msg))
        record.args = None
        return super().format(record)

def setup_logging() -> None:
    log_format = "%(asctime)s [%(levelname)-8s] %(message)s"
    console_h  = logging.StreamHandler(sys.stdout)
    console_h.setFormatter(logging.Formatter(log_format))
    handlers: list[logging.Handler] = [console_h]
    try:
        file_h = logging.FileHandler(CONFIG["LOG_FILE"])
        file_h.setFormatter(_StripAnsiFormatter(log_format))
        handlers.append(file_h)
    except PermissionError:
        print(f"{C.YELLOW}[!] Cannot write to {CONFIG['LOG_FILE']} — console only.{C.RESET}")
    root = logging.getLogger()
    root.setLevel(CONFIG["LOG_LEVEL"])
    for h in handlers:
        root.addHandler(h)

logger = logging.getLogger("DDoS-Mitigator")

# ──────────────────────────────────────────────────────────
#  WHITELIST
# ──────────────────────────────────────────────────────────

_WHITELIST_NETWORKS: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []

def build_whitelist() -> None:
    for entry in CONFIG["WHITELIST"]:
        try:
            _WHITELIST_NETWORKS.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            logger.warning(f"[CFG] Skipping invalid whitelist entry: '{entry}'")

def is_whitelisted(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in net for net in _WHITELIST_NETWORKS)

# ──────────────────────────────────────────────────────────
#  STATISTICS & STATE
# ──────────────────────────────────────────────────────────

class TrafficStats:
    def __init__(self, window: int):
        self.window = window
        self._lock   = threading.Lock()
        self._timestamps: dict[str, dict[str, deque]] = defaultdict(lambda: defaultdict(deque))
        self.total_packets: int = 0
        self.blocked_ips:   dict[str, float] = {}
        self.alert_counts:  dict[str, int]   = defaultdict(int)

    def record(self, ip: str, proto: str) -> None:
        now = time.time()
        with self._lock:
            self.total_packets += 1
            dq = self._timestamps[ip][proto]
            dq.append(now)
            self._prune(dq, now)

    def rate(self, ip: str, proto: str) -> float:
        now = time.time()
        with self._lock:
            dq = self._timestamps[ip][proto]
            self._prune(dq, now)
            return len(dq) / self.window

    def _prune(self, dq: deque, now: float) -> None:
        cutoff = now - self.window
        while dq and dq[0] < cutoff:
            dq.popleft()

    # ── read-only check — does NOT mutate state ────────────
    def is_blocked(self, ip: str) -> bool:
        with self._lock:
            if ip not in self.blocked_ips:
                return False
            if CONFIG["BLOCK_DURATION"] == -1:
                return True
            return (time.time() - self.blocked_ips[ip]) <= CONFIG["BLOCK_DURATION"]

    def try_block_ip(self, ip: str) -> bool:
        """Attempt to record a new block. Returns True if newly blocked."""
        with self._lock:
            if ip in self.blocked_ips:
                if CONFIG["BLOCK_DURATION"] == -1:
                    return False
                if (time.time() - self.blocked_ips[ip]) <= CONFIG["BLOCK_DURATION"]:
                    return False
            self.blocked_ips[ip] = time.time()
            return True

    def unblock_ip(self, ip: str) -> None:
        with self._lock:
            self.blocked_ips.pop(ip, None)
            self.alert_counts.pop(ip, None)

    def get_expired_blocks(self) -> list[str]:
        """Collect and remove expired blocks (called only from auto_unblock_loop)."""
        if CONFIG["BLOCK_DURATION"] == -1:
            return []
        now     = time.time()
        expired = []
        with self._lock:
            for ip, start in list(self.blocked_ips.items()):
                if now - start > CONFIG["BLOCK_DURATION"]:
                    expired.append(ip)
                    del self.blocked_ips[ip]
                    self.alert_counts.pop(ip, None)
        return expired

    def increment_alert(self, ip: str) -> int:
        with self._lock:
            self.alert_counts[ip] += 1
            return self.alert_counts[ip]

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "total_packets": self.total_packets,
                "blocked_ips":   dict(self.blocked_ips),
                "alert_counts":  dict(self.alert_counts),
            }

stats = TrafficStats(CONFIG["RATE_WINDOW"])

# ──────────────────────────────────────────────────────────
#  IPS — iptables integration
# ──────────────────────────────────────────────────────────

CHAIN_NAME = "DDOS_MITIGATOR"

def iptables_setup() -> None:
    try:
        table = iptc.Table(iptc.Table.FILTER)
        if CHAIN_NAME not in [c.name for c in table.chains]:
            table.create_chain(CHAIN_NAME)
            logger.info(f"[IPS] Created iptables chain: {CHAIN_NAME}")

        input_chain = iptc.Chain(table, "INPUT")
        if any(r.target and r.target.name == CHAIN_NAME for r in input_chain.rules):
            return
        rule = iptc.Rule()
        rule.target = iptc.Target(rule, CHAIN_NAME)
        input_chain.insert_rule(rule)
        logger.info("[IPS] Inserted jump rule into INPUT chain.")
    except Exception as e:
        logger.error(f"[IPS] iptables setup failed: {e}")

def iptables_block(ip: str) -> None:
    try:
        table = iptc.Table(iptc.Table.FILTER)
        chain = iptc.Chain(table, CHAIN_NAME)
        for rule in chain.rules:
            if rule.src in (ip, ip + "/255.255.255.255"):
                logger.debug(f"[IPS] Rule for {ip} already present.")
                return
        rule = iptc.Rule()
        rule.src    = ip
        rule.target = iptc.Target(rule, "DROP")
        chain.insert_rule(rule)
        logger.info(f"[IPS] BLOCKED {ip} via iptables")
    except Exception as e:
        logger.error(f"[IPS] Failed to block {ip}: {e}")

def iptables_unblock(ip: str) -> None:
    try:
        table = iptc.Table(iptc.Table.FILTER)
        chain = iptc.Chain(table, CHAIN_NAME)
        for rule in list(chain.rules):
            if rule.src in (ip, ip + "/255.255.255.255"):
                chain.delete_rule(rule)
                logger.info(f"[IPS] UNBLOCKED {ip}")
                return
        logger.debug(f"[IPS] No iptables rule found for {ip}.")
    except Exception as e:
        logger.error(f"[IPS] Failed to unblock {ip}: {e}")

def iptables_flush() -> None:
    try:
        table       = iptc.Table(iptc.Table.FILTER)
        input_chain = iptc.Chain(table, "INPUT")
        for rule in list(input_chain.rules):
            if rule.target and rule.target.name == CHAIN_NAME:
                input_chain.delete_rule(rule)
        if CHAIN_NAME in [c.name for c in table.chains]:
            chain = iptc.Chain(table, CHAIN_NAME)
            chain.flush()
            table.delete_chain(chain)
        logger.info("[IPS] iptables rules cleaned up.")
    except Exception as e:
        logger.error(f"[IPS] Cleanup error: {e}")

# ──────────────────────────────────────────────────────────
#  IDS — Detection Engine
# ──────────────────────────────────────────────────────────

def ids_alert(ip: str, attack_type: str, rate: float) -> None:
    count = stats.increment_alert(ip)
    # Rich visual alert (console only — logger strips ANSI for file)
    print_ids_alert(ip, attack_type, rate, count)
    logger.warning(f"[IDS] ALERT src={ip} type={attack_type} rate={rate:.1f} pkt/s alerts={count}")

    if not CONFIG["IPS_ENABLED"]:
        return

    if count >= CONFIG["IPS_BLOCK_THRESHOLD"]:
        if stats.try_block_ip(ip):
            iptables_block(ip)
            print_block_event(ip, count)   # "Bananas !" moment

def inspect_packet(pkt) -> None:
    if IP not in pkt:
        return

    src_ip = pkt[IP].src

    if is_whitelisted(src_ip):
        return
    if stats.is_blocked(src_ip):
        return

    if TCP in pkt and pkt[TCP].flags & 0x02:
        proto        = "SYN"
        threshold    = CONFIG["SYN_FLOOD_THRESHOLD"]
        attack_label = "SYN Flood"
    elif UDP in pkt:
        proto        = "UDP"
        threshold    = CONFIG["UDP_FLOOD_THRESHOLD"]
        attack_label = "UDP Flood"
    elif ICMP in pkt:
        proto        = "ICMP"
        threshold    = CONFIG["ICMP_FLOOD_THRESHOLD"]
        attack_label = "ICMP Flood"
    else:
        proto        = "OTHER"
        threshold    = CONFIG["GENERAL_PKT_THRESHOLD"]
        attack_label = "Packet Flood"

    stats.record(src_ip,       proto)
    stats.record("__global__", proto)

    per_ip_rate = stats.rate(src_ip, proto)
    logger.debug(f"[PKT] src={src_ip} proto={proto} rate={per_ip_rate:.1f} pkt/s")

    if per_ip_rate >= threshold:
        ids_alert(src_ip, attack_label, per_ip_rate)
        return

    global_rate = stats.rate("__global__", proto)
    if global_rate >= CONFIG["GLOBAL_PKT_THRESHOLD"]:
        print_distributed_alert(proto, global_rate, src_ip)
        logger.warning(
            f"[IDS] DISTRIBUTED FLOOD proto={proto} "
            f"global_rate={global_rate:.1f} pkt/s last_src={src_ip}"
        )

# ──────────────────────────────────────────────────────────
#  AUTO-UNBLOCK THREAD
# ──────────────────────────────────────────────────────────

_stop_event = threading.Event()

def auto_unblock_loop() -> None:
    while not _stop_event.wait(timeout=CONFIG["UNBLOCK_CHECK_INTERVAL"]):
        try:
            expired = stats.get_expired_blocks()
            for ip in expired:
                iptables_unblock(ip)
                print_unblock_event(ip)
        except Exception as e:
            logger.error(f"[AutoUnblock] Unexpected error: {e}")

# ──────────────────────────────────────────────────────────
#  DASHBOARD-THREAD
# ──────────────────────────────────────────────────────────

def dashboard_loop(interval: int = 10) -> None:
    while not _stop_event.wait(timeout=interval):
        try:
            print_dashboard(stats.snapshot())
        except Exception as e:
            logger.error(f"[Dashboard] Unexpected error: {e}")

# ──────────────────────────────────────────────────────────
#  SIGNAL HANDLER
# ──────────────────────────────────────────────────────────

def handle_exit(sig, frame) -> None:
    print_shutdown()
    _stop_event.set()
    iptables_flush()
    sys.exit(0)

# ──────────────────────────────────────────────────────────
#  INTERFACE SELECTION
# ──────────────────────────────────────────────────────────

def pick_interface() -> str:
    if CONFIG["INTERFACE"]:
        return CONFIG["INTERFACE"]
    interfaces = [i for i in get_if_list() if i != "lo"]
    if not interfaces:
        logger.error("No suitable network interface found.")
        sys.exit(1)
    iface = interfaces[0]
    logger.info(f"[*] Auto-selected interface: {iface}")
    return iface

# ──────────────────────────────────────────────────────────
#  MAIN
# ──────────────────────────────────────────────────────────

def main() -> None:
    if os.geteuid() != 0:
        print(_box_top("PERMISSION ERROR"))
        print(_box_row(f"  {C.RED}Root privileges required.{C.RESET}"))
        print(_box_row(f"  Run: {C.WHITE}sudo python3 ddos_mitigator.py{C.RESET}"))
        print(_box_bot())
        sys.exit(1)

    validate_config()
    setup_logging()
    build_whitelist()

    print_banner()

    signal.signal(signal.SIGINT,  handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    if CONFIG["IPS_ENABLED"]:
        iptables_setup()

    iface = pick_interface()
    print_config_summary(iface)

    logger.info(f"[*] Sniffing on {iface} — Press Ctrl+C to stop.")

    threading.Thread(target=dashboard_loop,   args=(10,), daemon=True, name="Dashboard").start()
    threading.Thread(target=auto_unblock_loop,            daemon=True, name="AutoUnblock").start()

    sniff(iface=iface, prn=inspect_packet, store=False)


if __name__ == "__main__":
    main()
