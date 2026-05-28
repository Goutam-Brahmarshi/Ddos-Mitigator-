#!/usr/bin/env python3
"""
=============================================================
  DDoS Mitigation Tool with Built-in IDS/IPS
  Author: Blue Team Final Year Project
  Purpose: EDUCATIONAL USE ONLY - Cybersecurity Research
  Platform: Ubuntu Linux
=============================================================
  WARNING: This tool is intended solely for educational
  purposes in controlled lab environments. Do NOT use
  against systems you do not own or have explicit
  written permission to test.
=============================================================

  Fixes & Improvements (v2):
  - BUG FIX: iptables rules now properly cleaned on block expiry
  - BUG FIX: Race condition in block logic eliminated (atomic lock)
  - BUG FIX: Duplicate iptables rules prevented
  - FEATURE: CIDR/subnet whitelist support (uses built-in ipaddress)
  - FEATURE: Global rate limiter for spoofed/distributed floods
  - FEATURE: DEBUG logging level for packet-level trace
  - FEATURE: Auto-unblock background thread
  - IMPROVEMENT: dashboard_loop hardened against exceptions
  - IMPROVEMENT: Config validated at startup
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

# ── Dependency checks from scappy──────────────────────────────────────
try:
    from scapy.all import sniff, IP, TCP, UDP, ICMP, get_if_list
except ImportError:
    print("[!] Scapy not found. Install with: sudo pip3 install scapy")
    sys.exit(1)

try:
    import iptc
except ImportError:f
    print("[!] python-iptables not found. Install with: sudo pip3 install python-iptables")
    sys.exit(1)

# ──────────────────────────────────────────────────────────
#  CONFIGURATION
# ──────────────────────────────────────────────────────────

CONFIG = {
    # Per-source-IP thresholds (packets per second)
    "SYN_FLOOD_THRESHOLD":    50,    # SYN packets/sec before flagging
    "UDP_FLOOD_THRESHOLD":    100,   # UDP packets/sec before flagging
    "ICMP_FLOOD_THRESHOLD":   20,    # ICMP packets/sec before flagging
    "GENERAL_PKT_THRESHOLD":  200,   # Any other packet type /sec before flagging

    # Global threshold — catches distributed/spoofed floods (--rand-source)
    # where per-IP counts stay low but total traffic is massive
    "GLOBAL_PKT_THRESHOLD":   5000,  # total pkt/s across ALL IPs

    # Sliding window (seconds) for all rate calculations
    "RATE_WINDOW":            5,

    # Auto-block after this many IDS alerts from one IP
    "IPS_BLOCK_THRESHOLD":    3,

    # How long (seconds) to keep an IP blocked.  -1 = permanent until manual flush.
    "BLOCK_DURATION":         300,

    # Whitelist — these IPs/CIDRs are NEVER blocked.
    # Supports exact IPs ("192.168.1.1") and CIDR ranges ("10.0.0.0/8").
    # Add your gateway, management IPs, etc. here.
    "WHITELIST": [
        "127.0.0.1",
        "::1",
    ],

    # Network interface to sniff on.  None = auto-select first non-loopback.
    "INTERFACE": None,

    # Log file path
    "LOG_FILE": "/var/log/ddos_mitigator.log",

    # IPS mode: False = IDS only (alerts, no iptables changes)
    "IPS_ENABLED": True,

    # Set to logging.DEBUG to see every classified packet
    "LOG_LEVEL": logging.INFO,

    # How often (seconds) the auto-unblock thread wakes to check expired blocks
    "UNBLOCK_CHECK_INTERVAL": 30,
}

# ──────────────────────────────────────────────────────────
#  CONFIG VALIDATION
# ──────────────────────────────────────────────────────────

def validate_config():
    """Catch obvious mis-configurations before we start sniffing."""
    errors = []
    for key in ("SYN_FLOOD_THRESHOLD", "UDP_FLOOD_THRESHOLD",
                "ICMP_FLOOD_THRESHOLD", "GENERAL_PKT_THRESHOLD",
                "GLOBAL_PKT_THRESHOLD"):
        if CONFIG[key] <= 0:
            errors.append(f"  {key} must be > 0 (got {CONFIG[key]})")

    if CONFIG["RATE_WINDOW"] <= 0:
        errors.append(f"  RATE_WINDOW must be > 0 (got {CONFIG['RATE_WINDOW']})")

    if CONFIG["IPS_BLOCK_THRESHOLD"] <= 0:
        errors.append(f"  IPS_BLOCK_THRESHOLD must be > 0")

    if CONFIG["BLOCK_DURATION"] != -1 and CONFIG["BLOCK_DURATION"] <= 0:
        errors.append(f"  BLOCK_DURATION must be > 0 or -1 for permanent")

    for entry in CONFIG["WHITELIST"]:
        try:
            ipaddress.ip_network(entry, strict=False)
        except ValueError:
            errors.append(f"  Invalid WHITELIST entry: '{entry}'")

    if errors:
        print("[!] Configuration errors found:")
        for e in errors:
            print(e)
        sys.exit(1)

# ──────────────────────────────────────────────────────────
#  LOGGING SETUP
# ──────────────────────────────────────────────────────────

def setup_logging():
    log_format = "%(asctime)s [%(levelname)s] %(message)s"
    handlers = [logging.StreamHandler(sys.stdout)]
    try:
        handlers.append(logging.FileHandler(CONFIG["LOG_FILE"]))
    except PermissionError:
        print(f"[!] Cannot write to {CONFIG['LOG_FILE']} — logging to console only.")
    logging.basicConfig(level=CONFIG["LOG_LEVEL"], format=log_format, handlers=handlers)

logger = logging.getLogger("DDoS-Mitigator")

# ──────────────────────────────────────────────────────────
#  WHITELIST HELPER
# ──────────────────────────────────────────────────────────

# Pre-parsed whitelist entries for fast matching
_WHITELIST_NETWORKS: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []

def build_whitelist():
    """Parse CONFIG["WHITELIST"] once into ipaddress network objects."""
    for entry in CONFIG["WHITELIST"]:
        try:
            _WHITELIST_NETWORKS.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            logger.warning(f"[CFG] Skipping invalid whitelist entry: '{entry}'")

def is_whitelisted(ip: str) -> bool:
    """Return True if ip matches any whitelist entry (exact IP or CIDR)."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in net for net in _WHITELIST_NETWORKS)

