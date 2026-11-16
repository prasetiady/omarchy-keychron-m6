import QtQuick

// Sits over a PanelSlider so the scroll wheel scrolls the panel instead of
// changing the value. PanelSlider turns each wheel step into a finished
// change, which here would write to the mouse while you only meant to scroll.
// Clicks and drags still reach the slider: this area accepts no buttons.
MouseArea {
  id: root

  property Flickable flickable: null

  anchors.fill: parent
  acceptedButtons: Qt.NoButton

  onWheel: function(wheel) {
    wheel.accepted = true
    if (!root.flickable) return
    var step = wheel.pixelDelta.y !== 0 ? wheel.pixelDelta.y : wheel.angleDelta.y / 2
    var maxY = Math.max(0, root.flickable.contentHeight - root.flickable.height)
    root.flickable.contentY = Math.max(0, Math.min(maxY, root.flickable.contentY - step))
  }
}
