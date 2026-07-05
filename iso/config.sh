# Linux Ultra image build configuration
# shellcheck disable=SC2034

DISTRO_NAME="Linux Ultra"
DISTRO_VERSION="1.0"
HOSTNAME="ultra"

ARCH="${ARCH:-arm64}"
SUITE="${SUITE:-bookworm}"
IMAGE_SIZE="${IMAGE_SIZE:-4G}"
BOOT_SIZE="${BOOT_SIZE:-512MiB}"

# Debian + Raspberry Pi firmware/kernel (Pi 5 / bcm2712)
DEBIAN_MIRROR="${DEBIAN_MIRROR:-http://deb.debian.org/debian}"
RPI_MIRROR="${RPI_MIRROR:-http://archive.raspberrypi.com/debian}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

WORK_DIR="${WORK_DIR:-${SCRIPT_DIR}/work}"
ROOTFS="${ROOTFS:-${WORK_DIR}/rootfs}"
OUTPUT_DIR="${OUTPUT_DIR:-${REPO_ROOT}/dist}"
IMAGE_NAME="${IMAGE_NAME:-linux-ultra-pi5-${DISTRO_VERSION}.img}"
IMAGE_PATH="${OUTPUT_DIR}/${IMAGE_NAME}"

ULTRA_USER="ultra"
ULTRA_SRC_IN_IMAGE="/opt/ultra-src"
