#!/bin/bash
# Install Bright Berry on a Raspberry Pi and open the dashboard in kiosk mode at boot.
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run: sudo bash deploy/install-pi.sh"
  exit 1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
sed -i 's/\r$//' "$ROOT/deploy/ledmatrix.service"
OWNER="${SUDO_USER:-pi}"
HOME_DIR="$(getent passwd "$OWNER" | cut -d: -f6)"
BROWSER="$(command -v chromium || command -v chromium-browser || true)"

apt-get update
apt-get install -y python3-venv python3-pip python3-dev bluetooth bluez libgpiod2 python3-libgpiod
if [[ -z "$BROWSER" ]]; then
  apt-get install -y chromium || apt-get install -y chromium-browser
  BROWSER="$(command -v chromium || command -v chromium-browser)"
fi

sudo -u "$OWNER" python3 -m venv "$ROOT/.venv"
sudo -u "$OWNER" "$ROOT/.venv/bin/pip" install -r "$ROOT/requirements.txt"
usermod -aG bluetooth,input "$OWNER"
if getent group gpio >/dev/null; then
  usermod -aG gpio "$OWNER"
fi

sed -e "s|@USER@|$OWNER|g" -e "s|@ROOT@|$ROOT|g" "$ROOT/deploy/ledmatrix.service" \
  > /etc/systemd/system/ledmatrix.service
systemctl daemon-reload
systemctl enable --now ledmatrix.service

mkdir -p "$HOME_DIR/.config/labwc" "$HOME_DIR/.config/autostart"
AUTO="$HOME_DIR/.config/labwc/autostart"
if [[ ! -f "$AUTO" && -f /etc/xdg/labwc/autostart ]]; then
  cp /etc/xdg/labwc/autostart "$AUTO"
fi
touch "$AUTO"
KIOSK="$BROWSER --kiosk --ozone-platform=wayland --start-maximized --noerrdialogs --disable-infobars --disable-session-crashed-bubble http://127.0.0.1:8765/?kiosk=1"
if ! grep -q "kiosk=1" "$AUTO"; then
  printf '\n%s &\n' "$KIOSK" >> "$AUTO"
fi

cat > "$HOME_DIR/.config/autostart/bright-berry-kiosk.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Bright Berry
Exec=$KIOSK
X-GNOME-Autostart-enabled=true
EOF

chown -R "$OWNER:$OWNER" "$HOME_DIR/.config/labwc" "$HOME_DIR/.config/autostart" "$ROOT/data" || true
echo "Bright Berry will start at boot and open the dashboard full screen."
echo "Plug the USB number pad into the Pi. Saved keys work with no monitor."
echo "Wire the DHT11 data pin to GPIO 4, power to 3.3V, and ground to ground."
echo "Reboot the Pi so the pad can be read, then enter kiosk mode."
