"""Persistent robot controller. Python 3.10+, standard library only."""

import argparse
import copy
import json
import logging
import math
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
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


class APIError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


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
        "motion": {"stopped": None, "candidate": None, "count": 0},
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
                raw = response.read(1024 * 1024)
            if body is not None:
                return None
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError("Expected a JSON object")
            return result
        except (OSError, URLError, HTTPError, ValueError) as error:
            raise APIError("Нет связи с роботом или неверный ответ API", 502) from error

    def read(self, name):
        paths = {"base": "/reeman/base_encode", "speed": "/reeman/speed", "nav": "/reeman/nav_status"}
        return self.request(paths[name])

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
    def __init__(self, store, robot, clock=time.time):
        self.store, self.robot, self.clock = store, robot, clock
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread = None
        # Old telemetry is a cache, not evidence that the robot is online now.
        for sample in store.state["robot"].values():
            sample["error"] = "Ожидание связи после запуска сервера"
        if store.state["lift"]["status"] == "sending":
            store.state["lift"]["status"] = "error"
            store.state["lift"]["error"] = "Результат команды лифта после перезапуска неизвестен"
        store.save()

    @property
    def state(self):
        return self.store.state

    def fresh(self, name):
        sample = self.state["robot"][name]
        return not sample["error"] and self.clock() - sample["updated_at"] < FRESH_SECONDS

    def snapshot(self):
        with self.lock:
            result = copy.deepcopy(self.state)
            result["server_time"] = self.clock()
            result["online"] = all(self.fresh(name) for name in ("base", "speed", "nav"))
            result["demo"] = isinstance(self.robot, DemoRobot)
            return result

    def action(self, path, body):
        with self.lock:
            route = self.state["route"]
            if path == "/api/draft":
                if body.get("version") != self.state["draft"]["version"]:
                    raise APIError("Маршрут изменён в другом окне. Список обновлён, повторите действие.", 409)
                self.state["draft"] = {"points": point_list(body.get("points")),
                                       "version": self.state["draft"]["version"] + 1}
            elif path == "/api/route/start":
                self.ensure_idle()
                if body.get("version") != self.state["draft"]["version"]:
                    raise APIError("Маршрут изменён в другом окне. Проверьте список точек.", 409)
                points = list(self.state["draft"]["points"])
                if not points:
                    raise APIError("Добавьте точки маршрута")
                if points[-1] != CHARGER:
                    points.append(CHARGER)
                self.new_route(points, "route", "running")
            elif path == "/api/route/cancel":
                if route["status"] == "returning":
                    return self.snapshot()
                if route["status"] not in ("running", "error"):
                    raise APIError("Нет маршрута для отмены", 409)
                self.new_route([CHARGER], "route", "returning")
            elif path == "/api/navigate":
                self.ensure_idle()
                self.new_route([point_name(body.get("point"))], "manual", "running")
            elif path == "/api/lift":
                if body.get("direction") not in ("up", "down"):
                    raise APIError("Направление лифта: up или down")
                if self.state["lift"]["status"] in ("queued", "sending"):
                    raise APIError("Команда лифта уже выполняется", 409)
                self.state["lift"].update(direction=body["direction"], status="queued", error=None)
            else:
                raise APIError("Неизвестная команда", 404)
            self.store.save()
            return self.snapshot()

    def ensure_idle(self):
        if self.state["route"]["status"] in ACTIVE:
            raise APIError("Сначала отмените выполняемый маршрут или дождитесь прибытия", 409)

    def new_route(self, points, kind, status):
        self.state["route"] = {
            "id": uuid.uuid4().hex, "kind": kind, "status": status, "points": points,
            "index": 0, "phase": "ready", "near_count": 0, "was_far": False,
            "next_at": 0, "started_at": self.clock(),
            "message": "Отмена маршрута: возврат на зарядку" if status == "returning" else "Маршрут принят сервером",
        }

    def poll(self):
        for name in ("base", "speed", "nav"):
            try:
                data = self.robot.read(name)
                if name == "base":
                    battery = number(data.get("battery"))
                    valid = battery is not None and 0 <= battery <= 100 and number(data.get("chargeFlag")) is not None
                    valid = valid and number(data.get("emergencyButton")) in (0, 1)
                elif name == "speed":
                    valid = number(data.get("vx")) is not None
                else:
                    distance = number(data.get("dist"))
                    valid = isinstance(data.get("goal"), str) and distance is not None and distance >= 0
                if not valid:
                    raise ValueError("Неверные поля телеметрии робота")
                sample = {"data": data, "updated_at": self.clock(), "error": None}
            except Exception as error:
                with self.lock:
                    sample = dict(self.state["robot"][name], error=str(error))
            with self.lock:
                self.state["robot"][name] = sample
        with self.lock:
            motion = self.state["motion"]
            speed = number(self.state["robot"]["speed"]["data"].get("vx"))
            distance = number(self.state["robot"]["nav"]["data"].get("dist"))
            if self.fresh("speed") and speed is not None:
                stopped = abs(speed) <= 0.001 and not (self.fresh("nav") and distance is not None and distance >= 1)
                motion["count"] = min(3, motion["count"] + 1) if motion["candidate"] == stopped else 1
                motion["candidate"] = stopped
                if motion["count"] >= 3:
                    motion["stopped"] = stopped
            else:
                motion.update(candidate=None, count=0, stopped=None)
            self.store.save()

    def route_tick(self):
        with self.lock:
            route = self.state["route"]
            if route["status"] not in ACTIVE:
                return
            if not all(self.fresh(name) for name in ("base", "speed", "nav")):
                route.update(near_count=0, message="Нет связи с роботом. Маршрут ожидает восстановления связи")
                self.store.save()
                return
            if number(self.state["robot"]["base"]["data"].get("emergencyButton")) == 0:
                route.update(near_count=0, message="Аварийная кнопка нажата. Маршрут ожидает")
                self.store.save()
                return
            point = route["points"][route["index"]]
            nav = self.state["robot"]["nav"]["data"]
            if route["phase"] == "sending":
                # A crash/timeout may happen after the robot accepted a command.
                # Reconcile with telemetry; never blindly repeat that command.
                if nav.get("goal") != point:
                    route.update(status="error", message="Результат отправки команды неизвестен. Проверьте цель робота; маршрут остановлен")
                    self.store.save()
                    return
                route["phase"] = "waiting"
            if route["phase"] == "pause":
                if self.clock() < route["next_at"]:
                    return
                route["phase"] = "ready"
            if route["phase"] == "ready":
                route.update(phase="sending", message=f"Отправка к точке: {point}")
                route_id = route["id"]
                self.store.save()  # Durable intent BEFORE the external command.
            else:
                if self.clock() < route["next_at"]:
                    return
                distance = number(nav.get("dist"))
                same_goal = nav.get("goal") == point
                speed = number(self.state["robot"]["speed"]["data"].get("vx"))
                route["was_far"] |= same_goal and distance is not None and distance > 0.2
                near = same_goal and distance is not None and 0 <= distance <= 1
                near = near and (route["was_far"] or (speed is not None and abs(speed) <= 0.001))
                route["near_count"] = route["near_count"] + 1 if near else 0
                route["next_at"] = self.clock() + 2
                label = "Возврат на зарядку" if route["status"] == "returning" else f"Маршрут выполняется: {point} ({route['index'] + 1}/{len(route['points'])})"
                route["message"] = label
                if route["near_count"] >= 3:
                    route["index"] += 1
                    if route["index"] == len(route["points"]):
                        cancelled = route["status"] == "returning"
                        route.update(status="cancelled" if cancelled else "completed", phase="done",
                                     message="Маршрут отменён. Робот на зарядке" if cancelled else "Маршрут завершён")
                    else:
                        route.update(phase="pause", next_at=self.clock() + 1, near_count=0, was_far=False)
                self.store.save()
                return
        # Only the worker sends navigation commands. Cancellation replaces the
        # route immediately, but its charger command is dispatched after this I/O.
        try:
            self.robot.navigate(point)
        except Exception:
            # Keep phase=sending: on the next fresh sample reconcile the goal.
            logging.exception("Navigation result unknown")
            return
        with self.lock:
            current = self.state["route"]
            if current.get("id") == route_id:
                current.update(phase="waiting", next_at=self.clock(), near_count=0)
                self.store.save()

    def lift_tick(self):
        with self.lock:
            lift = self.state["lift"]
            if lift["status"] != "queued" or not self.fresh("base"):
                return
            if number(self.state["robot"]["base"]["data"].get("emergencyButton")) == 0:
                return
            direction = lift["direction"]
            lift["status"] = "sending"
            self.store.save()
        try:
            self.robot.lift(direction)
            result = {"status": "sent", "last_command": direction, "error": None}
        except Exception as error:
            result = {"status": "error", "error": str(error)}
        with self.lock:
            self.state["lift"].update(result)
            self.store.save()

    def run(self):
        while not self.stop_event.is_set():
            try:
                self.poll()
                if self.stop_event.is_set():
                    break
                self.route_tick()
                self.lift_tick()
            except Exception:
                logging.exception("Controller iteration failed")
            self.stop_event.wait(POLL_INTERVAL)

    def start(self):
        self.thread = threading.Thread(target=self.run, name="robot-controller", daemon=True)
        self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=15)


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
            allowed = {"/": ROOT / "code/TestHtml/index.html",
                       "/code/TestHtml/index.html": ROOT / "code/TestHtml/index.html",
                       "/main.js": ROOT / "code/TestHtml/main.js",
                       "/style.css": ROOT / "code/TestHtml/style.css",
                       "/code/TestHtml/main.js": ROOT / "code/TestHtml/main.js",
                       "/code/TestHtml/style.css": ROOT / "code/TestHtml/style.css"}
            file = allowed.get(path)
            if path.startswith("/reference/"):
                candidate = (ROOT / path.lstrip("/")).resolve()
                if candidate.is_relative_to((ROOT / "reference").resolve()) and candidate.suffix.lower() in (".png", ".gif", ".svg", ".jpg", ".jpeg", ".webp"):
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
                self.json_response(error.status, {"error": str(error), "state": controller.snapshot()})
            except Exception:
                logging.exception("API action failed")
                self.json_response(500, {"error": "Ошибка сервера"})

        def log_message(self, format, *args):
            if self.path != "/api/state":
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
        if __import__("os").name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--robot-url", default="http://10.6.20.95")
    parser.add_argument("--db", type=Path)
    parser.add_argument("--demo", action="store_true", help="Simulated robot; no real robot requests")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    database = args.db or Path(__file__).parent / "data" / ("demo.sqlite3" if args.demo else "robot.sqlite3")
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
