"""Persistent robot controller. Python 3.10+, standard library only."""

import argparse
import copy
import json
import logging
import math
import os
import re
import signal
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
CHARGER = "Зарядка"
ALIASES = {"ВП4": "ВП4_2", "ВП2.1-3.1": "ВП2.1,3.1"}
POINTS = {CHARGER, "АС", "ворота", "склад", "ВП4_1", "ВП4_2", "ВП2.1,3.1"}
POINTS.update(f"ОП{i}" for i in range(1, 6))
POINTS.update(f"ВП{i}" for i in range(1, 6) if i != 4)
ACTIVE = {"running", "returning"}
POLL_INTERVAL = 0.5
FRESH_SECONDS = 5
WEB_ROOT = ROOT / 'code'
ASSET_ROOT = WEB_ROOT / 'assets'
TIMING_FILE = WEB_ROOT / 'main.js'
ROBOT_PATHS = {"base": "/reeman/base_encode", "speed": "/reeman/speed", "nav": "/reeman/nav_status"}


class APIError(Exception):
    def __init__(self, message, status=400, **details):
        super().__init__(message)
        self.status = status
        self.details = details


def load_timing(path=TIMING_FILE):
    """Read numeric constants without evaluating JavaScript."""
    source = path.read_text(encoding='utf-8')
    result = {}
    for constant, key in (('ROUTE_WAIT_SECONDS', 'route_wait_seconds'), ('IDLE_RETURN_SECONDS', 'idle_return_seconds')):
        match = re.search(r'^const\s+' + constant + r'\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*;', source, re.MULTILINE)
        if not match or not 0 < float(match[1]) < float('inf'):
            raise ValueError(f'{constant}: задайте положительное число секунд в main.js')
        result[key] = float(match[1])
    return result


def number(value):
    if value is None or isinstance(value, bool) or str(value).strip() == "":
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def point_name(value):
    if not isinstance(value, str) or ALIASES.get(value, value) not in POINTS:
        raise APIError("Неизвестная точка")
    return ALIASES.get(value, value)


def point_list(value):
    if not isinstance(value, list) or len(value) > 100:
        raise APIError("Маршрут должен содержать не более 100 точек")
    return [point_name(point) for point in value]


def initial_state():
    return {
        "revision": 0,
        "draft": {"points": [], "version": 0},
        "route": {"status": "idle", "message": "Маршрут не запущен", "points": []},
        "robot": {name: {"data": {}, "updated_at": 0, "error": "Нет данных"}
                  for name in ("base", "speed", "nav")},
        "navigation": {"status": "idle", "message": ""},
        "stationary": {"point": None, "since": None, "last_sample": None},
        # Last accepted lift command, not a physical position sensor.
        "lift": {"last_command": None, "status": "idle"},
    }


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL)")
            row = connection.execute("SELECT body FROM state WHERE id=1").fetchone()
        self.state = json.loads(row[0]) if row else initial_state()
        if not row:
            self.save()

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def save(self):
        self.state["revision"] += 1
        with self.connect() as connection:
            connection.execute("INSERT OR REPLACE INTO state VALUES (1, ?)",
                               (json.dumps(self.state, ensure_ascii=False, allow_nan=False),))


