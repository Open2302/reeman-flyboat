const ROBOT_URL = 'http://10.6.20.95';
const UPDATE_INTERVAL = 2000;

const dotOP1 = { "point": "ОП1" };
const dotOP2 = { "point": "ОП2" }




let OP1, OP2, OP3, OP4, speedDisplay;
let batteryDisplay;
let chargeDisplay;
let goalDisplay;
let emergencyDisplay;


document.addEventListener('DOMContentLoaded', () => {
    OP1 = document.getElementById("OP1")
    OP2 = document.getElementById("OP2")
    OP3 = document.getElementById("OP3")
    OP4 = document.getElementById("OP4")

    speedDisplay = document.getElementById('speed');
    batteryDisplay = document.getElementById('battery');
    chargeDisplay = document.getElementById('chargeFlag');
    goalDisplay = document.getElementById('goal');
    emergencyDisplay = document.getElementById('emergency');

    OP1.addEventListener('click', GoToOP1);
    OP2.addEventListener('click', GoToOP2);


    updateStatus();
    setInterval(updateStatus, UPDATE_INTERVAL);
    updateBatteryAndEmergency();
    setInterval(updateBatteryAndEmergency, UPDATE_INTERVAL);
    updateGoal();
    setInterval(updateGoal, UPDATE_INTERVAL);
});

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

        chargeDisplay.textContent = data.chargeFlag  == 2 ? "Да" : "Нет";

        emergencyDisplay.textContent = data.emergency == 0 ? "🔴" : "🟢";
}

async function updateGoal() {
    const responce = await fetch (`${ROBOT_URL}/reeman/nav_status`);
    const data = await responce.json();

    goalDisplay.textContent = data.goal;
}