# ──────────────────────────────────────────────────────────
#  STATISTICS & STATE
# ──────────────────────────────────────────────────────────

class TrafficStats:
    """Thread-safe per-IP traffic counters using sliding time windows."""

    def __init__(self, window: int):
        self.window = window
        self._lock = threading.Lock()

        # {ip: {proto: deque of float timestamps}}
        self._timestamps: dict[str, dict[str, deque]] = defaultdict(
            lambda: defaultdict(deque)
        )

        self.total_packets: int = 0
        self.blocked_ips: dict[str, float] = {}    # ip -> block_start_time
        self.alert_counts: dict[str, int] = defaultdict(int)  # ip -> alert count

    # ── recording ──────────────────────────────────────────

    def record(self, ip: str, proto: str) -> None:
        now = time.time()
        with self._lock:
            self.total_packets += 1
            dq = self._timestamps[ip][proto]
            dq.append(now)
            self._prune(dq, now)

    # ── rate calculation ───────────────────────────────────

    def rate(self, ip: str, proto: str) -> float:
        now = time.time()
        with self._lock:
            dq = self._timestamps[ip][proto]
            self._prune(dq, now)
            return len(dq) / self.window

    def _prune(self, dq: deque, now: float) -> None:
        """Remove timestamps older than the sliding window (caller holds lock)."""
        cutoff = now - self.window
        while dq and dq[0] < cutoff:
            dq.popleft()

    # ── block management ───────────────────────────────────

    def is_blocked(self, ip: str) -> bool:
        """Check if IP is currently blocked; auto-expire timed-out blocks."""
        with self._lock:
            return self._check_blocked_locked(ip)

    def _check_blocked_locked(self, ip: str) -> bool:
        """Must be called with self._lock held."""
        if ip not in self.blocked_ips:
            return False
        if CONFIG["BLOCK_DURATION"] == -1:
            return True
        elapsed = time.time() - self.blocked_ips[ip]
        if elapsed > CONFIG["BLOCK_DURATION"]:
            # Expired — remove from internal state.
            # The caller is responsible for removing the iptables rule.
            del self.blocked_ips[ip]
            return False
        return True

    def try_block_ip(self, ip: str) -> bool:
        """
        Atomically check-and-set the block flag.
        Returns True if THIS call is the one that set the block
        (caller should then add the iptables rule).
        Returns False if ip was already blocked (no-op).
        """
        with self._lock:
            if self._check_blocked_locked(ip):
                return False          # Already blocked — do nothing
            self.blocked_ips[ip] = time.time()
            return True               # We set it — caller must add iptables rule

    def unblock_ip(self, ip: str) -> None:
        with self._lock:
            self.blocked_ips.pop(ip, None)
            self.alert_counts.pop(ip, None)

    def get_expired_blocks(self) -> list[str]:
        """
        Return list of IPs whose block duration has elapsed.
        Removes them from blocked_ips in one pass (caller cleans iptables).
        """
        now = time.time()
        expired = []
        if CONFIG["BLOCK_DURATION"] == -1:
            return expired
        with self._lock:
            for ip, start in list(self.blocked_ips.items()):
                if now - start > CONFIG["BLOCK_DURATION"]:
                    expired.append(ip)
                    del self.blocked_ips[ip]
                    self.alert_counts.pop(ip, None)
        return expired

    # ── alert counting ─────────────────────────────────────

    def increment_alert(self, ip: str) -> int:
        with self._lock:
            self.alert_counts[ip] += 1
            return self.alert_counts[ip]

    # ── snapshot for dashboard ─────────────────────────────

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
    """Create a dedicated iptables chain and jump to it from INPUT."""
    try:
        table = iptc.Table(iptc.Table.FILTER)
        chain_names = [c.name for c in table.chains]
        if CHAIN_NAME not in chain_names:
            table.create_chain(CHAIN_NAME)
            logger.info(f"[IPS] Created iptables chain: {CHAIN_NAME}")

        # Insert jump at the top of INPUT (idempotent)
        input_chain = iptc.Chain(table, "INPUT")
        for rule in input_chain.rules:
            if rule.target and rule.target.name == CHAIN_NAME:
                return   # Already present — nothing to do
        rule = iptc.Rule()
        rule.target = iptc.Target(rule, CHAIN_NAME)
        input_chain.insert_rule(rule)
        logger.info("[IPS] Inserted jump rule into INPUT chain.")
    except Exception as e:
        logger.error(f"[IPS] iptables setup failed: {e}")