class Robot:
    def __init__(self, url, timeout=3):
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("Robot URL must be an HTTP(S) URL")
        self.url = url.rstrip("/")
        self.timeout = timeout

    def request(self, path, body=None):
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = Request(self.url + path, data=data, headers={"Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                if body is not None:
                    return None  # The HTTP acknowledgement is enough; do not wait for an unused body.
                raw = response.read(1024 * 1024)
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError("Expected a JSON object")
            return result
        except (OSError, ValueError) as error:
            if isinstance(error, HTTPError):
                error.close()
            raise APIError("Нет связи с роботом или неверный ответ API", 502) from error

    def read(self, name):
        return self.request(ROBOT_PATHS[name])

    def navigate(self, point):
        self.request("/cmd/nav_name", {"point": point})

    def lift(self, direction):
        self.request(f"/cmd/hydraulic_{direction}", 0)


class DemoRobot:
    """Offline simulator; never opens a connection to the real robot."""
    def __init__(self, nav=None):
        self.goal = (nav or {}).get("goal", CHARGER)
        self.distance = number((nav or {}).get("dist")) or 0

    def read(self, name):
        if name == "base":
            return {"battery": 100, "chargeFlag": 2 if self.goal == CHARGER and self.distance == 0 else 0,
                    "emergencyButton": 1}
        if name == "speed":
            return {"vx": 0.3 if self.distance > 0 else 0, "vth": 0}
        self.distance = max(0, self.distance - 0.3)
        return {"goal": self.goal, "dist": round(self.distance, 2)}

    def navigate(self, point):
        self.goal, self.distance = point, 2.5

    def lift(self, direction):
        pass


class Controller:
    def __init__(self, store, robot, clock=time.time, timing=None):
        self.store, self.robot, self.clock = store, robot, clock
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.wake_event = threading.Event()
        self.thread = self.poll_thread = None
        self.read_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix='telemetry')
        self.command_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='robot-command')
        self.closed = False
        self.timing = dict(timing) if timing is not None else load_timing(TIMING_FILE)
        self.watch_timing = timing is None
        self.timing_signature = TIMING_FILE.stat().st_mtime_ns
        state = store.state
        state.pop('motion', None)  # Motion display is computed from direct GETs in the panel.
        state.setdefault('navigation', {'status': 'idle', 'message': ''})
        state.setdefault('stationary', {'point': None, 'since': None, 'last_sample': None})
        # Migrate old manual calls out of the route state without resending them.
        if state['route'].get('kind') == 'manual':
            old = state['route']
            state['navigation'] = {'id': old['id'], 'point': old['points'][0],
                                   'status': 'sending' if old['status'] in ACTIVE else 'completed', 'message': ''}
            state['route'] = initial_state()['route']
        for sample in state['robot'].values():
            sample['error'] = 'Ожидание связи после запуска сервера'
        if state['lift']['status'] == 'sending':
            state['lift'].update(status='error', error='Результат команды лифта после перезапуска неизвестен')
        # A physical lift command cannot be reconstructed from navigation alone.
        route = state['route']
        route.pop('dwell_paused', None)
        route.pop('dwell_remaining', None)
        if route.get('phase') in ('lowering', 'raising') or (route.get('phase') == 'sending' and route.get('raise_on_departure')):
            route.update(status='error', message='Результат команды лифта неизвестен. Проверьте положение лифта')
        self.expire_navigation_notice()
        store.save()

    @property
    def state(self):
        return self.store.state

    def fresh(self, name):
        sample = self.state['robot'][name]
        return not sample['error'] and self.clock() - sample['updated_at'] < FRESH_SECONDS

    def ready(self):
        return all(self.fresh(name) for name in ROBOT_PATHS) and number(self.state['robot']['base']['data'].get('emergencyButton')) == 1

    def physically_stopped(self):
        data = self.state['robot']['speed']['data']
        vx, vth = number(data.get('vx')), number(data.get('vth', 0))
        return vx is not None and vth is not None and abs(vx) <= 0.001 and abs(vth) <= 0.001

    def at_charger(self):
        base, nav = self.state['robot']['base']['data'], self.state['robot']['nav']['data']
        distance = number(nav.get('dist'))
        return number(base.get('chargeFlag')) == 2 or (nav.get('goal') == CHARGER and distance is not None and distance <= 0.2 and self.physically_stopped())

    def route_locked(self):
        route = self.state['route']
        # A command error is not a route cancellation. Keep control ownership
        # until confirmed completion or an explicit cancellation by the operator.
        return (route.get('status') in ('running', 'error') and bool(route.get('points'))
                and not route.get('cancel_requested', False))

    def snapshot(self):
        with self.lock:
            result = copy.deepcopy(self.state)
            result['route']['locked'] = self.route_locked()
            result.update(server_time=self.clock(), online=all(self.fresh(name) for name in ROBOT_PATHS),
                          demo=isinstance(self.robot, DemoRobot))
            result['telemetry_urls'] = {name: f'/api/telemetry/{name}' if result['demo'] else self.robot.url + path
                                        for name, path in ROBOT_PATHS.items()}
            result['timing'] = dict(self.timing)
            return result

    def ensure_idle(self):
        if self.route_locked():
            raise APIError('Сначала отмените выполняемый маршрут или дождитесь его завершения', 409)

    def action(self, path, body):
        with self.lock:
            route = self.state['route']
            if path == '/api/draft':
                self.ensure_idle()
                if body.get('version') != self.state['draft']['version']:
                    raise APIError('Маршрут изменён в другом окне. Проверьте список точек.', 409)
                self.state['draft'] = {'points': point_list(body.get('points')), 'version': self.state['draft']['version'] + 1}
            elif path == '/api/route/start':
                self.ensure_idle()
                if body.get('version') != self.state['draft']['version']:
                    raise APIError('Маршрут изменён в другом окне. Проверьте список точек.', 409)
                points = list(self.state['draft']['points'])
                if not points:
                    raise APIError('Добавьте точки маршрута')
                if points[-1] != CHARGER:
                    points.append(CHARGER)
                self.state['navigation'].update(status='superseded', message='', notice_until=0)
                if self.state['lift']['status'] == 'queued':
                    self.state['lift']['status'] = 'idle'
                self.new_route(points, 'running')
            elif path == '/api/route/cancel':
                if route['status'] == 'returning':
                    return self.snapshot()
                if route['status'] not in ('running', 'error'):
                    raise APIError('Нет маршрута для отмены', 409)
                self.new_route([CHARGER], 'returning')
            elif path == '/api/navigate':
                self.ensure_idle()
                point = point_name(body.get('point'))
                if not self.ready():
                    raise APIError('Нет свежих данных робота или нажата аварийная кнопка', 503)
                navigation = self.state['navigation']
                token = {'goal': self.state['robot']['nav']['data'].get('goal'), 'navigation_id': navigation.get('id'),
                         'return_id': route.get('id') if route['status'] == 'returning' else None}
                pending = navigation['status'] in ('ready', 'sending', 'waiting') or route['status'] == 'returning'
                if (not self.at_charger() or pending) and body.get('confirmation') != token:
                    raise APIError('Вы хотите прервать направление?', 409, code='confirmation_required', confirmation=token)
                if route['status'] == 'returning':
                    # Invalidate any in-flight charger result before accepting a new target.
                    route.update(id=uuid.uuid4().hex, status='cancelled', phase='done', message='Маршрут отменён')
                self.new_navigation(point)
            elif path == '/api/lift':
                if body.get('direction') not in ('up', 'down'):
                    raise APIError('Направление лифта: up или down')
                if self.route_locked():
                    raise APIError('Ручное управление лифтом заблокировано на время маршрута', 409)
                if self.state['lift']['status'] in ('queued', 'sending'):
                    raise APIError('Команда лифта уже выполняется', 409)
                self.state['lift'].update(direction=body['direction'], status='queued', error=None)
            else:
                raise APIError('Неизвестная команда', 404)
            self.store.save()
            self.wake_event.set()  # Commands do not wait for the next telemetry polling cycle.
            return self.snapshot()

    def new_route(self, points, status):
        self.state['route'] = {
            'id': uuid.uuid4().hex, 'kind': 'route', 'status': status, 'points': points,
            'index': 0, 'phase': 'preparing' if status == 'running' else 'ready', 'near_count': 0, 'next_at': 0,
            'raise_on_departure': status == 'returning', 'started_at': self.clock(),
            'cancel_requested': status == 'returning',
            'message': 'Отмена маршрута: возврат на зарядку' if status == 'returning' else 'Маршрут принят сервером',
        }
        self.reset_stationary()

    def new_navigation(self, point, automatic=False):
        self.state['navigation'] = {'id': uuid.uuid4().hex, 'point': point, 'status': 'ready',
                                    'automatic': automatic, 'message': 'Автовозврат на зарядку' if automatic else '',
                                    'notice_until': self.clock() + 6 if automatic else 0}
        self.reset_stationary()

    def expire_navigation_notice(self):
        navigation = self.state['navigation']
        if navigation.get('automatic') and navigation.get('message') == 'Автовозврат на зарядку':
            if navigation['status'] not in ('ready', 'sending', 'waiting') or self.clock() >= navigation.get('notice_until', 0):
                navigation['message'] = ''

    def emergency_active(self):
        return self.fresh('base') and number(self.state['robot']['base']['data'].get('emergencyButton')) == 0

    def observe_emergency(self):
        route = self.state['route']
        if not self.emergency_active() or not (self.route_locked() or route['status'] == 'returning'):
            return
        route.update(emergency_interrupted=True, near_count=0)
        if route['status'] == 'error':
            # POST failures can precede the base GET reporting the physical
            # stop. Restore the saved command step when that sample arrives.
            retry_phase = {'raising': 'preparing', 'lowering': 'lower_retry', 'sending': 'ready'}
            if route.get('phase') in retry_phase:
                route.update(status='running', phase=retry_phase[route['phase']],
                             message='Маршрут сохранён. Ожидание отпускания аварийной кнопки')

    def read_sample(self, name):
        try:
            data = self.robot.read(name)
            if name == 'base':
                battery = number(data.get('battery'))
                valid = battery is not None and 0 <= battery <= 100 and number(data.get('chargeFlag')) is not None
                valid = valid and number(data.get('emergencyButton')) in (0, 1)
            elif name == 'speed':
                valid = number(data.get('vx')) is not None
            else:
                distance = number(data.get('dist'))
                valid = isinstance(data.get('goal'), str) and distance is not None and distance >= 0
            if not valid:
                raise ValueError('Неверные поля телеметрии робота')
            return {'data': data, 'updated_at': self.clock(), 'error': None}
        except Exception as error:
            with self.lock:
                return dict(self.state['robot'][name], error=str(error))

    def poll(self):
        futures = {name: self.read_pool.submit(self.read_sample, name) for name in ROBOT_PATHS}
        samples = {name: future.result() for name, future in futures.items()}
        with self.lock:
            self.state['robot'].update(samples)
            self.observe_emergency()
            self.expire_navigation_notice()
            self.refresh_timing()
            self.stationary_tick()
            self.store.save()
        self.wake_event.set()

    def reset_stationary(self):
        self.state['stationary'] = {'point': None, 'since': None, 'last_sample': None}

    def stationary_tick(self):
        nav = self.state['robot']['nav']['data']
        distance = number(nav.get('dist'))
        navigation = self.state['navigation']
        eligible = (self.ready() and not self.route_locked() and self.state['route']['status'] != 'returning' and
                    navigation['status'] not in ('ready', 'sending') and not self.at_charger() and
                    self.physically_stopped() and bool(nav.get('goal')) and distance is not None and 0 <= distance <= 1)
        if not eligible:
            self.reset_stationary()
            return
        stationary = self.state['stationary']
        if (stationary['point'] != nav['goal'] or stationary['last_sample'] is None or
                self.clock() - stationary['last_sample'] > FRESH_SECONDS):
            stationary.update(point=nav['goal'], since=self.clock())
        stationary['last_sample'] = self.clock()
        if self.clock() - stationary['since'] >= self.timing['idle_return_seconds']:
            self.new_navigation(CHARGER, automatic=True)

    def refresh_timing(self):
        if not self.watch_timing:
            return
        signature = TIMING_FILE.stat().st_mtime_ns
        if signature == self.timing_signature:
            return
        self.timing_signature = signature
        try:
            self.timing = load_timing(TIMING_FILE)
        except (OSError, ValueError):
            logging.exception('Не удалось обновить времена ожидания; сохранены прежние значения')

    def record_lift(self, direction, error=None):
        if error:
            self.state['lift'].update(status='error', error=str(error))
        else:
            self.state['lift'].update(status='sent', last_command=direction, error=None)

    def route_tick(self):
        command = None
        with self.lock:
            self.observe_emergency()
            route = self.state['route']
            if route['status'] not in ACTIVE:
                return
            if not self.ready():
                if self.emergency_active():
                    route['emergency_interrupted'] = True
                message = 'Маршрут ожидает связи или отпускания аварийной кнопки'
                route.update(near_count=0, message=message)
                self.store.save()
                return
            point = route['points'][route['index']]
            nav = self.state['robot']['nav']['data']
            interrupted = route.pop('emergency_interrupted', False)
            if interrupted and route['phase'] in ('waiting', 'sending') and nav.get('goal') != point:
                # The robot may clear its native goal on emergency stop. Keep
                # the same route/index and restore only that target on release.
                route.update(phase='ready', near_count=0, next_at=0)
            if route['phase'] == 'sending':
                if route.get('raise_on_departure'):
                    route.update(status='error', message='Проверьте результат подъёма лифта перед продолжением')
                    self.store.save()
                    return
                if nav.get('goal') != point:
                    route.update(status='error', message='Результат отправки команды неизвестен. Проверьте цель робота')
                    self.store.save()
                    return
                route['phase'] = 'waiting'
            if route['phase'] == 'dwell':
                route['message'] = f'Остановка на точке: {point}'
                if self.clock() < route['dwell_until']:
                    return
                route.update(index=route['index'] + 1, phase='ready', raise_on_departure=True,
                             next_at=0, near_count=0)
                point = route['points'][route['index']]
            if route['phase'] == 'pause':  # Migration of pre-dwell stored routes.
                route['phase'] = 'ready'
            if route['phase'] == 'preparing':
                route.update(phase='raising', message='Подъём лифта перед началом маршрута')
                self.state['lift'].update(status='sending', direction='up', error=None)
                command = ('start_lift', point, False)
            elif route['phase'] == 'ready':
                route.update(phase='sending', message=f'Отправка к точке: {point}')
                if route.get('raise_on_departure'):
                    self.state['lift'].update(status='sending', direction='up', error=None)
                command = ('navigate', point, route.get('raise_on_departure', False))
            elif route['phase'] == 'lower_retry':
                route['phase'] = 'lowering'
                self.state['lift'].update(status='sending', direction='down', error=None)
                command = ('lower', point, False)
            elif route['phase'] == 'waiting':
                if self.clock() < route['next_at']:
                    return
                distance = number(nav.get('dist'))
                near = nav.get('goal') == point and distance is not None and 0 <= distance <= 1 and self.physically_stopped()
                if point == CHARGER and route['index'] == len(route['points']) - 1:
                    # Emergency stop can reset nav distance to zero. Only the
                    # physical charging flag confirms the final destination.
                    near = near and number(self.state['robot']['base']['data'].get('chargeFlag')) == 2
                route['near_count'] = route['near_count'] + 1 if near else 0
                route['next_at'] = self.clock() + 2
                route['message'] = ('Возврат на зарядку' if route['status'] == 'returning' else
                                    f"Маршрут выполняется: {point} ({route['index'] + 1}/{len(route['points'])})")
                if route['near_count'] >= 3:
                    if point == CHARGER and route['index'] == len(route['points']) - 1:
                        cancelled = route['status'] == 'returning'
                        route.update(status='cancelled' if cancelled else 'completed', phase='done',
                                     message='Маршрут отменён. Робот на зарядке' if cancelled else 'Маршрут завершён')
                    else:
                        route['phase'] = 'lowering'
                        self.state['lift'].update(status='sending', direction='down', error=None)
                        command = ('lower', point, False)
            elif route['phase'] in ('lowering', 'raising'):
                route.update(status='error', message='Результат команды лифта неизвестен')
            route_id = route['id']
            self.store.save()  # Persist each intent before external I/O.
        if command is None:
            return
        kind, point, raise_lift = command
        if kind in ('lower', 'start_lift'):
            direction = 'up' if kind == 'start_lift' else 'down'
            try:
                self.robot.lift(direction)
                error = None
            except Exception as caught:
                error = caught
            with self.lock:
                self.record_lift(direction, error)
                continue_start = False
                if self.state['route'].get('id') == route_id:
                    if error:
                        if self.emergency_active() or self.state['route'].get('emergency_interrupted'):
                            self.state['route'].update(phase='preparing' if kind == 'start_lift' else 'lower_retry',
                                                      emergency_interrupted=True,
                                                      message='Маршрут ожидает отпускания аварийной кнопки')
                        else:
                            self.state['route'].update(status='error', message='Ошибка управления лифтом. Маршрут остановлен')
                    elif kind == 'start_lift':
                        self.state['route']['phase'] = 'ready'
                        continue_start = True
                    else:
                        self.state['route'].update(phase='dwell', dwell_until=self.clock() + self.timing['route_wait_seconds'],
                                                   message=f'Остановка на точке: {point}')
                self.store.save()
            if continue_start:
                self.route_tick()  # First movement starts only after lift-up acknowledgement.
            return
        # At departure, send navigation and lift-up concurrently; the command
        # worker awaits both before it can dispatch a cancellation/another target.
        navigation_future = self.command_pool.submit(self.robot.navigate, point)
        lift_future = self.command_pool.submit(self.robot.lift, 'up') if raise_lift else None
        errors = {}
        for name, future in (('navigation', navigation_future), ('lift', lift_future)):
            if future:
                try:
                    future.result()
                except Exception as error:
                    errors[name] = error
        with self.lock:
            if raise_lift:
                self.record_lift('up', errors.get('lift'))
            current = self.state['route']
            if current.get('id') == route_id:
                if 'lift' in errors:
                    if self.emergency_active() or current.get('emergency_interrupted'):
                        current.update(phase='ready', emergency_interrupted=True,
                                       message='Маршрут ожидает отпускания аварийной кнопки')
                    else:
                        current.update(status='error', message='Не удалось поднять лифт. Маршрут остановлен')
                elif 'navigation' in errors:
                    current['raise_on_departure'] = False  # Lift succeeded, only goal needs reconciliation.
                    logging.error('Navigation result unknown: %s', errors['navigation'])
                else:
                    current.update(phase='waiting', next_at=self.clock(), near_count=0, raise_on_departure=False)
            self.store.save()

    def navigation_tick(self):
        with self.lock:
            if self.route_locked() or self.state['route']['status'] == 'returning' or not self.ready():
                return
            navigation = self.state['navigation']
            if navigation['status'] in ('sending', 'waiting'):
                nav = self.state['robot']['nav']['data']
                if navigation['status'] == 'sending':
                    navigation['status'] = 'waiting' if nav.get('goal') == navigation['point'] else 'error'
                    navigation['message'] = '' if navigation['status'] == 'waiting' else 'Результат обычного вызова неизвестен'
                distance = number(nav.get('dist'))
                if nav.get('goal') == navigation['point'] and distance is not None and distance <= 1 and self.physically_stopped():
                    navigation.update(status='completed', message='', notice_until=0)
                self.store.save()
                return
            if navigation['status'] != 'ready':
                return
            point, navigation_id = navigation['point'], navigation['id']
            navigation['status'] = 'sending'
            self.store.save()
        try:
            self.robot.navigate(point)
            success = True
        except Exception:
            success = False
        with self.lock:
            if self.state['navigation'].get('id') == navigation_id:
                self.state['navigation']['status'] = 'waiting' if success else 'sending'
            self.store.save()

    def lift_tick(self):
        with self.lock:
            lift = self.state['lift']
            if self.route_locked():
                return
            if lift['status'] != 'queued' or not self.ready():
                return
            direction = lift['direction']
            lift['status'] = 'sending'
            self.store.save()
        try:
            self.robot.lift(direction)
            error = None
        except Exception as caught:
            error = caught
        with self.lock:
            self.record_lift(direction, error)
            self.store.save()

    def poll_loop(self):
        while not self.stop_event.is_set():
            try:
                self.poll()
            except Exception:
                logging.exception('Telemetry polling failed')
            self.stop_event.wait(POLL_INTERVAL)

    def run(self):
        while not self.stop_event.is_set():
            self.wake_event.clear()
            try:
                self.lift_tick()
                self.route_tick()
                self.navigation_tick()
            except Exception:
                logging.exception('Controller iteration failed')
            self.wake_event.wait(0.1)

    def start(self):
        self.poll_thread = threading.Thread(target=self.poll_loop, name='robot-telemetry', daemon=True)
        self.thread = threading.Thread(target=self.run, name='robot-controller', daemon=True)
        self.poll_thread.start()
        self.thread.start()

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.stop_event.set()
        self.wake_event.set()
        for thread in (self.thread, self.poll_thread):
            if thread:
                thread.join(timeout=15)
        self.read_pool.shutdown(wait=True)
        self.command_pool.shutdown(wait=True)


