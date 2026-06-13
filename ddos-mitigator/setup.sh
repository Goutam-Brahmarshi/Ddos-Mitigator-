#!/bin/bash

# ==============================================================
#  Setup Script for DDoS Mitigation Tool
# ==============================================================

# Define colors for output
RED='\033[91m'
GREEN='\033[92m'
CYAN='\033[96m'
RESET='\033[0m'

echo -e "${CYAN}=== DDoS Mitigator Setup ===${RESET}"

# 1. Check for root privileges
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}[!] This script must be run as root. Try: sudo ./setup.sh${RESET}" 
   exit 1
fi

# 2. Update package lists
echo -e "\n${CYAN}[*] Updating package lists...${RESET}"
apt-get update

# 3. Install system dependencies
# Note: libxtables-dev is often required to build python-iptables successfully
echo -e "\n${CYAN}[*] Installing system dependencies (Python3, pip, iptables, build tools)...${RESET}"
apt-get install -y python3 python3-pip iptables gcc python3-dev libxtables-dev

# 4. Install Python dependencies
echo -e "\n${CYAN}[*] Installing Python modules (scapy, python-iptables)...${RESET}"
# Modern Ubuntu versions (23.04+) enforce PEP 668, requiring the break-system-packages flag for global pip installs
if pip3 --help | grep -q "break-system-packages"; then
    pip3 install scapy python-iptables --break-system-packages
else
    pip3 install scapy python-iptables
fi

# 5. Set executable permissions
echo -e "\n${CYAN}[*] Setting executable permissions for Python scripts...${RESET}"
if [[ -f "ddos_mitigator.py" && -f "manage.py" ]]; then
    chmod +x ddos_mitigator.py
    chmod +x manage.py
    echo -e "${GREEN}✔ Permissions set.${RESET}"
else
    echo -e "${RED}[!] Could not find ddos_mitigator.py or manage.py in the current directory.${RESET}"
fi

# 6. Initialize log file
echo -e "\n${CYAN}[*] Initializing log file at /var/log/ddos_mitigator.log...${RESET}"
touch /var/log/ddos_mitigator.log
chmod 644 /var/log/ddos_mitigator.log

echo -e "\n${GREEN}=== Setup Complete! ===${RESET}"
echo -e "You can now run the tool and management CLI using:"
echo -e "  ${CYAN}sudo ./ddos_mitigator.py${RESET}"
echo -e "  ${CYAN}sudo ./manage.py help${RESET}\n"
