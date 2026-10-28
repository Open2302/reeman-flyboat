const ROBOT_URL = 'http://10.6.20.95';
const UPDATE_INTERVAL = 500;
const SPEED_THRESHOLD = 0.001;
const MOTION_CONFIRMATIONS = 3;
let navigationDistance = null;
let navigationUpdatedAt = 0;
let confirmedStopped = null;
let candidateStopped = null;
let motionConfirmations = 0;
let motionUpdatePending = false;

function updateSelectedPoint(point) {
    const statusPoint = document.getElementById("StatusPoint");

    if (statusPoint) {
        statusPoint.textContent = `Точка: ${point}`;
    }
}

const PointDoor = { "point": "ворота" };
const PointOP5 = { "point": "ОП5" };
const PointOP4 = { "point": "ОП4" };
const PointOP3 = { "point": "ОП3" };
const PointOP2 = { "point": "ОП2" };
const PointOP1 = { "point": "ОП1" };
const PointCharger = { "point": "Зарядка" };
const PointVP5 = { "point": "ВП5" };
const PointAS = { "point": "АС" };
const PointVP4 = { "point": "ВП4_2" };
const PointVP3 = { "point": "ВП3" };
const PointVP2 = { "point": "ВП2" };
const PointVP1 = { "point": "ВП1" };
const PointVP21_31 = { "point": "ВП2.1,3.1" };
const PointStorage = { "point": "склад" };

let OP1, OP2, OP3, OP4, OP5;
let VP1, VP2, VP3, VP4, VP5;
let Storage, VP21_31, AS, Charger, Door;
let speedDisplay;
let LiftbatteryDisplay;
let batteryDisplay;
let chargeDisplay;
let goalDisplay;
let distanceDisplay;
let emergencyDisplay;
let LiftStatus = false;
let BTNLift;
let BTNRoute;
let modalWindow, pointsList, routeList, routePanelFooter;
let sendRouteBtn, clearRouteBtn, closeModal, openModal;
let routeRunning = false;
let routeCancelling = false;
let activeRoute = null;
let routeCommand = null;

document.addEventListener('DOMContentLoaded', () => {
    OP1 = document.getElementById("op1")
    OP2 = document.getElementById("op2")
    OP3 = document.getElementById("op3")
    OP4 = document.getElementById("op4")
    OP5 = document.getElementById("op5")

    VP1 = document.getElementById("vp1")
    VP2 = document.getElementById("vp2")
    VP3 = document.getElementById("vp3")
    VP4 = document.getElementById("vp4")
    VP5 = document.getElementById("vp5")

    AS = document.getElementById("as")
    VP21_31 = document.getElementById("vp2.1-3.1")
    BTNLift = document.getElementById("lift")
    BTNRoute = document.getElementById("route")
    Charger = document.getElementById("charger")

    speedDisplay = document.getElementById('speed');
    Lift = document.getElementById("lift")
    batteryDisplay = document.getElementById('battery');
    chargeDisplay = document.getElementById('chargeFlag');
    goalDisplay = document.getElementById('goal');
    emergencyDisplay = document.getElementById('emergency');

    OP1.addEventListener('click', () => {
        GoToPoint(PointOP1);
        updateSelectedPoint("ОП1");
    });

    OP2.addEventListener('click', () => {
        GoToPoint(PointOP2);
        updateSelectedPoint("ОП2");
    });

    OP3.addEventListener('click', () => {
        GoToPoint(PointOP3);
        updateSelectedPoint("ОП3");
    });

    OP4.addEventListener('click', () => {
        GoToPoint(PointOP4);
        updateSelectedPoint("ОП4");
    });

    OP5.addEventListener('click', () => {
        GoToPoint(PointOP5);
        updateSelectedPoint("ОП5");
    });

    VP1.addEventListener('click', () => {
        GoToPoint(PointVP1);
        updateSelectedPoint("ВП1");
    });

    VP2.addEventListener('click', () => {
        GoToPoint(PointVP2);
        updateSelectedPoint("ВП2");
    });

    VP3.addEventListener('click', () => {
        GoToPoint(PointVP3);
        updateSelectedPoint("ВП3");
    });

    VP4.addEventListener('click', () => {
        GoToPoint(PointVP4);
        updateSelectedPoint("ВП4");
    });

    VP5.addEventListener('click', () => {
        GoToPoint(PointVP5);
        updateSelectedPoint("ВП5");
    });

    VP21_31.addEventListener('click', () => {
        GoToPoint(PointVP21_31);
        updateSelectedPoint("ВП2.1-3.1");
    });

    Charger.addEventListener('click', () => {
        GoToPoint(PointCharger);
        updateSelectedPoint("Зарядка");
    });

    AS.addEventListener('click', () => {
        GoToPoint(PointAS);
        updateSelectedPoint("АС");
    });

    // Modal Window
    modalWindow = document.getElementById("modal")
    pointsList = document.getElementById('points-list');
    routeList = document.getElementById('points-list-route');
    routePanelFooter = document.getElementById('route-panel-footer');
    sendRouteBtn = document.getElementById('send-route-btn');
    clearRouteBtn = document.getElementById('clear-route-btn');
    closeModal = document.querySelector('.close-btn');
    openModal = BTNRoute;
    
    pointsList?.addEventListener('click', addList);
    routeList?.addEventListener('click', handleRouteClick); 
    openModal?.addEventListener('click', () => {
        modalWindow?.classList.remove('hidden');
        document.body.classList.add('modal-open');
        closeModal?.focus();
    });
    closeModal?.addEventListener('click', () => {
        modalWindow?.classList.add('hidden');
        document.body.classList.remove('modal-open');
        BTNRoute.focus();
    });
    modalWindow.addEventListener('click', event => {
        if (event.target === modalWindow) closeModal.click();
    });
    modalWindow.addEventListener('keydown', event => {
        if (event.key === 'Escape') closeModal.click();
        if (event.key === 'Tab') {
            const buttons = [...modalWindow.querySelectorAll('button:not(:disabled)')]
                .filter(button => button.getClientRects().length);
            const first = buttons[0];
            const last = buttons[buttons.length - 1];
            if (event.shiftKey && document.activeElement === first) {
                event.preventDefault();
                last.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first.focus();
            }
        }
    });
    
    sendRouteBtn?.addEventListener('click', sendRoute);
    clearRouteBtn?.addEventListener('click', clearRoute);
    document.getElementById('cancel-route-btn').addEventListener('click', cancelRoute);
    updateRouteButtonsState();

    Lift.addEventListener('click', LiftUD);
    updateStatus();
    setInterval(updateStatus, UPDATE_INTERVAL);
    updateBatteryAndEmergency();
    setInterval(updateBatteryAndEmergency, UPDATE_INTERVAL);
    updateGoal();
    setInterval(updateGoal, UPDATE_INTERVAL);
});

