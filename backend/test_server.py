"""Run with: python backend/test_server.py. No real robot connections."""

import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
from server import APIError, CHARGER, Controller, Store, ThreadingHTTPServer, handler_for


class FakeRobot:
    def __init__(self):
        self.goal = CHARGER
        self.distance = 0
        self.commands = []
        self.offline = False
        self.emergency = 1

    def read(self, name):
        if self.offline:
            raise OSError("offline")
        return {
            "base": {"battery": 95, "chargeFlag": 0, "emergencyButton": self.emergency},
            "speed": {"vx": 0},
            "nav": {"goal": self.goal, "dist": self.distance},
        }[name]

    def navigate(self, point):
        self.commands.append(point)
        self.goal, self.distance = point, 0.5

    def lift(self, direction):
        self.commands.append("lift:" + direction)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "state.sqlite3"
        self.robot = FakeRobot()
        self.now = 1000.0
        self.controller = self.restore()

    def restore(self):
        return Controller(Store(self.db), self.robot, clock=lambda: self.now)

    def tick(self, count=1):
        for _ in range(count):
            self.now += 2
            self.controller.poll()
            self.controller.route_tick()

    def draft(self, points):
        version = self.controller.snapshot()["draft"]["version"]
        return self.controller.action("/api/draft", {"points": points, "version": version})

    def start(self, points):
        state = self.draft(points)
        return self.controller.action("/api/route/start", {"version": state["draft"]["version"]})

    def test_draft_survives_restart_and_conflicting_edit_is_rejected(self):
        self.draft(["ОП1", "ВП4", "ВП2.1-3.1"])
        self.controller = self.restore()
        self.assertEqual(self.controller.snapshot()["draft"]["points"], ["ОП1", "ВП4_2", "ВП2.1,3.1"])
        with self.assertRaises(APIError) as error:
            self.controller.action("/api/draft", {"points": [], "version": 0})
        self.assertEqual(error.exception.status, 409)

    def test_route_continues_after_controller_restart_without_duplicate_command(self):
        self.start(["ОП1", "ВП4"])
        self.tick()
        self.assertEqual(self.robot.commands, ["ОП1"])
        self.controller = self.restore()
        self.assertFalse(self.controller.snapshot()["online"])
        self.tick(12)
        self.assertEqual(self.robot.commands, ["ОП1", "ВП4_2", CHARGER])
        self.assertEqual(self.controller.snapshot()["route"]["status"], "completed")

    def test_cancel_skips_remaining_points_and_persists_return(self):
        self.start(["ОП1", "ОП2"])
        self.tick()
        self.controller.action("/api/route/cancel", {})
        self.controller = self.restore()
        self.tick(5)
        self.assertEqual(self.robot.commands, ["ОП1", CHARGER])
        self.assertEqual(self.controller.snapshot()["route"]["status"], "cancelled")

    def test_cancel_during_inflight_command_preserves_order(self):
        self.start(["ОП1", "ОП2"])
        self.controller.poll()
        entered, release = threading.Event(), threading.Event()
        original = self.robot.navigate

        def blocking_navigate(point):
            entered.set()
            if not release.wait(3):
                raise TimeoutError("test command was not released")
            original(point)

        self.robot.navigate = blocking_navigate
        worker = threading.Thread(target=self.controller.route_tick)
        worker.start()
        try:
            self.assertTrue(entered.wait(3))
            self.controller.action("/api/route/cancel", {})
        finally:
            release.set()
            worker.join(3)
        self.robot.navigate = original
        self.tick(5)
        self.assertEqual(self.robot.commands, ["ОП1", CHARGER])
        self.assertEqual(self.controller.snapshot()["route"]["status"], "cancelled")

    def test_unknown_command_is_reconciled_without_blind_resend(self):
        self.start(["ОП1"])
        with self.controller.lock:
            self.controller.state["route"]["phase"] = "sending"
            self.controller.store.save()
        self.controller = self.restore()
        self.tick()
        self.assertEqual(self.robot.commands, [])
        self.assertEqual(self.controller.snapshot()["route"]["status"], "error")

    def test_accepted_command_after_crash_is_not_resent(self):
        self.start(["ОП1"])
        self.controller.state["route"]["phase"] = "sending"
        self.controller.store.save()
        self.robot.goal, self.robot.distance = "ОП1", 0.5
        self.controller = self.restore()
        self.tick(8)
        self.assertEqual(self.robot.commands, [CHARGER])
        self.assertEqual(self.controller.snapshot()["route"]["status"], "completed")

    def test_offline_and_emergency_do_not_dispatch_commands(self):
        self.start(["ОП1"])
        self.robot.offline = True
        self.tick(2)
        self.assertFalse(self.controller.snapshot()["online"])
        self.assertEqual(self.robot.commands, [])
        self.robot.offline, self.robot.emergency = False, 0
        self.tick()
        self.assertEqual(self.robot.commands, [])
        self.robot.emergency = 1
        self.tick()
        self.assertEqual(self.robot.commands, ["ОП1"])

    def test_start_and_manual_commands_conflict_with_active_route(self):
        self.start(["ОП1"])
        for path, body in [("/api/route/start", {"version": 1}), ("/api/navigate", {"point": "ОП2"})]:
            with self.assertRaises(APIError) as error:
                self.controller.action(path, body)
            self.assertEqual(error.exception.status, 409)

    def test_clearing_draft_does_not_change_running_route(self):
        self.start(["ОП1"])
        self.draft([])
        self.tick(8)
        self.assertEqual(self.robot.commands, ["ОП1", CHARGER])
        self.assertEqual(self.controller.snapshot()["draft"]["points"], [])

    def test_same_point_and_repeated_charger_can_finish(self):
        self.start([CHARGER, CHARGER])
        self.tick(8)
        self.assertEqual(self.robot.commands, [CHARGER, CHARGER])
        self.assertEqual(self.controller.snapshot()["route"]["status"], "completed")

    def test_motion_uses_distance_and_three_confirmations(self):
        self.robot.goal, self.robot.distance = "ОП1", 3
        self.tick(3)
        self.assertFalse(self.controller.snapshot()["motion"]["stopped"])
        self.robot.distance = 0.5
        self.tick(2)
        self.assertFalse(self.controller.snapshot()["motion"]["stopped"])
        self.tick()
        self.assertTrue(self.controller.snapshot()["motion"]["stopped"])

    def test_last_lift_command_persists(self):
        self.controller.action("/api/lift", {"direction": "up"})
        self.controller.poll()
        self.controller.lift_tick()
        self.controller = self.restore()
        self.assertEqual(self.controller.snapshot()["lift"]["last_command"], "up")
        self.assertEqual(self.robot.commands, ["lift:up"])

    def test_invalid_telemetry_is_not_treated_as_online(self):
        self.start(["ОП1"])
        original = self.robot.read
        self.robot.read = lambda name: {} if name == "nav" else original(name)
        self.tick()
        self.assertFalse(self.controller.snapshot()["online"])
        self.assertEqual(self.robot.commands, [])

    def test_timeout_after_command_acceptance_does_not_repeat_point(self):
        self.start(["ОП1"])
        original = self.robot.navigate

        def accepted_then_timeout(point):
            original(point)
            raise TimeoutError("response lost")

        self.robot.navigate = accepted_then_timeout
        with self.assertLogs(level="ERROR"):
            self.tick()
        self.robot.navigate = original
        self.tick(8)
        self.assertEqual(self.robot.commands, ["ОП1", CHARGER])
        self.assertEqual(self.controller.snapshot()["route"]["status"], "completed")

    def test_invalid_points_and_versions_do_not_change_state(self):
        for points in [["unknown"], "ОП1", [None], ["ОП1"] * 101]:
            with self.assertRaises(APIError):
                self.draft(points)
        self.assertEqual(self.controller.snapshot()["draft"]["points"], [])

    def test_http_api_and_static_files(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(self.controller))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with urlopen(base + "/") as response:
                self.assertIn(b"connection-status", response.read())
            request = Request(base + "/api/draft", data=json.dumps({"points": ["ОП1"], "version": 0}).encode(),
                              headers={"Content-Type": "application/json", "Origin": base})
            with urlopen(request) as response:
                self.assertEqual(json.load(response)["draft"]["points"], ["ОП1"])
            with urlopen(base + "/api/state") as response:
                self.assertEqual(json.load(response)["draft"]["version"], 1)
            for path in ("/backend/data/robot.sqlite3", "/reference/../README.md", "/.git/config"):
                with self.assertRaises(HTTPError) as error:
                    urlopen(base + path)
                self.assertEqual(error.exception.code, 404)
            request = Request(base + "/api/route/start", data=b'{"version":1}',
                              headers={"Content-Type": "application/json", "Origin": "http://other-site"})
            with self.assertRaises(HTTPError) as error:
                urlopen(request)
            self.assertEqual(error.exception.code, 403)
            self.assertEqual(self.robot.commands, [])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
