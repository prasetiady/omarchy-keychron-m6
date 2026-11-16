import QtQuick
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Model.js" as Model

// Bar widget for a Keychron M6.
//
// Everything routes through `keychron-ctl`, which speaks the mouse's vendor HID
// protocol through the 2.4 GHz receiver, the USB cable, or Bluetooth. Mouse
// settings land in the mouse's onboard memory, so the panel is a view over
// device state, not a store of its own. The one exception is pointer
// acceleration, which is a Hyprland setting for this computer.
Panel {
  id: root
  moduleName: "keychron-m6.panel"
  ipcTarget: "keychron-m6.panel"

  Translations { id: strings; directory: Qt.resolvedUrl("i18n") }

  property var status: ({})
  property bool everLoaded: false

  // Optimistic overlay: until the read-back after a write lands, controls read
  // from here so they do not snap back under the pointer.
  property var pending: ({})

  property var buttonsData: ({ buttons: [], actions: [] })

  // Bar widgets get `bar`, `moduleName`, and `settings` from the host but not
  // their manifest, so the helper is found relative to this file.
  readonly property string ctl: String(Qt.resolvedUrl("keychron-ctl")).replace("file://", "")
  readonly property bool showPercentage: setting("showPercentage", true) === true
  readonly property int lowThreshold: setting("lowBatteryThreshold", 15)
  readonly property int refreshIntervalSec: setting("refreshIntervalSec", 300)

  readonly property bool present: Model.isPresent(root.status)
  readonly property bool canConfigure: root.present && Model.toBool(root.status.settings) && root.status.link === "ok"
  readonly property int battery: Model.battery(root.status)
  readonly property bool charging: Model.toBool(root.status.charging)
  readonly property bool lowBattery: Model.isLow(root.status, root.lowThreshold)

  readonly property var dpiLevels: Model.intList(root.value("dpi-levels"))
  readonly property int dpiCount: Model.toInt(root.status["dpi-count"], 5)
  readonly property int dpiActive: Model.toInt(root.value("dpi-active"), 0)
  readonly property int dpiStep: Math.max(50, Model.toInt(root.status["dpi-step"], 50))
  readonly property int dpiMax: Model.toInt(root.status["dpi-max"], 12000)
  // The thumb wheel's step per notch; 0 when it is remapped ("custom").
  readonly property int hscroll: Model.toInt(root.value("hscroll"), 0)

  // Hyprland's scroll_factor for the mouse; 0 when no value is stored.
  readonly property real scrollSpeed: {
    var n = parseFloat(root.value("scroll-speed"))
    return isFinite(n) ? n : 0
  }
  readonly property int activeDpi: root.dpiActive < root.dpiLevels.length ? root.dpiLevels[root.dpiActive] : 0

  // Current value of `key`, preferring an in-flight write over the last poll.
  function value(key) {
    if (root.pending.hasOwnProperty(key)) return root.pending[key]
    return root.status[key]
  }

  function stateText() {
    var key = Model.stateKey(root.status, root.everLoaded)
    if (key === "connected") {
      var via = Model.connectionLabel(root.status.connection)
      return via !== "" ? strings.t("state.connectedVia").arg(via) : strings.t("state.connected")
    }
    return strings.t("state." + key)
  }

  function refresh(withButtons) {
    if (!statusProc.running) statusProc.running = true
    if (withButtons && !buttonsProc.running) buttonsProc.running = true
  }

  // Writes are serialized: the receiver answers one command at a time, and
  // keychron-ctl also takes a lock so a CLI call cannot interleave.
  property var writeQueue: []
  property bool buttonsDirty: false

  function run(args, overlay) {
    if (overlay) root.pending = Object.assign({}, root.pending, overlay)
    // The thumb wheel speed is stored as two button mappings.
    if (args[0] === "buttons" || args[0] === "reset" || args[1] === "hscroll") root.buttonsDirty = true
    root.writeQueue = root.writeQueue.concat([args])
    root.drainQueue()
  }

  function setValue(key, value) {
    var overlay = {}
    overlay[key] = String(value)
    root.run(["set", key, String(value)], overlay)
  }

  function drainQueue() {
    if (writeProc.running || root.writeQueue.length === 0) return
    var job = root.writeQueue[0]
    root.writeQueue = root.writeQueue.slice(1)
    writeProc.command = [root.ctl].concat(job)
    writeProc.running = true
  }

  function setDpiForActive(v) {
    var levels = root.dpiLevels.slice()
    if (root.dpiActive >= levels.length) return
    levels[root.dpiActive] = Model.snapDpi(v, root.dpiStep, root.dpiMax)
    root.run(["set", "dpi", String(levels[root.dpiActive])], { "dpi-levels": levels.join(",") })
  }

  function togglePercentage() {
    root.settings = Object.assign({}, root.settings, { showPercentage: !root.showPercentage })
    if (root.bar && root.bar.shell) root.bar.shell.updateEntryInline(root.moduleName, root.settings)
  }

  onOpenedChanged: if (opened) refresh(true)

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  // The bar draws the open-panel underline at 55% of the slot unless the
  // widget says how wide its painted content is. With the percentage shown,
  // span from the start of "92%" to the right edge of the glyph, which sits
  // centered in a wider icon canvas.
  readonly property real openPanelIndicatorWidth: button.labelText !== "" && !button.vertical
    ? labelMetrics.advanceWidth + Style.space(4) + (button.canvasSize + button.glyphPaintedWidth) / 2
    : 0

  TextMetrics {
    id: labelMetrics
    font.family: button.fontFamily
    font.pixelSize: button.fontSize
    text: button.labelText
  }

  Process {
    id: statusProc
    command: [root.ctl, "status"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var parsed = Model.parseStatus(text)
        if (Object.keys(parsed).length === 0) return
        // A sleeping mouse answers with no settings; keep its last values and
        // let the header carry the state. An absent mouse has no values left.
        if (parsed.link === "asleep")
          root.status = Object.assign({}, root.status, parsed)
        else
          root.status = parsed
        root.pending = ({})
        root.everLoaded = true
      }
    }
  }

  Process {
    id: buttonsProc
    command: [root.ctl, "buttons", "get"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var parsed = Model.parseButtons(text)
        if (parsed && parsed.buttons.length > 0) root.buttonsData = parsed
      }
    }
  }

  Process {
    id: writeProc
    onExited: {
      if (root.writeQueue.length > 0) {
        Qt.callLater(root.drainQueue)
        return
      }
      // Read back rather than trusting the write: the panel should show what
      // the mouse actually stored.
      var withButtons = root.buttonsDirty
      root.buttonsDirty = false
      Qt.callLater(function() { root.refresh(withButtons) })
    }
  }

  // Background poll keeps the bar percentage and the low-battery tint honest
  // while the panel is closed.
  Timer {
    interval: root.refreshIntervalSec * 1000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: if (!root.opened) root.refresh(false)
  }

  Timer {
    interval: 10000
    running: root.opened
    repeat: true
    onTriggered: root.refresh(false)
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: Model.deviceIcon()
    // Same shape as the built-in battery widget: glyph plus a sized label.
    labelText: root.showPercentage && !vertical && root.battery >= 0
      ? I18n.formatNumber(root.battery) + "%"
      : ""
    slotSize: Style.bar.iconSlot * (labelText !== "" ? 2 : 1)
    active: root.lowBattery
    tooltipText: root.battery >= 0
      ? strings.t("tooltip.battery").arg(root.battery)
      : strings.t("tooltip.noBattery")
    onPressed: function(b) {
      if (b === Qt.RightButton) root.togglePercentage()
      else root.toggle()
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(400))
    contentHeight: panel.fittedContentHeight(column.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }

      Flickable {
        id: flick
        anchors.fill: parent
        contentHeight: column.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        interactive: contentHeight > height

        Column {
          id: column
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.top: parent.top
          spacing: Style.space(14)

          // ---------- Hero: icon · name/state · battery ----------
          Item {
            width: parent.width
            implicitHeight: Math.max(heroIcon.implicitHeight, heroLabels.implicitHeight, heroPercent.implicitHeight)

            Text {
              id: heroIcon
              textFormat: Text.PlainText
              text: root.charging ? "󰂄" : Model.deviceIcon()
              color: root.lowBattery ? Color.urgent : root.bar.foreground
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.display
              anchors.left: parent.left
              anchors.verticalCenter: parent.verticalCenter
              Behavior on color { ColorAnimation { duration: Style.duration(200) } }
            }

            Column {
              id: heroLabels
              anchors.left: heroIcon.right
              anchors.leftMargin: Style.space(14)
              anchors.right: heroPercent.left
              anchors.rightMargin: Style.space(10)
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(2)

              Text {
                textFormat: Text.PlainText
                text: strings.t("device.name")
                color: root.bar.foreground
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.title
                font.bold: true
                elide: Text.ElideRight
                width: parent.width
              }

              Text {
                textFormat: Text.PlainText
                text: Model.plain(root.stateText(), 64).toUpperCase()
                color: Qt.darker(root.bar.foreground, 1.4)
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.caption
                font.bold: true
                font.letterSpacing: 1.2
                elide: Text.ElideRight
                width: parent.width
              }
            }

            Text {
              id: heroPercent
              textFormat: Text.PlainText
              text: root.battery >= 0 ? root.battery + "%" : "—"
              color: root.lowBattery ? Color.urgent : root.bar.foreground
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.displayLarge
              font.bold: true
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              Behavior on color { ColorAnimation { duration: Style.duration(200) } }
            }
          }

          // ---------- Battery bar ----------
          Item {
            width: parent.width
            implicitHeight: Style.space(8)

            Rectangle {
              id: barTrack
              anchors.fill: parent
              radius: height / 2
              color: Qt.rgba(root.bar.foreground.r, root.bar.foreground.g, root.bar.foreground.b, 0.12)
            }

            Rectangle {
              anchors.left: barTrack.left
              anchors.verticalCenter: barTrack.verticalCenter
              height: barTrack.height
              radius: barTrack.radius
              color: root.lowBattery ? Color.urgent : root.bar.foreground
              width: root.battery >= 0 ? Math.max(barTrack.height, barTrack.width * root.battery / 100) : 0
              Behavior on width { NumberAnimation { duration: Style.duration(280); easing.type: Easing.OutCubic } }
              Behavior on color { ColorAnimation { duration: Style.duration(200) } }
            }
          }

          // Shown when the mouse is reachable for battery only (Bluetooth
          // without the vendor page) or is asleep.
          Text {
            width: parent.width
            visible: root.present && !root.canConfigure && root.status.link !== "asleep"
            textFormat: Text.PlainText
            text: strings.t("settings.unavailable")
            color: root.bar.foreground
            opacity: 0.6
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.WordWrap
          }

          PanelSeparator { foreground: root.bar.foreground }


          // ---------- Pointer: DPI (on the mouse) ----------
          Column {
            width: parent.width
            spacing: Style.space(8)
            visible: root.dpiLevels.length > 0
            enabled: root.canConfigure
            opacity: enabled ? 1 : 0.5

            Item {
              width: parent.width
              implicitHeight: dpiHeader.implicitHeight

              PanelSectionHeader {
                id: dpiHeader
                textFormat: Text.PlainText
                text: strings.t("section.pointer")
                foreground: root.bar.foreground
                fontFamily: root.bar.fontFamily
              }

              Text {
                anchors.right: parent.right
                anchors.verticalCenter: dpiHeader.verticalCenter
                textFormat: Text.PlainText
                text: strings.t("dpi.value").arg(dpiSlider.dragging
                  ? Model.snapDpi(dpiSlider.liveValue, root.dpiStep, root.dpiMax)
                  : root.activeDpi)
                color: root.bar.foreground
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.bodySmall
              }
            }

            Dropdown {
              width: parent.width
              label: strings.t("dpi.active")
              options: Model.levelOptions(root.dpiLevels, root.dpiCount, strings.t("dpi.level"))
              value: String(root.dpiActive)
              foreground: root.bar.foreground
              fontFamily: root.bar.fontFamily
              onChanged: function(v) {
                if (v !== String(root.dpiActive)) root.setValue("dpi-active", v)
                // Dropdown assigns `value` on a pick, which drops this binding.
                value = Qt.binding(function() { return String(root.dpiActive) })
              }
            }

            PanelSlider {
              id: dpiSlider
              width: parent.width
              bar: root.bar
              minimum: 50
              maximum: root.dpiMax
              step: root.dpiStep
              integer: true
              value: root.activeDpi
              onReleased: function(v) { root.setDpiForActive(v) }
              WheelGuard { flickable: flick }
            }
          }


          // Acceleration is a Hyprland setting, so it stays usable while the
          // mouse sleeps; it sits outside the DPI column and its gate.
          Column {
            width: parent.width
            spacing: Style.space(6)

            Dropdown {
              width: parent.width
              label: strings.t("accel.label")
              options: [
                { value: "default", label: strings.t("accel.default") },
                { value: "flat", label: strings.t("accel.flat") },
                { value: "adaptive", label: strings.t("accel.adaptive") }
              ]
              value: String(root.value("accel") || "default")
              foreground: root.bar.foreground
              fontFamily: root.bar.fontFamily
              onChanged: function(v) {
                if (v !== String(root.value("accel"))) root.setValue("accel", v)
                value = Qt.binding(function() { return String(root.value("accel") || "default") })
              }
            }

            Text {
              width: parent.width
              textFormat: Text.PlainText
              text: strings.t("scope.computer")
              color: root.bar.foreground
              opacity: 0.5
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
              wrapMode: Text.WordWrap
            }
          }

          PanelSeparator { foreground: root.bar.foreground }

          // ---------- Scrolling: scroll speed (Hyprland), thumb wheel (mouse) ----------
          Column {
            width: parent.width
            spacing: Style.space(6)

            PanelSectionHeader {
              textFormat: Text.PlainText
              text: strings.t("section.scrolling")
              foreground: root.bar.foreground
              fontFamily: root.bar.fontFamily
            }

            Item {
              width: parent.width
              implicitHeight: scrollLabel.implicitHeight
              Text {
                id: scrollLabel
                textFormat: Text.PlainText
                text: strings.t("scroll.label")
                color: root.bar.foreground
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.bodySmall
              }
              Text {
                anchors.right: parent.right
                textFormat: Text.PlainText
                text: scrollSlider.dragging
                  ? strings.t("scroll.value").arg(I18n.formatNumber(scrollSlider.liveValue, 1))
                  : (root.scrollSpeed > 0
                    ? strings.t("scroll.value").arg(I18n.formatNumber(root.scrollSpeed, 1))
                    : strings.t("scroll.default"))
                color: root.bar.foreground
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.bodySmall
              }
            }

            PanelSlider {
              id: scrollSlider
              width: parent.width
              bar: root.bar
              minimum: 0.1
              maximum: 3.0
              step: 0.1
              value: root.scrollSpeed > 0 ? root.scrollSpeed : 1.0
              onReleased: function(v) { root.setValue("scroll-speed", (Math.round(v * 10) / 10).toFixed(2)) }
              WheelGuard { flickable: flick }
            }

            Text {
              width: parent.width
              textFormat: Text.PlainText
              text: strings.t("scope.computer")
              color: root.bar.foreground
              opacity: 0.5
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
              wrapMode: Text.WordWrap
            }

            // The thumb wheel speed is a mouse setting, so only this part
            // waits for the mouse.
            Column {
              width: parent.width
              spacing: Style.space(6)
              topPadding: Style.space(6)
              visible: root.status.hscroll !== undefined
              enabled: root.canConfigure
              opacity: enabled ? 1 : 0.5

              Item {
                width: parent.width
                implicitHeight: hscrollLabel.implicitHeight
                Text {
                  id: hscrollLabel
                  textFormat: Text.PlainText
                  text: strings.t("hscroll.label")
                  color: root.bar.foreground
                  font.family: root.bar.fontFamily
                  font.pixelSize: Style.font.bodySmall
                }
                Text {
                  anchors.right: parent.right
                  textFormat: Text.PlainText
                  text: hscrollSlider.dragging
                    ? strings.t("hscroll.value").arg(Math.round(hscrollSlider.liveValue))
                    : (root.hscroll > 0 ? strings.t("hscroll.value").arg(root.hscroll) : strings.t("hscroll.custom"))
                  color: root.bar.foreground
                  font.family: root.bar.fontFamily
                  font.pixelSize: Style.font.bodySmall
                }
              }

              PanelSlider {
                id: hscrollSlider
                width: parent.width
                bar: root.bar
                minimum: 1
                maximum: 10
                step: 1
                integer: true
                value: root.hscroll > 0 ? root.hscroll : 1
                onReleased: function(v) { root.setValue("hscroll", Math.round(v)) }
                WheelGuard { flickable: flick }
              }

              Text {
                width: parent.width
                textFormat: Text.PlainText
                text: strings.t("scope.mouse")
                color: root.bar.foreground
                opacity: 0.5
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.caption
                wrapMode: Text.WordWrap
              }
            }

            Text {
              width: parent.width
              textFormat: Text.PlainText
              text: strings.t("scroll.combined")
              color: root.bar.foreground
              opacity: 0.5
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
              wrapMode: Text.WordWrap
            }
          }

          PanelSeparator { foreground: root.bar.foreground }

          // ---------- Buttons ----------
          // Left click is absent on purpose, so a remap cannot lock you out.
          Column {
            width: parent.width
            spacing: Style.space(8)
            enabled: root.canConfigure
            opacity: enabled ? 1 : 0.5

            PanelSectionHeader {
              textFormat: Text.PlainText
              text: strings.t("section.buttons")
              foreground: root.bar.foreground
              fontFamily: root.bar.fontFamily
            }

            Text {
              width: parent.width
              visible: (root.buttonsData.buttons || []).length === 0
              textFormat: Text.PlainText
              text: strings.t("buttons.empty")
              color: root.bar.foreground
              opacity: 0.5
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
              wrapMode: Text.WordWrap
            }

            Repeater {
              model: root.buttonsData.buttons || []

              Column {
                id: buttonRow
                required property var modelData
                readonly property bool isShortcut: String(modelData.action) === "shortcut"
                width: parent.width
                spacing: Style.space(4)

                Item {
                  width: parent.width
                  implicitHeight: Math.max(nameLabel.implicitHeight, actionPicker.implicitHeight)

                  Text {
                    id: nameLabel
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    width: parent.width * 0.46
                    textFormat: Text.PlainText
                    text: Model.plain(buttonRow.modelData.name, 40)
                    color: root.bar.foreground
                    font.family: root.bar.fontFamily
                    font.pixelSize: Style.font.bodySmall
                    elide: Text.ElideRight

                    MouseArea {
                      id: nameMouse
                      anchors.fill: parent
                      hoverEnabled: true
                      acceptedButtons: Qt.NoButton
                    }

                    PanelToolTip {
                      visible: nameMouse.containsMouse && Model.plain(buttonRow.modelData.help, 200) !== ""
                      text: Model.plain(buttonRow.modelData.help, 200)
                      fontFamily: root.bar.fontFamily
                    }
                  }

                  Dropdown {
                    id: actionPicker
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    width: parent.width * 0.5
                    showLabel: false
                    options: root.buttonsData.actions || []
                    value: String(buttonRow.modelData.action)
                    foreground: root.bar.foreground
                    fontFamily: root.bar.fontFamily
                    onChanged: function(v) {
                      if (v === String(buttonRow.modelData.action)) return
                      // A shortcut is written once there is a key combination
                      // to store; picking it only opens the field.
                      if (v === "shortcut") {
                        shortcutField.visible = true
                        shortcutField.forceActiveFocus()
                        return
                      }
                      root.run(["buttons", "set", String(buttonRow.modelData.index), v])
                    }
                  }
                }

                TextField {
                  id: shortcutField
                  width: parent.width
                  visible: buttonRow.isShortcut
                  text: Model.plain(buttonRow.modelData.argument, 64)
                  placeholderText: strings.t("buttons.shortcutPlaceholder")
                  foreground: root.bar.foreground
                  font.family: root.bar.fontFamily
                  font.pixelSize: Style.font.bodySmall
                  onAccepted: {
                    var combo = Model.normalizeShortcut(text)
                    if (combo === null) return
                    root.run(["buttons", "set", String(buttonRow.modelData.index), "shortcut", combo])
                  }
                }
              }
            }
          }


          PanelSeparator { foreground: root.bar.foreground }

          // ---------- Performance: polling rate and sensor ----------
          Column {
            width: parent.width
            spacing: Style.space(8)
            visible: Model.intList(root.status["rate-options"]).length > 0
            enabled: root.canConfigure
            opacity: enabled ? 1 : 0.5

            PanelSectionHeader {
              textFormat: Text.PlainText
              text: strings.t("section.performance")
              foreground: root.bar.foreground
              fontFamily: root.bar.fontFamily
            }

            Dropdown {
              width: parent.width
              label: strings.t("rate.label")
              options: Model.rateOptions(Model.intList(root.status["rate-options"]))
              value: String(root.value("rate") || "")
              foreground: root.bar.foreground
              fontFamily: root.bar.fontFamily
              onChanged: function(v) {
                if (v !== String(root.value("rate"))) root.setValue("rate", v)
                value = Qt.binding(function() { return String(root.value("rate") || "") })
              }
            }
          }


          Column {
            width: parent.width
            spacing: Style.space(8)
            visible: root.status["motion-sync"] !== undefined
            enabled: root.canConfigure
            opacity: enabled ? 1 : 0.5


            Repeater {
              model: [
                { key: "motion-sync", label: "sensor.motionSync", desc: "sensor.motionSyncDesc" },
                { key: "angle-snap", label: "sensor.angleSnap", desc: "sensor.angleSnapDesc" },
                { key: "ripple", label: "sensor.ripple", desc: "sensor.rippleDesc" }
              ]

              Toggle {
                required property var modelData
                width: parent.width
                label: strings.t(modelData.label)
                description: strings.t(modelData.desc)
                checked: Model.toBool(root.value(modelData.key))
                foreground: root.bar.foreground
                fontFamily: root.bar.fontFamily
                onClicked: root.setValue(modelData.key, checked ? "0" : "1")
              }
            }
          }


          PanelSeparator { foreground: root.bar.foreground; visible: powerSection.visible }

          // ---------- Power ----------
          Column {
            id: powerSection
            width: parent.width
            spacing: Style.space(6)
            visible: root.status.sleep !== undefined
            enabled: root.canConfigure
            opacity: enabled ? 1 : 0.5

            PanelSectionHeader {
              textFormat: Text.PlainText
              text: strings.t("section.power")
              foreground: root.bar.foreground
              fontFamily: root.bar.fontFamily
            }

            Item {
              width: parent.width
              implicitHeight: sleepLabel.implicitHeight
              Text {
                id: sleepLabel
                textFormat: Text.PlainText
                text: strings.t("power.sleep")
                color: root.bar.foreground
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.bodySmall
              }
              Text {
                anchors.right: parent.right
                textFormat: Text.PlainText
                text: strings.t("power.sleepValue").arg(sleepSlider.dragging
                  ? Math.round(sleepSlider.liveValue) : Model.toInt(root.value("sleep"), 10))
                color: root.bar.foreground
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.bodySmall
              }
            }

            PanelSlider {
              id: sleepSlider
              width: parent.width
              bar: root.bar
              minimum: 1
              maximum: 60
              step: 1
              integer: true
              value: Model.toInt(root.value("sleep"), 10)
              onReleased: function(v) { root.setValue("sleep", Math.round(v)) }
              WheelGuard { flickable: flick }
            }

            Item {
              width: parent.width
              implicitHeight: debounceLabel.implicitHeight
              Text {
                id: debounceLabel
                textFormat: Text.PlainText
                text: strings.t("power.debounce")
                color: root.bar.foreground
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.bodySmall
              }
              Text {
                anchors.right: parent.right
                textFormat: Text.PlainText
                text: strings.t("power.debounceValue").arg(debounceSlider.dragging
                  ? Math.round(debounceSlider.liveValue) : Model.toInt(root.value("debounce"), 0))
                color: root.bar.foreground
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.bodySmall
              }
            }

            PanelSlider {
              id: debounceSlider
              width: parent.width
              bar: root.bar
              minimum: 0
              maximum: 20
              step: 1
              integer: true
              value: Model.toInt(root.value("debounce"), 0)
              onReleased: function(v) { root.setValue("debounce", Math.round(v)) }
              WheelGuard { flickable: flick }
            }
          }


          PanelSeparator { foreground: root.bar.foreground }

          // ---------- Factory reset ----------
          Column {
            width: parent.width
            spacing: Style.space(6)
            enabled: root.canConfigure
            opacity: enabled ? 1 : 0.5

            id: resetSection
            property bool armed: false

            Timer {
              id: disarm
              interval: 4000
              onTriggered: resetSection.armed = false
            }

            Button {
              id: resetButton
              width: parent.width
              bordered: true
              text: resetSection.armed ? strings.t("reset.confirm") : strings.t("reset.button")
              foreground: resetSection.armed ? Color.urgent : root.bar.foreground
              fontFamily: root.bar.fontFamily
              onClicked: {
                if (!resetSection.armed) {
                  resetSection.armed = true
                  disarm.restart()
                  return
                }
                resetSection.armed = false
                disarm.stop()
                root.run(["reset"])
              }
            }

            Text {
              width: parent.width
              textFormat: Text.PlainText
              text: strings.t("reset.note")
              color: root.bar.foreground
              opacity: 0.5
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
              wrapMode: Text.WordWrap
            }
          }
        }
      }
    }
  }
}
