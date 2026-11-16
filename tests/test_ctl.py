"""keychron-ctl: discovery, protocol encoding, transport, and status output."""

import contextlib
import io
import os
import shutil
import subprocess
import unittest
from unittest import mock

from support import ROOT, CtlTestCase, FakeMouse, MOUSE_DESCRIPTOR, bond_reply, snapshot

REPLY_LONG = 0xB4
REPLY_SHORT = 0xB6


def run(ctl, *argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = ctl.main(["keychron-ctl"] + list(argv))
    return code, out.getvalue()


def receiver(snap=None, paired=0xD064):
    """A fake receiver: answers the bond query, and the snapshot when awake."""
    def handler(rid, payload):
        if payload[0] == 0x03:
            return [bond_reply(paired)]
        if payload[0] == 0x06 and snap is not None:
            return [[REPLY_LONG] + list(snap)]
        return []
    return handler


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

    def test_only_the_3311_m6_is_found_but_any_receiver_is(self):
        self.add_node("hidraw5", 3, 0x3434, 0xD049, product="Keychron Keychron M6 8K")
        self.add_node("hidraw6", 3, 0x3434, 0xD028, product="Keychron Ultra-Link 8K")
        kinds = [(n.name, n.kind) for n in self.ctl.find_nodes()]
        self.assertEqual(kinds, [("hidraw6", "receiver")])

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
        # ripple off, angle snap on, motion sync off; scroll direction (p[6]),
        # 20K FPS (p[8]), and lift-off (p[1], p[11]) are re-sent unchanged.
        self.assertEqual(p, [0x42, 0, 2, 1, 2, 0, 1, 0, 1, 0, 0, 0])

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



class WriteTest(CtlTestCase):
    """`set` validates first, waits for the acknowledgement, and reads back."""

    def mouse(self, ack=True, status=0, stores=True):
        state = {"rate_level": 2}
        sent = []

        def handler(rid, payload):
            sent.append((rid, list(payload)))
            op = payload[0]
            if op == 0x03:
                return [bond_reply()]
            if op == 0x06:
                return [[REPLY_LONG] + list(snapshot(rate_level=state["rate_level"]))]
            if op == 0x02:
                return []
            if op == 0x41 and stores and status == 0:
                state["rate_level"] = payload[1]
            return [[REPLY_SHORT, 0xE4, status, op] + [0] * 17] if ack else []

        self.add_node("hidraw8", 3, 0x3434, 0xD029)
        self.attach(FakeMouse(handler))
        return sent

    def test_set_rate_sends_the_exact_payload_and_reads_back(self):
        sent = self.mouse()
        code, _ = run(self.ctl, "set", "rate", "500")
        self.assertEqual(code, 0)
        writes = [p for rid, p in sent if rid == 0xB5 and p[0] == 0x41]
        self.assertEqual(writes, [[0x41, 1, 1, 0, 1, 2, 0, 0, 0, 3] + [0] * 10])

    def test_no_acknowledgement_is_an_error(self):
        self.mouse(ack=False)
        self.assertEqual(run(self.ctl, "set", "rate", "500")[0], 4)

    def test_refused_write_exits_1(self):
        self.mouse(status=2)
        self.assertEqual(run(self.ctl, "set", "rate", "500")[0], 1)

    def test_value_the_mouse_did_not_store_exits_1(self):
        self.mouse(stores=False)
        self.assertEqual(run(self.ctl, "set", "rate", "500")[0], 1)

    def test_invalid_values_exit_1_without_a_mouse(self):
        for key, value in (("rate", "300"), ("dpi", "20000"), ("motion-sync", "maybe"), ("bogus", "1")):
            with self.assertRaises(SystemExit) as cm:
                self.ctl.cmd_set(key, value)
            self.assertNotEqual(cm.exception.code, 0)


class ThumbWheelTest(CtlTestCase):
    """The thumb wheel speed is a scroll step stored on buttons 10 and 11."""

    def mouse(self, buttons=None):
        table = buttons if buttons is not None else {}

        def handler(rid, payload):
            op = payload[0]
            if op == 0x03:
                return [bond_reply()]
            if op == 0x06:
                return [[REPLY_LONG] + list(snapshot())]
            if op == 0x62:
                kind, data = table.get(payload[1], (0, [0, 0, 0]))
                return [[REPLY_LONG, 0x62, payload[1], 0, kind] + data + [0] * 56]
            if op == 0x52:
                table[payload[1]] = (payload[3], list(payload[4:7]))
                return [[REPLY_SHORT, 0xE4, 0, 0x52] + [0] * 17]
            return []

        self.add_node("hidraw8", 3, 0x3434, 0xD029)
        self.attach(FakeMouse(handler))
        return table

    def test_set_writes_both_buttons_with_opposite_steps(self):
        table = self.mouse()
        self.assertEqual(run(self.ctl, "set", "hscroll", "4")[0], 0)
        self.assertEqual(table, {10: (1, [0, 0, 4]), 11: (1, [0, 0, 0xFC])})
        self.assertEqual(pairs(run(self.ctl, "status")[1])["hscroll"], "4")

    def test_step_1_restores_the_factory_mapping(self):
        table = self.mouse({10: (1, [0, 0, 4]), 11: (1, [0, 0, 0xFC])})
        self.assertEqual(run(self.ctl, "set", "hscroll", "1")[0], 0)
        self.assertEqual(table, {10: (0, [0, 0, 0]), 11: (0, [0, 0, 0])})

    def test_a_remapped_thumb_wheel_reads_as_custom(self):
        self.mouse({10: (2, [8, 104, 0]), 11: (0, [0, 0, 0])})
        self.assertEqual(pairs(run(self.ctl, "status")[1])["hscroll"], "custom")

    def test_range_is_checked_before_the_mouse(self):
        for bad in ("0", "11", "x"):
            with self.assertRaises(SystemExit):
                self.ctl.parse_setting("hscroll", bad)

    def test_buttons_decode_any_scroll_step(self):
        self.assertEqual(self.ctl.decode_key(1, [0, 0, 4]), ("scroll-right", "4"))
        self.assertEqual(self.ctl.decode_key(1, [0, 0, 0xFC]), ("scroll-left", "4"))
        self.assertEqual(self.ctl.decode_key(1, [0, 0, 2]), ("scroll-right", ""))


class StatusTest(CtlTestCase):
    def test_receiver_status(self):
        self.add_node("hidraw8", 3, 0x3434, 0xD029)
        self.attach(FakeMouse(receiver(snapshot(battery=61))))
        code, out = run(self.ctl, "status")
        got = pairs(out)
        self.assertEqual(code, 0)
        self.assertEqual(got["present"], "true")
        self.assertEqual(got["connection"], "receiver")
        self.assertEqual(got["battery"], "61")
        self.assertEqual(got["settings"], "true")

    def test_sleeping_mouse_behind_receiver_is_asleep_not_gone(self):
        self.add_node("hidraw8", 3, 0x3434, 0xD029)
        self.attach(FakeMouse(receiver(snap=None)))
        _, out = run(self.ctl, "status")
        got = pairs(out)
        self.assertEqual((got["present"], got["link"]), ("true", "asleep"))

    def test_bluetooth_mouse_wins_over_a_silent_receiver(self):
        self.add_node("hidraw8", 3, 0x3434, 0xD029)
        self.add_node("hidraw21", 5, 0x3434, 0xD064, descriptor=MOUSE_DESCRIPTOR)
        self.attach(FakeMouse(receiver(snap=None)))
        with mock.patch.object(self.ctl, "upower_battery", return_value={"battery": 70, "charging": False}):
            _, out = run(self.ctl, "status")
        got = pairs(out)
        self.assertEqual((got["connection"], got["battery"]), ("bluetooth", "70"))

    def test_receiver_paired_with_another_mouse_is_ignored(self):
        self.add_node("hidraw8", 3, 0x3434, 0xD029)
        self.attach(FakeMouse(receiver(snapshot(), paired=0xD049)))
        _, out = run(self.ctl, "status")
        self.assertEqual(pairs(out)["present"], "false")

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

    def test_upower_parser_reads_the_m6_only(self):
        listing = "/org/freedesktop/UPower/devices/keyboard_dev_1\n/org/freedesktop/UPower/devices/mouse_dev_2\n"
        keyboard = "  model:                Keychron K3 Max\n  percentage:          40%\n  state:               discharging\n"
        mouse = "  model:                Keychron M6\n  percentage:          81%\n  state:               charging\n"

        def fake_run(args, **kwargs):
            text = listing if args[1] == "-e" else (keyboard if "keyboard" in args[2] else mouse)
            return mock.Mock(stdout=text.encode())

        with mock.patch.object(self.ctl.subprocess, "run", side_effect=fake_run):
            self.assertEqual(self.ctl.upower_battery(), {"battery": 81, "charging": True})

    def test_status_values_are_plain(self):
        self.add_node("hidraw8", 3, 0x3434, 0xD029)
        self.attach(FakeMouse(receiver(snapshot())))
        _, out = run(self.ctl, "status")
        for line in out.splitlines():
            key, _, value = line.partition("=")
            self.assertRegex(key, r"^[a-z0-9-]+$")
            self.assertRegex(value, r"^[A-Za-z0-9.,-]*$")


class PointerSettingsTest(CtlTestCase):
    """Acceleration and scroll speed: Hyprland settings stored as plain data."""

    def write(self, changes, mice=()):
        with mock.patch.object(self.ctl, "hypr_mouse_names", return_value=list(mice)), \
             mock.patch.object(self.ctl.subprocess, "run") as srun:
            self.ctl.write_hypr(changes)
        return srun

    def read_state(self, name):
        with open(os.path.join(os.environ["KEYCHRON_STATE_DIR"], name)) as f:
            return f.read().split()

    def test_writes_data_files_and_reloads_once(self):
        srun = self.write({"accel": "flat", "scroll-speed": "0.75"}, mice=["keychron-m6-bt"])
        self.assertEqual(self.read_state("accel-profile"), ["flat"])
        self.assertEqual(self.read_state("scroll-factor"), ["0.75"])
        self.assertEqual(self.read_state("device-names"),
                         ["keychron-keychron-m6", "keychron--keychron-link-km", "keychron-m6-bt"])
        srun.assert_called_once_with(["hyprctl", "reload"], capture_output=True, timeout=10, check=False)

    def test_hyprland_names_are_filtered(self):
        devices = ('{"mice": [{"name": "keychron-keychron-m6"}, {"name": "keychron-m6\\nhl.exec(1)"},'
                   ' {"name": "Keychron M6"}, {"name": "keychron-keychron-m6-keyboard-1"},'
                   ' {"name": "logitech-mx-master"}]}')
        result = mock.Mock(stdout=devices.encode())
        with mock.patch.object(self.ctl.subprocess, "run", return_value=result):
            self.assertEqual(self.ctl.hypr_mouse_names(), ["keychron-keychron-m6"])

    def test_values_are_validated_and_normalized(self):
        self.assertEqual(self.ctl.parse_hypr("scroll-speed", "1.5"), "1.50")
        self.assertEqual(self.ctl.parse_hypr("scroll-speed", "default"), "default")
        for bad in ("0", "3.5", "nan", "inf", "1e9", "os.exit()"):
            with self.assertRaises(SystemExit, msg=bad):
                self.ctl.parse_hypr("scroll-speed", bad)
        with self.assertRaises(SystemExit):
            self.ctl.parse_hypr("accel", "custom")

    def test_default_removes_the_file(self):
        self.write({"accel": "adaptive", "scroll-speed": "2"})
        self.write({"accel": "default", "scroll-speed": "default"})
        self.assertEqual((self.ctl.read_hypr("accel"), self.ctl.read_hypr("scroll-speed")), ("default", "default"))

    def test_a_tampered_file_reads_as_default(self):
        os.makedirs(os.environ["KEYCHRON_STATE_DIR"], exist_ok=True)
        with open(os.path.join(os.environ["KEYCHRON_STATE_DIR"], "scroll-factor"), "w") as f:
            f.write("<b>9</b>\n")
        self.assertEqual(self.ctl.read_hypr("scroll-speed"), "default")


@unittest.skipUnless(shutil.which("lua"), "lua is not installed")
class PointerLuaTest(CtlTestCase):
    """hypr/pointer.lua applies only validated values."""

    def run_lua(self, files):
        state = os.path.join(self.tmp, "home", ".local", "state", "keychron-m6")
        os.makedirs(state)
        for name, text in files.items():
            with open(os.path.join(state, name), "w") as f:
                f.write(text)
        stub = 'hl={device=function(t) print(t.name, tostring(t.accel_profile), tostring(t.scroll_factor)) end}'
        out = subprocess.run(["lua", "-e", stub, os.path.join(ROOT, "hypr", "pointer.lua")],
                             env={"HOME": os.path.join(self.tmp, "home")}, capture_output=True, text=True)
        self.assertEqual(out.stderr, "")
        return out.stdout.splitlines()

    def test_applies_both_settings_to_valid_names_only(self):
        lines = self.run_lua({"accel-profile": "flat\n", "scroll-factor": "0.50\n",
                              "device-names": "keychron-keychron-m6\nBad Name\n"})
        self.assertEqual(lines[0], "keychron-keychron-m6\tflat\t0.5")
        self.assertFalse([line for line in lines if line.startswith("Bad")])

    def test_numbered_variants_of_a_name_are_covered(self):
        lines = self.run_lua({"scroll-factor": "0.5\n", "device-names": "keychron--keychron-link-km-1\n"})
        names = [line.split("\t")[0] for line in lines]
        self.assertEqual(names[0], "keychron--keychron-link-km")
        self.assertIn("keychron--keychron-link-km-1", names)
        self.assertIn("keychron--keychron-link-km-9", names)
        self.assertEqual(len(names), len(set(names)))

    def test_ignores_invalid_values(self):
        self.assertEqual(self.run_lua({"accel-profile": "custom\n", "scroll-factor": "os.exit()\n"}), [])

    def test_scroll_speed_alone_is_applied(self):
        lines = self.run_lua({"scroll-factor": "2\n"})
        self.assertIn("keychron-keychron-m6\tnil\t2", lines)


if __name__ == "__main__":
    unittest.main()
