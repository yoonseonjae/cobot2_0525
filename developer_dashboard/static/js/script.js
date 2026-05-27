// Clock
function updateClock() {
    const now = new Date();
    document.getElementById('clock').innerText = now.toLocaleString('ko-KR', {
        year: 'numeric', month: '2-digit', day: '2-digit', 
        hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
    });
}
setInterval(updateClock, 1000);
updateClock();

// Telemetry Polling
function updateStagePipeline(currentStage, stagesOrder, stageLabel) {
    const idx = stagesOrder.indexOf(currentStage);
    document.querySelectorAll('.stage-step').forEach((el) => {
        const stage = el.dataset.stage;
        const stageIdx = stagesOrder.indexOf(stage);
        el.classList.remove('done', 'active');
        if (idx < 0) return;  // IDLE: 전부 비활성
        if (stageIdx < idx) el.classList.add('done');
        else if (stageIdx === idx) el.classList.add('active');
    });
    // 커넥터: 각 .stage-connector는 직전 .stage-step 다음에 옴 (DOM 순서: step,conn,step,conn,step,conn,step)
    const connectors = document.querySelectorAll('.stage-connector');
    connectors.forEach((c, i) => {
        c.classList.toggle('done', idx > i);
    });
    const statusEl = document.getElementById('stage-status-text');
    if (statusEl) {
        statusEl.innerText = stageLabel || '대기 중';
        statusEl.classList.remove('active', 'complete');
        if (currentStage === 'COMPLETE') statusEl.classList.add('complete');
        else if (idx >= 0) statusEl.classList.add('active');
    }
}

async function fetchTelemetry() {
    try {
        const response = await fetch('/api/telemetry');
        const data = await response.json();

        // Update Status
        document.getElementById('robot-status-text').innerText = data.robot_status;

        // Update Stage Pipeline
        updateStagePipeline(
            data.current_stage || 'IDLE',
            data.stages_order || ['RECOGNIZE','PICKUP','CAPTURE','COMPLETE'],
            data.stage_label || '대기'
        );

        // Update Joints
        document.getElementById('j1-val').innerText = data.joints.j1.toFixed(1) + '°';
        document.getElementById('j2-val').innerText = data.joints.j2.toFixed(1) + '°';
        document.getElementById('j3-val').innerText = data.joints.j3.toFixed(1) + '°';
        document.getElementById('j4-val').innerText = data.joints.j4.toFixed(1) + '°';
        document.getElementById('j5-val').innerText = data.joints.j5.toFixed(1) + '°';
        document.getElementById('j6-val').innerText = data.joints.j6.toFixed(1) + '°';

        // Update Safety Mode banner
        renderSafetyBanner(data.safety_mode);

        // Update Logs
        renderLogs(data.logs);

        // Update DB Status
        const dbText = document.getElementById('db-status-text');
        const dbDot = document.getElementById('db-dot');
        dbText.innerText = data.db_status || 'OFFLINE';
        if (data.db_status === 'ONLINE') {
            dbDot.classList.add('online');
            dbDot.style.background = '';
            dbDot.style.color = '';
            dbText.style.color = '';

            // ── MISSION STATUS: 서버에서 추론한 mission 객체 우선 사용 ──
            const m = data.mission || {};
            document.getElementById('rtdb-scene').innerText  = m.scene  || '-';
            document.getElementById('rtdb-task').innerText   = m.task   || '-';
            document.getElementById('rtdb-state').innerText  = m.state  || '-';
            document.getElementById('rtdb-picked').innerText = (m.picked != null) ? m.picked : 0;
            
            // Update RTDB Tools
            if (data.rtdb && data.rtdb.tool) {
                const toolsGrid = document.getElementById('tools-grid');
                toolsGrid.innerHTML = '';
                Object.keys(data.rtdb.tool).forEach(toolName => {
                    const isPicked = data.rtdb.tool[toolName];
                    const badge = document.createElement('div');
                    badge.innerText = toolName.toUpperCase();
                    badge.style.padding = '0.2rem 0.5rem';
                    badge.style.borderRadius = '4px';
                    badge.style.fontSize = '0.75rem';
                    badge.style.fontWeight = 'bold';
                    badge.style.border = '1px solid';
                    if (isPicked) {
                        badge.style.backgroundColor = 'rgba(0, 255, 136, 0.2)';
                        badge.style.borderColor = 'var(--neon-green)';
                        badge.style.color = 'var(--neon-green)';
                    } else {
                        badge.style.backgroundColor = 'rgba(255, 255, 255, 0.05)';
                        badge.style.borderColor = 'rgba(255, 255, 255, 0.2)';
                        badge.style.color = 'var(--text-secondary)';
                    }
                    toolsGrid.appendChild(badge);
                });
            }
            
        } else {
            dbDot.classList.remove('online');
            dbDot.style.background = 'red';
            dbDot.style.color = 'red';
            dbText.style.color = 'red';
        }
        
    } catch (e) {
        console.error("Telemetry fetch failed:", e);
        document.getElementById('robot-status-text').innerText = 'OFFLINE';
        document.getElementById('robot-dot').classList.remove('online');
        document.getElementById('robot-dot').style.background = 'red';
        document.getElementById('robot-dot').style.color = 'red';
        document.getElementById('robot-status-text').style.color = 'red';
        
        document.getElementById('db-status-text').innerText = 'OFFLINE';
        document.getElementById('db-dot').classList.remove('online');
        document.getElementById('db-dot').style.background = 'red';
        document.getElementById('db-dot').style.color = 'red';
        document.getElementById('db-status-text').style.color = 'red';
    }
}

