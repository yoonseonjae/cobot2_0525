// static/js/last.js 전체 코드 (코드 리뷰 대비 상세 주석 포함)
document.addEventListener('DOMContentLoaded', () => {
    // [구현 내용] BGM 컨트롤
    // 앞선 페이지들에서 이어지던 세션 스토리지를 지우고, 최종 결과 페이지에 맞는 엔딩곡으로 교체합니다.
    sessionStorage.removeItem('bgm_track');
    sessionStorage.removeItem('bgm_time');
    let currentBGM = new Audio('/sound/bgm/ending.mp3');
    currentBGM.loop = true;
    currentBGM.play().catch(e => {
        document.body.addEventListener('click', () => currentBGM.play().catch(console.log), { once: true });
    });

    // 1. [구현 내용] 동적 날짜/시간 주입 렌더링
    // 사진 스트립 하단에 들어갈 YYYY.MM.DD 형태의 현재 시간을 Javascript 내장 Date 객체로 파싱하여 텍스트로 넣습니다.
    const dateLabel = document.getElementById('currentDate');
    const now = new Date();
    if (dateLabel) {
        // padStart(2, '0')를 사용해 한 자리 수 달/일의 경우 앞에 0을 붙여 자릿수를 맞춥니다 (예: 05).
        dateLabel.textContent = `${now.getFullYear()}.${String(now.getMonth()+1).padStart(2, '0')}.${String(now.getDate()).padStart(2, '0')} | SEOUL`;
    }

    // 2. [구현 내용] 세션 스토리지 기반 테마(디자인) 복원 엔진
    // frame.html(프레임 선택 페이지)에서 사용자가 골랐던 색상과 커스텀 배경값을 세션 스토리지에서 꺼내옵니다.
    const chosenColor = sessionStorage.getItem('chosenFrameColor') || 'black';
    const chosenCustomBg = sessionStorage.getItem('chosenCustomBg') || 'none';
    const frameTarget = document.getElementById('userSelectedFrame');
    const stripHeader = document.getElementById('stripHeader');

    // DOM 요소에 동적으로 클래스를 부여하여 CSS 디자인을 입힙니다.
    if (frameTarget) {
        frameTarget.className = 'photo-strip';
        frameTarget.classList.add(chosenColor);

        // 프레임 배경이 밝은 계열(핑크, 화이트)일 경우 글씨 색을 어둡게, 
        // 어두운 계열일 경우 글씨를 밝게 반전시켜 가시성을 확보하는 반응형 폰트 색상 로직입니다.
        if (chosenColor === 'pink' || chosenColor === 'white') {
            if (stripHeader) stripHeader.style.color = '#111111';
            if (dateLabel) dateLabel.style.color = '#555555';
        } else {
            if (stripHeader) stripHeader.style.color = '#DEFF9A';
            if (dateLabel) dateLabel.style.color = '#888888';
        }

        // 사용자가 커스텀 배경(이미지)을 선택했을 경우, cssText를 강제 주입(inline-style)하여 덮어씌웁니다.
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

    // 3. [구현 내용] 캡처된 사진 데이터(Base64) 복구 및 img 태그 바인딩
    // 카메라 뷰(camera.js)에서 백엔드 뷰티 필터를 거쳐 세션 스토리지에 배열 형태로 임시 저장된 사진 데이터를 가져옵니다.
    const savedCuts = JSON.parse(sessionStorage.getItem('capturedImages')) || [];
    const cut1El = document.getElementById('cut1');
    const cut2El = document.getElementById('cut2');
    
    if (savedCuts.length >= 2) {
        // 브라우저 캐시 메모리에 있는 사진 문자열을 바로 src 속성에 연결하여 렌더링 딜레이를 없앱니다.
        if (cut1El) cut1El.src = savedCuts[0];
        if (cut2El) cut2El.src = savedCuts[1];
    } else {
        // 통신 에러 등으로 사진이 유실되었을 경우를 대비한 placeholder(대체 이미지) Fallback 처리입니다.
        if (cut1El) cut1El.src = "https://placehold.co/1080x1440/111/DEFF9A?text=SHOT+1";
        if (cut2El) cut2El.src = "https://placehold.co/1080x1440/111/DEFF9A?text=SHOT+2";
    }

    // 4. 결과창 렌더링이 끝나면 자동으로 로봇에게 종료 신호 전송
    triggerEndFlagTrue();
});

// [구현 내용] 로봇 초기화 신호 전송
async function triggerEndFlagTrue() {
    // 키오스크의 모든 촬영/선택 절차가 끝났음을 의미하는 /end 플래그를 파이어베이스에 true로 기록합니다.
    // 이 값을 로봇이 감지하면 원래의 대기 위치(HOME)로 복귀 이동하게 됩니다.
    const FIREBASE_END_URL = "https://rokey-coop2-default-rtdb.asia-southeast1.firebasedatabase.app/end.json";
    try {
        console.log("🚀 [자동화 엔진] 결과창 진입 확인. Firebase /end = true 전송을 시작합니다.");
        const response = await fetch(FIREBASE_END_URL, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(true) 
        });
        
        if (response.ok) {
            console.log("✅ [클라우드 동기화 완료] 로봇 PC 수신 대기열로 /end=true 전달 성공. 로봇 HOME 복귀 개시.");
        }
    } catch (error) {
        console.error("❌ 결과창 자동 종료 신호 주입 중 통신 에러:", error);
    }
}

