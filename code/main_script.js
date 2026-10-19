const ROBOT_URL = 'http://10.6.20.95';
const UPDATE_INTERVAL = 2000;

const dotOP1 = { "point": "ОП1" };
const dotOP2 = { "point": "ОП2" }




let OP1, OP2, OP3, OP4, speedDisplay;

document.addEventListener('DOMContentLoaded', () => {
    OP1 = document.getElementById("OP1")
    OP2 = document.getElementById("OP2")
    OP3 = document.getElementById("OP3")
    OP4 = document.getElementById("OP4")
    speedDisplay = document.getElementById('speed');

    OP1.addEventListener('click', GoToOP1);
    OP2.addEventListener('click', GoToOP2);


    updateStatus();
    setInterval(updateStatus, UPDATE_INTERVAL);
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