async function LiftUD() {
    if (LiftStatus == false) {
        fetch(`${ROBOT_URL}/cmd/hydraulic_up`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: "0"
        });
        Lift.textContent = "Опустить лифт";
        LiftStatus = true;
    } else {
        fetch(`${ROBOT_URL}/cmd/hydraulic_down`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: "0"
        });
        Lift.textContent = "Поднять лифт";
        LiftStatus = false;
    }
}

async function updateStatus() {
    if (motionUpdatePending) return;
    motionUpdatePending = true;
    try {
    const response = await fetch(`${ROBOT_URL}/reeman/speed`);
    if (!response.ok) throw new Error(`Speed HTTP ${response.status}`);
    const data = await response.json();

    const speed = Number(data.vx);
    if (data.vx === null || data.vx === undefined || !Number.isFinite(speed)) return;

    // Далеко от цели сохраняем движение даже при кратком падении скорости.
    const hasDistance = navigationDistance !== null &&
        Date.now() - navigationUpdatedAt < UPDATE_INTERVAL * 6;
    const isStopped = !(hasDistance && navigationDistance >= 1) &&
        Math.abs(speed) <= SPEED_THRESHOLD;

    if (candidateStopped === isStopped) {
        motionConfirmations++;
    } else {
        candidateStopped = isStopped;
        motionConfirmations = 1;
    }
    if (motionConfirmations >= MOTION_CONFIRMATIONS) {
        confirmedStopped = isStopped;
    }
    if (confirmedStopped === null) return;

    const speedDisplay = document.getElementById("speed");
    const dot = document.querySelector("#StatusMov .statusbar__dot");

    if (speedDisplay) {
        speedDisplay.textContent = confirmedStopped ?
            "Стоит" :
            "Движется";
    }

    if (dot) {
        dot.style.background = confirmedStopped ?
            "radial-gradient(circle at 35% 30%, #ff9999, #e60000 55%, #990000)" :
            "radial-gradient(circle at 35% 30%, #8cf08c, #17c517 55%, #0a9e0a)";

        dot.style.borderColor = confirmedStopped ? "#8b0000" : "#0b8b0b";
    }
    } catch (error) {
        candidateStopped = null;
        motionConfirmations = 0;
        console.error("Ошибка получения скорости робота:", error);
    } finally {
        motionUpdatePending = false;
    }
}