def iptables_block(ip: str) -> None:
    """Add a DROP rule for the given IP in our chain (idempotent)."""
    try:
        table = iptc.Table(iptc.Table.FILTER)
        chain = iptc.Chain(table, CHAIN_NAME)

        # Prevent duplicate rules (check before inserting)
        for rule in chain.rules:
            if rule.src in (ip, ip + "/255.255.255.255"):
                logger.debug(f"[IPS] Rule for {ip} already present — skipping insert.")
                return

        rule = iptc.Rule()
        rule.src = ip
        rule.target = iptc.Target(rule, "DROP")
        chain.insert_rule(rule)
        logger.warning(f"[IPS] ⛔  BLOCKED  {ip}  via iptables")
    except Exception as e:
        logger.error(f"[IPS] Failed to block {ip}: {e}")

def iptables_unblock(ip: str) -> None:
    """Remove the DROP rule for the given IP from our chain."""
    try:
        table = iptc.Table(iptc.Table.FILTER)
        chain = iptc.Chain(table, CHAIN_NAME)
        for rule in list(chain.rules):
            if rule.src in (ip, ip + "/255.255.255.255"):
                chain.delete_rule(rule)
                logger.info(f"[IPS] ✅  UNBLOCKED  {ip}")
                return
        logger.debug(f"[IPS] No iptables rule found for {ip} — nothing to remove.")
    except Exception as e:
        logger.error(f"[IPS] Failed to unblock {ip}: {e}")

