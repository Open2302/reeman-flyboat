const UPDATE_INTERVAL = 500;
const POINT_NAMES = { 'ВП4_2': 'ВП4', 'ВП2.1,3.1': 'ВП2.1-3.1', 'ворота': 'Ворота', 'склад': 'Склад' };
let serverState = null;
let backendConnected = false;
let actionPending = false;
let refreshPending = false;
let renderedDraftVersion = -1;
let clientMessage = '';
let clientMessageUntil = 0;

// The server serves both the panel and the API from the same origin.
if (location.protocol === 'file:') location.replace('http://127.0.0.1:8000/');

const byId = id => document.getElementById(id);
const displayPoint = point => POINT_NAMES[point] || point;

async function api(path, body) {
    const response = await fetch(path, {
        method: body === undefined ? 'GET' : 'POST',
        headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
        cache: 'no-store',
        signal: AbortSignal.timeout(10000)
    });
    const data = await response.json();
    if (!response.ok) {
        if (data.state) applyState(data.state);
        throw new Error(data.error || 'Ошибка сервера');
    }
    return data;
}

async function refreshState() {
    if (refreshPending) return;
    refreshPending = true;
    try {
        applyState(await api('/api/state'));
    } catch (error) {
        backendConnected = false;
        byId('connection-status').textContent = 'Нет связи с сервером. Показаны последние полученные данные';
        byId('connection-status').classList.remove('hidden');
        updateRouteButtonsState();
    } finally {
        refreshPending = false;
    }
}

async function performAction(path, body) {
    if (actionPending || !backendConnected) return;
    actionPending = true;
    clientMessage = '';
    updateRouteButtonsState();
    try {
        applyState(await api(path, body));
    } catch (error) {
        clientMessage = error.message;
        clientMessageUntil = Date.now() + 6000;
        byId('route-message').textContent = clientMessage;
        // A timed-out POST may already be committed: refresh before any retry.
        await refreshState();
    } finally {
        actionPending = false;
        updateRouteButtonsState();
    }
}

function applyState(state) {
    backendConnected = true;
    if (serverState && state.revision < serverState.revision) return;
    serverState = state;
    const connection = byId('connection-status');
    connection.textContent = !state.online ? 'Нет актуальных данных от робота. Ожидание связи' :
        state.demo ? 'Деморежим: подключён симулятор, команды настоящему роботу не отправляются' : '';
    connection.classList.toggle('hidden', state.online && !state.demo);

    if (state.draft.version !== renderedDraftVersion) {
        byId('points-list-route').replaceChildren(...state.draft.points.map(createRouteItem));
        renderedDraftVersion = state.draft.version;
    }
    const sampleFresh = name => {
        const sample = state.robot[name];
        return !sample.error && state.server_time - sample.updated_at < 5;
    };
    if (sampleFresh('base')) updateBatteryAndEmergency(state.robot.base.data);
    else {
        byId('StatusBattery').title = 'Заряд батареи: нет актуальных данных';
        const emergency = byId('emergencyIcon');
        emergency.style.color = '#8b8b8b';
        emergency.setAttribute('aria-label', 'Состояние аварийной кнопки неизвестно');
        emergency.querySelector('title').textContent = 'Состояние аварийной кнопки неизвестно';
    }
    updateStatus(state, sampleFresh('speed') && sampleFresh('nav'));
    if (sampleFresh('nav')) {
        const goal = state.robot.nav.data.goal;
        byId('StatusPoint').textContent = goal ? `Точка: ${displayPoint(goal)}` : 'Точка: —';
    }
    const lift = state.lift;
    byId('lift').textContent = lift.last_command === 'up' ? 'Опустить лифт' : 'Поднять лифт';
    byId('lift').title = lift.last_command ? 'По последней принятой команде; датчик положения не подключён' : 'Положение лифта неизвестно';
    const message = state.lift.status === 'error' ? `Ошибка лифта: ${state.lift.error}` : state.route.message;
    byId('route-message').textContent = clientMessage && Date.now() < clientMessageUntil ? clientMessage : message;
    updateRouteButtonsState();
}

function updateStatus(state, fresh) {
    const stopped = fresh ? state.motion.stopped : null;
    byId('speed').textContent = stopped === null ? 'Нет данных' : stopped ? 'Стоит' : 'Движется';
    const dot = document.querySelector('#StatusMov .statusbar__dot');
    dot.style.background = stopped === null ? '#8b8b8b' : stopped ?
        'radial-gradient(circle at 35% 30%, #ff9999, #e60000 55%, #990000)' :
        'radial-gradient(circle at 35% 30%, #8cf08c, #17c517 55%, #0a9e0a)';
    dot.style.borderColor = stopped === null ? '#666' : stopped ? '#8b0000' : '#0b8b0b';
}

function updateBatteryAndEmergency(data) {
    const battery = Number(data.battery);
    const image = Number(data.chargeFlag) === 2 ? 'battery.gif' :
        battery >= 80 ? 'batteryFULL.png' : battery >= 30 ? 'batteryMEDIUM.png' : 'batteryLOW.png';
    const icon = byId('StatusBattery');
    if (!icon.src.endsWith(image)) icon.src = `../../reference/${image}`;
    icon.title = `Заряд батареи: ${data.battery}%`;
    const emergency = byId('emergencyIcon');
    const value = String(data.emergencyButton);
    const label = value === '0' ? 'Аварийная кнопка нажата' : value === '1' ?
        'Аварийная кнопка отпущена' : 'Состояние аварийной кнопки неизвестно';
    emergency.style.color = value === '0' ? '#e60000' : '#8b8b8b';
    emergency.setAttribute('aria-label', label);
    emergency.querySelector('title').textContent = label;
}