async function updateBatteryAndEmergency() {
    const response = await fetch(`${ROBOT_URL}/reeman/base_encode`);
    const data = await response.json();

    const batteryIcon = document.getElementById("StatusBattery");
    const battery = Number(data.battery);
    const isCharging = Number(data.chargeFlag) === 2;

    if (batteryIcon) {
        let imagePath;

        if (isCharging) {
            imagePath = "../../reference/battery.gif";
        } else if (battery >= 80) {
            imagePath = "../../reference/batteryFULL.png";
        } else if (battery >= 30) {
            imagePath = "../../reference/batteryMEDIUM.png";
        } else {
            imagePath = "../../reference/batteryLOW.png";
        }

        if (!batteryIcon.src.endsWith(imagePath.split("/").pop())) {
            batteryIcon.src = imagePath;
        }

        batteryIcon.title = `Заряд батареи: ${data.battery}%`;
    }

    // Аварийная кнопка: 0 — нажата, 1 — отпущена.
    const emergencyIcon = document.getElementById("emergencyIcon");

    if (emergencyIcon) {
        const emergencyState = String(data.emergencyButton);
        const isEmergency = emergencyState === "0";
        const label = isEmergency ? "Аварийная кнопка нажата" :
            emergencyState === "1" ? "Аварийная кнопка отпущена" :
            "Состояние аварийной кнопки неизвестно";

        emergencyIcon.style.color = isEmergency ? "#e60000" : "#8b8b8b";
        emergencyIcon.setAttribute("aria-label", label);
        emergencyIcon.querySelector("title").textContent = label;
    }
    
}

async function updateGoal() {
    const response = await fetch(`${ROBOT_URL}/reeman/nav_status`);
    const data = await response.json();
    const goal = data.goal;

    const distance = Number(data.dist);
    navigationDistance = data.dist !== null && data.dist !== undefined &&
        String(data.dist).trim() !== "" && Number.isFinite(distance) && distance >= 0 ? distance : null;
    navigationUpdatedAt = Date.now();
    if (distanceDisplay) distanceDisplay.textContent = data.dist;

    if (goal === undefined || goal === null || goal === "") {
        return;
    }

    const statusPoint = document.getElementById("StatusPoint");

    if (statusPoint) {
        const pointNames = {
            "ВП4_2": "ВП4",
            "ВП2.1,3.1": "ВП2.1-3.1",
            "ворота": "Ворота",
            "склад": "Склад"
        };

        const displayGoal = pointNames[String(goal)] || String(goal);
        statusPoint.textContent = `Точка: ${displayGoal}`;
    }
}

async function GoToPoint(point) {
    fetch(`${ROBOT_URL}/cmd/nav_name`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(point)
    });
}

async function addList(event) {
    if (!pointsList || !routeList) {
        return;
    }

    const clickedButton = event.target.closest('button');

    if (!clickedButton || !pointsList.contains(clickedButton)) {
        return;
    }

    const pointName = clickedButton.textContent.trim();
    const newLi = document.createElement('li');
    const nameSpan = document.createElement('span');
    nameSpan.className = 'route-point-name';
    nameSpan.textContent = pointName;
    const actionsDiv = document.createElement('div');
    actionsDiv.className = 'route-point-actions';
    const upBtn = document.createElement('button');
    upBtn.className = 'move-up-btn';
    upBtn.textContent = '↑';
    upBtn.title = 'Переместить вверх';
    const downBtn = document.createElement('button');
    downBtn.className = 'move-down-btn';
    downBtn.textContent = '↓';
    downBtn.title = 'Переместить вниз';
    const delBtn = document.createElement('button');
    delBtn.className = 'delete-btn';
    delBtn.textContent = '×';
    delBtn.title = 'Удалить из маршрута';
    actionsDiv.appendChild(upBtn);
    actionsDiv.appendChild(downBtn);
    actionsDiv.appendChild(delBtn);
    newLi.appendChild(nameSpan);
    newLi.appendChild(actionsDiv);
    routeList.appendChild(newLi);
    updateRouteButtonsState();
}

async function handleRouteClick(event) {
    const target = event.target;

    const deleteBtn = target.closest('.delete-btn');
    const upBtn     = target.closest('.move-up-btn');
    const downBtn   = target.closest('.move-down-btn');

    if (!deleteBtn && !upBtn && !downBtn) {
        return;
    }

    const li = target.closest('li');
    if (!li) {
        return;
    }

    if (deleteBtn) {
        li.remove();
        updateRouteButtonsState();
        return;
    }

    if (upBtn) {
        const prev = li.previousElementSibling;
        if (prev) {
        prev.before(li);
        }
        return;
    }

    if (downBtn) {
        const next = li.nextElementSibling;
        if (next) {
        next.after(li);
        }
        return;
    }
}

