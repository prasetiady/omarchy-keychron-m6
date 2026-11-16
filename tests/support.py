"""Shared setup for the keychron-ctl tests.

`keychron-ctl` is a script without a .py extension, so it is loaded by path.
No test touches real hardware: discovery runs against a fake sysfs tree, and
the HID transport runs over a SOCK_SEQPACKET socketpair, which keeps message
boundaries the way a hidraw node does.
"""

import importlib.machinery
import importlib.util
import os
import shutil
import socket
import tempfile
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CTL = os.path.join(ROOT, "keychron-ctl")

# The vendor-page descriptor the M6 and the Link-KM receiver both expose.
VENDOR_DESCRIPTOR = bytes.fromhex(
    "06 c1 ff 09 01 a1 01 15 00 26 ff 00 75 08 85 b4 09 02 95 3f 81 02"
    " 85 b3 09 03 95 3f 91 02 85 b5 09 04 95 14 91 02 85 b6 09 07 95 14 81 02 c0"
)
MOUSE_DESCRIPTOR = bytes.fromhex("05010902a1018501c0")


def load_ctl():
    loader = importlib.machinery.SourceFileLoader("keychron_ctl", CTL)
    spec = importlib.util.spec_from_loader("keychron_ctl", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def snapshot(battery=85, charging=False, levels=(400, 800, 1600, 3200, 5000),
             level=2, rate_level=2, sensor=0, debounce=4, sleep=10):
    """An opcode 0x06 reply body (report id stripped), M6-shaped."""
    b = bytearray(63)
    b[0] = 0x06
    b[1] = 0
    slot = (rate_level << 4) | level
    b[2] = b[3] = b[4] = slot
    for i, v in enumerate(levels):
        b[5 + 2 * i] = v & 0xFF
        b[6 + 2 * i] = v >> 8
    b[15] = sensor
    b[16] = len(levels)
    b[17] = debounce
    b[18] = sleep
    b[19] = (battery & 0x7F) | (0x80 if charging else 0)
    b[40], b[41] = 12000 & 0xFF, 12000 >> 8
    b[42] = 50
    b[43:46] = bytes([0, 1, 2])  # 125, 500, 1000 Hz
    b[49] = 3
    return bytes(b)


class FakeMouse:
    """Answers commands written to one end of a socketpair.

    `handler(report_id, payload)` returns a list of reply frames (each with its
    report id first), so a test can inject stale or unrelated reports.
    """

    def __init__(self, handler):
        self.ours, self.theirs = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        self.handler = handler
        self.sent = []
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        while True:
            try:
                data = self.theirs.recv(128)
            except OSError:
                return
            if not data:
                return
            self.sent.append(data)
            for frame in self.handler(data[0], data[1:]) or []:
                self.theirs.send(bytes(frame))

    def close(self):
        for s in (self.ours, self.theirs):
            try:
                s.close()
            except OSError:
                pass


class CtlTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="keychron-test-")
        os.environ["KEYCHRON_SYSFS"] = os.path.join(self.tmp, "sys")
        os.environ["KEYCHRON_DEVDIR"] = os.path.join(self.tmp, "dev")
        os.environ["KEYCHRON_STATE_DIR"] = os.path.join(self.tmp, "state")
        os.environ["KEYCHRON_TIMEOUT"] = "0.2"
        os.environ["XDG_RUNTIME_DIR"] = self.tmp
        os.makedirs(os.environ["KEYCHRON_SYSFS"])
        os.makedirs(os.environ["KEYCHRON_DEVDIR"])
        self.ctl = load_ctl()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def add_node(self, name, bus, vid, pid, descriptor=VENDOR_DESCRIPTOR):
        dev = os.path.join(os.environ["KEYCHRON_SYSFS"], name, "device")
        os.makedirs(dev)
        with open(os.path.join(dev, "uevent"), "w") as f:
            f.write("DRIVER=hid-generic\nHID_ID=%04X:%08X:%08X\nHID_NAME=Keychron\n" % (bus, vid, pid))
        with open(os.path.join(dev, "report_descriptor"), "wb") as f:
            f.write(descriptor)

    def attach(self, mouse):
        """Make every Device in the module talk to `mouse` instead of /dev."""
        test = self

        class Fake(self.ctl.Device):
            def __init__(self, node):
                self.node = node
                self.fd = os.dup(mouse.ours.fileno())
                os.set_blocking(self.fd, False)

        self.ctl.Device = Fake
        self.addCleanup(mouse.close)
        return test
