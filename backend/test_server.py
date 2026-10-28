"""Run with: python backend/test_server.py. No real robot connections."""

import json
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
from server import APIError, CHARGER, Controller, Robot, Store, ThreadingHTTPServer, handler_for, BaseHTTPRequestHandler, load_timing


class FakeRobot:
    def __init__(self):
        self.url = 'http://test-robot'
        self.goal = CHARGER
        self.distance = 0
        self.commands = []
        self.offline = False
        self.emergency = 1

    def read(self, name):
        if self.offline:
            raise OSError("offline")
        return {
            "base": {"battery": 95, "chargeFlag": 2 if self.goal == CHARGER else 0, "emergencyButton": self.emergency},
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
        self.timing = {'route_wait_seconds': 120, 'idle_return_seconds': 600}
        self.controller = self.restore()

    def restore(self):
        controller = Controller(Store(self.db), self.robot, clock=lambda: self.now, timing=self.timing)
        self.addCleanup(controller.close)
        return controller

    def tick(self, count=1):
        for _ in range(count):
            self.now += 2
            self.controller.poll()
            self.controller.route_tick()

    def navigation_commands(self):
        return [command for command in self.robot.commands if not command.startswith('lift:')]

    def finish_route(self):
        for _ in range(40):
            route = self.controller.snapshot()['route']
            if route['status'] not in ('running', 'returning'):
                return
            if route['phase'] == 'dwell':
                self.now = max(self.now, route['dwell_until'])
            self.tick()
        self.fail('Route did not finish')

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

    def test_manual_navigation_does_not_change_route_status(self):
        self.controller.poll()
        before = self.controller.snapshot()["route"]
        self.controller.action("/api/navigate", {"point": "ОП1"})
        self.assertEqual(self.controller.snapshot()["route"], before)

    def test_route_arrival_lowers_lift_and_waits_two_minutes(self):
        self.start(["ОП1", "ОП2"])
        self.tick(4)
        state = self.controller.snapshot()
        self.assertEqual(state["route"]["phase"], "dwell")
        self.assertEqual(self.robot.commands, ['lift:up', "ОП1", "lift:down"])

    def test_lift_is_raised_before_first_movement_and_stays_up_at_finish(self):
        self.start(['ОП1'])
        self.finish_route()
        self.assertEqual(self.robot.commands[:2], ['lift:up', 'ОП1'])
        self.assertEqual(self.robot.commands.count('lift:down'), 1)
        self.assertEqual(self.controller.snapshot()['lift']['last_command'], 'up')
        self.assertEqual(self.robot.goal, CHARGER)

    def test_failed_initial_lift_prevents_first_movement(self):
        self.start(['ОП1'])
        self.robot.lift = lambda direction: (_ for _ in ()).throw(OSError('lift unavailable'))
        self.tick()
        self.assertEqual(self.navigation_commands(), [])
        self.assertEqual(self.controller.snapshot()['route']['status'], 'error')

    def test_emergency_does_not_extend_wait_but_blocks_departure(self):
        self.start(['ОП1', 'ОП2'])
        self.tick(4)
        deadline = self.controller.snapshot()['route']['dwell_until']
        self.now += 30
        self.robot.emergency = 0
        self.controller.poll()
        self.controller.route_tick()
        self.assertEqual(self.controller.snapshot()['route']['dwell_until'], deadline)
        self.now += 300
        self.controller.poll()
        self.controller.route_tick()
        self.assertEqual(self.controller.snapshot()['route']['dwell_until'], deadline)
        self.assertEqual(self.navigation_commands(), ['ОП1'])
        self.robot.emergency = 1
        self.controller.poll()
        self.controller.route_tick()
        self.assertEqual(self.navigation_commands(), ['ОП1', 'ОП2'])

    def test_deadline_survives_restart_during_emergency_without_extension(self):
        self.start(['ОП1'])
        self.tick(4)
        deadline = self.controller.snapshot()['route']['dwell_until']
        self.now += 20
        self.robot.emergency = 0
        self.controller.poll()
        self.now += 200
        self.controller = self.restore()
        self.controller.poll()
        self.assertEqual(self.controller.snapshot()['route']['dwell_until'], deadline)
        self.robot.emergency = 1
        self.controller.poll()
        self.assertEqual(self.controller.snapshot()['route']['dwell_until'], deadline)

    def test_custom_wait_values_control_dwell_and_idle_return(self):
        self.controller.timing = {'route_wait_seconds': 7, 'idle_return_seconds': 12}
        self.start(['ОП1'])
        self.tick(4)
        self.assertEqual(self.controller.snapshot()['route']['dwell_until'], self.now + 7)
        self.controller.action('/api/route/cancel', {})
        # Simulate an independent, cancelled route and a stationary robot.
        self.controller.state['route'].update(status='cancelled', phase='done')
        self.controller.state['navigation']['status'] = 'idle'
        self.controller.reset_stationary()
        self.controller.poll()
        for _ in range(5):
            self.now += 2
            self.controller.poll()
        self.assertFalse(self.controller.snapshot()['navigation'].get('automatic', False))
        self.now += 2
        self.controller.poll()
        self.assertTrue(self.controller.snapshot()['navigation']['automatic'])

    def test_main_js_wait_constants_are_parsed_without_evaluating_code(self):
        source = Path(self.temp.name) / 'settings.js'
        source.write_text('const ROUTE_WAIT_SECONDS = 15;\nconst IDLE_RETURN_SECONDS = 45;', encoding='utf-8')
        self.assertEqual(load_timing(source), {'route_wait_seconds': 15, 'idle_return_seconds': 45})
        source.write_text('const ROUTE_WAIT_SECONDS = 0;\nconst IDLE_RETURN_SECONDS = 45;', encoding='utf-8')
        with self.assertRaises(ValueError):
            load_timing(source)

    def test_saved_main_js_settings_are_reloaded_and_bad_edits_keep_previous_values(self):
        source = Path(self.temp.name) / 'settings.js'
        source.write_text('const ROUTE_WAIT_SECONDS = 15;\nconst IDLE_RETURN_SECONDS = 45;', encoding='utf-8')
        self.controller.watch_timing = True
        self.controller.timing_signature = -1
        with patch('server.TIMING_FILE', source):
            self.controller.refresh_timing()
            self.assertEqual(self.controller.timing, {'route_wait_seconds': 15, 'idle_return_seconds': 45})
            source.write_text('const ROUTE_WAIT_SECONDS = invalid;', encoding='utf-8')
            self.controller.timing_signature = -1
            with self.assertLogs(level='ERROR'):
                self.controller.refresh_timing()
            self.assertEqual(self.controller.timing, {'route_wait_seconds': 15, 'idle_return_seconds': 45})

    def test_departure_waits_full_two_minutes_and_raises_lift_concurrently(self):
        self.start(['ОП1', 'ОП2'])
        self.tick(4)
        deadline = self.controller.snapshot()['route']['dwell_until']
        self.now = deadline - 0.1
        self.controller.poll()
        self.controller.route_tick()
        self.assertEqual(self.robot.commands, ['lift:up', 'ОП1', 'lift:down'])
        raised = threading.Event()
        navigate, lift = self.robot.navigate, self.robot.lift

        def depart(point):
            self.assertTrue(raised.wait(3), 'Lift-up was not concurrent with navigation')
            navigate(point)

        def raise_lift(direction):
            lift(direction)
            raised.set()

        self.robot.navigate, self.robot.lift = depart, raise_lift
        self.now = deadline
        self.controller.poll()
        self.controller.route_tick()
        self.assertEqual(self.navigation_commands(), ['ОП1', 'ОП2'])
        self.assertIn('lift:up', self.robot.commands)

    def test_dwell_survives_restart_without_repeating_lift_down(self):
        self.start(['ОП1', 'ОП2'])
        self.tick(4)
        deadline = self.controller.snapshot()['route']['dwell_until']
        self.now += 60
        self.controller = self.restore()
        self.controller.poll()
        self.controller.route_tick()
        self.assertEqual(self.controller.snapshot()['route']['dwell_until'], deadline)
        self.assertEqual(self.robot.commands, ['lift:up', 'ОП1', 'lift:down'])
        self.now = deadline
        self.controller.poll()
        self.controller.route_tick()
        self.assertEqual(self.navigation_commands(), ['ОП1', 'ОП2'])

    def test_moving_robot_near_target_does_not_lower_lift(self):
        self.start(['ОП1'])
        self.tick()
        read = self.robot.read
        self.robot.read = lambda name: {'vx': 0.2, 'vth': 0} if name == 'speed' else read(name)
        self.tick(5)
        self.assertNotIn('lift:down', self.robot.commands)
        self.assertEqual(self.controller.snapshot()['route']['phase'], 'waiting')

    def test_manual_retarget_requires_confirmation_and_preserves_route_status(self):
        self.controller.poll()
        self.controller.action('/api/navigate', {'point': 'ОП1'})
        self.controller.navigation_tick()
        self.controller.poll()
        before = self.controller.snapshot()['route']
        with self.assertRaises(APIError) as error:
            self.controller.action('/api/navigate', {'point': 'ОП2'})
        self.assertEqual(error.exception.details['code'], 'confirmation_required')
        token = error.exception.details['confirmation']
        self.controller.action('/api/navigate', {'point': 'ОП2', 'confirmation': token})
        self.controller.navigation_tick()
        self.assertEqual(self.navigation_commands(), ['ОП1', 'ОП2'])
        self.assertEqual(self.controller.snapshot()['route'], before)

    def test_stale_confirmation_does_not_interrupt_a_newer_call(self):
        self.robot.goal = 'ОП1'
        self.controller.poll()
        with self.assertRaises(APIError) as error:
            self.controller.action('/api/navigate', {'point': 'ОП2'})
        token = error.exception.details['confirmation']
        self.controller.action('/api/navigate', {'point': 'ОП3', 'confirmation': token})
        with self.assertRaises(APIError) as error:
            self.controller.action('/api/navigate', {'point': 'ОП2', 'confirmation': token})
        self.assertEqual(error.exception.details['code'], 'confirmation_required')

    def test_ten_minute_standstill_schedules_return_without_changing_route(self):
        self.robot.goal = 'ОП1'
        self.controller.poll()
        before = self.controller.snapshot()['route']
        since = self.now
        for _ in range(299):
            self.now += 2
            self.controller.poll()
        self.assertEqual(self.navigation_commands(), [])
        self.assertEqual(self.controller.snapshot()['stationary']['since'], since)
        self.now += 2
        self.controller.poll()
        self.controller.navigation_tick()
        self.assertEqual(self.navigation_commands(), [CHARGER])
        self.assertEqual(self.controller.snapshot()['route'], before)
        self.assertTrue(self.controller.snapshot()['navigation']['automatic'])

    def test_idle_timer_resets_on_motion_and_offline_and_ignores_charger(self):
        self.robot.goal = 'ОП1'
        self.controller.poll()
        self.assertIsNotNone(self.controller.snapshot()['stationary']['since'])
        read = self.robot.read
        self.robot.read = lambda name: {'vx': 0.1} if name == 'speed' else read(name)
        self.tick()
        self.assertIsNone(self.controller.snapshot()['stationary']['since'])
        self.robot.read = read
        self.controller.poll()
        self.robot.offline = True
        self.controller.poll()
        self.assertIsNone(self.controller.snapshot()['stationary']['since'])
        self.robot.offline = False
        self.robot.goal = CHARGER
        self.controller.poll()
        self.assertIsNone(self.controller.snapshot()['stationary']['since'])

    def test_manual_lift_is_blocked_while_route_is_active(self):
        self.start(['ОП1'])
        self.controller.poll()
        for direction in ('up', 'down'):
            with self.assertRaises(APIError) as error:
                self.controller.action('/api/lift', {'direction': direction})
            self.assertEqual(error.exception.status, 409)

    def test_emergency_goal_reset_during_dwell_does_not_discard_route(self):
        self.start(['ОП1', 'ОП2'])
        self.tick(4)
        original = self.controller.snapshot()['route']
        self.robot.emergency, self.robot.goal = 0, ''
        self.tick()
        self.robot.emergency = 1
        self.tick()
        current = self.controller.snapshot()['route']
        self.assertEqual(current['status'], 'running')
        self.assertEqual(current['id'], original['id'])
        self.assertEqual(current['dwell_until'], original['dwell_until'])
        self.assertEqual(self.navigation_commands(), ['ОП1'])
        self.now = original['dwell_until']
        self.controller.poll()
        self.controller.route_tick()
        self.assertEqual(self.navigation_commands(), ['ОП1', 'ОП2'])

    def test_emergency_goal_reset_while_moving_restores_same_route_step(self):
        self.start(['ОП1', 'ОП2'])
        self.tick()
        original = self.controller.snapshot()['route']
        self.robot.emergency, self.robot.goal = 0, ''
        self.tick()
        self.assertEqual(self.controller.snapshot()['route']['status'], 'running')
        self.assertEqual(self.navigation_commands(), ['ОП1'])
        self.robot.emergency = 1
        self.tick()
        current = self.controller.snapshot()['route']
        self.assertEqual(current['id'], original['id'])
        self.assertEqual(current['index'], 0)
        self.assertEqual(current['points'], original['points'])
        self.assertEqual(self.navigation_commands(), ['ОП1', 'ОП1'])

    def test_emergency_during_initial_lift_does_not_fail_route(self):
        self.start(['ОП1'])
        lift = self.robot.lift

        def stopped_lift(direction):
            self.robot.emergency = 0
            self.controller.poll()
            raise OSError('emergency stop')

        self.robot.lift = stopped_lift
        self.tick()
        self.assertEqual(self.controller.snapshot()['route']['status'], 'running')
        self.assertEqual(self.controller.snapshot()['route']['phase'], 'preparing')
        self.assertEqual(self.navigation_commands(), [])
        self.robot.emergency, self.robot.lift = 1, lift
        self.tick()
        self.assertEqual(self.navigation_commands(), ['ОП1'])

    def test_late_emergency_sample_keeps_buttons_locked_and_recovers_route(self):
        self.start(['ОП1', 'ОП2'])
        lift = self.robot.lift
        self.robot.lift = lambda direction: (_ for _ in ()).throw(OSError('emergency before next GET'))
        self.tick()
        state = self.controller.snapshot()
        self.assertTrue(state['route'].get('locked', state['route']['status'] == 'running'))
        self.robot.emergency = 0
        self.controller.poll()
        self.controller.route_tick()
        self.assertEqual(self.controller.snapshot()['route']['status'], 'running')
        self.assertTrue(self.controller.snapshot()['route']['locked'])
        self.robot.emergency, self.robot.lift = 1, lift
        self.tick()
        self.assertEqual(self.navigation_commands(), ['ОП1'])

    def test_final_charger_goal_without_charging_does_not_complete_route(self):
        self.start(['ОП1'])
        self.tick(4)
        self.now = self.controller.snapshot()['route']['dwell_until']
        self.controller.poll()
        self.controller.route_tick()
        read = self.robot.read
        self.robot.read = lambda name: dict(read(name), chargeFlag=0) if name == 'base' else read(name)
        self.tick(5)
        self.assertEqual(self.controller.snapshot()['route']['status'], 'running')
        self.assertTrue(self.controller.snapshot()['route']['locked'])

    def test_command_error_keeps_control_locked_until_explicit_cancel(self):
        self.start(['ОП1'])
        self.robot.lift = lambda direction: (_ for _ in ()).throw(OSError('command rejected'))
        self.tick()
        self.assertEqual(self.controller.snapshot()['route']['status'], 'error')
        self.assertTrue(self.controller.snapshot()['route']['locked'])
        for path, body in [('/api/draft', {'points': [], 'version': 1}),
                           ('/api/navigate', {'point': 'ОП2'}),
                           ('/api/lift', {'direction': 'up'})]:
            with self.assertRaises(APIError) as error:
                self.controller.action(path, body)
            self.assertEqual(error.exception.status, 409)
        self.controller.action('/api/route/cancel', {})
        self.assertFalse(self.controller.snapshot()['route']['locked'])

    def test_emergency_during_lowering_preserves_route_and_retries_after_release(self):
        self.start(['ОП1', 'ОП2'])
        self.tick(3)
        lift = self.robot.lift

        def stopped_lift(direction):
            self.robot.emergency = 0
            self.controller.poll()
            raise OSError('emergency stop')

        self.robot.lift = stopped_lift
        self.tick()
        self.assertEqual(self.controller.snapshot()['route']['status'], 'running')
        self.assertEqual(self.controller.snapshot()['route']['phase'], 'lower_retry')
        self.robot.emergency, self.robot.lift = 1, lift
        self.tick()
        self.assertEqual(self.controller.snapshot()['route']['phase'], 'dwell')
        self.assertEqual(self.navigation_commands(), ['ОП1'])

    def test_automatic_return_notice_expires_while_return_continues(self):
        self.controller.new_navigation(CHARGER, automatic=True)
        self.assertEqual(self.controller.snapshot()['navigation']['message'], 'Автовозврат на зарядку')
        self.now += 7
        self.controller.poll()
        self.assertEqual(self.controller.snapshot()['navigation']['message'], '')
        self.assertEqual(self.controller.snapshot()['navigation']['status'], 'ready')

    def test_automatic_return_notice_clears_on_arrival_and_new_route(self):
        self.controller.poll()
        self.controller.new_navigation(CHARGER, automatic=True)
        self.controller.navigation_tick()
        self.controller.poll()
        self.controller.navigation_tick()
        self.assertEqual(self.controller.snapshot()['navigation']['message'], '')
        self.controller.new_navigation(CHARGER, automatic=True)
        self.start(['ОП1'])
        self.assertEqual(self.controller.snapshot()['navigation']['message'], '')

    def test_post_does_not_wait_for_unused_robot_response_body(self):
        release = threading.Event()

        class SlowBody(BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(200)
                self.send_header('Content-Length', '4096')
                self.end_headers()
                release.wait(3)  # Deliberately never send a response body.

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), SlowBody)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        done = threading.Event()
        errors = []

        def send():
            try:
                Robot(f'http://127.0.0.1:{server.server_port}', timeout=1).navigate('ОП1')
            except Exception as error:
                errors.append(error)
            finally:
                done.set()

        command = threading.Thread(target=send)
        command.start()
        try:
            self.assertTrue(done.wait(0.8), 'Command waited for an unused HTTP response body')
            self.assertEqual(errors, [])
        finally:
            release.set()
            command.join(3)
            server.shutdown()
            server.server_close()
            server_thread.join(3)

    def test_command_dispatch_does_not_wait_for_slow_telemetry(self):
        self.controller.poll()
        blocked, release = threading.Event(), threading.Event()
        read = self.robot.read

        def slow_read(name):
            blocked.set()
            release.wait(3)
            return read(name)

        self.robot.read = slow_read
        poller = threading.Thread(target=self.controller.poll)
        poller.start()
        try:
            self.assertTrue(blocked.wait(3))
            self.controller.action('/api/navigate', {'point': 'ОП1'})
            self.controller.navigation_tick()
            self.assertEqual(self.navigation_commands(), ['ОП1'])
        finally:
            release.set()
            poller.join(3)

    def test_route_continues_after_controller_restart_without_duplicate_command(self):
        self.start(["ОП1", "ВП4"])
        self.tick()
        self.assertEqual(self.robot.commands, ['lift:up', "ОП1"])
        self.controller = self.restore()
        self.assertFalse(self.controller.snapshot()["online"])
        self.finish_route()
        self.assertEqual(self.navigation_commands(), ["ОП1", "ВП4_2", CHARGER])
        self.assertEqual(self.controller.snapshot()["route"]["status"], "completed")

    def test_cancel_skips_remaining_points_and_persists_return(self):
        self.start(["ОП1", "ОП2"])
        self.tick()
        self.controller.action("/api/route/cancel", {})
        self.controller = self.restore()
        self.tick(5)
        self.assertEqual(self.navigation_commands(), ["ОП1", CHARGER])
        self.assertEqual(self.controller.snapshot()["route"]["status"], "cancelled")

    def test_cancel_immediately_unlocks_draft_and_new_route(self):
        self.start(['ОП1', 'ОП2'])
        self.tick()
        self.controller.action('/api/route/cancel', {})
        self.assertEqual(self.controller.snapshot()['route']['status'], 'returning')
        state = self.draft(['ОП3'])
        self.controller.action('/api/route/start', {'version': state['draft']['version']})
        self.tick()
        self.assertEqual(self.navigation_commands(), ['ОП1', 'ОП3'])

    def test_cancel_allows_confirmed_manual_retarget_without_late_charger(self):
        self.start(['ОП1', 'ОП2'])
        self.tick()
        self.controller.action('/api/route/cancel', {})
        self.controller.poll()
        with self.assertRaises(APIError) as error:
            self.controller.action('/api/navigate', {'point': 'ОП3'})
        self.assertEqual(error.exception.details['code'], 'confirmation_required')
        self.controller.action('/api/navigate', {'point': 'ОП3', 'confirmation': error.exception.details['confirmation']})
        self.controller.navigation_tick()
        self.tick(5)
        self.assertEqual(self.navigation_commands(), ['ОП1', 'ОП3'])
        self.assertEqual(self.controller.snapshot()['route']['status'], 'cancelled')

    def test_cancel_allows_manual_lift_down_during_return(self):
        self.start(['ОП1'])
        self.controller.action('/api/route/cancel', {})
        self.controller.poll()
        self.controller.action('/api/lift', {'direction': 'down'})
        self.controller.lift_tick()
        self.assertIn('lift:down', self.robot.commands)

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
        self.assertEqual(self.navigation_commands(), ["ОП1", CHARGER])
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
        self.finish_route()
        self.assertEqual(self.navigation_commands(), [CHARGER])
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
        self.assertEqual(self.robot.commands, ['lift:up', "ОП1"])

    def test_start_and_manual_commands_conflict_with_active_route(self):
        self.start(["ОП1"])
        for path, body in [("/api/route/start", {"version": 1}), ("/api/navigate", {"point": "ОП2"})]:
            with self.assertRaises(APIError) as error:
                self.controller.action(path, body)
            self.assertEqual(error.exception.status, 409)

    def test_active_route_blocks_draft_changes(self):
        self.start(["ОП1"])
        with self.assertRaises(APIError) as error:
            self.draft([])
        self.assertEqual(error.exception.status, 409)
        self.finish_route()
        self.assertEqual(self.navigation_commands(), ["ОП1", CHARGER])

    def test_same_point_and_repeated_charger_can_finish(self):
        self.start([CHARGER, CHARGER])
        self.finish_route()
        self.assertEqual(self.navigation_commands(), [CHARGER, CHARGER])
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
        self.finish_route()
        self.assertEqual(self.navigation_commands(), ["ОП1", CHARGER])
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
