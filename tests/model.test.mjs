// Model.js under node:test.
//
// It is a QML `.pragma library`: plain JavaScript with one directive on top.
// Strip that line and the file evaluates as a function body.

import { test } from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { dirname, join } from "node:path"

const root = dirname(dirname(fileURLToPath(import.meta.url)))
const source = readFileSync(join(root, "Model.js"), "utf8").replace(/^\.pragma library\s*$/m, "")
const exported = [
  "MAX_INPUT_CHARS", "MAX_LINES", "plain", "capInput", "parseStatus", "toInt", "toBool",
  "intList", "snapDpi", "connectionLabel", "battery", "stateKey", "isLow",
  "levelOptions", "rateOptions", "parseButtons", "normalizeShortcut",
]
const Model = new Function(`${source}\nreturn {${exported.join(",")}}`)()

test("plain strips markup and control characters", () => {
  assert.equal(Model.plain('<img src="https://example.invalid/t">x'), 'img src="https://example.invalid/t"x')
  assert.equal(Model.plain("a\u0001b"), "a b")
  assert.equal(Model.plain("x".repeat(300), 10), "xxxxxxxxxx…")
})

test("parseStatus keeps well-formed keys only", () => {
  const s = Model.parseStatus("present=true\nbattery=85\nBAD KEY=1\n=nokey\ndpi-levels=400,800\n")
  assert.deepEqual(s, { present: "true", battery: "85", "dpi-levels": "400,800" })
})

test("parseStatus caps lines and input", () => {
  const raw = Array.from({ length: 1000 }, (_, i) => `k${i}=v`).join("\n")
  assert.equal(Object.keys(Model.parseStatus(raw)).length, Model.MAX_LINES)
  assert.equal(Model.capInput("x".repeat(Model.MAX_INPUT_CHARS + 10)).length, Model.MAX_INPUT_CHARS)
})

test("battery is -1 outside 0..100", () => {
  assert.equal(Model.battery({ battery: "85" }), 85)
  assert.equal(Model.battery({ battery: "150" }), -1)
  assert.equal(Model.battery({}), -1)
})

test("stateKey covers every state", () => {
  assert.equal(Model.stateKey({}, false), "checking")
  assert.equal(Model.stateKey({ present: "false", access: "denied" }, true), "denied")
  assert.equal(Model.stateKey({ present: "false" }, true), "disconnected")
  assert.equal(Model.stateKey({ present: "true", link: "asleep" }, true), "asleep")
  assert.equal(Model.stateKey({ present: "true", link: "ok", charging: "true", battery: "40" }, true), "charging")
  assert.equal(Model.stateKey({ present: "true", link: "ok", charging: "true", battery: "100" }, true), "full")
  assert.equal(Model.stateKey({ present: "true", link: "ok", charging: "false" }, true), "connected")
})

test("isLow ignores a charging mouse", () => {
  assert.equal(Model.isLow({ present: "true", battery: "10", charging: "false" }, 15), true)
  assert.equal(Model.isLow({ present: "true", battery: "10", charging: "true" }, 15), false)
  assert.equal(Model.isLow({ present: "true", battery: "50", charging: "false" }, 15), false)
})

test("snapDpi clamps and snaps", () => {
  assert.equal(Model.snapDpi(1234, 50, 12000), 1250)
  assert.equal(Model.snapDpi(10, 50, 12000), 50)
  assert.equal(Model.snapDpi(30000, 50, 12000), 12000)
})

test("level and rate options", () => {
  assert.deepEqual(Model.levelOptions([400, 800], 2, "Level %1 · %2 DPI"), [
    { value: "0", label: "Level 1 · 400 DPI" },
    { value: "1", label: "Level 2 · 800 DPI" },
  ])
  assert.deepEqual(Model.rateOptions(Model.intList("125,500,x,1000")), [
    { value: "125", label: "125 Hz" }, { value: "500", label: "500 Hz" }, { value: "1000", label: "1000 Hz" },
  ])
})

test("parseButtons validates and neutralizes markup", () => {
  const raw = JSON.stringify({
    buttons: [
      { index: 3, name: "<b>Back</b>", help: "h", action: "back", argument: "" },
      { index: 99, name: "bad" },
      { name: "no index" },
    ],
    actions: [{ id: "back", label: "Back" }, { id: "BAD ID", label: "x" }, { id: "shortcut", label: "S", kind: "shortcut" }],
  })
  const parsed = Model.parseButtons(raw)
  assert.equal(parsed.buttons.length, 1)
  assert.equal(parsed.buttons[0].name, "bBack/b")
  assert.deepEqual(parsed.actions.map(a => a.value), ["back", "shortcut"])
  assert.equal(Model.parseButtons("not json"), null)
  assert.equal(Model.parseButtons('{"buttons": 1}'), null)
})

test("normalizeShortcut", () => {
  assert.equal(Model.normalizeShortcut("Super + Shift + F13"), "super+shift+f13")
  assert.equal(Model.normalizeShortcut("control+c"), "ctrl+c")
  assert.equal(Model.normalizeShortcut("super"), null)
  assert.equal(Model.normalizeShortcut("hyper+a"), null)
  assert.equal(Model.normalizeShortcut("super+<x>"), null)
})
