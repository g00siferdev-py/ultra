# Building the Linux Ultra Pi image

The image is a minimal **Debian Bookworm arm64** rootfs with the **Raspberry Pi 5 kernel**, Linux Ultra pre-installed, and first-boot services enabled.

## GitHub Actions (recommended)

No Linux machine required.

1. Fork or push this repository to GitHub.
2. Open **Actions** → **Build Linux Ultra Pi Image** → **Run workflow**.
3. Wait 30–90 minutes for the first build.
4. Download the artifact:
   - `linux-ultra-pi5-1.0.img.xz`
   - `linux-ultra-pi5-1.0.img.sha256`
5. Verify: `sha256sum -c linux-ultra-pi5-1.0.img.sha256`
6. Decompress: `xz -dk linux-ultra-pi5-1.0.img.xz`

### Release builds

Pushing a version tag attaches the image to a GitHub Release:

```bash
git tag v1.0.0
git push origin v1.0.0
```

## Local build (Linux / WSL Ubuntu)

```bash
sudo apt install debootstrap qemu-user-static binfmt-support \
     parted dosfstools rsync curl gnupg e2fsprogs

cd ultra
chmod +x iso/build.sh iso/scripts/chroot-setup.sh
sudo ./iso/build.sh
```

Output: `dist/linux-ultra-pi5-1.0.img`

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `IMAGE_SIZE` | `4G` | Image file size (expands on first boot) |
| `IMAGE_NAME` | `linux-ultra-pi5-1.0.img` | Output filename |
| `WORK_DIR` | `iso/work` | Build scratch space |

## Flash to Pi 5 NVMe

### Windows — Raspberry Pi Imager

1. Install [Raspberry Pi Imager](https://www.raspberrypi.com/software/).
2. Choose **Use custom** and select `linux-ultra-pi5-1.0.img`.
3. Select your NVMe drive as the target.
4. Flash.

### Linux

```bash
# Replace /dev/nvme0n1 with your device — THIS ERASES THE DISK
sudo dd if=linux-ultra-pi5-1.0.img of=/dev/nvme0n1 bs=4M status=progress conv=fsync
```

Ensure Pi 5 EEPROM is configured for NVMe boot (default on recent firmware).

## First boot

1. Connect ethernet (recommended for first setup).
2. SSH: `ssh ultra@ultra.local`
   - Username: `ultra`
   - Default password: `ultra` (you will be prompted to change it)
3. Run setup wizard: `ultra setup --prod`
4. Verify: `ultra doctor`
5. Chat: `ultra chat`

The root partition **auto-expands** to fill your NVMe on first boot.

## What's on the image

- Debian Bookworm + `linux-image-rpi-2712` (Pi 5)
- `ultra` user with passwordless sudo (for agent orchestration)
- `ultra` CLI at `/usr/local/bin/ultra`
- systemd: `ultra-setup`, `ultra-tasks.timer`, `ultra-expand-root`
- Hostname: `ultra` — OS name: **Linux Ultra 1.0**