def handler_for(controller):
    class Handler(BaseHTTPRequestHandler):
        def json_response(self, status, body):
            data = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = unquote(urlsplit(self.path).path)
            if path == "/api/state":
                return self.json_response(200, controller.snapshot())
            if path == '/api/health':
                return self.json_response(200, {'status': 'ok'})
            if path.startswith('/api/telemetry/'):
                name = path.rsplit('/', 1)[-1]
                if name not in ROBOT_PATHS:
                    return self.json_response(404, {'error': 'Не найдено'})
                with controller.lock:
                    sample = copy.deepcopy(controller.state['robot'][name])
                    fresh = controller.fresh(name)
                if not fresh:
                    return self.json_response(503, {'error': 'Нет свежих данных робота'})
                return self.json_response(200, sample['data'])
            allowed = {'/': WEB_ROOT / 'index.html', '/index.html': WEB_ROOT / 'index.html',
                       '/main.js': WEB_ROOT / 'main.js', '/style.css': WEB_ROOT / 'style.css'}
            file = allowed.get(path)
            if path.startswith('/assets/'):
                candidate = (ASSET_ROOT / path.removeprefix('/assets/')).resolve()
                if candidate.is_relative_to(ASSET_ROOT.resolve()) and candidate.suffix.lower() in (".png", ".gif", ".svg", ".jpg", ".jpeg", ".webp"):
                    file = candidate
            if file is None or not file.is_file():
                return self.json_response(404, {"error": "Не найдено"})
            types = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
                     ".png": "image/png", ".gif": "image/gif", ".svg": "image/svg+xml", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
            data = file.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", types[file.suffix.lower()])
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            try:
                origin = self.headers.get("Origin")
                if origin is not None and origin != f"http://{self.headers.get('Host')}":
                    raise APIError("Команды разрешены только со страницы пульта", 403)
                if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                    raise APIError("Требуется application/json", 415)
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    raise APIError("Некорректная длина запроса")
                if not 0 < length <= 32768:
                    raise APIError("Недопустимый размер запроса", 413)
                try:
                    body = json.loads(self.rfile.read(length))
                except (ValueError, UnicodeError):
                    raise APIError("Некорректный JSON")
                if not isinstance(body, dict):
                    raise APIError("Требуется JSON-объект")
                result = controller.action(urlsplit(self.path).path, body)
                self.json_response(200, result)
            except APIError as error:
                self.json_response(error.status, {"error": str(error), "state": controller.snapshot(), **error.details})
            except Exception:
                logging.exception("API action failed")
                self.json_response(500, {"error": "Ошибка сервера"})

        def log_message(self, format, *args):
            if self.path not in ('/api/state', '/api/health') and not self.path.startswith('/api/telemetry/'):
                logging.info(format, *args)

    return Handler


