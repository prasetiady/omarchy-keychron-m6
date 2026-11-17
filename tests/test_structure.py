"""Conventions the code depends on, checked so they cannot drift silently."""

import ast
import json
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*path):
    with open(os.path.join(ROOT, *path), encoding="utf-8") as f:
        return f.read()


def qml_blocks(source, type_name):
    """The text of every `<type_name> {` block, braces balanced."""
    blocks = []
    for match in re.finditer(r"(?m)^\s*%s \{" % re.escape(type_name), source):
        depth, i = 0, match.end() - 1
        while i < len(source):
            depth += {"{": 1, "}": -1}.get(source[i], 0)
            if depth == 0:
                break
            i += 1
        blocks.append(source[match.start():i + 1])
    return blocks


class PanelStructureTest(unittest.TestCase):
    def setUp(self):
        self.panel = read("Panel.qml")

    def test_every_slider_has_a_wheel_guard(self):
        # PanelSlider writes on every wheel step; WheelGuard turns the wheel
        # back into panel scrolling.
        sliders = qml_blocks(self.panel, "PanelSlider")
        self.assertTrue(sliders)
        for block in sliders:
            self.assertIn("WheelGuard", block, block.splitlines()[1].strip())

    def test_every_text_is_plain_text(self):
        # Text defaults to AutoText, which renders markup from device names
        # and other untrusted input.
        for type_name in ("Text", "PanelSectionHeader"):
            for block in qml_blocks(self.panel, type_name):
                self.assertIn("textFormat: Text.PlainText", block, block[:120])

    def test_ui_strings_exist_and_are_used(self):
        catalog = json.loads(read("i18n", "en.json"))
        called = set(re.findall(r'strings\.t\("([A-Za-z.]+)"', self.panel))
        unknown = sorted(k for k in called if k not in catalog and not k.endswith("."))
        unused = sorted(k for k in catalog if '"%s"' % k not in self.panel and not k.startswith("state."))
        self.assertEqual((unknown, unused), ([], []))


class SharedListsTest(unittest.TestCase):
    def test_hyprland_device_names_match(self):
        ctl = re.search(r"^DEFAULT_HYPR_NAMES = (\[.*?\])", read("keychron-ctl"), re.M | re.S).group(1)
        lua = re.search(r"^local names = \{(.*?)\}", read("hypr", "pointer.lua"), re.M | re.S).group(1)
        self.assertEqual(ast.literal_eval(ctl), re.findall(r'"([^"]+)"', lua))


class UdevRuleTest(unittest.TestCase):
    def test_rules_never_mix_kernels_with_parent_attrs(self):
        # udev matches every parent key against one device, and KERNELS (the
        # HID device) and ATTRS{bInterfaceNumber} (the USB interface) never
        # share one, so such a rule matches nothing. Match ENV{ID_USB_*}.
        for line in read("70-keychron-m6.rules").splitlines():
            if line.strip() and not line.lstrip().startswith("#"):
                self.assertFalse("KERNELS" in line and "ATTRS{" in line, line)
                self.assertIn('TAG+="uaccess"', line)


if __name__ == "__main__":
    unittest.main()