// 스와이프 애니메이션이 끝날 때까지 fetchTelemetry가 logs를 다시 채우지 못하게 막음
let _logsRenderSuppressedUntil = 0;
// CLEAR 누를 때 시점에 화면에 있던 로그들의 키를 저장 → 다시 안 보이게 (서버 clear 실패 시 방어)
const _clearedLogKeys = new Set();
const _logKey = (log) => `${log.time}|${log.category}|${log.message}`;

function renderLogs(logs) {
    if (Date.now() < _logsRenderSuppressedUntil) return;
    const container = document.getElementById('logs-container');
    container.innerHTML = '';

    logs.forEach(log => {
        if (_clearedLogKeys.has(_logKey(log))) return;  // 사용자가 지운 로그는 다시 그리지 않음
        const div = document.createElement('div');
        div.className = `log-card ${log.category}`;

        const confStr = log.confidence ? ` (CONF: ${log.confidence})` : '';

        div.innerHTML = `
            <div class="log-header">
                <span>[${log.time}]</span>
                <span>${log.category}</span>
            </div>
            <div class="log-message">${log.message}${confStr}</div>
        `;
        container.appendChild(div);
    });
}

// ── AI Logs 일괄 삭제 (휴대폰 탭 닫기 식 스와이프) ──
document.getElementById('logs-clear-btn').addEventListener('click', async () => {
    const container = document.getElementById('logs-container');
    const cards = Array.from(container.querySelectorAll('.log-card'));

    // 최근 폴링으로 받은 로그도 함께 blacklist (애니메이션 중에 폴링이 다시 와도 안 보이도록)
    // 우선 화면에 있는 카드들의 키를 추출
    cards.forEach(card => {
        const time = card.querySelector('.log-header span:first-child')?.innerText?.replace(/^\[|\]$/g, '') || '';
        const cat  = card.querySelector('.log-header span:last-child')?.innerText || '';
        const msg  = card.querySelector('.log-message')?.innerText?.replace(/\s*\(CONF: [^)]+\)$/, '') || '';
        _clearedLogKeys.add(`${time}|${cat}|${msg}`);
    });

    const PER_DELAY = 35;
    const ANIM_MS   = 320;
    const totalMs   = cards.length * PER_DELAY + ANIM_MS + 100;
    _logsRenderSuppressedUntil = Date.now() + totalMs;

    cards.forEach((card, i) => {
        setTimeout(() => card.classList.add('swiping'), i * PER_DELAY);
    });

    // 서버 측 로그 버퍼 비우기 (실패해도 클라이언트 blacklist로 가려짐)
    try {
        const res = await fetch('/api/logs/clear', { method: 'POST' });
        if (!res.ok) console.warn('[CLEAR] server returned', res.status, '— Flask 재시작 필요?');
    } catch (e) {
        console.warn('[CLEAR] fetch failed', e);
    }

    setTimeout(() => { container.innerHTML = ''; }, totalMs);
});

// Poll every 500ms
setInterval(fetchTelemetry, 500);

// Removed dummy log polling, now using real Firebase and ROS data

// Emergency Stop Button
document.getElementById('estop-btn').addEventListener('click', async () => {
    try { await fetch('/api/estop', { method: 'POST' }); }
    catch (e) { console.warn("Failed to trigger E-STOP", e); }
});

