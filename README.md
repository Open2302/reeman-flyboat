# Reeman Flyboat

Пульт управления роботом: HTML/CSS/JavaScript, Python backend и SQLite.
Маршрут выполняется на сервере и сохраняется при закрытии страницы.

## Запуск через Docker Compose

Нужен Docker Engine с Compose (в Windows — Docker Desktop с Linux-контейнерами).
Из корня проекта:

```powershell
Copy-Item .env.example .env
docker compose up -d --build
```

Открыть **http://127.0.0.1:8000/**. По умолчанию запускается деморежим без
подключения к настоящему роботу. Параметры — в [.env.example](.env.example):

| Параметр | Значение по умолчанию | Назначение |
|---|---|---|
| `DEMO` | `true` | `false` для настоящего робота |
| `ROBOT_URL` | `http://10.6.20.95` | Адрес API робота, доступный контейнеру |
| `PORT` | `8000` | Порт пульта на компьютере |
| `BIND_ADDRESS` | `127.0.0.1` | `0.0.0.0` для доступа из доверенной локальной сети |

Для настоящего робота изменить `DEMO=false` и проверить `ROBOT_URL` в `.env`,
затем выполнить `docker compose up -d`. Для доступа с другого устройства
указать `BIND_ADDRESS=0.0.0.0` и открыть `http://IP-СЕРВЕРА:8000/`.

```powershell
docker compose config --quiet   # Проверка конфигурации
docker compose logs -f panel    # Журнал сервера
docker compose ps              # Состояние контейнера и healthcheck
docker compose down            # Остановка с сохранением базы
```

SQLite хранится в именованном томе `robot-data`. Деморежим и настоящий робот
используют разные файлы: `demo.sqlite3` и `robot.sqlite3`. Обычная остановка,
пересоздание контейнера и пересборка образа сохраняют данные. Команда
`docker compose down -v` удаляет том вместе с базами.

Если уже есть локальная база `backend/data/robot.sqlite3`, сначала остановить
локальный Python-сервер. До первого запуска в режиме робота перенести базу
в том, например через работающий демоконтейнер:

```powershell
docker compose cp backend/data/robot.sqlite3 panel:/data/robot.sqlite3
docker compose exec --user root panel chown 10001:10001 /data/robot.sqlite3
```

Копировать базу следует после штатной остановки локального сервера, когда
нет активных записей и незавершённого WAL. Сам перенос пульта локальную базу
не изменяет и не удаляет.

## Структура

```text
code/
  index.html          — пульт и модальные окна
  main.js             — интерфейс и времена ожидания
  style.css           — стили и адаптивная вёрстка
  assets/             — используемые картинки и анимации
backend/
  server.py           — API, выполнение маршрутов и SQLite
  test_server.py      — проверки без настоящего робота
  README.md           — поведение маршрута и описание API
Dockerfile            — сборка с проверкой тестов
compose.yaml          — сервис, постоянный том и healthcheck
.env.example          — пример параметров запуска
web-api.md            — заметки по API робота
```

Backend раздаёт пульт и его ресурсы сам; отдельный веб-сервер и отдельная СУБД
не требуются. Контейнер работает от непривилегированного пользователя.

## Настройки и обновления

В начале [code/main.js](code/main.js) задаются `ROUTE_WAIT_SECONDS` и
`IDLE_RETURN_SECONDS` в секундах. Папка `code` подключена к контейнеру только
для чтения: после сохранения файла сервер подхватит новые значения без
пересборки. Для HTML/CSS/JS достаточно обновить страницу.

После изменения Python-кода выполнить `docker compose up -d --build`.
Тесты выполняются при сборке образа; их ошибка прерывает сборку.

## Запуск без Docker и тесты

Нужен Python 3.10+ без сторонних библиотек:

```powershell
python backend/server.py --demo
python backend/test_server.py
```

Для настоящего робота: `python backend/server.py --robot-url http://10.6.20.95`.
Подробнее: [backend/README.md](backend/README.md).
