# Bright Berry

Local console for two 16×96 LED panels, shown as one 16×192 sign. It plays a library of text and pictures, then local weather, and keeps going on its own.

## Run

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m app
```

Open http://127.0.0.1:8765. On Windows, `activate.cmd` connects the saved panels and starts the playlist.

## Raspberry Pi

Use a Pi with Bluetooth (Pi 4, Pi 5, or Zero 2 W), a keyboard, a monitor, and Raspberry Pi OS 64-bit with desktop. Lite has no kiosk desktop. The panels use their own power and Bluetooth. The Pi does not drive them from GPIO.

In Raspberry Pi Imager, set the username, password, Wi-Fi, locale, and timezone. Put that card in the Pi and boot it. Open Terminal on the Pi desktop.

```bash
sudo apt-get update
sudo apt-get full-upgrade -y
sudo reboot
```

Plug in the drive that has the `ledmatrix` folder. Raspberry Pi OS mounts it under `/media/$USER/`. Copy it onto the Pi before installing. The service keeps running after the drive is unplugged, so it cannot stay on the drive.

```bash
ls /media/$USER
cp -a /media/$USER/DRIVENAME/ledmatrix ~/ledmatrix
rm -rf ~/ledmatrix/.venv
cd ~/ledmatrix
sed -i 's/\r$//' deploy/install-pi.sh deploy/ledmatrix.service
sudo bash deploy/install-pi.sh
```

`sed` strips Windows line endings. Without that, bash stops on line 3 with `set: pipefail: invalid option name`.

Replace `DRIVENAME` with the name from `ls`. If `app` and `deploy` are on the root of the drive, copy that folder instead:

```bash
cp -a /media/$USER/DRIVENAME ~/ledmatrix
```

The installer updates packages, installs Python, BlueZ, libgpiod, and Chromium, creates `.venv`, installs `requirements.txt`, and adds your user to `bluetooth`, `input`, and `gpio`. It enables `ledmatrix.service`, which starts `python -m app` at boot with `LEDMATRIX_ACTIVATE=1` so saved panels reconnect. Chromium opens full screen to http://127.0.0.1:8765/?kiosk=1. The console listens only on the Pi.

Wire the DHT11 before the last reboot:

| DHT11 | Pi |
| --- | --- |
| VCC | 3.3V (physical pin 1) |
| GND | Ground (physical pin 6) |
| DATA | GPIO 4 (physical pin 7) |

GPIO 4 is the default. Override it with `LEDMATRIX_DHT_PIN`. Plug the USB number pad into the Pi.

```bash
sudo reboot
```

After boot, check the service:

```bash
systemctl status ledmatrix
journalctl -u ledmatrix -n 50 --no-pager
curl -s http://127.0.0.1:8765/api/status
rfkill unblock bluetooth
bluetoothctl show
```

Power both panels, then in the dashboard scan and assign left and right. Addresses stay in `data/config.json`. The number pad works with no monitor.

If the desktop goes black, turn screen blanking off: `sudo raspi-config`, then Display, Screen Blanking, No.

To run it by hand, stop the service first so port 8765 is free:

```bash
sudo systemctl stop ledmatrix
cd ~/ledmatrix
.venv/bin/python -m app
```

## Layout

- `app/` — sign protocol, playlist, weather, DHT11, and USB number pad
- `static/` — dashboard
- `tests/` — unit tests
- `deploy/` — Raspberry Pi service and kiosk install

Panel addresses, the library, and number-pad commands stay in `data/` and are not part of the repo.