// ── Safety Mode Banner rendering ───────────────────────────────────────
function renderSafetyBanner(sm) {
    const banner = document.getElementById('safety-banner');
    if (!banner || !sm) return;
    const title   = document.getElementById('safety-banner-title');
    const sub     = document.getElementById('safety-banner-sub');
    const timer   = document.getElementById('safety-banner-timer');
    const actions = document.getElementById('safety-banner-actions');

    if (sm.mode === 'NORMAL') {
        banner.classList.add('hidden');
        banner.classList.remove('pause', 'emerg');
        return;
    }
    banner.classList.remove('hidden');

    if (sm.mode === 'SAFETY_PAUSE') {
        banner.classList.add('pause'); banner.classList.remove('emerg');
        title.innerText = '안전정지모드';
        const srcLabel = sm.source === 'COLLISION' ? '로봇 접촉(노란불)' :
                         sm.source === 'VISION'    ? '안전구역 침범 감지' : (sm.source || '');
        sub.innerText = `${srcLabel} · ${sm.message || ''}`;
        actions.classList.add('hidden');
        if (sm.countdown > 0) {
            timer.classList.remove('hidden');
            timer.innerText = `복귀까지 ${sm.countdown.toFixed(1)}s`;
        } else {
            timer.classList.add('hidden');
        }
    } else if (sm.mode === 'EMERGENCY') {
        banner.classList.add('emerg'); banner.classList.remove('pause');
        title.innerText = '비상정지모드';
        let srcLabel;
        if (sm.last_robot_state === 6) {
            srcLabel = '⚠️ 펜던트의 비상정지 버튼이 눌려 있습니다';
        } else if (sm.last_robot_state === 3 || sm.last_robot_state === 10) {
            srcLabel = '서보 꺼짐(SAFE_OFF) - 재기동 필요';
        } else if (sm.source === 'EMERGENCY_STATE') {
            srcLabel = '로봇 충돌(빨간불)';
        } else if (sm.source === 'BUTTON') {
            srcLabel = '대시보드 비상정지 버튼';
        } else {
            srcLabel = sm.source || '';
        }
        sub.innerText = `${srcLabel} · ${sm.message || ''}`;

        // state 6 (펜던트 E-Stop 물리적으로 눌림) → 두 버튼 모두 비활성화 + 안내
        const resumeBtn = document.getElementById('safety-resume-btn');
        const homeBtn   = document.getElementById('safety-home-btn');
        const eStopHeld = (sm.last_robot_state === 6);

        if (eStopHeld) {
            sub.innerText = `${srcLabel} · 펜던트 버튼 해제 후 자동 복구됩니다`;
        }
        if (sm.countdown > 0) {
            timer.classList.remove('hidden');
            timer.innerText = `복귀까지 ${sm.countdown.toFixed(1)}s`;
            actions.classList.add('hidden');
        } else {
            timer.classList.add('hidden');
            actions.classList.remove('hidden');
            resumeBtn.disabled = eStopHeld;
            homeBtn.disabled   = eStopHeld;
            const tip = eStopHeld ? '비상정지 버튼을 먼저 해제하세요' : '';
            resumeBtn.title = tip;
            homeBtn.title   = tip;
        }
    }
}

document.getElementById('safety-resume-btn').addEventListener('click', async () => {
    try { await fetch('/api/safety/resume', { method: 'POST' }); }
    catch (e) { console.warn(e); }
});
document.getElementById('safety-home-btn').addEventListener('click', async () => {
    if (!confirm('처음으로 돌아갑니다. 로봇이 홈으로 이동하고 클라우드가 리셋됩니다. 진행할까요?')) return;
    try { await fetch('/api/safety/reset_home', { method: 'POST' }); }
    catch (e) { console.warn(e); }
});

// ─── Safety Zone Drawing ─────────────────────────────────────────────────
const zoneState = {
    drawing: false,
    pointsDisp: [],   // 화면 좌표 (canvas px)
};

const videoImg = document.getElementById('main-video-stream');
const canvas = document.getElementById('zone-canvas');
const ctx = canvas.getContext('2d');
const drawBtn = document.getElementById('zone-draw-btn');
const confirmBtn = document.getElementById('zone-confirm-btn');
const clearBtn = document.getElementById('zone-clear-btn');
const zoneStatus = document.getElementById('zone-status');

function resizeCanvas() {
    const rect = videoImg.getBoundingClientRect();
    // CSS 크기와 drawing buffer 1:1 매핑 (좌표 변환 단순화)
    canvas.width = Math.max(1, Math.round(rect.width));
    canvas.height = Math.max(1, Math.round(rect.height));
    canvas.style.width = rect.width + 'px';
    canvas.style.height = rect.height + 'px';
    drawZonePreview();
}
window.addEventListener('resize', resizeCanvas);
videoImg.addEventListener('load', resizeCanvas);
// 컨테이너 크기 변화 감지 (패널 리사이즈 등)
if (typeof ResizeObserver !== 'undefined') {
    new ResizeObserver(resizeCanvas).observe(videoImg);
}
setTimeout(resizeCanvas, 200);

