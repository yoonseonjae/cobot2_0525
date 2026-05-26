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
async function fetchTelemetry() {
    try {
        const response = await fetch('/api/telemetry');
        const data = await response.json();
        
        // Update Status
        document.getElementById('robot-status-text').innerText = data.robot_status;
        document.getElementById('current-state-text').innerText = data.current_state;
        
        // Update Joints
        document.getElementById('j1-val').innerText = data.joints.j1.toFixed(1) + '°';
        document.getElementById('j2-val').innerText = data.joints.j2.toFixed(1) + '°';
        document.getElementById('j3-val').innerText = data.joints.j3.toFixed(1) + '°';
        document.getElementById('j4-val').innerText = data.joints.j4.toFixed(1) + '°';
        document.getElementById('j5-val').innerText = data.joints.j5.toFixed(1) + '°';
        document.getElementById('j6-val').innerText = data.joints.j6.toFixed(1) + '°';
        
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
            
            // Update RTDB Mission Status
            if (data.rtdb && data.rtdb.robot_status) {
                document.getElementById('rtdb-scene').innerText = data.rtdb.robot_status.scene || '-';
                document.getElementById('rtdb-task').innerText = data.rtdb.robot_status.current_task || '-';
                document.getElementById('rtdb-state').innerText = data.rtdb.robot_status.state || '-';
                document.getElementById('rtdb-picked').innerText = data.rtdb.robot_status.picked_count || '0';
            }
            
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

function renderLogs(logs) {
    const container = document.getElementById('logs-container');
    container.innerHTML = '';
    
    logs.forEach(log => {
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

// Poll every 500ms
setInterval(fetchTelemetry, 500);

// Removed dummy log polling, now using real Firebase and ROS data

// Emergency Stop Button
document.getElementById('estop-btn').addEventListener('click', async () => {
    try {
        const res = await fetch('/api/estop', { method: 'POST' });
        const data = await res.json();
        alert(data.status);
    } catch (e) {
        alert("Failed to trigger E-STOP");
    }
});

// Camera Selector
document.getElementById('cam-select').addEventListener('change', (e) => {
    const camIdx = e.target.value;
    const img = document.getElementById('main-video-stream');
    img.src = `/video_feed?cam=${camIdx}&t=${new Date().getTime()}`;
});
