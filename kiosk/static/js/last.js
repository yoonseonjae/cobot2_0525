// csg@csg-com:~/doocut_ws/static/js/last.js 완전체 교정본
document.addEventListener('DOMContentLoaded', () => {
    // 🎵 BGM: 최종 엔딩 음악 재생
    sessionStorage.removeItem('bgm_track');
    sessionStorage.removeItem('bgm_time');
    let currentBGM = new Audio('/sound/bgm/ending.mp3');
    currentBGM.loop = true;
    currentBGM.play().catch(e => {
        document.body.addEventListener('click', () => currentBGM.play().catch(console.log), { once: true });
    });

    // 1. 하단에 찍힐 날짜 표시 파라미터 조율
    const dateLabel = document.getElementById('currentDate');
    const now = new Date();
    if (dateLabel) {
        dateLabel.textContent = `${now.getFullYear()}.${String(now.getMonth()+1).padStart(2, '0')}.${String(now.getDate()).padStart(2, '0')} | SEOUL`;
    }

    // 2. 세션 디자인 테마 복원 엔진 기동
    const chosenColor = sessionStorage.getItem('chosenFrameColor') || 'black';
    const chosenCustomBg = sessionStorage.getItem('chosenCustomBg') || 'none';
    const frameTarget = document.getElementById('userSelectedFrame');
    const stripHeader = document.getElementById('stripHeader');

    if (frameTarget) {
        frameTarget.className = 'photo-strip';
        frameTarget.classList.add(chosenColor);

        if (chosenColor === 'pink' || chosenColor === 'white') {
            if (stripHeader) stripHeader.style.color = '#111111';
            if (dateLabel) dateLabel.style.color = '#555555';
        } else {
            if (stripHeader) stripHeader.style.color = '#DEFF9A';
            if (dateLabel) dateLabel.style.color = '#888888';
        }

        if (chosenColor === 'custom' && chosenCustomBg !== 'none') {
            frameTarget.style.cssText = `
                background-image: url('${chosenCustomBg}') !important;
                background-size: cover !important;
                background-position: center !important;
                border: 1px solid rgba(255,255,255,0.2) !important;
            `;
            if (stripHeader) stripHeader.style.color = '#ffffff';
            if (dateLabel) dateLabel.style.color = '#eeeeee';
        }
    }

    // 3. 비동기 캡처 이미지 데이터 세션 복구 매핑
    const savedCuts = JSON.parse(sessionStorage.getItem('capturedImages')) || [];
    const cut1El = document.getElementById('cut1');
    const cut2El = document.getElementById('cut2');
    
    if (savedCuts.length >= 2) {
        if (cut1El) cut1El.src = savedCuts[0];
        if (cut2El) cut2El.src = savedCuts[1];
    } else {
        if (cut1El) cut1El.src = "https://placehold.co/1080x1440/111/DEFF9A?text=SHOT+1";
        if (cut2El) cut2El.src = "https://placehold.co/1080x1440/111/DEFF9A?text=SHOT+2";
    }

    // 4. 결과창 진입과 동시에 자동으로 /end 플래그를 true로 송출
    triggerEndFlagTrue();
});

// 🎯 진입 시점 자동화 파이프라인 함수
async function triggerEndFlagTrue() {
    const FIREBASE_END_URL = "https://rokey-coop2-default-rtdb.asia-southeast1.firebasedatabase.app/end.json";
    try {
        console.log("🚀 [자동화 엔진] 결과창 진입 확인. Firebase /end = true 전송을 시작합니다.");
        const response = await fetch(FIREBASE_END_URL, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(true) 
        });
        
        if (response.ok) {
            // 🎯 [완벽 교정] 기존의 print(...) 호출 노이즈를 console.log(...) 파라미터로 철저히 변경!
            console.log("✅ [클라우드 동기화 완료] 로봇 PC 수신 대기열로 /end=true 전달 성공. 로봇 HOME 복귀 개시.");
        }
    } catch (error) {
        console.error("❌ 결과창 자동 종료 신호 주입 중 통신 에러:", error);
    }
}

function getHostIp() {
    const hostname = window.location.hostname;
    if (hostname === 'localhost' || hostname === '127.0.0.1') {
        return window.SERVER_IP || hostname;
    }
    return hostname;
}

// 고해상도 캡처 및 QR 생성 엔진 파라미터
async function generateQR() {
    const btnQr = document.getElementById('btnQr');
    const originalText = btnQr.innerHTML;
    try {
        btnQr.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> 프레임 생성 중...';
        btnQr.disabled = true;
        const frameElement = document.getElementById('userSelectedFrame');
        const canvas = await html2canvas(frameElement, { scale: 3, useCORS: true, backgroundColor: null });
        const stripDataUrl = canvas.toDataURL('image/jpeg', 0.95);
        const response = await fetch('/save_strip', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ image: stripDataUrl })
        });
        const result = await response.json();
        if (result.status === 'success') {
            const hostIp = getHostIp(); 
            const port = window.location.port ? ':' + window.location.port : '';
            const downloadUrl = `http://${hostIp}${port}${result.saved_file}`;
            const qrCanvas = document.getElementById('qrCanvas');
            
            // 텍스트 업데이트 (사진용)
            document.querySelector('.qr-title').textContent = "SCAN ME";
            document.querySelector('.qr-desc').innerHTML = "스마트폰 카메라로 스캔하여<br>고화질 원본 사진을 다운로드하세요!";
            
            new QRious({ element: qrCanvas, value: downloadUrl, size: 250, background: '#ffffff', foreground: '#000000' });
            document.getElementById('qrModal').style.display = 'flex';
        }
    } catch (error) {
        alert("QR코드 인화 엔진 렌더링 에러");
    } finally {
        btnQr.innerHTML = originalText;
        btnQr.disabled = false;
    }
}

function closeQrModal() { document.getElementById('qrModal').style.display = 'none'; }
function saveVideo() {
    const savedVideoUrl = sessionStorage.getItem('savedVideoUrl');
    if (!savedVideoUrl) {
        alert("타임랩스 영상을 찾을 수 없습니다.");
        return;
    }
    
    const hostIp = getHostIp(); 
    const port = window.location.port ? ':' + window.location.port : '';
    const downloadUrl = `http://${hostIp}${port}${savedVideoUrl}`;
    
    const qrCanvas = document.getElementById('qrCanvas');
    
    // 텍스트 업데이트 (영상용)
    document.querySelector('.qr-title').textContent = "TIMELAPSE QR";
    document.querySelector('.qr-desc').innerHTML = "스마트폰 카메라로 스캔하여<br>타임랩스 영상을 다운로드하세요!";
    
    new QRious({ element: qrCanvas, value: downloadUrl, size: 250, background: '#ffffff', foreground: '#000000' });
    document.getElementById('qrModal').style.display = 'flex';
}