function getHostIp() {
    // 외부 기기(스마트폰)에서 스캔 시 localhost로 가면 접속할 수 없으므로,
    // Flask 서버에서 주입해둔 외부망 IP(window.SERVER_IP)로 변환해주는 유틸 함수입니다.
    const hostname = window.location.hostname;
    if (hostname === 'localhost' || hostname === '127.0.0.1') {
        return window.SERVER_IP || hostname;
    }
    return hostname;
}

// [구현 내용] 완성본 렌더링 캡처 및 QR 생성 엔진 (핵심 모듈)
async function generateQR() {
    const btnQr = document.getElementById('btnQr');
    const originalText = btnQr.innerHTML;
    try {
        // 로딩 스피너 UI 시각적 피드백 제공 및 중복 클릭 방지 (버튼 disabled)
        btnQr.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> 프레임 생성 중...';
        btnQr.disabled = true;
        
        // 1. html2canvas 라이브러리를 사용하여 DOM 구조 전체(이미지+CSS)를 캔버스(그림)로 변환합니다.
        // scale: 3 속성으로 해상도를 3배 뻥튀기하여 스마트폰에서 확대해도 깨지지 않게 고화질로 만듭니다.
        const frameElement = document.getElementById('userSelectedFrame');
        const canvas = await html2canvas(frameElement, { scale: 3, useCORS: true, backgroundColor: null });
        const stripDataUrl = canvas.toDataURL('image/jpeg', 0.95); // JPG 압축률 95%
        
        // 2. 그려낸 그림을 백엔드 서버(/save_strip)로 보내 파일로 저장하게 시킵니다.
        const response = await fetch('/save_strip', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ image: stripDataUrl })
        });
        const result = await response.json();
        
        // 3. 서버가 저장에 성공하면, 다운로드 가능한 절대경로 URL을 생성하여 QR코드를 그립니다.
        if (result.status === 'success') {
            const hostIp = getHostIp(); 
            const port = window.location.port ? ':' + window.location.port : '';
            const downloadUrl = `http://${hostIp}${port}${result.saved_file}`;
            const qrCanvas = document.getElementById('qrCanvas');
            
            document.querySelector('.qr-title').textContent = "SCAN ME";
            document.querySelector('.qr-desc').innerHTML = "스마트폰 카메라로 스캔하여<br>고화질 원본 사진을 다운로드하세요!";
            
            // QRious 라이브러리를 통해 Canvas에 QR코드 이미지를 매핑
            new QRious({ element: qrCanvas, value: downloadUrl, size: 250, background: '#ffffff', foreground: '#000000' });
            
            // 숨겨져 있던 모달 팝업창 표시
            document.getElementById('qrModal').style.display = 'flex';
        }
    } catch (error) {
        alert("QR코드 인화 엔진 렌더링 에러");
    } finally {
        // 통신이 끝나면 버튼 상태 원상복구
        btnQr.innerHTML = originalText;
        btnQr.disabled = false;
    }
}

function closeQrModal() { document.getElementById('qrModal').style.display = 'none'; }

// [구현 내용] 타임랩스 비디오용 QR 생성 로직
function saveVideo() {
    // 백엔드에서 미리 인코딩되어 세션에 URL이 저장된 비디오 경로를 가져옵니다.
    const savedVideoUrl = sessionStorage.getItem('savedVideoUrl');
    if (!savedVideoUrl) {
        alert("타임랩스 영상을 찾을 수 없습니다.");
        return;
    }
    
    // 비디오 다운로드용 절대경로 구성
    const hostIp = getHostIp(); 
    const port = window.location.port ? ':' + window.location.port : '';
    const downloadUrl = `http://${hostIp}${port}${savedVideoUrl}`;
    
    const qrCanvas = document.getElementById('qrCanvas');
    
    // 모달창 텍스트 컨텍스트 스위칭 (사진용 -> 영상용 설명글로 변경)
    document.querySelector('.qr-title').textContent = "TIMELAPSE QR";
    document.querySelector('.qr-desc').innerHTML = "스마트폰 카메라로 스캔하여<br>타임랩스 영상을 다운로드하세요!";
    
    // QRious 생성 및 매핑
    new QRious({ element: qrCanvas, value: downloadUrl, size: 250, background: '#ffffff', foreground: '#000000' });
    document.getElementById('qrModal').style.display = 'flex';
}