function createRouteItem(point) {
    const item = document.createElement('li');
    const label = document.createElement('span');
    label.className = 'route-point-name';
    label.textContent = displayPoint(point);
    const actions = document.createElement('div');
    actions.className = 'route-point-actions';
    for (const [className, text, title] of [
        ['move-up-btn', '↑', 'Переместить вверх'],
        ['move-down-btn', '↓', 'Переместить вниз'],
        ['delete-btn', '×', 'Удалить из маршрута']
    ]) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = className;
        button.textContent = text;
        button.title = title;
        button.setAttribute('aria-label', `${title}: ${displayPoint(point)}`);
        actions.append(button);
    }
    item.append(label, actions);
    return item;
}

function updateRouteButtonsState() {
    const available = backendConnected && !!serverState && !actionPending;
    const route = serverState?.route;
    const active = route && ['running', 'returning'].includes(route.status);
    const hasPoints = !!serverState?.draft.points.length;
    byId('route-empty').classList.toggle('hidden', hasPoints);
    byId('route-count').textContent = serverState?.draft.points.length || 0;
    byId('send-route-btn').disabled = !available || !hasPoints || active;
    byId('clear-route-btn').disabled = !available || !hasPoints;
    byId('cancel-route-btn').disabled = !available || !['running', 'error'].includes(route?.status);
    document.querySelectorAll('#points-list button, #points-list-route button').forEach(button => {
        button.disabled = !available;
    });
    document.querySelectorAll('.points button, #charger').forEach(button => {
        button.disabled = !available || active || !serverState?.online;
    });
    byId('lift').disabled = !available || !serverState?.online || ['queued', 'sending'].includes(serverState?.lift.status);
    const map = byId('mapIcon');
    const routeRunning = route?.kind === 'route' && route.status === 'running';
    const image = routeRunning ? 'mapActive.gif' : 'map.png';
    if (!map.src.endsWith(image)) map.src = `../../reference/${image}`;
    map.title = routeRunning ? 'Маршрут выполняется' : 'Нет активного маршрута';
}

function saveDraft(points) {
    return performAction('/api/draft', { points, version: serverState.draft.version });
}

function addList(event) {
    const button = event.target.closest('button');
    if (!button || actionPending || !serverState || !backendConnected) return;
    saveDraft([...serverState.draft.points, button.textContent.trim()]);
}

function handleRouteClick(event) {
    const button = event.target.closest('button');
    const item = button?.closest('li');
    if (!item || actionPending || !serverState || !backendConnected) return;
    const points = [...serverState.draft.points];
    const index = [...item.parentElement.children].indexOf(item);
    if (button.classList.contains('delete-btn')) points.splice(index, 1);
    else {
        const next = button.classList.contains('move-up-btn') ? index - 1 : index + 1;
        if (next < 0 || next >= points.length) return;
        [points[index], points[next]] = [points[next], points[index]];
    }
    saveDraft(points);
}

function sendRoute() {
    if (serverState) performAction('/api/route/start', { version: serverState.draft.version });
}

function cancelRoute() {
    performAction('/api/route/cancel', {});
}

function clearRoute() {
    if (serverState) saveDraft([]);
}

function GoToPoint(point) {
    performAction('/api/navigate', { point });
}

function LiftUD() {
    performAction('/api/lift', { direction: serverState.lift.last_command === 'up' ? 'down' : 'up' });
}

document.addEventListener('DOMContentLoaded', () => {
    if (location.protocol === 'file:') return;
    document.querySelector('.points').addEventListener('click', event => {
        const button = event.target.closest('button');
        if (button) GoToPoint(button.textContent.trim());
    });
    byId('charger').addEventListener('click', () => GoToPoint('Зарядка'));
    byId('lift').addEventListener('click', LiftUD);
    byId('points-list').addEventListener('click', addList);
    byId('points-list-route').addEventListener('click', handleRouteClick);
    byId('send-route-btn').addEventListener('click', sendRoute);
    byId('clear-route-btn').addEventListener('click', clearRoute);
    byId('cancel-route-btn').addEventListener('click', cancelRoute);
    const modal = byId('modal');
    const closeButton = modal.querySelector('.close-btn');
    byId('route').addEventListener('click', () => {
        modal.classList.remove('hidden');
        document.body.classList.add('modal-open');
        closeButton.focus();
    });
    closeButton.addEventListener('click', () => {
        modal.classList.add('hidden');
        document.body.classList.remove('modal-open');
        byId('route').focus();
    });
    modal.addEventListener('click', event => {
        if (event.target === modal) closeButton.click();
    });
    modal.addEventListener('keydown', event => {
        if (event.key === 'Escape') closeButton.click();
        if (event.key !== 'Tab') return;
        const buttons = [...modal.querySelectorAll('button:not(:disabled)')].filter(button => button.getClientRects().length);
        const first = buttons[0], last = buttons[buttons.length - 1];
        if (event.shiftKey && document.activeElement === first) {
            event.preventDefault(); last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault(); first.focus();
        }
    });
    updateRouteButtonsState();
    refreshState();
    setInterval(refreshState, UPDATE_INTERVAL);
});
