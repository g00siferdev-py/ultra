#!/usr/bin/env bash
# Build Linux Ultra — flashable Raspberry Pi 5 (arm64) image.
#
# Run on Debian/Ubuntu or WSL2 (as root):
#   sudo ./iso/build.sh
#
# Output: dist/linux-ultra-pi5-1.0.img
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=config.sh
source "${SCRIPT_DIR}/config.sh"

log() { echo "==> $*"; }
die() { echo "ERROR: $*" >&2; exit 1; }

if [ "$(id -u)" -ne 0 ]; then
  die "Run as root: sudo ./iso/build.sh"
fi

if [ "$(uname -s)" = "Linux" ]; then
  :
else
  die "Image build requires Linux or WSL2. Current OS: $(uname -s)"
fi

for cmd in debootstrap parted mkfs.ext4 mkfs.vfat rsync partprobe losetup; do
  command -v "${cmd}" >/dev/null 2>&1 || die "Missing command: ${cmd}"
done

# Cross-arch build on x86_64
if [ "$(uname -m)" = "x86_64" ] && [ "${ARCH}" = "arm64" ]; then
  if [ ! -f /usr/bin/qemu-aarch64-static ]; then
    die "Install qemu-user-static for cross-build: apt install qemu-user-static binfmt-support"
  fi
  if [ ! -f /proc/sys/fs/binfmt_misc/qemu-aarch64 ]; then
    die "Enable binfmt: systemctl restart systemd-binfmt"
  fi
fi

mkdir -p "${WORK_DIR}" "${OUTPUT_DIR}" "${ROOTFS}"

# --- Stage 1: debootstrap ---
if [ ! -f "${ROOTFS}/etc/debian_version" ]; then
  log "Stage 1: debootstrap ${SUITE} ${ARCH}"
  debootstrap --arch="${ARCH}" --variant=minbase \
    --include=systemd,systemd-sysv,sudo,ca-certificates,gnupg \
    "${SUITE}" "${ROOTFS}" "${DEBIAN_MIRROR}"
else
  log "Stage 1: reusing existing rootfs at ${ROOTFS}"
fi

# --- Stage 2: chroot setup ---
log "Stage 2: chroot setup"
QEMU_BIN="/usr/bin/qemu-aarch64-static"
if [ -f "${QEMU_BIN}" ]; then
  cp "${QEMU_BIN}" "${ROOTFS}/usr/bin/"
fi

mount -t proc proc "${ROOTFS}/proc"
mount -t sysfs sysfs "${ROOTFS}/sys"
mount --bind /dev "${ROOTFS}/dev"
mount --bind /dev/pts "${ROOTFS}/dev/pts"

cleanup_mounts() {
  umount -lf "${ROOTFS}/dev/pts" 2>/dev/null || true
  umount -lf "${ROOTFS}/dev" 2>/dev/null || true
  umount -lf "${ROOTFS}/sys" 2>/dev/null || true
  umount -lf "${ROOTFS}/proc" 2>/dev/null || true
}
trap cleanup_mounts EXIT

# Copy source and assets into chroot
rm -rf "${ROOTFS}${ULTRA_SRC_IN_IMAGE}"
mkdir -p "${ROOTFS}${ULTRA_SRC_IN_IMAGE}"
rsync -a --exclude '.git' --exclude 'iso/work' --exclude 'dist' --exclude 'workspace' \
  --exclude '__pycache__' --exclude '*.egg-info' --exclude 'config.local.yaml' \
  "${REPO_ROOT}/" "${ROOTFS}${ULTRA_SRC_IN_IMAGE}/"

mkdir -p "${ROOTFS}/tmp/ultra-deploy" "${ROOTFS}/tmp/ultra-overlay"
rsync -a "${REPO_ROOT}/deploy/" "${ROOTFS}/tmp/ultra-deploy/"
rsync -a "${SCRIPT_DIR}/overlay/" "${ROOTFS}/tmp/ultra-overlay/"
install -m 755 "${REPO_ROOT}/deploy/scripts/ultra-expand-root" "${ROOTFS}/usr/local/sbin/ultra-expand-root"

# Raspberry Pi apt signing key
if curl -fsSL https://archive.raspberrypi.com/debian/raspberrypi.gpg.key -o "${ROOTFS}/tmp/raspberrypi.gpg.key"; then
  :
else
  log "Warning: could not download Raspberry Pi apt key"
fi

