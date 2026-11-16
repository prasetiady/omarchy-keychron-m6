# omarchy-keychron-m6

An [Omarchy](https://omarchy.org/) bar widget for the Keychron M6 mouse. It
shows the battery in the bar and lets you change the mouse settings from a
panel, without the Keychron Launcher web app.

<p align="center">
  <img src="preview.png" alt="The Keychron M6 panel open from the Omarchy bar, connected over 2.4 GHz at 97% battery, with the active DPI level, polling rate, Motion Sync, Angle Snapping, and Ripple Control toggles, Flat pointer acceleration, and the sleep and click debounce sliders" width="340">
</p>

Built and tested against a **Keychron M6 Ultra Silent (M6S-A72)**: PixArt 3311
sensor, 1000 Hz, USB ID `3434:d064`. It works over all three connections:

| Connection | How the widget reaches the mouse |
|---|---|
| 2.4 GHz Keychron Link receiver | Through the receiver (`3434:d026` or `3434:d029`) |
| USB-C cable | Directly; this path also reports charging |
| Bluetooth | Directly when the Bluetooth HID map exposes the vendor page; otherwise battery from UPower only |

## What the panel does

- Battery percentage and charging state, in the bar and in the panel. The bar
  icon turns the urgent color at or below the low-battery threshold.
- DPI: pick the active level and change its value (50–12000, steps of 50).
- Polling rate: 125, 500, or 1000 Hz.
- Pointer acceleration: Flat or Adaptive, through Hyprland.
- Sleep timer and click debounce.
- Button remapping for the middle, right, side, wheel-tilt, wheel, and thumb
  wheel inputs. Left click is not offered, so a remap cannot lock you out.
- Restore factory defaults.

Mouse settings are written to the mouse's onboard memory. They persist across
reboots and follow the mouse to other computers. Pointer acceleration is the
exception: it is a Hyprland setting for this computer only.

### About Motion Sync and Angle Snapping

Keychron's own device definition for the 3311 version of the M6 marks the
sensor options (Motion Sync, Angle Snapping, Ripple Control) as unsupported,
and the Keychron Launcher hides them. The panel shows them only when the mouse
reports them in its settings.

## How it talks to the mouse

The M6 has no HID++ or Solaar support. It speaks Keychron's vendor protocol on
HID usage page `0xFFC1` (output reports `0xB3`/`0xB5`, replies on
`0xB4`/`0xB6`), the same one the Keychron Launcher uses through WebHID. The
`keychron-ctl` helper (Python 3, standard library only) is the only part that
touches the device:

```bash
~/.config/omarchy/plugins/keychron-m6.panel/keychron-ctl status
~/.config/omarchy/plugins/keychron-m6.panel/keychron-ctl set dpi-active 2
~/.config/omarchy/plugins/keychron-m6.panel/keychron-ctl set rate 1000
~/.config/omarchy/plugins/keychron-m6.panel/keychron-ctl buttons set 9 shortcut super+shift+f13
~/.config/omarchy/plugins/keychron-m6.panel/keychron-ctl probe
```

`probe` prints the raw replies. Attach its output to a bug report.

## Requirements

- Omarchy with the Quickshell-based shell (`omarchy-shell`)
- Python 3
- A Keychron M6 (`3434:d064`)

## Install

```bash
omarchy plugin add https://github.com/prasetiady/omarchy-keychron-m6.git --enable
```

### Manual setup

The plugin does not change system files or your Hyprland config for you.

1. To give your user access to the mouse's HID raw nodes, install the udev
   rule:

   ```bash
   cd ~/.config/omarchy/plugins/keychron-m6.panel
   sudo install -m 644 70-keychron-m6.rules /etc/udev/rules.d/
   sudo udevadm control --reload && sudo udevadm trigger --subsystem-match=hidraw
   ```

   Without the rule, the panel shows "No access: install the udev rule".

2. To let the panel set pointer acceleration, add this line to
   `~/.config/hypr/input.lua`:

   ```lua
   dofile(os.getenv("HOME") .. "/.config/omarchy/plugins/keychron-m6.panel/hypr/accel.lua")
   ```

   The widget stores your choice as plain data in
   `~/.local/state/keychron-m6/`, and `accel.lua` validates it before it calls
   `hl.device`. Without this line, the Acceleration setting has no effect.

## Development

To load the widget from a clone:

```bash
ln -s "$PWD" ~/.config/omarchy/plugins/keychron-m6.panel
omarchy plugin enable keychron-m6.panel
```

The shell does not watch a symlinked plugin folder for changes. To load an
edit to `Panel.qml` or `Model.js`, run `omarchy restart shell`.

To run the tests, which use a fake sysfs tree and a fake HID transport, not the
mouse:

```bash
tests/run
```

## Uninstall

Reset the mouse first if you changed buttons, because removing the plugin
does not undo settings stored on the mouse:

```bash
~/.config/omarchy/plugins/keychron-m6.panel/keychron-ctl reset
omarchy plugin remove keychron-m6.panel
```

Then remove the `dofile` line from `~/.config/hypr/input.lua`, and remove the
udev rule with `sudo rm /etc/udev/rules.d/70-keychron-m6.rules`.

## Credits

The protocol details come from the Keychron Launcher's own client code, with
help from
[keychron-battery-dkms](https://github.com/csutcliff/keychron-battery-dkms),
[chron-tui](https://github.com/kubastick/chron-tui), and the
[Darmoshark M3 protocol notes](https://github.com/Barba2k2/darmoshark-m3-configurator/blob/main/PROTOCOL.md).
The widget layout follows
[omarchy-mx-master](https://github.com/gastonmira/omarchy-mx-master).
