.pragma library

// Caps applied to everything that crosses into the shell process. The values
// are generous for real data and small enough that a malformed source cannot
// materialize unbounded inside a session-long process.
var MAX_INPUT_CHARS = 256 * 1024
var MAX_LINES = 200
var MAX_DISPLAY_CHARS = 200
var MAX_ITEMS = 32

var DPI_MIN = 50
var DPI_MAX = 12000

// Everything here can reach a QML Text or a kit component (Dropdown draws its
// own labels) whose Text defaults to Text.AutoText, which sniffs markup. Our
// own Text elements also set textFormat explicitly; this covers the rest.
function plain(value, max) {
  var out = String(value === undefined || value === null ? "" : value)
    .replace(/[\x00-\x1f\x7f]/g, " ")
    .replace(/[<>&]/g, "")
  var cap = max || MAX_DISPLAY_CHARS
  return out.length > cap ? out.slice(0, cap) + "…" : out
}

function capInput(raw) {
  var text = String(raw || "")
  return text.length > MAX_INPUT_CHARS ? text.slice(0, MAX_INPUT_CHARS) : text
}

// `keychron-ctl status` prints one `key=value` per line.
function parseStatus(raw) {
  var out = {}
  var lines = capInput(raw).split("\n")
  if (lines.length > MAX_LINES) lines = lines.slice(0, MAX_LINES)
  for (var i = 0; i < lines.length; i++) {
    var line = lines[i].trim()
    var eq = line.indexOf("=")
    if (eq <= 0) continue
    var key = line.slice(0, eq)
    if (!/^[a-z0-9-]{1,32}$/.test(key)) continue
    out[key] = line.slice(eq + 1).slice(0, 256)
  }
  return out
}

function toInt(value, fallback) {
  var n = parseInt(value, 10)
  return isFinite(n) ? n : fallback
}

function toBool(value) {
  var s = String(value)
  return s === "true" || s === "1"
}

// "400,800,1600" -> [400, 800, 1600]; non-numbers dropped, list capped.
function intList(value) {
  var out = []
  var parts = String(value || "").split(",")
  for (var i = 0; i < parts.length && out.length < MAX_ITEMS; i++) {
    var n = parseInt(parts[i], 10)
    if (isFinite(n)) out.push(n)
  }
  return out
}

// The mouse accepts DPI in steps (50 on the M6) between 50 and 12000.
function snapDpi(value, step, max) {
  var s = step > 0 ? step : 50
  var hi = max > 0 ? Math.min(max, DPI_MAX) : DPI_MAX
  var snapped = Math.round(value / s) * s
  return Math.max(DPI_MIN, Math.min(hi, snapped))
}

function deviceIcon() {
  return "󰍽"
}

function connectionLabel(connection) {
  if (connection === "receiver") return "2.4 GHz"
  if (connection === "usb") return "USB"
  if (connection === "bluetooth") return "Bluetooth"
  return ""
}

function isPresent(status) {
  return String(status.present || "") === "true"
}

function battery(status) {
  var n = toInt(status.battery, -1)
  return n >= 0 && n <= 100 ? n : -1
}

// One line under the device name. Before the first read lands there is
// nothing to conclude, so it says "Checking…" rather than "Disconnected".
function stateKey(status, everLoaded) {
  if (!everLoaded) return "checking"
  if (status.access === "denied" && !isPresent(status)) return "denied"
  if (!isPresent(status)) return "disconnected"
  if (status.link === "asleep") return "asleep"
  if (toBool(status.charging)) return battery(status) >= 100 ? "full" : "charging"
  return "connected"
}

function isLow(status, threshold) {
  var b = battery(status)
  return isPresent(status) && b >= 0 && b <= threshold && !toBool(status.charging)
}

// [{value: "2", label: "Level 3 · 1600 DPI"}] for the active-level picker.
function levelOptions(levels, count, labelFormat) {
  var out = []
  var n = Math.min(levels.length, count > 0 ? count : levels.length)
  for (var i = 0; i < n; i++)
    out.push({ value: String(i), label: plain(String(labelFormat).replace("%1", i + 1).replace("%2", levels[i]), 48) })
  return out
}

function rateOptions(rates) {
  var out = []
  for (var i = 0; i < rates.length; i++)
    if (rates[i] > 0) out.push({ value: String(rates[i]), label: rates[i] + " Hz" })
  return out
}

// `keychron-ctl buttons get` JSON, validated and bounded. Anything malformed
// returns null so the panel keeps its last good copy.
function parseButtons(raw) {
  var data
  try {
    data = JSON.parse(capInput(raw))
  } catch (e) {
    return null
  }
  if (!data || !Array.isArray(data.buttons) || !Array.isArray(data.actions)) return null
  var buttons = []
  for (var i = 0; i < data.buttons.length && buttons.length < MAX_ITEMS; i++) {
    var b = data.buttons[i]
    if (!b || typeof b.index !== "number" || b.index < 0 || b.index > 31) continue
    buttons.push({
      index: b.index,
      name: plain(b.name, 40),
      help: plain(b.help, 200),
      action: plain(b.action, 32),
      argument: plain(b.argument, 64)
    })
  }
  var actions = []
  for (var j = 0; j < data.actions.length && actions.length < 64; j++) {
    var a = data.actions[j]
    if (!a || typeof a.id !== "string" || !/^[a-z0-9-]{1,32}$/.test(a.id)) continue
    actions.push({ value: a.id, label: plain(a.label, 40), kind: a.kind === "shortcut" ? "shortcut" : "plain" })
  }
  return { buttons: buttons, actions: actions }
}

// "Super + Shift + F13" -> "super+shift+f13"; null when it is not a shortcut
// the mouse can store (up to four modifiers and one key).
function normalizeShortcut(text) {
  var parts = String(text || "").toLowerCase().split("+")
  var out = []
  for (var i = 0; i < parts.length; i++) {
    var p = parts[i].trim()
    if (p === "") continue
    if (p === "control") p = "ctrl"
    if (p === "win" || p === "meta" || p === "cmd") p = "super"
    if (!/^[a-z0-9]{1,12}$/.test(p)) return null
    out.push(p)
  }
  if (out.length === 0 || out.length > 5) return null
  var mods = { ctrl: 1, shift: 1, alt: 1, super: 1 }
  for (var j = 0; j < out.length - 1; j++)
    if (!mods[out[j]]) return null
  if (mods[out[out.length - 1]]) return null
  return out.join("+")
}
