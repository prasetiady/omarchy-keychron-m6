"""keychron-ctl: discovery, protocol encoding, transport, and status output."""

import contextlib
import io
import os
import unittest
from unittest import mock

from support import CtlTestCase, FakeMouse, MOUSE_DESCRIPTOR, snapshot

REPLY_LONG = 0xB4
REPLY_SHORT = 0xB6


def run(ctl, *argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = ctl.main(["keychron-ctl"] + list(argv))
    return code, out.getvalue()


def pairs(text):
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)


class DiscoveryTest(CtlTestCase):
    def test_parse_hid_id(self):
        self.assertEqual(self.ctl.parse_hid_id("HID_ID=0003:00003434:0000D029\n"), (3, 0x3434, 0xD029))
        self.assertIsNone(self.ctl.parse_hid_id("HID_ID=garbage"))

    def test_receiver_with_either_pid_is_found(self):
        self.add_node("hidraw8", 3, 0x3434, 0xD029)
        self.add_node("hidraw9", 3, 0x3434, 0xD026)
        kinds = [(n.name, n.kind) for n in self.ctl.find_nodes()]
        self.assertEqual(kinds, [("hidraw8", "receiver"), ("hidraw9", "receiver")])

    def test_cable_wins_over_receiver(self):
        self.add_node("hidraw8", 3, 0x3434, 0xD029)
        self.add_node("hidraw18", 3, 0x3434, 0xD064)
        self.assertEqual([n.kind for n in self.ctl.find_nodes()], ["usb", "receiver"])

    def test_bluetooth_node_with_vendor_page(self):
        self.add_node("hidraw20", 5, 0x3434, 0xD064)
        self.assertEqual([n.kind for n in self.ctl.find_nodes()], ["bluetooth"])

    def test_nodes_without_vendor_page_or_other_vendor_are_skipped(self):
        self.add_node("hidraw3", 3, 0x3434, 0xD029, descriptor=MOUSE_DESCRIPTOR)
        self.add_node("hidraw4", 3, 0x046D, 0xC52B)
        self.assertEqual(self.ctl.find_nodes(), [])

    def test_bluetooth_without_vendor_page_is_noticed(self):
        self.add_node("hidraw21", 5, 0x3434, 0xD064, descriptor=MOUSE_DESCRIPTOR)
        self.assertEqual(self.ctl.find_nodes(), [])
        self.assertTrue(self.ctl.any_keychron_bluetooth())


class ProtocolTest(CtlTestCase):
    def test_snapshot_decodes_battery_dpi_and_rate(self):
        snap = self.ctl.parse_snapshot(snapshot(battery=73, charging=True, level=3, rate_level=1))
        self.assertEqual(snap["battery"], 73)
        self.assertTrue(snap["charging"])
        self.assertEqual(snap["dpi_levels"], [400, 800, 1600, 3200, 5000])
        out = dict(self.ctl.snapshot_pairs(snap, None))
        self.assertEqual(out["dpi-active"], 3)
        self.assertEqual(out["rate"], 500)
        self.assertEqual(out["rate-options"], [125, 500, 1000])

    def test_real_m6s_a72_snapshot(self):
        # Captured from an M6S-A72 (PixArt 3311, firmware 1.0.2) on the cable,
        # charging, while measured at 125 Hz (8.00 ms between reports).
        raw = bytes.fromhex(
            "06 00 01 01 01 90 01 20 03 40 06 80 0c 88 13 15 05 04 0a d3 00 00 00 00 00 00 37 00 00 00"
            " 04 04 14 04 04 04 04 04 04 04 00 00 00 00 01 02 00 00 00 03 05 00 00 00 00 00 00 00 00 00 00 00 00"
        )
        snap = self.ctl.parse_snapshot(raw)
        out = dict(self.ctl.snapshot_pairs(snap, None))
        self.assertEqual((out["battery"], out["charging"]), (83, True))
        self.assertEqual(out["dpi-levels"], [400, 800, 1600, 3200, 5000])
        self.assertEqual((out["dpi-active"], out["rate"]), (1, 125))
        self.assertEqual(out["rate-options"], [125, 500, 1000])
        self.assertEqual((out["ripple"], out["angle-snap"], out["motion-sync"]), (1, 0, 1))
        self.assertEqual((out["debounce"], out["sleep"]), (4, 10))

    def test_real_info_reply(self):
        info = self.ctl.parse_info(bytes.fromhex("02 04 00 34 34 64 d0 02 01 10 00 00 00 00 00 00 00 00 00 00"))
        self.assertEqual((info["pid"], info["firmware"], info["work_mode"]), (0xD064, "1.0.2", 0))

    def test_snapshot_rejects_wrong_opcode_or_short_body(self):
        self.assertIsNone(self.ctl.parse_snapshot(b"\x05" + bytes(62)))
        self.assertIsNone(self.ctl.parse_snapshot(b"\x06" + bytes(10)))

    def test_sensor_bits(self):
        bits = self.ctl.sensor_bits(0b01011100)
        self.assertEqual((bits["ripple"], bits["angle-snap"], bits["motion-sync"], bits["scroll-reverse"]), (1, 1, 1, 1))

    def test_dpi_payload_is_little_endian(self):
        p = self.ctl.dpi_payload(2, [400, 800, 1600, 3200, 5000], 5)
        self.assertEqual(p[:4], [0x40, 2, 2, 2])
        self.assertEqual(p[4:6], [0x90, 0x01])
        self.assertEqual(p[-1], 5)

    def test_rate_payload(self):
        self.assertEqual(self.ctl.rate_payload(1, [0, 1, 2]), [0x41, 1, 1, 0, 1, 2, 0, 0, 0, 3])

    def test_sensor_payload_uses_one_for_on_and_two_for_off(self):
        snap = self.ctl.parse_snapshot(snapshot(sensor=0b00010000))  # motion sync on
        p = self.ctl.sensor_payload(snap, {"motion-sync": 0, "angle-snap": 1})
        self.assertEqual(p[0], 0x42)
        self.assertEqual(p[2:5], [2, 1, 2])  # ripple off, angle snap on, motion sync off

    def test_snap_dpi(self):
        self.assertEqual(self.ctl.snap_dpi(1234), 1250)
        self.assertEqual(self.ctl.snap_dpi(10), 50)
        self.assertEqual(self.ctl.snap_dpi(99999), 12000)


