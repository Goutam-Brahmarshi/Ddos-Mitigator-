#!/bin/bash
# =============================================================
#  DDoS Mitigator — Ubuntu Setup Script  v2
#  EDUCATIONAL USE ONLY
# =============================================================
#  Supported: Ubuntu 20.04 / 22.04 / 24.04
# =============================================================

set -euo pipefail

# ── Colour helpers ─────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[*]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[✗]${NC} $*"; exit 1; }
ok()    { echo -e "${GREEN}[✓]${NC} $*"; }

echo ""
echo "=============================================="
echo "  DDoS Mitigator — Dependency Installer  v2"
echo "  Ubuntu 20.04 / 22.04 / 24.04"
echo "=============================================="
echo ""

# ── Root check ────────────────────────────────────────────
if [ "$EUID" -ne 0 ]; then
    error "Please run as root:  sudo bash setup.sh"
fi

# ── OS check ──────────────────────────────────────────────
if ! grep -qiE "ubuntu" /etc/os-release 2>/dev/null; then
    warn "This script is designed for Ubuntu. Proceeding anyway..."
fi

# ── Python 3.10+ check ───────────────────────────────────
# The code uses 'dict[str, deque]' type hints (PEP 585) which
# require Python 3.10 or later.
info "Checking Python version..."
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
    error "Python 3.10+ is required (found $PY_VER). Install it with:\n  sudo apt install python3.10"
fi
ok "Python $PY_VER found."

# ── System packages ───────────────────────────────────────
info "Updating package lists..."
apt-get update -qq

info "Installing system packages..."
apt-get install -y -qq \
    python3 \
    python3-pip \
    python3-dev \
    libnetfilter-queue-dev \
    iptables \
    hping3 \
    tcpdump \
    net-tools \
    build-essential \
    libffi-dev \
    libssl-dev
ok "System packages installed."

# ── Python packages ───────────────────────────────────────
info "Installing Python packages (scapy, python-iptables)..."
pip3 install --quiet --upgrade scapy python-iptables
ok "Python packages installed."

# ── Verify imports work ───────────────────────────────────
info "Verifying imports..."

python3 -c "from scapy.all import sniff, IP, TCP, UDP, ICMP" 2>/dev/null \
    && ok "scapy import OK." \
    || error "scapy import failed. Try: pip3 install scapy --break-system-packages"

python3 -c "import iptc" 2>/dev/null \
    && ok "python-iptables import OK." \
    || error "python-iptables import failed. Try: pip3 install python-iptables --break-system-packages"

# ── Log file ──────────────────────────────────────────────
info "Setting up log file..."
LOG=/var/log/ddos_mitigator.log
touch "$LOG"
chmod 640 "$LOG"
ok "Log file ready: $LOG"

# ── iptables kernel module ────────────────────────────────
info "Ensuring iptables kernel modules are loaded..."
modprobe ip_tables 2>/dev/null  && ok "ip_tables module loaded." \
    || warn "Could not load ip_tables — may already be built-in."
modprobe iptable_filter 2>/dev/null && ok "iptable_filter module loaded." \
    || warn "Could not load iptable_filter — may already be built-in."

# ── Self-test: validate the mitigator can be imported ─────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/ddos_mitigator.py" ]; then
    info "Running syntax check on ddos_mitigator.py..."
    python3 -m py_compile "$SCRIPT_DIR/ddos_mitigator.py" \
        && ok "ddos_mitigator.py syntax OK." \
        || error "ddos_mitigator.py has syntax errors. Fix them before running."

    info "Running syntax check on manage.py..."
    python3 -m py_compile "$SCRIPT_DIR/manage.py" \
        && ok "manage.py syntax OK." \
        || error "manage.py has syntax errors."
else
    warn "ddos_mitigator.py not found in $SCRIPT_DIR — skipping syntax check."
fi

# ── Summary ───────────────────────────────────────────────
echo ""
echo "=============================================="
echo -e "  ${GREEN}✅  Setup complete!${NC}"
echo ""
echo "  Quick-start:"
echo "    sudo python3 ddos_mitigator.py       # start the engine"
echo "    sudo python3 manage.py status        # check blocked IPs"
echo "    sudo python3 manage.py log           # watch the log"
echo ""
echo "  Testing (from attacker VM):"
echo "    sudo hping3 -S -p 80 --flood <DEFENDER_IP>"
echo ""
echo "  See SETUP_AND_TEST_GUIDE.md for the full walkthrough."
echo "=============================================="
echo ""
