// csg@csg-com:~/doocut_ws/static/js/main.js
document.addEventListener('DOMContentLoaded', () => {
    // 🎵 BGM: 시작 화면
    sessionStorage.removeItem('bgm_track');
    sessionStorage.removeItem('bgm_time');
    let currentBGM = new Audio('/sound/bgm/intro.mp3');
    currentBGM.loop = true;
    currentBGM.play().catch(e => {
        document.body.addEventListener('click', () => currentBGM.play().catch(console.log), { once: true });
    });
    sessionStorage.setItem('bgm_track', 'bgm/intro.mp3');
    window.addEventListener('beforeunload', () => {
        if (currentBGM) sessionStorage.setItem('bgm_time', currentBGM.currentTime);
    });

    const startScreen = document.getElementById('startScreen');
    
    // 🎯 Firebase /start 및 /end 목적지 주소 파라미터 세팅
    const FIREBASE_START_URL = "https://rokey-coop2-default-rtdb.asia-southeast1.firebasedatabase.app/start.json";
    const FIREBASE_END_URL = "https://rokey-coop2-default-rtdb.asia-southeast1.firebasedatabase.app/end.json";
    const FIREBASE_VOICE_OK_URL = "https://rokey-coop2-default-rtdb.asia-southeast1.firebasedatabase.app/voice_ok.json";
    const FIREBASE_CONCEPT_URL = "https://rokey-coop2-default-rtdb.asia-southeast1.firebasedatabase.app/concept.json";
    const FIREBASE_TOOL_URL = "https://rokey-coop2-default-rtdb.asia-southeast1.firebasedatabase.app/tool.json";
    const FIREBASE_CAPTURE_URL = "https://rokey-coop2-default-rtdb.asia-southeast1.firebasedatabase.app/capture.json";

    // 1. [초기화 시퀀스] 첫 장에 진입하자마자 주요 플래그들을 동시에 초기화
    function initializeDatabaseFlags() {
        // /start 초기화
        fetch(FIREBASE_START_URL, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(false) });
        // /end 초기화
        fetch(FIREBASE_END_URL, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(false) });
        // /voice_ok 초기화
        fetch(FIREBASE_VOICE_OK_URL, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(false) });
        // /concept 초기화
        fetch(FIREBASE_CONCEPT_URL, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify("") });
        // /tool 초기화
        fetch(FIREBASE_TOOL_URL, { 
            method: 'PUT', 
            headers: { 'Content-Type': 'application/json' }, 
            body: JSON.stringify({
                "black": false,
                "crown": false,
                "gun": false,
                "hat": false,
                "pink": false,
                "wand": false
            }) 
        });
        // /capture 초기화
        fetch(FIREBASE_CAPTURE_URL, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(false) });
        console.log("💾 [Firebase RTDB] 시스템 기동 개시 -> /start, /end, /voice_ok, /concept, /tool, /capture 파라미터 초기화 완료.");
    }

    initializeDatabaseFlags();

    // 2. [클릭 터치 트리거] 시작 버튼 터치 시 /start만 true로 쏘아보내고 이동
    if (startScreen) {
        startScreen.addEventListener('click', async () => {
            console.log("⚡ [시작 트리거 포착] Firebase /start = true 전송 엔진 기동.");
            try {
                const response = await fetch(FIREBASE_START_URL, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(true) 
                });

                if (response.ok) {
                    console.log("✅ 시작 동기화 성공. voice.html로 라우팅합니다.");
                    window.location.href = '/voice';
                } else {
                    alert("데이터베이스 바인딩 에러 발생.");
                }
            } catch (error) {
                alert("네트워크 통신 오류가 감지되었습니다.");
            }
        });
    }
});