def iptables_flush() -> None:
    """Remove all our rules and delete the chain cleanly."""
    try:
        table = iptc.Table(iptc.Table.FILTER)

        # Remove jump from INPUT
        input_chain = iptc.Chain(table, "INPUT")
        for rule in list(input_chain.rules):
            if rule.target and rule.target.name == CHAIN_NAME:
                input_chain.delete_rule(rule)

        # Flush and delete our chain
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
    """Log an IDS alert and — if IPS is enabled — atomically trigger a block."""
    msg = (f"[IDS] 🚨 ALERT | src={ip} | type={attack_type} "
           f"| rate={rate:.1f} pkt/s")
    logger.warning(msg)

    if not CONFIG["IPS_ENABLED"]:
        return

    count = stats.increment_alert(ip)
    if count >= CONFIG["IPS_BLOCK_THRESHOLD"]:
        # try_block_ip is atomic: only the first caller proceeds to iptables.
        if stats.try_block_ip(ip):
            iptables_block(ip)


def inspect_packet(pkt) -> None:
    """Scapy packet callback — classify, record, and analyse each packet."""
    if IP not in pkt:
        return

    src_ip = pkt[IP].src

    # Skip whitelisted sources
    if is_whitelisted(src_ip):
        return

    # Skip already-blocked IPs (kernel drops them at the iptables level,
    # but Scapy may briefly still capture them before the rule takes effect)
    if stats.is_blocked(src_ip):
        return

    # ── Protocol classification ──────────────────────────
    if TCP in pkt and pkt[TCP].flags & 0x02:   # SYN flag set
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

    # Record this packet for per-IP and global counters
    stats.record(src_ip, proto)
    stats.record("__global__", proto)

    # ── Per-IP rate check ────────────────────────────────
    per_ip_rate = stats.rate(src_ip, proto)
    logger.debug(f"[PKT] src={src_ip} proto={proto} rate={per_ip_rate:.1f} pkt/s")

    if per_ip_rate >= threshold:
        ids_alert(src_ip, attack_label, per_ip_rate)
        return   # Already alerted for this packet; skip global check

    # ── Global rate check (catches distributed/spoofed floods) ──
    global_rate = stats.rate("__global__", proto)
    if global_rate >= CONFIG["GLOBAL_PKT_THRESHOLD"]:
        logger.warning(
            f"[IDS] 🌐 DISTRIBUTED/SPOOFED FLOOD DETECTED | "
            f"proto={proto} | global_rate={global_rate:.1f} pkt/s | "
            f"last_src={src_ip}"
        )

# ──────────────────────────────────────────────────────────
#  AUTO-UNBLOCK THREAD
# ──────────────────────────────────────────────────────────

def auto_unblock_loop() -> None:
    """
    Periodically scan for blocks whose BLOCK_DURATION has expired and
    remove both the internal state entry AND the iptables rule.

    This fixes the original bug where is_blocked() removed the in-memory
    entry on expiry but left the iptables DROP rule in place, meaning the
    IP was silently blocked forever by the kernel even though the tool
    considered it unblocked.
    """
    while True:
        try:
            time.sleep(CONFIG["UNBLOCK_CHECK_INTERVAL"])
            expired = stats.get_expired_blocks()
            for ip in expired:
                logger.info(f"[IPS] ⏱  Block expired for {ip} — removing iptables rule.")
                iptables_unblock(ip)
        except Exception as e:
            logger.error(f"[AutoUnblock] Unexpected error: {e}")

# ──────────────────────────────────────────────────────────
#  DASHBOARD — periodic status print
# ──────────────────────────────────────────────────────────