async function updateRouteButtonsState() {
    const hasPoints = routeList.children.length > 0;
    document.getElementById('route-empty').classList.toggle('hidden', hasPoints);
    document.getElementById('route-count').textContent = routeList.children.length;
    sendRouteBtn.disabled = !hasPoints || routeRunning || routeCancelling;
    const cancelButton = document.getElementById('cancel-route-btn');
    cancelButton.disabled = !routeRunning || routeCancelling;
    const mapIcon = document.getElementById('mapIcon');
    const mapImage = routeRunning ? 'mapActive.gif' : 'map.png';
    if (!mapIcon.src.endsWith(mapImage)) mapIcon.src = `../../reference/${mapImage}`;
    mapIcon.title = routeRunning ? 'Маршрут выполняется' : 'Нет активного маршрута';
}

async function clearRoute() {
    routeList.innerHTML = '';
    updateRouteButtonsState();
}

async function sendRoute() {
    if (routeRunning || routeCancelling) return;
    const points = [...routeList.querySelectorAll('.route-point-name')]
        .map(el => el.textContent.trim());

    if (points.length === 0) return;
    if (points[points.length - 1] !== 'Зарядка') points.push('Зарядка');

    const robotPointNames = { 'ВП4': PointVP4.point, 'ВП2.1-3.1': PointVP21_31.point };
    const controller = new AbortController();
    activeRoute = controller;
    routeRunning = true;
    updateRouteButtonsState();
    const message = document.getElementById('route-message');
    try {
        for (let i = 0; i < points.length; i++) {
            controller.signal.throwIfAborted();
            const point = robotPointNames[points[i]] || points[i];
            message.textContent = `Маршрут выполняется: ${points[i]} (${i + 1}/${points.length})`;
            // Уже отправленную команду дожидаемся перед командой возврата на зарядку.
            routeCommand = goToRoutePoint(point);
            await routeCommand;
            controller.signal.throwIfAborted();
            await waitForArrival(point, controller.signal);

            if (i < points.length - 1) {
                await routeDelay(1000, controller.signal);
            }
        }
        controller.signal.throwIfAborted();
        message.textContent = 'Маршрут завершён';
    } catch (error) {
        if (!controller.signal.aborted) {
            message.textContent = 'Ошибка выполнения маршрута. Проверьте связь с роботом.';
            console.error('Ошибка выполнения маршрута:', error);
        }
    } finally {
        if (activeRoute === controller) {
            activeRoute = null;
            routeRunning = false;
            routeCommand = null;
            updateRouteButtonsState();
        }
    }
}

async function cancelRoute() {
    if (!routeRunning || routeCancelling) return;
    const controller = activeRoute;
    activeRoute = null;
    routeRunning = false;
    routeCancelling = true;
    controller.abort();
    updateRouteButtonsState();
    const message = document.getElementById('route-message');
    message.textContent = 'Маршрут отменён. Отправка на зарядку…';
    try {
        // Не позволяем старой команде маршрута прийти после команды зарядки.
        if (routeCommand) await routeCommand.catch(() => {});
        await goToRoutePoint(PointCharger.point);
        message.textContent = 'Маршрут отменён';
    } catch (error) {
        message.textContent = 'Маршрут отменён, но отправить робота на зарядку не удалось. Проверьте связь.';
        console.error('Ошибка возврата на зарядку:', error);
    } finally {
        routeCommand = null;
        routeCancelling = false;
        updateRouteButtonsState();
    }
}

function routeDelay(milliseconds, signal) {
    signal.throwIfAborted();
    return new Promise((resolve, reject) => {
        const onAbort = () => {
            clearTimeout(timer);
            reject(signal.reason);
        };
        const timer = setTimeout(() => {
            signal.removeEventListener('abort', onAbort);
            resolve();
        }, milliseconds);
        signal.addEventListener('abort', onAbort, { once: true });
    });
}

async function goToRoutePoint(point) {
    const response = await fetch(`${ROBOT_URL}/cmd/nav_name`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ point })
    });
    if (!response.ok) throw new Error(`Navigation HTTP ${response.status}`);
}

async function waitForArrival(point, signal) {
    let wasFar = false;
    let nearCount = 0;

    while (true) {
        signal.throwIfAborted();
        const response = await fetch(`${ROBOT_URL}/reeman/nav_status`, { signal });
        if (!response.ok) throw new Error(`Navigation status HTTP ${response.status}`);
        const data = await response.json();

        if (data.goal === point && Number(data.dist) > 0.2) wasFar = true;
        if (wasFar && data.goal === point && Number(data.dist) <= 1) {
            nearCount++;
            if (nearCount >= 3) return;
        } else {
            nearCount = 0;
        }

        await routeDelay(2000, signal);
    }
}
