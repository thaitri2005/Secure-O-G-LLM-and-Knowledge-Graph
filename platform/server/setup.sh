#!/usr/bin/env bash
# One-time setup of the shared Track C server (plan task B1; docs/tracks/C-storage/server-runbook.md).
# Run as root on a fresh Ubuntu 24.04 LTS server whose root login already has your SSH key:
#
#   bash setup.sh            # creates the user kg
#
# It installs Docker from Docker's own apt repository, creates a user with sudo and Docker rights that logs in with
# the same SSH keys as root, turns off password and root logins, opens only ports 22 and 443, and creates /srv folders.
# Keep the root session open until `ssh kg@<server>` works from a second terminal.
set -euo pipefail

USER_NAME="${1:-kg}"

echo "== 1. Updates and tools"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get -y upgrade
apt-get install -y ca-certificates curl git ufw unattended-upgrades rsync

echo "== 2. Docker Engine and the compose plugin, from Docker's apt repository"
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

echo "== 3. User $USER_NAME, logging in with root's SSH keys"
id "$USER_NAME" >/dev/null 2>&1 || adduser --disabled-password --gecos "" "$USER_NAME"
usermod -aG sudo,docker "$USER_NAME"
echo "$USER_NAME ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/90-$USER_NAME"   # the user has no password; keys only
chmod 440 "/etc/sudoers.d/90-$USER_NAME"
install -d -m 700 -o "$USER_NAME" -g "$USER_NAME" "/home/$USER_NAME/.ssh"
install -m 600 -o "$USER_NAME" -g "$USER_NAME" /root/.ssh/authorized_keys "/home/$USER_NAME/.ssh/authorized_keys"

echo "== 4. SSH: keys only, no root login"
cat > /etc/ssh/sshd_config.d/90-kg.conf <<'CONF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
CONF
sshd -t
systemctl reload ssh

echo "== 5. Firewall: only 22 (SSH) and 443 (HTTPS, for the application later)"
# The databases are published on 127.0.0.1 only (platform/docker-compose.yml), so they are not reachable from
# outside even though Docker's published ports bypass ufw. Never publish them on 0.0.0.0.
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 443/tcp
ufw --force enable

echo "== 6. Folders: the repository, K1 releases, backups"
install -d -o "$USER_NAME" -g "$USER_NAME" /srv/kg /srv/k1 /srv/backups

echo
echo "Done. From a SECOND terminal on your computer, check:  ssh $USER_NAME@<server address>"
echo "Only then close this root session: root can no longer log in over SSH."