// object-fit: contain → 실제 렌더 영역 계산 (이미지 원본 좌표 변환용)
function getImageRect() {
    const cw = canvas.width, ch = canvas.height;
    const nw = videoImg.naturalWidth || cw;
    const nh = videoImg.naturalHeight || ch;
    const scale = Math.min(cw / nw, ch / nh);
    const w = nw * scale, h = nh * scale;
    return { x: (cw - w) / 2, y: (ch - h) / 2, w, h, scale, nw, nh };
}

function drawZonePreview() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (!zoneState.drawing || zoneState.pointsDisp.length === 0) return;
    ctx.strokeStyle = '#ffff00';
    ctx.fillStyle = '#ffff00';
    ctx.lineWidth = 2;
    ctx.beginPath();
    zoneState.pointsDisp.forEach((p, i) => {
        if (i === 0) ctx.moveTo(p[0], p[1]);
        else ctx.lineTo(p[0], p[1]);
    });
    if (zoneState.pointsDisp.length >= 3) {
        ctx.closePath();
        ctx.fillStyle = 'rgba(255, 255, 0, 0.15)';
        ctx.fill();
    }
    ctx.stroke();
    zoneState.pointsDisp.forEach(p => {
        ctx.beginPath();
        ctx.arc(p[0], p[1], 5, 0, Math.PI * 2);
        ctx.fillStyle = '#ffff00';
        ctx.fill();
    });
}

canvas.addEventListener('click', (ev) => {
    if (!zoneState.drawing) return;
    const rect = canvas.getBoundingClientRect();
    // CSS px → canvas drawing buffer px 변환 (둘이 1:1이 아닐 수 있음)
    const sx = canvas.width / rect.width;
    const sy = canvas.height / rect.height;
    const x = (ev.clientX - rect.left) * sx;
    const y = (ev.clientY - rect.top) * sy;
    // 캔버스 내부면 무조건 등록 (imgRect 바깥이면 CONFIRM 단계에서 clamp)
    if (x < 0 || y < 0 || x > canvas.width || y > canvas.height) return;
    zoneState.pointsDisp.push([x, y]);
    drawZonePreview();
    confirmBtn.disabled = zoneState.pointsDisp.length < 3;
    zoneStatus.innerText = `DRAWING: ${zoneState.pointsDisp.length} pts (right-click=undo, ≥3 to confirm)`;
});

// 우클릭으로 마지막 점 제거 (undo)
canvas.addEventListener('contextmenu', (ev) => {
    if (!zoneState.drawing) return;
    ev.preventDefault();
    if (zoneState.pointsDisp.length === 0) return;
    zoneState.pointsDisp.pop();
    drawZonePreview();
    confirmBtn.disabled = zoneState.pointsDisp.length < 3;
    zoneStatus.innerText = `DRAWING: ${zoneState.pointsDisp.length} pts (right-click=undo, ≥3 to confirm)`;
});

drawBtn.addEventListener('click', () => {
    zoneState.drawing = true;
    zoneState.pointsDisp = [];
    canvas.classList.add('drawing');
    confirmBtn.disabled = true;
    zoneStatus.innerText = 'DRAWING: click points (right-click = undo)';
    drawZonePreview();
});

confirmBtn.addEventListener('click', async () => {
    const imgRect = getImageRect();
    const polygonSrc = zoneState.pointsDisp.map(([x, y]) => {
        // 이미지 영역 바깥 클릭은 가장 가까운 이미지 가장자리로 clamp
        const sx = Math.round((x - imgRect.x) / imgRect.scale);
        const sy = Math.round((y - imgRect.y) / imgRect.scale);
        return [
            Math.max(0, Math.min(imgRect.nw - 1, sx)),
            Math.max(0, Math.min(imgRect.nh - 1, sy)),
        ];
    });
    try {
        const res = await fetch('/api/safety_zone', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ polygon: polygonSrc }),
        });
        const data = await res.json();
        if (data.ok) {
            zoneStatus.innerText = `ZONE SET (${data.points} pts)`;
        } else {
            zoneStatus.innerText = `ERROR: ${data.error}`;
        }
    } catch (e) {
        zoneStatus.innerText = `ERROR: ${e}`;
    }
    zoneState.drawing = false;
    zoneState.pointsDisp = [];
    canvas.classList.remove('drawing');
    confirmBtn.disabled = true;
    drawZonePreview();
});

clearBtn.addEventListener('click', async () => {
    try {
        await fetch('/api/safety_zone', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ polygon: [] }),
        });
        zoneStatus.innerText = 'ZONE CLEARED';
    } catch (e) {
        zoneStatus.innerText = `ERROR: ${e}`;
    }
    zoneState.drawing = false;
    zoneState.pointsDisp = [];
    canvas.classList.remove('drawing');
    confirmBtn.disabled = true;
    drawZonePreview();
});
