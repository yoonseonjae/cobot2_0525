// static/js/main.js 전체 코드 (코드 리뷰 대비 상세 주석 포함)
document.addEventListener('DOMContentLoaded', () => {
    // [구현 내용] 전역 BGM(배경음악) 재생 로직
    // sessionStorage를 이용해 이전 BGM 상태를 초기화하고, 새로운 intro 음악을 할당합니다.
    sessionStorage.removeItem('bgm_track');
    sessionStorage.removeItem('bgm_time');
    let currentBGM = new Audio('/sound/bgm/intro.mp3');
    currentBGM.loop = true;
    
    // 브라우저의 오디오 자동 재생 정책(Autoplay block) 우회 처리:
    // 자동 재생이 브라우저 정책에 막혀 에러(DOMException)가 발생할 경우, 
    // 사용자가 화면의 어느 곳이든 클릭하는 순간(이벤트 리스너 once 옵션) 음악이 시작되도록 Fallback을 구현했습니다.
    currentBGM.play().catch(e => {
        document.body.addEventListener('click', () => currentBGM.play().catch(console.log), { once: true });
    });
    
    // 페이지 이동 시 BGM이 끊기지 않고 이어서 재생되게 하기 위해 트랙 정보와 시간을 세션 스토리지에 백업합니다.
    sessionStorage.setItem('bgm_track', 'bgm/intro.mp3');
    window.addEventListener('beforeunload', () => {
        if (currentBGM) sessionStorage.setItem('bgm_time', currentBGM.currentTime);
    });

    const startScreen = document.getElementById('startScreen');
    
    // [구현 내용] 로봇 통신을 위한 Firebase RTDB (실시간 데이터베이스) URL 목록
    // 각 URL은 로봇 내 ROS(Robot Operating System) 노드와 연동되어 비동기적으로 동작을 제어하는 상태 플래그 변수들입니다.
    const FIREBASE_START_URL = "https://rokey-coop2-default-rtdb.asia-southeast1.firebasedatabase.app/start.json";
    const FIREBASE_END_URL = "https://rokey-coop2-default-rtdb.asia-southeast1.firebasedatabase.app/end.json";
    const FIREBASE_VOICE_OK_URL = "https://rokey-coop2-default-rtdb.asia-southeast1.firebasedatabase.app/voice_ok.json";
    const FIREBASE_CONCEPT_URL = "https://rokey-coop2-default-rtdb.asia-southeast1.firebasedatabase.app/concept.json";
    const FIREBASE_TOOL_URL = "https://rokey-coop2-default-rtdb.asia-southeast1.firebasedatabase.app/tool.json";
    const FIREBASE_CAPTURE_URL = "https://rokey-coop2-default-rtdb.asia-southeast1.firebasedatabase.app/capture.json";

    // 1. [초기화 시퀀스] DB 상태 클렌징 (Cleansing)
    // 이전 사용자의 세션이 예기치 않게 종료되었을 가능성을 대비하여,
    // 첫 화면(index.html)이 로드되자마자 모든 로봇 제어 플래그를 원상 복구(False 또는 초기값)합니다.
    function initializeDatabaseFlags() {
        // 비동기 fetch API의 PUT 메서드를 사용하여 해당 경로의 JSON 데이터를 덮어씌웁니다.
        fetch(FIREBASE_START_URL, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(false) });
        fetch(FIREBASE_END_URL, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(false) });
        fetch(FIREBASE_VOICE_OK_URL, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(false) });
        fetch(FIREBASE_CONCEPT_URL, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify("") });
        fetch(FIREBASE_TOOL_URL, { 
            method: 'PUT', 
            headers: { 'Content-Type': 'application/json' }, 
            // 툴 객체는 여러 소품에 대한 Boolean 값을 가진 Dict 구조로 초기화합니다.
            body: JSON.stringify({
                "black": false, "crown": false, "gun": false,
                "hat": false, "pink": false, "wand": false
            }) 
        });
        fetch(FIREBASE_CAPTURE_URL, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(false) });
        console.log("💾 [Firebase RTDB] 시스템 기동 개시 -> 모든 파라미터 초기화 완료.");
    }

    initializeDatabaseFlags();

    // 2. [클릭 터치 트리거] 세션 시작 시그널 전송
    // 화면(startScreen)을 터치(클릭)하면 이벤트 리스너가 반응하여 시작 시퀀스를 가동합니다.
    if (startScreen) {
        startScreen.addEventListener('click', async () => {
            console.log("⚡ [시작 트리거 포착] Firebase /start = true 전송 엔진 기동.");
            try {
                // await을 통해 네트워크 요청이 완료될 때까지 대기합니다.
                // 로봇 쪽에서 이 /start 값을 감지하면 메인 루프를 돌기 시작합니다.
                const response = await fetch(FIREBASE_START_URL, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(true) 
                });

                if (response.ok) {
                    console.log("✅ 시작 동기화 성공. voice.html로 라우팅합니다.");
                    // 통신이 완전히 성공한 후에만 다음 페이지(음성 안내 화면)로 이동시킵니다.
                    window.location.href = '/voice';
                } else {
                    alert("데이터베이스 바인딩 에러 발생.");
                }
            } catch (error) {
                // Wi-Fi 단절 등의 네트워크 계층 문제 발생 시 에러 핸들링
                alert("네트워크 통신 오류가 감지되었습니다.");
            }
        });
    }
});