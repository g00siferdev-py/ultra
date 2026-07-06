#!/usr/bin/env bash
# Runs inside the debootstrapped chroot (qemu-arm-static on cross-build hosts).
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

HOSTNAME="${HOSTNAME:-ultra}"
ULTRA_USER="${ULTRA_USER:-ultra}"
ULTRA_SRC="${ULTRA_SRC:-/opt/ultra-src}"

echo "[chroot] Configuring apt sources..."
cat > /etc/apt/sources.list <<EOF
deb http://deb.debian.org/debian bookworm main contrib non-free non-free-firmware
deb http://deb.debian.org/debian bookworm-updates main contrib non-free non-free-firmware
deb http://security.debian.org/debian-security bookworm-security main contrib non-free non-free-firmware
EOF

cat > /etc/apt/sources.list.d/raspi.list <<EOF
deb http://archive.raspberrypi.com/debian/ bookworm main
EOF

if [ -f /tmp/raspberrypi.gpg.key ]; then
  mkdir -p /etc/apt/keyrings
  gpg --dearmor < /tmp/raspberrypi.gpg.key > /etc/apt/keyrings/raspberrypi.gpg
  sed -i 's|deb http://archive.raspberrypi.com/debian/|deb [signed-by=/etc/apt/keyrings/raspberrypi.gpg] http://archive.raspberrypi.com/debian/|' /etc/apt/sources.list.d/raspi.list
fi

echo "[chroot] Installing packages..."
apt-get update
apt-get install -y --no-install-recommends \
  openssh-server \
  network-manager \
  sudo \
  python3 \
  python3-pip \
  python3-venv \
  git \
  curl \
  ca-certificates \
  locales \
  systemd-timesyncd \
  raspi-firmware \
  linux-image-rpi-2712 \
  firmware-brcm80211 \
  bluez \
  parted \
  dosfstools \
  libgomp1 \
  arp-scan \
  avahi-utils \
  iproute2 \
  docker.io \
  containerd

echo "[chroot] Locale..."
echo "en_US.UTF-8 UTF-8" >> /etc/locale.gen
locale-gen
update-locale LANG=en_US.UTF-8

echo "[chroot] Hostname & ultra user..."
hostnamectl set-hostname "${HOSTNAME}" 2>/dev/null || echo "${HOSTNAME}" > /etc/hostname
useradd -m -s /bin/bash -G sudo,netdev,docker "${ULTRA_USER}" 2>/dev/null || usermod -aG docker "${ULTRA_USER}" 2>/dev/null || true
echo "${ULTRA_USER}:ultra" | chpasswd
passwd -e "${ULTRA_USER}" >/dev/null 2>&1 || true
echo "${ULTRA_USER} ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/${ULTRA_USER}"
chmod 440 "/etc/sudoers.d/${ULTRA_USER}"

echo "[chroot] SSH..."
sed -i 's/#PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config
systemctl enable ssh

echo "[chroot] NetworkManager..."
systemctl enable NetworkManager

echo "[chroot] Boot firmware config (Pi 5)..."
mkdir -p /boot/firmware
if [ ! -f /boot/firmware/config.txt ]; then
  cat > /boot/firmware/config.txt <<'EOF'
# Linux Ultra — Raspberry Pi 5
arm_64bit=1
kernel=kernel_2712.img
disable_overscan=1
EOF
fi

if [ ! -f /boot/firmware/cmdline.txt ]; then
  echo "console=serial0,115200 console=tty1 root=ROOTDEV rootfstype=ext4 fsck.repair=yes rootwait quiet" > /boot/firmware/cmdline.txt
fi

echo "[chroot] Install Linux Ultra agent..."
python3 -m venv /opt/ultra/venv
/opt/ultra/venv/bin/pip install --upgrade pip
/opt/ultra/venv/bin/pip install "${ULTRA_SRC}"
ln -sf /opt/ultra/venv/bin/ultra /usr/local/bin/ultra

mkdir -p /etc/ultra /var/ultra/workspace /var/log/ultra /var/lib/ultra /var/lib/ultra/fastembed /var/lib/homeassistant
cp -r "${ULTRA_SRC}/tasks" /etc/ultra/tasks

echo "[chroot] Preload baked-in memory embed model (fastembed ONNX)..."
export FASTEMBED_CACHE_PATH=/var/lib/ultra/fastembed
/opt/ultra/venv/bin/python "${ULTRA_SRC}/deploy/scripts/preload-embed-model.py" && \
  touch /var/lib/ultra/embed-ready || {
  echo "[chroot] Warning: embed preload failed (network?). First boot will retry."
}

echo "[chroot] Default memory config snippet..."
cat > /etc/ultra/memory.defaults.yaml <<'EOF'
memory:
  enabled: true
  embed_backend: fastembed
  embed_model: nomic-embed-text
  embed_cache_dir: /var/lib/ultra/fastembed
EOF

echo "[chroot] Default smart home config snippet..."
cat > /etc/ultra/smart-home.defaults.yaml <<'EOF'
smart_home:
  home_assistant:
    enabled: true
    url: "http://127.0.0.1:8123"
    token: ""
    token_file: "/var/ultra/workspace/projects/smart-home/secrets/ha-token.txt"
EOF

echo "[chroot] Systemd units..."
cp /tmp/ultra-deploy/systemd/ultra-tasks.service /etc/systemd/system/
cp /tmp/ultra-deploy/systemd/ultra-tasks.timer /etc/systemd/system/
cp /tmp/ultra-deploy/systemd/ultra-setup.service /etc/systemd/system/
cp /tmp/ultra-deploy/systemd/ultra-expand-root.service /etc/systemd/system/
cp /tmp/ultra-deploy/systemd/ultra-embed-preload.service /etc/systemd/system/
cp /tmp/ultra-deploy/systemd/ultra-memory-embed.service /etc/systemd/system/
cp /tmp/ultra-deploy/systemd/ultra-memory-embed.timer /etc/systemd/system/
cp /tmp/ultra-deploy/systemd/ultra-homeassistant-pull.service /etc/systemd/system/
cp /tmp/ultra-deploy/systemd/ultra-homeassistant.service /etc/systemd/system/
install -m 755 /tmp/ultra-deploy/scripts/homeassistant-container.sh /usr/local/sbin/ultra-homeassistant
systemctl enable docker.service
systemctl enable ultra-expand-root.service
systemctl enable ultra-embed-preload.service
systemctl enable ultra-memory-embed.timer
systemctl enable ultra-homeassistant-pull.service
systemctl enable ultra-homeassistant.service
systemctl enable ultra-tasks.timer
systemctl enable ultra-setup.service

cp /tmp/ultra-deploy/profile.d/ultra-setup.sh /etc/profile.d/ultra-setup.sh
chmod 644 /etc/profile.d/ultra-setup.sh

echo "[chroot] Branding overlay..."
if [ -d /tmp/ultra-overlay ]; then
  cp -a /tmp/ultra-overlay/. /
fi

echo "[chroot] Cleanup..."
apt-get clean
rm -rf /var/lib/apt/lists/*

echo "[chroot] Done."
