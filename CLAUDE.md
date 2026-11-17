# omarchy-keychron-m6

Omarchy bar widget for the Keychron M6, PixArt 3311 version only (USB ID
`3434:d064`, M6S-A72). `README.md` covers what it does and how to install it.

## Map

- `keychron-ctl`: the only code that opens the mouse. Python 3, standard
  library only. Opcodes and snapshot offsets live in its constants and in
  `parse_snapshot`.
- `Panel.qml`, `Model.js`, `WheelGuard.qml`, `i18n/en.json`: the bar widget.
- `hypr/pointer.lua`: applies acceleration and scroll speed from
  `~/.local/state/keychron-m6/`.
- `70-keychron-m6.rules`: the udev rule users install by hand.
- `tests/run`: the whole suite. `tests/test_structure.py` enforces the
  mechanical conventions (a `WheelGuard` on every slider, plain-text QML, UI
  strings in sync with `i18n/en.json`, matching Hyprland name lists, udev rule
  shape). When it fails, fix the code it names.

## Contracts

- **Read-back:** every write to the mouse reads the value back and exits `1`
  on a mismatch. The panel shows what the mouse stored, not what was sent.
- **Data, not code:** Hyprland settings are plain words in
  `~/.local/state/keychron-m6/`, validated in `pointer.lua`. Device names come
  from USB and Bluetooth descriptors, so nothing from them ever runs as Lua.
- **Dropdown bindings:** the kit `Dropdown` assigns `value` on a pick, which
  drops a binding to mouse state. Restore it with `Qt.binding` in `onChanged`
  when the value must keep following the mouse.

## Protocol

- The source is the Keychron Launcher's `main.js` (launcher.keychron.com). The
  M6 uses its "8k" protocol classes. Find a command by searching for
  `write(181,` (report `0xB5`) or `write(179,` (report `0xB3`). Opcodes from
  third-party notes for other Keychron mice can be wrong here: button read and
  write are `0x62` and `0x52`.
- `E4 07 <op>` means the firmware lacks the command. Firmware 1.0.2 lacks
  scroll guard (`0x6A`) and has no newer release.
- Over Bluetooth the M6 has no vendor page `0xFFC1`, so only the battery
  (UPower) and the Hyprland settings work there.

## Verify on hardware

- `./keychron-ctl probe` prints raw replies; `./keychron-ctl status` prints the
  decoded state. Settings need the receiver or the cable.
- Note the user's values first, and restore them after a write test.
- A plugin folder symlinked into `~/.config/omarchy/plugins/` does not
  hot-reload. Run `omarchy restart shell` after a QML or `Model.js` edit.
