const ROBOT_URL = 'http://10.6.20.95';
const UPDATE_INTERVAL = 500;

const dotOP1 = { "point": "ОП1" };
const dotOP2 = { "point": "ОП2" }
const LiftXddd = document.getElementById("lift")




let OP1, OP2, OP3, OP4, speedDisplay, Lift, routePanelFooter, sendRouteBtn, clearRouteBtn;
let modalWindow, pointsList, routeList, closeModal, openModal;
let batteryDisplay;
let chargeDisplay;
let goalDisplay;
let distanceDisplay;
let emergencyDisplay;
let LiftStatus = false;
let routeRunning = false;
function setRouteMessage(message) {
    const display = document.getElementById('route-message');
    if (display) display.textContent = message;
}
function hideRouteModal() {
    modalWindow.classList.add('hidden');
    document.body.classList.remove('modal-open');
    openModal.focus();
}
document.addEventListener('DOMContentLoaded', () => {
    OP1 = document.getElementById("OP1")
    OP2 = document.getElementById("OP2")
    OP3 = document.getElementById("OP3")
    OP4 = document.getElementById("OP4")
    modalWindow = document.getElementById("modal")
    pointsList = document.getElementById('points-list');
    routeList = document.getElementById('points-list-route');
    routePanelFooter = document.getElementById('route-panel-footer');
    sendRouteBtn = document.getElementById('send-route-btn');
    clearRouteBtn = document.getElementById('clear-route-btn');
    closeModal = document.querySelector('.close-btn');

    openModal = document.getElementById('Route')
    pointsList.addEventListener('click', addList);
    routeList.addEventListener('click', handleRouteClick); 
    openModal.addEventListener('click', () => {
        modalWindow.classList.remove('hidden');
        document.body.classList.add('modal-open');
        closeModal.focus();
    });
    closeModal.addEventListener('click', hideRouteModal);
    modalWindow.addEventListener('click', (event) => {
        if (event.target === modalWindow) hideRouteModal();
    });
    document.addEventListener('keydown', (event) => {
        if (modalWindow.classList.contains('hidden')) return;
        if (event.key === 'Escape') hideRouteModal();
        if (event.key === 'Tab') {
            const buttons = [...modalWindow.querySelectorAll('button:not(:disabled)')]
                .filter(button => button.getClientRects().length);
            const first = buttons[0], last = buttons[buttons.length - 1];
            if (event.shiftKey && document.activeElement === first) {
                event.preventDefault(); last.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault(); first.focus();
            }
        }
    });
    const fullscreenButton = document.getElementById('fullscreen-btn');
    const enterFullscreen = () => {
        if (document.fullscreenEnabled && !document.fullscreenElement) {
            document.documentElement.requestFullscreen().catch(() => {});
        }
    };
    document.addEventListener('click', enterFullscreen, { once: true });
    fullscreenButton?.addEventListener('click', () => {
        if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
        else enterFullscreen();
    });
    document.addEventListener('fullscreenchange', () => {
        if (fullscreenButton) fullscreenButton.textContent = document.fullscreenElement
            ? 'Выйти из полного экрана' : 'На весь экран';
    });
    speedDisplay = document.getElementById('speed');
    Lift = document.getElementById("lift")
    distanceDisplay = document.getElementById('distance');
    batteryDisplay = document.getElementById('battery');
    chargeDisplay = document.getElementById('chargeFlag');
    goalDisplay = document.getElementById('goal');
    emergencyDisplay = document.getElementById('emergency');

    sendRouteBtn.addEventListener('click', sendRoute);
    clearRouteBtn.addEventListener('click', clearRoute);
    OP1?.addEventListener('click', GoToOP1);
    OP2?.addEventListener('click', GoToOP2);
    Lift?.addEventListener('click', LiftUD);

    updateRouteButtonsState();
    const poll = (update) => {
        update().catch(console.error);
        setInterval(() => update().catch(console.error), UPDATE_INTERVAL);
    };
    if (speedDisplay) poll(updateStatus);
    if (batteryDisplay && chargeDisplay && emergencyDisplay) poll(updateBatteryAndEmergency);
    if (goalDisplay && distanceDisplay) poll(updateGoal);
});

