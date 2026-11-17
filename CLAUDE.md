# omarchy-keychron-m6

Omarchy bar widget for the Keychron M6, PixArt 3311 version only (USB ID
`3434:d064`, M6S-A72). `README.md` covers what it does and how to install it.

## Map

- `keychron-ctl`: the only code that opens the mouse. Python 3, standard
  library only. Opcodes and snapshot offsets live in its constants and in
  `parse_snapshot`.
- `Panel.qml`, `Model.js`, `WheelGuard.qml`: the bar widget. `Model.js` holds
  the pure logic that `tests/model.test.mjs` covers.
- `hypr/pointer.lua`: applies acceleration and scroll speed from
  `~/.local/state/keychron-m6/`.
- `70-keychron-m6.rules`: the udev rule users install by hand.
- `tests/run`: the whole suite. It uses a fake sysfs tree and a socketpair
  transport, plus bytes captured from a real M6S-A72.

## Conventions

- Every write to the mouse reads the value back and exits `1` on a mismatch.
  The README promises this.
- Hyprland settings are stored as plain data and validated in `pointer.lua`,
  never written as Lua: device names come from USB and Bluetooth descriptors.
- Hyprland's pointer names for the M6 appear twice, in `DEFAULT_HYPR_NAMES`
  in `keychron-ctl` and at the top of `pointer.lua`. Change both together.
- Dynamic text in QML uses `textFormat: Text.PlainText`, and strings for kit
  components go through `Model.plain()`. UI strings live in `i18n/en.json`.
- Give every `PanelSlider` a `WheelGuard`: the kit slider writes on each wheel
  step.
- After a `Dropdown` pick, restore its `value` binding with `Qt.binding`: the
  kit assigns `value` and drops the binding.

## Gotchas

- The protocol source is the Keychron Launcher's `main.js`
  (launcher.keychron.com). The M6 uses its "8k" protocol classes. Find a
  command by searching for `write(181,` (report `0xB5`) or `write(179,`
  (report `0xB3`). Opcodes that third-party notes list for other Keychron mice
  can be wrong here: button read and write are `0x62` and `0x52`.
- Probe a new command on the hardware before relying on it. `E4 07 <op>` means
  the firmware does not support it (firmware 1.0.2 lacks scroll guard, `0x6A`).
- Over Bluetooth the M6 has no vendor page `0xFFC1`, so only the battery
  (UPower) and the Hyprland settings work there.
- In the udev rule, match `ENV{ID_USB_*}`. A rule that combines `KERNELS` with
  `ATTRS{bInterfaceNumber}` never matches, because udev checks all parent keys
  against one device.
- A plugin folder symlinked into `~/.config/omarchy/plugins/` does not
  hot-reload. Run `omarchy restart shell` after a QML or `Model.js` edit.
