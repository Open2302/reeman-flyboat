const ROBOT_URL = 'http://10.6.20.95';
const UPDATE_INTERVAL = 2000;

const dotOP1 = { "point": "ОП1" };
const dotOP2 = { "point": "ОП2" }
const LiftXddd = document.getElementById("lift")



let OP1, OP2, OP3, OP4, speedDisplay, Lift;
let LiftStatus = false;
document.addEventListener('DOMContentLoaded', () => {
    OP1 = document.getElementById("OP1")
    OP2 = document.getElementById("OP2")
    OP3 = document.getElementById("OP3")
    OP4 = document.getElementById("OP4")
    SpeedDisplay = document.getElementById('speed');
    Lift = document.getElementById("lift")

    OP1.addEventListener('click', GoToOP1);
    OP2.addEventListener('click', GoToOP2);
    Lift.addEventListener('click', LiftUD);


    updateStatus();
    setInterval(updateStatus, UPDATE_INTERVAL);
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

    SpeedDisplay.textContent = SpeedTest;
}