async function LiftUD() {
    if (LiftStatus == false) {
        fetch(`${ROBOT_URL}/cmd/hydraulic_up`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: "0"
        });
        LiftXddd.style.transform = 'rotate(-180deg)'
        LiftStatus = true;
    } else {
        fetch(`${ROBOT_URL}/cmd/hydraulic_down`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: "0"
        });
        LiftXddd.style.transform = 'rotate(360deg)'
        LiftStatus = false;
    }
}

async function GoToOP1() {
    fetch(`${ROBOT_URL}/cmd/nav_name`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(dotOP1)
    });
}

async function GoToOP2() {
    fetch(`${ROBOT_URL}/cmd/nav_name`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(dotOP2)
    });
}

async function updateStatus() {
    const response = await fetch(`${ROBOT_URL}/reeman/speed`);
    const data = await response.json();
    const speed = data.vx;

    let SpeedTest = speed == 0 ? "Стоянка" : "Движенение";

    speedDisplay.textContent = SpeedTest;
}

async function updateBatteryAndEmergency() {
    const response = await fetch(`${ROBOT_URL}/reeman/base_encode`);
    const data = await response.json();

    batteryDisplay.textContent = data.battery;
    updateBatteryImage(data.battery, data.chargeFlag);
}

function updateBatteryImage(percent, chargeFlag) {
    const batteryImage = document.getElementById("batteryAnimation");

    if (!batteryImage) return;

    let imagePath;
    const battery = Number(percent);

    if (Number(chargeFlag) === 2 && battery <= 100) {
        imagePath = "../reference/battery.gif";
    } else if (battery >= 70) {
        imagePath = "../reference/batteryFULL.png";
    } else if (battery >= 20) {
        imagePath = "../reference/batteryMEDIUM.png";
    } else {
        imagePath = "../reference/batteryLOW.png";
    }

    if (batteryImage.getAttribute("src") !== imagePath) {
        batteryImage.setAttribute("src", imagePath);
    }
}

async function updateGoal() {
    const responce = await fetch(`${ROBOT_URL}/reeman/nav_status`);
    const data = await responce.json();

    goalDisplay.textContent = data.goal;

    distanceDisplay.textContent = data.dist;
}

function addList(event) {
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

function handleRouteClick(event) {
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

function updateRouteButtonsState() {
    const hasPoints = routeList.children.length > 0;
    routePanelFooter.classList.toggle('hidden', !hasPoints);
    const empty = document.getElementById('route-empty');
    if (empty) empty.classList.toggle('hidden', hasPoints);
    const count = document.getElementById('route-count');
    if (count) count.textContent = routeList.children.length;
    sendRouteBtn.disabled = routeRunning;
}

function clearRoute() {
    routeList.innerHTML = '';
    updateRouteButtonsState();
}

async function sendRoute() {
    if (routeRunning) return;
    const points = [...routeList.querySelectorAll('.route-point-name')]
        .map(el => el.textContent.trim());

    if (points.length === 0) return;
    if (points[points.length - 1] !== 'Зарядка') points.push('Зарядка');
    routeRunning = true;
    updateRouteButtonsState();
    hideRouteModal();
    try {
    for (let i = 0; i < points.length; i++) {
        setRouteMessage(`Маршрут выполняется · ${i + 1}/${points.length} · ${points[i]}`);
        await goToRoutePoint(points[i]);
        await waitForArrival(points[i]);

        if (i < points.length - 1) {
            await new Promise(resolve => setTimeout(resolve, 1000));   
        }
    }
    setRouteMessage('Маршрут завершён');
    } catch (error) {
        setRouteMessage('Не удалось выполнить маршрут. Проверьте соединение с роботом.');
    } finally {
        routeRunning = false;
        updateRouteButtonsState();
    }
}

async function goToRoutePoint(point) {
    const response = await fetch(`${ROBOT_URL}/cmd/nav_name`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ point })
    });
}

async function waitForArrival(point) {
    let wasFar = false;
    let nearCount = 0;

    while (true) {
        const response = await fetch(`${ROBOT_URL}/reeman/nav_status`);
        if (!response.ok) throw new Error(`Ошибка статуса маршрута: ${response.status}`);
        const data = await response.json();

        if (data.goal === point && Number(data.dist) > 0.2) wasFar = true;
        if (wasFar && data.goal === point && Number(data.dist) <= 1) {
            nearCount++;
            if (nearCount >= 3) return;
        } else {
            nearCount = 0;
        }

        await new Promise(resolve => setTimeout(resolve, 2000));
    }
}