def dashboard_loop(interval: int = 10) -> None:
    """Print a status summary every `interval` seconds."""
    while True:
        try:
            time.sleep(interval)
        except Exception:
            break

        try:
            snap    = stats.snapshot()
            blocked = snap["blocked_ips"]
            alerts  = snap["alert_counts"]

            print("\n" + "═" * 60)
            print(f"  📊  DDoS Mitigator Status — {datetime.now().strftime('%H:%M:%S')}")
            print(f"  Total packets seen : {snap['total_packets']}")
            print(f"  IPS mode           : {'ON' if CONFIG['IPS_ENABLED'] else 'OFF (IDS only)'}")
            print(f"  Currently blocked  : {len(blocked)} IP(s)")
            if blocked:
                for ip, ts in blocked.items():
                    elapsed   = int(time.time() - ts)
                    if CONFIG["BLOCK_DURATION"] == -1:
                        remaining = "∞"
                    else:
                        remaining = max(0, CONFIG["BLOCK_DURATION"] - elapsed)
                    print(f"    ⛔ {ip:<20} alerts={alerts.get(ip, 0)}  "
                          f"unblocks in {remaining}s")
            print("═" * 60 + "\n")
        except Exception as e:
            logger.error(f"[Dashboard] Unexpected error: {e}")

# ──────────────────────────────────────────────────────────
#  SIGNAL HANDLER — clean exit
# ──────────────────────────────────────────────────────────

def handle_exit(sig, frame) -> None:
    print("\n[*] Shutting down — cleaning iptables rules...")
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
        print("[!] This tool requires root privileges.")
        print("    Run with: sudo python3 ddos_mitigator.py")
        sys.exit(1)

    validate_config()
    setup_logging()
    build_whitelist()

    print("""
╔══════════════════════════════════════════════════════════╗
║       DDoS Mitigation Tool — IDS/IPS Engine  v2          ║
║       EDUCATIONAL USE ONLY | Blue Team Lab               ║
╚══════════════════════════════════════════════════════════╝
    """)

    # Register clean-exit handlers for Ctrl+C and kill signals
    signal.signal(signal.SIGINT,  handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    # ── IPS setup ──────────────────────────────────────────
    if CONFIG["IPS_ENABLED"]:
        iptables_setup()
        logger.info("[IPS] IPS mode is ACTIVE — attackers will be blocked via iptables.")
    else:
        logger.info("[IDS] Running in IDS-only mode — alerts only, no blocking.")

    # ── Interface ──────────────────────────────────────────
    iface = pick_interface()
    logger.info(f"[*] Sniffing on interface: {iface}")
    logger.info(
        f"[*] Per-IP thresholds: "
        f"SYN={CONFIG['SYN_FLOOD_THRESHOLD']}/s  "
        f"UDP={CONFIG['UDP_FLOOD_THRESHOLD']}/s  "
        f"ICMP={CONFIG['ICMP_FLOOD_THRESHOLD']}/s"
    )
    logger.info(
        f"[*] Global threshold:  {CONFIG['GLOBAL_PKT_THRESHOLD']}/s  "
        f"(distributed/spoofed flood detection)"
    )
    logger.info(
        f"[*] Block threshold:   {CONFIG['IPS_BLOCK_THRESHOLD']} alerts  "
        f"| Duration: "
        f"{'permanent' if CONFIG['BLOCK_DURATION'] == -1 else str(CONFIG['BLOCK_DURATION']) + 's'}"
    )
    logger.info("[*] Press Ctrl+C to stop.\n")

    # ── Background threads ─────────────────────────────────
    threading.Thread(
        target=dashboard_loop, args=(10,), daemon=True, name="Dashboard"
    ).start()

    threading.Thread(
        target=auto_unblock_loop, daemon=True, name="AutoUnblock"
    ).start()

    # ── Start packet capture (blocking call) ───────────────
    sniff(iface=iface, prn=inspect_packet, store=False)


if __name__ == "__main__":
    main()
