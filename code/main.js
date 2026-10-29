// Время ожидания в секундах. Backend подхватывает изменения после сохранения файла.
const ROUTE_WAIT_SECONDS = 120;
const IDLE_RETURN_SECONDS = 600;
const UPDATE_INTERVAL = 500;
const POINT_NAMES = { 'ВП4_2': 'ВП4', 'ВП2.1,3.1': 'ВП2.1-3.1', 'ворота': 'Ворота', 'склад': 'Склад' };
let serverState = null;
let backendConnected = false;
let actionPending = false;
let refreshPending = false;
let renderedDraftVersion = -1;
let clientMessage = '';
let clientMessageUntil = 0;
let liftPending = false;
const liveTelemetry = {};
const telemetryPending = new Set();
const telemetryProxy = new Set();
let motionCandidate = null;
let motionCount = 0;
let stoppedState = null;
let motionSampleAt = 0;
let navigationConfirmationPending = false;

// The server serves both the panel and the API from the same origin.
if (location.protocol === 'file:') location.replace('http://127.0.0.1:8000/');

const byId = id => document.getElementById(id);
const displayPoint = point => POINT_NAMES[point] || point;
const isRouteLocked = route => !!route && (route.locked ?? (['running', 'error'].includes(route.status) && !route.cancel_requested));

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
        throw Object.assign(new Error(data.error || 'Ошибка сервера'), data);
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
        byId('connection-status').textContent = 'Нет связи с сервером управления';
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
        reportCommandError(error);
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
    const waitSeconds = state.timing?.route_wait_seconds ?? ROUTE_WAIT_SECONDS;
    byId('route-wait-label').textContent = waitSeconds % 60 === 0 ? `${waitSeconds / 60} мин` : `${waitSeconds} с`;
    const connection = byId('connection-status');
    connection.textContent = !state.online ? 'Нет актуальных данных от робота. Ожидание связи' :
        state.demo ? 'Деморежим: подключён симулятор, команды настоящему роботу не отправляются' : '';
    connection.classList.toggle('hidden', state.online && !state.demo);

    if (state.draft.version !== renderedDraftVersion) {
        byId('points-list-route').replaceChildren(...state.draft.points.map(createRouteItem));
        renderedDraftVersion = state.draft.version;
    }
    const lift = state.lift;
    const routeActive = isRouteLocked(state.route);
    byId('lift').textContent = !routeActive && lift.last_command === 'up' ? 'Опустить лифт' : 'Поднять лифт';
    byId('lift').title = lift.last_command ? 'По последней принятой команде; датчик положения не подключён' : 'Положение лифта неизвестно';
    let message = ['returning', 'cancelled'].includes(state.route.status) ? 'Маршрут отменён' : state.route.message;
    if (state.route.status === 'running' && state.route.phase === 'dwell') {
        const remaining = state.route.dwell_until - state.server_time;
        const seconds = Math.max(0, Math.ceil(remaining));
        message += ` · ${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
    }
    byId('route-message').textContent = message;
    if (clientMessage && Date.now() < clientMessageUntil) showCommandMessage(clientMessage);
    else if (state.lift.status === 'error') showCommandMessage(`Ошибка лифта: ${state.lift.error}`);
    else {
        const navigation = state.navigation;
        const autoNotice = navigation?.automatic && navigation.message === 'Автовозврат на зарядку';
        const noticeVisible = autoNotice && ['ready', 'sending', 'waiting'].includes(navigation.status) &&
            navigation.notice_until > state.server_time && !routeActive;
        showCommandMessage(autoNotice && !noticeVisible ? '' : navigation?.message || '');
    }
    updateRouteButtonsState();
}

function showCommandMessage(message) {
    byId('command-message').textContent = message;
    byId('command-message').classList.toggle('hidden', !message);
}

function reportCommandError(error) {
    clientMessage = error.message;
    clientMessageUntil = Date.now() + 6000;
    showCommandMessage(clientMessage);
}

async function refreshTelemetry() {
    if (!serverState?.telemetry_urls) return;
    await Promise.all(Object.entries(serverState.telemetry_urls).map(async ([name, url]) => {
        if (telemetryPending.has(name)) return;
        telemetryPending.add(name);
        try {
            const requestUrl = telemetryProxy.has(name) ? `/api/telemetry/${name}` : url;
            const response = await fetch(requestUrl, { cache: 'no-store', signal: AbortSignal.timeout(2500) });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            liveTelemetry[name] = { data: await response.json(), receivedAt: Date.now() };
        } catch (error) {
            // Robot APIs without CORS still work through a small GET endpoint.
            if (!url.startsWith('/api/telemetry/') && !telemetryProxy.has(name)) {
                try {
                    const response = await fetch(`/api/telemetry/${name}`, { cache: 'no-store', signal: AbortSignal.timeout(1500) });
                    if (!response.ok) throw new Error(`HTTP ${response.status}`);
                    liveTelemetry[name] = { data: await response.json(), receivedAt: Date.now() };
                    telemetryProxy.add(name);
                } catch (proxyError) { delete liveTelemetry[name]; }
            } else delete liveTelemetry[name];
        } finally {
            telemetryPending.delete(name);
            renderTelemetry();
        }
    }));
    renderTelemetry();
}

function renderTelemetry() {
    const fresh = name => liveTelemetry[name] && Date.now() - liveTelemetry[name].receivedAt < 5000;
    if (fresh('base')) updateBatteryAndEmergency(liveTelemetry.base.data);
    else {
        byId('StatusBattery').title = 'Заряд батареи: нет актуальных данных';
        const emergency = byId('emergencyIcon');
        emergency.style.color = '#8b8b8b';
        emergency.setAttribute('aria-label', 'Состояние аварийной кнопки неизвестно');
        emergency.querySelector('title').textContent = 'Состояние аварийной кнопки неизвестно';
    }
    if (fresh('nav')) {
        const goal = liveTelemetry.nav.data.goal;
        byId('StatusPoint').textContent = goal ? `Точка: ${displayPoint(goal)}` : 'Точка: —';
    } else byId('StatusPoint').textContent = 'Точка: нет данных';
    const speed = fresh('speed') ? Number(liveTelemetry.speed.data.vx) : NaN;
    const distance = fresh('nav') ? Number(liveTelemetry.nav.data.dist) : NaN;
    const validSpeed = fresh('speed') && liveTelemetry.speed.data.vx != null && Number.isFinite(speed);
    if (validSpeed && fresh('nav') && liveTelemetry.speed.receivedAt !== motionSampleAt) {
        motionSampleAt = liveTelemetry.speed.receivedAt;
        const candidate = !(Number.isFinite(distance) && distance >= 1) && Math.abs(speed) <= 0.001;
        motionCount = candidate === motionCandidate ? Math.min(3, motionCount + 1) : 1;
        motionCandidate = candidate;
        if (motionCount >= 3) stoppedState = candidate;
    } else if (!validSpeed || !fresh('nav')) {
        stoppedState = motionCandidate = null;
        motionCount = 0;
    }
    updateStatus(stoppedState);
}

function updateStatus(stopped) {
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
    if (!icon.src.endsWith(image)) icon.src = `/assets/${image}`;
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
    const active = isRouteLocked(route);
    const hasPoints = !!serverState?.draft.points.length;
    byId('route-empty').classList.toggle('hidden', hasPoints);
    byId('route-count').textContent = serverState?.draft.points.length || 0;
    byId('send-route-btn').disabled = !available || !hasPoints || active;
    byId('clear-route-btn').disabled = !available || !hasPoints || active;
    byId('cancel-route-btn').disabled = !available || !['running', 'error'].includes(route?.status);
    document.querySelectorAll('#points-list button, #points-list-route button').forEach(button => {
        button.disabled = !available || active;
    });
    document.querySelectorAll('.points button, #charger').forEach(button => {
        button.disabled = !backendConnected || !serverState || active || !serverState.online;
    });
    byId('lift').disabled = active || !backendConnected || !serverState?.online || liftPending || ['queued', 'sending'].includes(serverState?.lift.status);
    const map = byId('mapIcon');
    const routeRunning = route?.kind === 'route' && active;
    const image = routeRunning ? 'mapActive.gif' : 'map.png';
    if (!map.src.endsWith(image)) map.src = `/assets/${image}`;
    map.title = routeRunning ? 'Маршрут выполняется' : 'Нет активного маршрута';
}

function saveDraft(points) {
    return performAction('/api/draft', { points, version: serverState.draft.version });
}

function addList(event) {
    const button = event.target.closest('button');
    if (!button || button.disabled || actionPending || !serverState || !backendConnected) return;
    saveDraft([...serverState.draft.points, button.textContent.trim()]);
}

function handleRouteClick(event) {
    const button = event.target.closest('button');
    const item = button?.closest('li');
    if (!item || button.disabled || actionPending || !serverState || !backendConnected) return;
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

async function goToPoint(point, confirmation) {
    if (!backendConnected || !serverState || isRouteLocked(serverState.route) || navigationConfirmationPending) return;
    try {
        applyState(await api('/api/navigate', { point, confirmation }));
    } catch (error) {
        if (error.code === 'confirmation_required') {
            if (await confirmNavigation(point)) return goToPoint(point, error.confirmation);
            return;
        }
        reportCommandError(error);
    }
}

function confirmNavigation(point) {
    if (navigationConfirmationPending) return Promise.resolve(false);
    navigationConfirmationPending = true;
    const dialog = byId('navigation-confirm');
    const previousFocus = document.activeElement;
    byId('navigation-confirm-point').textContent = displayPoint(point);
    dialog.returnValue = 'keep';
    document.body.classList.add('modal-open');
    return new Promise(resolve => {
        dialog.addEventListener('close', () => {
            navigationConfirmationPending = false;
            if (byId('modal').classList.contains('hidden')) document.body.classList.remove('modal-open');
            if (previousFocus?.isConnected && !previousFocus.disabled) previousFocus.focus();
            resolve(dialog.returnValue === 'change');
        }, { once: true });
        dialog.showModal();
        byId('navigation-keep-btn').focus();
    });
}

async function toggleLift() {
    if (liftPending || !serverState || isRouteLocked(serverState.route)) return;
    liftPending = true;
    updateRouteButtonsState();
    try {
        const direction = serverState.lift.last_command === 'up' ? 'down' : 'up';
        applyState(await api('/api/lift', { direction }));
    } catch (error) {
        reportCommandError(error);
    } finally {
        liftPending = false;
        updateRouteButtonsState();
    }
}

document.addEventListener('DOMContentLoaded', () => {
    if (location.protocol === 'file:') return;
    document.querySelector('.points').addEventListener('click', event => {
        const button = event.target.closest('button');
        if (button && !button.disabled) goToPoint(button.textContent.trim());
    });
    byId('charger').addEventListener('click', () => goToPoint('Зарядка'));
    byId('lift').addEventListener('click', toggleLift);
    byId('points-list').addEventListener('click', addList);
    byId('points-list-route').addEventListener('click', handleRouteClick);
    byId('send-route-btn').addEventListener('click', sendRoute);
    byId('clear-route-btn').addEventListener('click', clearRoute);
    byId('cancel-route-btn').addEventListener('click', cancelRoute);
    const modal = byId('modal');
    const closeButton = modal.querySelector('.close-btn');
    const confirmationDialog = byId('navigation-confirm');
    confirmationDialog.addEventListener('keydown', event => {
        if (event.key === 'Escape') {
            event.preventDefault();
            confirmationDialog.close('keep');
        }
    });
    confirmationDialog.addEventListener('click', event => {
        if (event.target !== confirmationDialog) return;
        const bounds = confirmationDialog.getBoundingClientRect();
        if (event.clientX < bounds.left || event.clientX > bounds.right ||
            event.clientY < bounds.top || event.clientY > bounds.bottom) confirmationDialog.close('keep');
    });
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
    refreshState().then(refreshTelemetry);
    setInterval(refreshState, UPDATE_INTERVAL);
    setInterval(refreshTelemetry, UPDATE_INTERVAL);
});
