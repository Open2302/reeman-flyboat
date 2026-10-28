const ROBOT_URL = 'http://10.6.20.95';
const UPDATE_INTERVAL = 500;

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
    openModal = document.getElementById('Route')
    
    pointsList.addEventListener('click', addList);
    routeList.addEventListener('click', handleRouteClick); 
    openModal.addEventListener('click', () => {
        modalWindow.classList.remove('hidden');
    });
    closeModal.addEventListener('click', () => {
        modalWindow.classList.add('hidden');
    });
    
    sendRouteBtn.addEventListener('click', sendRoute);
    clearRouteBtn.addEventListener('click', clearRoute);

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
    const response = await fetch(`${ROBOT_URL}/reeman/speed`);
    const data = await response.json();

    const speed = Number(data.vx);

    const speedDisplay = document.getElementById("speed");
    const dot = document.querySelector("#StatusMov .statusbar__dot");

    if (speedDisplay) {
        speedDisplay.textContent = currentMotionState ?
            "Стоит" :
            "Движется";
    }

    if (dot) {
        dot.style.background = currentMotionState ?
            "radial-gradient(circle at 35% 30%, #ff9999, #e60000 55%, #990000)" :
            "radial-gradient(circle at 35% 30%, #8cf08c, #17c517 55%, #0a9e0a)";

        dot.style.borderColor = currentMotionState ? "#8b0000" : "#0b8b0b";
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

    // Аварийка — используем существующую иконку
    const emergencyIcon = document.getElementById("emergencyIcon");

    if (emergencyIcon) {
        emergencyIcon.src = Number(data.emergencyButton) === 0 ?
            "../../reference/emergency_red.png" :
            "../../reference/emergency_gray.png";
    }
    
}

async function updateGoal() {
    const response = await fetch(`${ROBOT_URL}/reeman/nav_status`);
    const data = await response.json();
    const goal = data.goal;

    distanceDisplay.textContent = data.dist;

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
    routePanelFooter.classList.toggle('hidden', !hasPoints);
}

async function clearRoute() {
    routeList.innerHTML = '';
    updateRouteButtonsState();
}

async function sendRoute() {
    const points = [...routeList.querySelectorAll('.route-point-name')]
        .map(el => el.textContent.trim());

    if (points.length === 0) return;
    if (points[points.length - 1] !== 'Зарядка') points.push('Зарядка');

    for (let i = 0; i < points.length; i++) {
        await goToRoutePoint(points[i]);
        await waitForArrival(points[i]);

        if (i < points.length - 1) {
            await new Promise(resolve => setTimeout(resolve, 1000));   
        }
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