class ButtonsTest(CtlTestCase):
    def test_shortcut_round_trip(self):
        kind, data = self.ctl.encode_action("shortcut", "super+shift+f13")
        self.assertEqual((kind, data), (2, [8 | 2, 104]))
        self.assertEqual(self.ctl.decode_key(kind, data + [0]), ("shortcut", "shift+super+f13"))

    def test_mouse_and_media_round_trip(self):
        for action in ("back", "forward", "scroll-left", "volume-up", "dpi-cycle", "disable", "default"):
            kind, data = self.ctl.encode_action(action, "")
            self.assertEqual(self.ctl.decode_key(kind, data + [0, 0, 0])[0], action)

    def test_real_default_button_reply(self):
        # 0xB3/62 for the middle button on an unmapped M6S-A72: type 0, no data.
        body = bytes.fromhex("6201") + bytes(61)
        self.assertEqual(self.ctl.decode_key(body[3], body[4:]), ("default", ""))

    def test_bad_shortcuts_are_refused(self):
        for bad in ("", "hyper+a", "super+notakey", "a+b"):
            with self.assertRaises(SystemExit):
                self.ctl.parse_shortcut(bad)

    def test_left_click_cannot_be_remapped(self):
        with self.assertRaises(SystemExit):
            self.ctl.cmd_buttons_set("0", "disable", "")


class TransportTest(CtlTestCase):
    def test_stale_and_unrelated_replies_are_skipped(self):
        def handler(rid, payload):
            return [
                [0x04] + [0] * 7,                           # a mouse movement report
                [REPLY_LONG, 0x62, 3] + [0] * 61,           # stale reply to another command
                [REPLY_LONG] + list(snapshot(battery=42)),  # the real answer
            ]

        self.add_node("hidraw8", 3, 0x3434, 0xD029)
        self.attach(FakeMouse(handler))
        dev = self.ctl.Device(self.ctl.find_nodes()[0])
        snap = self.ctl.get_snapshot(dev)
        self.assertEqual(snap["battery"], 42)

    def test_silent_mouse_raises_no_reply(self):
        self.add_node("hidraw8", 3, 0x3434, 0xD029)
        self.attach(FakeMouse(lambda rid, p: []))
        dev = self.ctl.Device(self.ctl.find_nodes()[0])
        with self.assertRaises(self.ctl.NoReply):
            self.ctl.get_snapshot(dev)

    def test_write_waits_for_ack(self):
        sent = []

        def handler(rid, payload):
            sent.append((rid, payload[0]))
            if payload[0] == 0x06:
                return [[REPLY_LONG] + list(snapshot())]
            if payload[0] == 0x02:
                return []
            return [[REPLY_SHORT, 0xE4, 0, payload[0]] + [0] * 17]

        self.add_node("hidraw8", 3, 0x3434, 0xD029)
        self.attach(FakeMouse(handler))
        code, _ = run(self.ctl, "set", "rate", "500")
        self.assertEqual(code, 0)
        self.assertIn((0xB5, 0x41), sent)


