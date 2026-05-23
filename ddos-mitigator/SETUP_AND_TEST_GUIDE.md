# DDoS Mitigator — Complete Setup & Testing Guide
## Blue Team Final Year Project | EDUCATIONAL USE ONLY

> ⚠️ **LEGAL WARNING:** All tests must be run inside a **private, isolated lab
> environment** (two VMs on a host-only network). Running DDoS simulations
> against systems you do not own is **illegal** in most jurisdictions.

---

## Table of Contents

1. [What Changed in v2](#1-what-changed-in-v2)
2. [Lab Environment](#2-lab-environment)
3. [Step-by-Step Setup](#3-step-by-step-setup)
4. [Running the Mitigator](#4-running-the-mitigator)
5. [Attack Simulations](#5-attack-simulations)
6. [Verifying It Works](#6-verifying-it-works)
7. [Management CLI Reference](#7-management-cli-reference)
8. [Configuration Reference](#8-configuration-reference)
9. [Troubleshooting](#9-troubleshooting)
10. [Architecture & Code Map](#10-architecture--code-map)

---

## 1. What Changed in v2

| # | Bug / Feature | Original | Fixed / Added |
|---|---------------|----------|---------------|
| 1 | **iptables rule not removed on expiry** | Block expired in memory but the kernel DROP rule stayed forever | `auto_unblock_loop()` thread calls `iptables_unblock()` when duration elapses |
| 2 | **Race condition in block logic** | Two threads could both pass the "not yet blocked" check and insert duplicate iptables rules | `try_block_ip()` does a single atomic lock acquire — only one caller proceeds to `iptables_block()` |
| 3 | **Duplicate iptables rules** | No check before inserting; repeated alerts inserted multiple DROP rules for the same IP | `iptables_block()` checks existing rules before inserting |
| 4 | **CIDR/subnet whitelist** | Only exact IPs supported | `is_whitelisted()` uses Python's built-in `ipaddress` module; supports `10.0.0.0/8`, etc. |
| 5 | **Global rate limiter** | `--rand-source` floods bypassed per-IP detection | `__global__` pseudo-IP tracks aggregate rate across all sources |
| 6 | **DEBUG logging** | No packet-level trace possible | `LOG_LEVEL: logging.DEBUG` prints every classified packet |
| 7 | **Config validation** | Bad config caused cryptic runtime crashes | `validate_config()` runs at startup and exits with a clear message |
| 8 | **`dashboard_loop` exception safety** | Any error silently killed the dashboard thread | Wrapped in `try/except`; errors logged, loop continues |
| 9 | **`manage.py` IP validation** | `unblock` accepted any string | `validate_ip()` rejects non-IP input before touching iptables |
| 10 | **`manage.py` missing jump-rule check** | Status never warned if INPUT jump was missing | `cmd_status()` warns when the jump is absent |
| 11 | **`setup.sh` Python version check** | No check; type hints failed silently on Python < 3.10 | Fails early with a clear message if Python < 3.10 |
| 12 | **`setup.sh` import verification** | No post-install test | Imports `scapy` and `iptc` to confirm they actually work |

---

## 2. Lab Environment

### Recommended topology

```
┌──────────────────────┐    Host-Only Network     ┌──────────────────────┐
│   ATTACKER VM        │◄────────────────────────►│   DEFENDER VM        │
│   Ubuntu (hping3)    │    e.g. 192.168.56.0/24  │   Ubuntu (mitigator) │
│   192.168.56.101     │                           │   192.168.56.100     │
└──────────────────────┘                           └──────────────────────┘
```

### VM requirements

| VM | RAM | Disk | Network adapter |
|----|-----|------|-----------------|
| Defender | 1 GB | 10 GB | VirtualBox Host-Only |
| Attacker | 512 MB | 10 GB | VirtualBox Host-Only |

### Creating the network in VirtualBox

1. **File → Host Network Manager → Create**
2. Set IPv4: `192.168.56.1/24`, disable DHCP
3. Assign this adapter to both VMs (Machine → Settings → Network → Adapter 2 → Host-Only)
4. Set static IPs inside each VM:

```bash
# Defender VM
sudo ip addr add 192.168.56.100/24 dev enp0s8
sudo ip link set enp0s8 up

# Attacker VM
sudo ip addr add 192.168.56.101/24 dev enp0s8
sudo ip link set enp0s8 up

# Verify connectivity from attacker
ping -c 3 192.168.56.100
```

---

## 3. Step-by-Step Setup

### On the Defender VM

**Step 1 — Clone / copy the project files**

Make sure these four files are in the same directory:
```
ddos_mitigator.py
manage.py
setup.sh
setup_and_test_guide.md   ← this file
```

**Step 2 — Run setup**

```bash
sudo bash setup.sh
```

The script will:
- Check Python ≥ 3.10
- Install system packages (`hping3`, `iptables`, `tcpdump`, etc.)
- Install Python packages (`scapy`, `python-iptables`)
- Verify both imports actually work
- Create `/var/log/ddos_mitigator.log`
- Check both Python files for syntax errors

**Step 3 — Add your IP to the whitelist (important!)**

Open `ddos_mitigator.py` and find the `WHITELIST` key:

```python
"WHITELIST": [
    "127.0.0.1",
    "::1",
    "192.168.56.1",     # ← Add your management IP / gateway here
],
```

This prevents you from accidentally locking yourself out of the defender VM.

---

## 4. Running the Mitigator

### Normal (IDS + IPS) mode

```bash
sudo python3 ddos_mitigator.py
```

Expected startup output:
```
╔══════════════════════════════════════════════════════════╗
║       DDoS Mitigation Tool — IDS/IPS Engine  v2          ║
║       EDUCATIONAL USE ONLY | Blue Team Lab               ║
╚══════════════════════════════════════════════════════════╝

2025-xx-xx [INFO] [IPS] IPS mode is ACTIVE — attackers will be blocked via iptables.
2025-xx-xx [INFO] [*] Auto-selected interface: enp0s8
2025-xx-xx [INFO] [*] Per-IP thresholds: SYN=50/s  UDP=100/s  ICMP=20/s
2025-xx-xx [INFO] [*] Global threshold:  5000/s  (distributed/spoofed flood detection)
2025-xx-xx [INFO] [*] Block threshold:   3 alerts  | Duration: 300s
2025-xx-xx [INFO] [*] Press Ctrl+C to stop.
```

### IDS-only mode (alerts but no blocking)

Edit the config:
```python
"IPS_ENABLED": False,
```
Then run normally. Useful for baselining legitimate traffic without accidentally blocking anything.

### Debug mode (see every packet)

```python
"LOG_LEVEL": logging.DEBUG,
```
Prints a line for every classified packet — very verbose; use only in testing.

### Lower thresholds for easy demo

```python
"SYN_FLOOD_THRESHOLD":  10,   # Triggers much faster
"ICMP_FLOOD_THRESHOLD":  5,
"IPS_BLOCK_THRESHOLD":   2,   # Block after 2 alerts instead of 3
"BLOCK_DURATION":        60,  # 1 minute for quick testing
```

---

## 5. Attack Simulations

Run all commands below **from the Attacker VM**.
Replace `192.168.56.100` with your Defender VM's IP.

---

### Test 1 — SYN Flood

```bash
# Flood mode (maximum speed, spoofed sources)
sudo hping3 -S -p 80 --flood --rand-source 192.168.56.100

# Controlled rate ~100 pkt/s (single real source IP)
sudo hping3 -S -p 80 -i u10000 192.168.56.100
#                        ^^^^^^ interval in microseconds (1,000,000 / 10,000 = 100 pkt/s)
```

Expected defender output:
```
[IDS] 🚨 ALERT | src=192.168.56.101 | type=SYN Flood | rate=87.3 pkt/s
[IDS] 🚨 ALERT | src=192.168.56.101 | type=SYN Flood | rate=142.6 pkt/s
[IDS] 🚨 ALERT | src=192.168.56.101 | type=SYN Flood | rate=178.1 pkt/s
[IPS] ⛔  BLOCKED  192.168.56.101  via iptables
```

---

### Test 2 — UDP Flood

```bash
# Flood to port 53 (DNS)
sudo hping3 --udp -p 53 --flood 192.168.56.100

# Controlled rate ~200 pkt/s
sudo hping3 --udp -p 53 -i u5000 192.168.56.100
```

---

### Test 3 — ICMP Flood

```bash
# Flood
sudo hping3 --icmp --flood 192.168.56.100

# Controlled rate ~20 pkt/s (just at threshold)
sudo hping3 --icmp -i u50000 192.168.56.100
```

---

### Test 4 — Distributed / Spoofed Flood (global rate limiter)

This tests the new v2 global threshold — per-IP rates stay low but aggregate volume is enormous:

```bash
# Random source IPs at flood speed
sudo hping3 -S -p 80 --flood --rand-source 192.168.56.100
```

Expected defender output:
```
[IDS] 🌐 DISTRIBUTED/SPOOFED FLOOD DETECTED | proto=SYN | global_rate=6234.1 pkt/s | last_src=...
```

Note: Individual random IPs may not hit the per-IP threshold since each appears only once, but the global counter catches it.

---

### Test 5 — Block Expiry (auto-unblock)

1. Set a short `BLOCK_DURATION` (e.g. `60`) in the config
2. Trigger a block with any flood test above
3. Wait 60 seconds
4. The auto-unblock thread logs:
```
[IPS] ⏱  Block expired for 192.168.56.101 — removing iptables rule.
[IPS] ✅  UNBLOCKED  192.168.56.101
```
5. Confirm the rule is gone: `sudo python3 manage.py status`

---

## 6. Verifying It Works

### Check blocked IPs

```bash
sudo python3 manage.py status
```

Sample output:
```
═══════════════════════════════════════════════════════
  iptables chain : DDOS_MITIGATOR
═══════════════════════════════════════════════════════
  #    Source IP              Action
  ----------------------------------------
  1    192.168.56.101         DROP
```

### Inspect iptables directly

```bash
# See all rules in our chain with packet counters
sudo iptables -L DDOS_MITIGATOR -v -n

# See the INPUT chain jump rule
sudo iptables -L INPUT -v -n | grep DDOS
```

### Watch the log live

```bash
sudo python3 manage.py log
# or:
sudo tail -f /var/log/ddos_mitigator.log
```

### Verify blocking with ping

```bash
# From attacker VM — should time out once IP is blocked
ping 192.168.56.100
```

### Monitor traffic with tcpdump (on Defender VM)

```bash
# All incoming traffic
sudo tcpdump -i enp0s8 -n

# SYN packets only
sudo tcpdump -i enp0s8 -n 'tcp[tcpflags] & tcp-syn != 0'

# ICMP only
sudo tcpdump -i enp0s8 -n icmp
```

---

## 7. Management CLI Reference

All commands require root:

```bash
sudo python3 manage.py <command>
```

| Command | Description |
|---------|-------------|
| `status` | List all currently blocked IPs and warn if the INPUT jump rule is missing |
| `unblock <ip>` | Remove the DROP rule for a specific IP (validates IP format first) |
| `flush` | Remove ALL rules from the DDOS_MITIGATOR chain and delete the chain |
| `log` | Tail the log file in real time (last 50 lines shown first) |
| `whitelist` | Print the WHITELIST entries from ddos_mitigator.py |
| `help` | Show the command list |

### Examples

```bash
# See what's blocked
sudo python3 manage.py status

# Unblock an IP that was wrongly flagged
sudo python3 manage.py unblock 192.168.56.50

# Clean slate — remove everything before stopping the mitigator
sudo python3 manage.py flush

# Watch alerts as they come in
sudo python3 manage.py log
```

---

## 8. Configuration Reference

All settings are in the `CONFIG` dictionary at the top of `ddos_mitigator.py`.

| Key | Default | Description |
|-----|---------|-------------|
| `SYN_FLOOD_THRESHOLD` | 50 | SYN packets/sec per source IP before IDS alert |
| `UDP_FLOOD_THRESHOLD` | 100 | UDP packets/sec per source IP |
| `ICMP_FLOOD_THRESHOLD` | 20 | ICMP packets/sec per source IP |
| `GENERAL_PKT_THRESHOLD` | 200 | Any other protocol packets/sec per source IP |
| `GLOBAL_PKT_THRESHOLD` | 5000 | Total packets/sec across ALL IPs (spoofed flood detection) |
| `RATE_WINDOW` | 5 | Sliding window size in seconds for rate calculation |
| `IPS_BLOCK_THRESHOLD` | 3 | Number of IDS alerts before IPS blocks the IP |
| `BLOCK_DURATION` | 300 | How long (seconds) to block. Use `-1` for permanent |
| `WHITELIST` | `["127.0.0.1", "::1"]` | IPs/CIDRs that are never blocked |
| `INTERFACE` | `None` | Interface to sniff (`None` = auto-detect) |
| `LOG_FILE` | `/var/log/ddos_mitigator.log` | Log output path |
| `IPS_ENABLED` | `True` | `False` = IDS-only (alerts but no iptables changes) |
| `LOG_LEVEL` | `logging.INFO` | Use `logging.DEBUG` for per-packet trace |
| `UNBLOCK_CHECK_INTERVAL` | 30 | How often (seconds) the auto-unblock thread wakes |

---

## 9. Troubleshooting

### "python-iptables not found" or "iptc import failed"

```bash
sudo pip3 install python-iptables
# If on Ubuntu 24.04 with externally managed Python:
sudo pip3 install python-iptables --break-system-packages
```

### "No suitable network interface found"

The tool skips `lo` (loopback). List available interfaces:
```bash
ip link show
python3 -c "from scapy.all import get_if_list; print(get_if_list())"
```
Then set `"INTERFACE": "enp0s8"` (or whichever is correct) in the config.

### "iptables: Permission denied"

The tool must run as root:
```bash
sudo python3 ddos_mitigator.py
```

### Blocks not expiring / iptables rule staying after duration

Make sure you are running **v2** — this was bug #1 in the original. The `auto_unblock_loop` thread handles it. Verify it is running:
```bash
# In a second terminal while the mitigator is running
ps aux | grep python3
# Should show the process. The thread is internal so won't appear separately.
```

### manage.py status shows "No jump rule found in INPUT"

This means the mitigator is not running or was killed without a clean shutdown. Fix:
```bash
sudo python3 manage.py flush      # clean any orphan rules
sudo python3 ddos_mitigator.py    # restart — it re-inserts the jump
```

### hping3 not found

```bash
sudo apt install hping3
```

### Scapy prints "WARNING: No IPv4 address found on enp0s8"

The interface exists but has no IP. This is fine for sniffing — Scapy sniffs at the raw packet level regardless. Set the IP if you need it:
```bash
sudo ip addr add 192.168.56.100/24 dev enp0s8
```

---

## 10. Architecture & Code Map

### Packet flow

```
Incoming Packet (Scapy sniff)
        │
        ▼
  inspect_packet()
        │
        ├── Not IP layer? ──────────────────────────────► SKIP
        ├── is_whitelisted(src_ip)? ────────────────────► SKIP (CIDR-aware in v2)
        ├── stats.is_blocked(src_ip)? ──────────────────► SKIP
        │
        ▼
  Protocol classifier
  SYN / UDP / ICMP / OTHER
        │
        ▼
  stats.record(src_ip, proto)
  stats.record("__global__", proto)    ← new in v2
        │
        ├── per-IP rate ≥ threshold?
        │       └── YES ──► ids_alert(ip, type, rate)
        │                         │
        │                         └── increment_alert(ip)
        │                               │
        │                               └── count ≥ IPS_BLOCK_THRESHOLD?
        │                                       │
        │                                 stats.try_block_ip(ip)  ← atomic in v2
        │                                       │  returns True only once
        │                                       └── iptables_block(ip)
        │
        └── global rate ≥ GLOBAL_PKT_THRESHOLD?   ← new in v2
                └── YES ──► Log distributed flood warning
```

### Thread map

| Thread | Name | Role |
|--------|------|------|
| Main | (main) | Scapy `sniff()` loop — captures packets, calls `inspect_packet()` |
| Daemon | Dashboard | Prints status every 10 s |
| Daemon | AutoUnblock | Scans for expired blocks every 30 s, removes iptables rules |

### File map

| File | Role |
|------|------|
| `ddos_mitigator.py` | Core engine: sniffing, classification, IDS alerts, IPS blocking |
| `manage.py` | Admin CLI: status, unblock, flush, log |
| `setup.sh` | One-shot dependency installer with verification |
| `SETUP_AND_TEST_GUIDE.md` | This document |

### Key classes & functions

| Symbol | Location | Purpose |
|--------|----------|---------|
| `TrafficStats` | ddos_mitigator.py | Thread-safe sliding-window counters + block state |
| `TrafficStats.try_block_ip()` | ddos_mitigator.py | Atomic check-and-set for IPS blocking (v2) |
| `TrafficStats.get_expired_blocks()` | ddos_mitigator.py | Batch expiry scan for auto-unblock thread (v2) |
| `inspect_packet()` | ddos_mitigator.py | Scapy callback: classify + rate-check every packet |
| `ids_alert()` | ddos_mitigator.py | Log alert + trigger IPS if threshold reached |
| `iptables_block()` | ddos_mitigator.py | Add DROP rule (idempotent in v2) |
| `iptables_unblock()` | ddos_mitigator.py | Remove DROP rule |
| `auto_unblock_loop()` | ddos_mitigator.py | Background thread — cleans expired blocks (v2) |
| `is_whitelisted()` | ddos_mitigator.py | CIDR-aware whitelist check (v2) |
| `validate_config()` | ddos_mitigator.py | Startup config sanity check (v2) |
| `build_whitelist()` | ddos_mitigator.py | Pre-parses WHITELIST to ip_network objects (v2) |

---

*For final year project blue team lab use only.*
