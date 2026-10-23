const ROBOT_URL = 'http://10.6.20.95';
const UPDATE_INTERVAL = 500;

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

    OP1.addEventListener('click', () => GoToPoint(PointOP1));
    OP2.addEventListener('click', () => GoToPoint(PointOP2));
    OP3.addEventListener('click', () => GoToPoint(PointOP3));
    OP4.addEventListener('click', () => GoToPoint(PointOP4));
    OP5.addEventListener('click', () => GoToPoint(PointOP5));

    VP1.addEventListener('click', () => GoToPoint(PointVP1));
    VP2.addEventListener('click', () => GoToPoint(PointVP2));
    VP3.addEventListener('click', () => GoToPoint(PointVP3));
    VP4.addEventListener('click', () => GoToPoint(PointVP4));
    VP5.addEventListener('click', () => GoToPoint(PointVP5));

    VP21_31.addEventListener('click', () => GoToPoint(PointVP21_31));
    Charger.addEventListener('click', () => GoToPoint(PointCharger));
    AS.addEventListener('click', () => GoToPoint(PointAS));


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

async function GoToPoint(point) {
    fetch(`${ROBOT_URL}/cmd/nav_name`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(point)
    });
}