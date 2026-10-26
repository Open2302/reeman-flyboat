const ROBOT_URL = 'http://10.6.20.95';
const UPDATE_INTERVAL = 2000;

const dotOP1 = { "point": "ОП1" };
const dotOP2 = { "point": "ОП2" }
const LiftXddd = document.getElementById("lift")




let OP1, OP2, OP3, OP4, speedDisplay, Lift, routePanelFooter, sendRouteBtn, clearRouteBtn;
let batteryDisplay;
let chargeDisplay;
let goalDisplay;
let emergencyDisplay;
let LiftStatus = false;
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
    SpeedDisplay = document.getElementById('speed');
    openModal = document.getElementById('Route')
    pointsList.addEventListener('click', addList);
    routeList.addEventListener('click', handleRouteClick); 
    openModal.addEventListener('click', () => {
        modalWindow.classList.remove('hidden');
    });
    closeModal.addEventListener('click', () => {
        modalWindow.classList.add('hidden');
    });
    speedDisplay = document.getElementById('speed');
    Lift = document.getElementById("lift")
    batteryDisplay = document.getElementById('battery');
    chargeDisplay = document.getElementById('chargeFlag');
    goalDisplay = document.getElementById('goal');
    emergencyDisplay = document.getElementById('emergency');

    sendRouteBtn.addEventListener('click', sendRoute);
    clearRouteBtn.addEventListener('click', clearRoute);
    OP1.addEventListener('click', GoToOP1);
    OP2.addEventListener('click', GoToOP2);
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
//уголок арбуза показывает поднимиться лифт или опуститься


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

    chargeDisplay.textContent = data.chargeFlag == 2 ? "Да" : "Нет";

    emergencyDisplay.textContent = data.emergency == 0 ? "🔴" : "🟢";
}

async function updateGoal() {
    const responce = await fetch(`${ROBOT_URL}/reeman/nav_status`);
    const data = await responce.json();

    goalDisplay.textContent = data.goal;
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
}

function clearRoute() {
    routeList.innerHTML = '';
    updateRouteButtonsState();
}

async function sendRoute() {
    const nameEls = routeList.querySelectorAll('.route-point-name');
    const points = Array.from(nameEls).map(el => el.textContent.trim());

    if (points.length === 0) {
        return;
    }

    sendRouteBtn.disabled = true;
    clearRouteBtn.disabled = true;
}