@contextmanager
def single_instance(path):
    """Prevent two workers controlling one persisted route simultaneously."""
    with open(str(path) + ".lock", "a+b") as handle:
        handle.seek(0)
        handle.write(b"0")
        handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--robot-url", default=os.environ.get('ROBOT_URL', 'http://10.6.20.95'))
    parser.add_argument("--db", type=Path)
    parser.add_argument('--data-dir', type=Path, default=Path(os.environ.get('DATA_DIR', str(Path(__file__).parent / 'data'))))
    demo = os.environ.get('DEMO', 'false').strip().lower()
    if demo not in ('true', 'false', '1', '0'):
        parser.error('DEMO must be true, false, 1 or 0')
    parser.add_argument('--demo', action=argparse.BooleanOptionalAction, default=demo in ('true', '1'),
                        help='Simulated robot; no real robot requests (or DEMO=true)')
    return parser.parse_args(argv)


def handle_shutdown_signal(signum, frame):
    raise KeyboardInterrupt


def main():
    args = parse_args()
    signal.signal(signal.SIGTERM, handle_shutdown_signal)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    database = args.db or args.data_dir / ('demo.sqlite3' if args.demo else 'robot.sqlite3')
    database.parent.mkdir(parents=True, exist_ok=True)
    with single_instance(database):
        store = Store(database)
        robot = DemoRobot(store.state["robot"]["nav"]["data"]) if args.demo else Robot(args.robot_url)
        controller = Controller(store, robot)
        server = ThreadingHTTPServer((args.host, args.port), handler_for(controller))
        controller.start()
        logging.info("Panel: http://%s:%s/ (demo=%s)", args.host, args.port, args.demo)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            controller.close()
            server.server_close()


if __name__ == "__main__":
    main()