cp "${SCRIPT_DIR}/scripts/chroot-setup.sh" "${ROOTFS}/tmp/chroot-setup.sh"
chmod +x "${ROOTFS}/tmp/chroot-setup.sh"

HOSTNAME="${HOSTNAME}" ULTRA_USER="${ULTRA_USER}" ULTRA_SRC="${ULTRA_SRC_IN_IMAGE}" \
  chroot "${ROOTFS}" /bin/bash /tmp/chroot-setup.sh

rm -f "${ROOTFS}/tmp/chroot-setup.sh" "${ROOTFS}/tmp/raspberrypi.gpg.key"
rm -rf "${ROOTFS}/tmp/ultra-deploy" "${ROOTFS}/tmp/ultra-overlay"
rm -f "${ROOTFS}/usr/bin/qemu-aarch64-static"

cleanup_mounts
trap - EXIT

# --- Stage 3: create disk image ---
log "Stage 3: create image ${IMAGE_PATH}"
rm -f "${IMAGE_PATH}"
truncate -s "${IMAGE_SIZE}" "${IMAGE_PATH}"

parted -s "${IMAGE_PATH}" mklabel gpt
parted -s "${IMAGE_PATH}" mkpart boot fat32 8192s "${BOOT_SIZE}"
parted -s "${IMAGE_PATH}" mkpart root ext4 "${BOOT_SIZE}" 100%
parted -s "${IMAGE_PATH}" set 1 boot on

LOOP=$(losetup -Pf --show "${IMAGE_PATH}")
BOOT_PART="${LOOP}p1"
ROOT_PART="${LOOP}p2"
sleep 1

mkfs.vfat -F 32 -n BOOT "${BOOT_PART}"
mkfs.ext4 -L ultra-root "${ROOT_PART}"

MNT="${WORK_DIR}/mnt"
BOOT_MNT="${WORK_DIR}/bootmnt"
mkdir -p "${MNT}" "${BOOT_MNT}"
mount "${ROOT_PART}" "${MNT}"
mkdir -p "${MNT}/boot/firmware"
mount "${BOOT_PART}" "${MNT}/boot/firmware"

log "Copying rootfs to image..."
rsync -aHAX "${ROOTFS}/" "${MNT}/"

# Sync boot firmware to FAT partition
if [ -d "${MNT}/boot/firmware" ]; then
  rsync -a "${MNT}/boot/firmware/" "${BOOT_MNT}/"
fi

ROOT_UUID=$(blkid -s PARTUUID -o value "${ROOT_PART}")
BOOT_UUID=$(blkid -s PARTUUID -o value "${BOOT_PART}")

# fstab
cat > "${MNT}/etc/fstab" <<EOF
PARTUUID=${BOOT_UUID}  /boot/firmware  vfat    defaults          0  2
PARTUUID=${ROOT_UUID}  /               ext4    defaults,noatime  0  1
EOF

# cmdline.txt with real root PARTUUID
if [ -f "${BOOT_MNT}/cmdline.txt" ]; then
  sed -i "s|ROOTDEV|PARTUUID=${ROOT_UUID}|g" "${BOOT_MNT}/cmdline.txt"
  cp "${BOOT_MNT}/cmdline.txt" "${MNT}/boot/firmware/cmdline.txt"
elif [ -f "${MNT}/boot/firmware/cmdline.txt" ]; then
  sed -i "s|ROOTDEV|PARTUUID=${ROOT_UUID}|g" "${MNT}/boot/firmware/cmdline.txt"
  cp "${MNT}/boot/firmware/cmdline.txt" "${BOOT_MNT}/cmdline.txt"
fi

sync
umount "${BOOT_MNT}"
umount "${MNT}"
losetup -d "${LOOP}"

log "Done."
log "Image: ${IMAGE_PATH}"
BYTES=$(stat -c%s "${IMAGE_PATH}" 2>/dev/null || stat -f%z "${IMAGE_PATH}")
log "Size:  $(( BYTES / 1024 / 1024 )) MB"
log ""
log "Flash to Pi 5 NVMe (from Linux):"
log "  xz -dk ${IMAGE_PATH}.xz   # if compressed"
log "  sudo dd if=${IMAGE_PATH} of=/dev/nvme0n1 bs=4M status=progress conv=fsync"
log ""
log "Or build in CI: push to GitHub and run Actions workflow, download artifact."
log ""
log "First boot: SSH to ultra.local, run: ultra setup --prod"