class StatusTest(CtlTestCase):
    def test_receiver_status(self):
        self.add_node("hidraw8", 3, 0x3434, 0xD029)
        self.attach(FakeMouse(lambda rid, p: [[REPLY_LONG] + list(snapshot(battery=61))] if p[0] == 6 else []))
        code, out = run(self.ctl, "status")
        got = pairs(out)
        self.assertEqual(code, 0)
        self.assertEqual(got["present"], "true")
        self.assertEqual(got["connection"], "receiver")
        self.assertEqual(got["battery"], "61")
        self.assertEqual(got["settings"], "true")

    def test_sleeping_mouse_behind_receiver_is_asleep_not_gone(self):
        self.add_node("hidraw8", 3, 0x3434, 0xD029)
        self.attach(FakeMouse(lambda rid, p: []))
        _, out = run(self.ctl, "status")
        got = pairs(out)
        self.assertEqual((got["present"], got["link"]), ("true", "asleep"))

    def test_access_denied_is_reported(self):
        self.add_node("hidraw8", 3, 0x3434, 0xD029)

        def deny(node):
            raise self.ctl.AccessDenied(node.path)

        with mock.patch.object(self.ctl.Device, "__init__", lambda s, n: deny(n)):
            _, out = run(self.ctl, "status")
        got = pairs(out)
        self.assertEqual((got["present"], got["access"]), ("false", "denied"))

    def test_bluetooth_without_vendor_page_uses_upower(self):
        self.add_node("hidraw21", 5, 0x3434, 0xD064, descriptor=MOUSE_DESCRIPTOR)
        with mock.patch.object(self.ctl, "upower_battery", return_value={"battery": 55, "charging": False}):
            _, out = run(self.ctl, "status")
        got = pairs(out)
        self.assertEqual((got["connection"], got["battery"], got["settings"]), ("bluetooth", "55", "false"))

    def test_status_values_are_plain(self):
        self.add_node("hidraw8", 3, 0x3434, 0xD029)
        self.attach(FakeMouse(lambda rid, p: [[REPLY_LONG] + list(snapshot())] if p[0] == 6 else []))
        _, out = run(self.ctl, "status")
        for line in out.splitlines():
            key, _, value = line.partition("=")
            self.assertRegex(key, r"^[a-z0-9-]+$")
            self.assertRegex(value, r"^[A-Za-z0-9.,-]*$")


class AccelTest(CtlTestCase):
    def test_accel_writes_data_files(self):
        with mock.patch.object(self.ctl, "hypr_mouse_names", return_value=["keychron-m6-bt"]), \
             mock.patch.object(self.ctl.subprocess, "run") as srun:
            self.ctl.write_accel("flat")
        state = os.environ["KEYCHRON_STATE_DIR"]
        with open(os.path.join(state, "accel-profile")) as f:
            self.assertEqual(f.read().strip(), "flat")
        with open(os.path.join(state, "device-names")) as f:
            names = f.read().split()
        self.assertEqual(names, ["keychron-keychron-m6", "keychron--keychron-link-km", "keychron-m6-bt"])
        srun.assert_called_with(["hyprctl", "reload"], capture_output=True, timeout=10, check=False)

    def test_hyprland_names_are_filtered(self):
        devices = ('{"mice": [{"name": "keychron-keychron-m6"}, {"name": "keychron-m6\\nhl.exec(1)"},'
                   ' {"name": "Keychron M6"}, {"name": "keychron-keychron-m6-keyboard-1"},'
                   ' {"name": "logitech-mx-master"}]}')
        result = mock.Mock(stdout=devices.encode())
        with mock.patch.object(self.ctl.subprocess, "run", return_value=result):
            self.assertEqual(self.ctl.hypr_mouse_names(), ["keychron-keychron-m6"])

    def test_accel_rejects_unknown_profile(self):
        with self.assertRaises(SystemExit):
            self.ctl.cmd_set("accel", "custom")

    def test_default_removes_profile(self):
        with mock.patch.object(self.ctl, "hypr_mouse_names", return_value=[]), \
             mock.patch.object(self.ctl.subprocess, "run"):
            self.ctl.write_accel("adaptive")
            self.ctl.write_accel("default")
        self.assertEqual(self.ctl.read_accel(), "default")


if __name__ == "__main__":
    unittest.main()
