// csg@csg-com:~/doocut_ws/static/js/camera.js (코드 리뷰 대비 상세 주석 포함)
document.addEventListener('DOMContentLoaded', () => {
    // 🎵 [구현 내용] BGM 재생: 컨셉 음악 이어 재생
    // 세션 스토리지에서 진행 중이던 BGM 트랙과 재생 시간을 가져와 끊김 없이 이어서 재생합니다.
    let bgmTrack = sessionStorage.getItem('bgm_track');
    let bgmTime = parseFloat(sessionStorage.getItem('bgm_time') || '0');
    let currentBGM = null;
    if (bgmTrack) {
        currentBGM = new Audio(`/sound/${bgmTrack}`);
        currentBGM.loop = true;
        currentBGM.currentTime = bgmTime;
        currentBGM.play().catch(e => console.log(e));
    }
    window.addEventListener('beforeunload', () => {
        if (currentBGM && !currentBGM.paused) sessionStorage.setItem('bgm_time', currentBGM.currentTime);
    });

    // 마우스 우클릭, 드래그 방지 (키오스크 환경 보안)
    document.addEventListener('contextmenu', e => e.preventDefault());
    document.addEventListener('dragstart', e => e.preventDefault());
    
    // 이전 촬영된 사진 배열 초기화
    sessionStorage.removeItem('capturedImages');

    const videoFeed = document.getElementById('realsenseFeed');
    const timerText = document.getElementById('timerText');
    const timelineBar = document.getElementById('timelineBar');
    const encodingOverlay = document.getElementById('encodingOverlay');

    // 🔊 [구현 내용] 사운드 객체 전역 프리로드(Preload)
    // 오디오 지연(딜레이) 현상을 막기 위해 로딩 시점에 Audio 객체를 메모리에 미리 올려둡니다.
    const PRELOADED_SOUNDS = {
        '3': new Audio('/static/sounds/robot_3.mp3'),
        '2': new Audio('/static/sounds/robot_2.mp3'),
        '1': new Audio('/static/sounds/robot_1.mp3'),
        'shutter': new Audio('/sound/soundeffect/shutter.mp3')
    };

    Object.values(PRELOADED_SOUNDS).forEach(audio => {
        audio.preload = 'auto';
        audio.load();
    });

    function playSound(name) {
        const audio = PRELOADED_SOUNDS[name];
        if (audio) {
            audio.currentTime = 0; // 재생 위치 초기화하여 연타 가능하도록 설정
            audio.play().catch(e => console.warn(`Audio '${name}' blocked/failed:`, e));
        }
    }

    // 🎯 [구현 내용] 로봇 PC 동적 IP 연동 아키텍처
    // Firebase에서 로봇 PC가 등록해둔 IP를 가져와 비디오 스트리밍을 직접 연결합니다.
    const FIREBASE_ROBOT_IP_URL = "https://rokey-coop2-default-rtdb.asia-southeast1.firebasedatabase.app/robot_ip.json";
    let streamUrl = "";

    let timeLeft = 40;
    let timerInterval = null;
    let mediaRecorder = null;
    let recordedChunks = [];
    let isRecording = false;

    // [구현 내용] 백그라운드 녹화용 숨김 Canvas
    // 파이어폭스 환경에서 captureStream() 버그(첫 프레임 정지)를 우회하기 위해, UI(타이머 등)가 없는 깨끗한 화면만 
    // 그려낼 투명 캔버스를 DOM에 추가해둡니다.
    const recordCanvas = document.createElement('canvas');
    recordCanvas.style.position = 'absolute';
    recordCanvas.style.opacity = '0';
    recordCanvas.style.pointerEvents = 'none';
    document.body.appendChild(recordCanvas);
    const ctx = recordCanvas.getContext('2d', { willReadFrequently: true });

    async function startMJPEGDecoder() {
        try {
            // 1. Firebase에서 최신 로봇 PC IP 가져오기
            let remoteIp = "192.168.10.68"; // Fallback IP
            try {
                const ipRes = await fetch(FIREBASE_ROBOT_IP_URL);
                const fetchedIp = await ipRes.json();
                if (fetchedIp && typeof fetchedIp === 'string') {
                    remoteIp = fetchedIp;
                    console.log("🌐 [Firebase IP 동기화] 로봇 PC IP 수신 완료:", remoteIp);
                }
            } catch (err) {
                console.warn("⚠️ Firebase IP 수신 실패. 기본 IP를 사용합니다.", err);
            }

            // 🎯 화면 표시용 스트림(UI 포함 가능) 연결
            videoFeed.src = `http://${remoteIp}:5000/video_feed`;

            // 🎯 녹화 및 캡처용 깨끗한 원본 스트림 연결
            streamUrl = `http://${remoteIp}:5000/clean_feed`;

            // 2. [구현 내용] MJPEG 스트림 직접 파싱 및 캔버스 드로잉 엔진
            // fetch API로 무한 스트림을 받아와서 JPEG의 시작(FFD8)과 끝(FFD9) 바이트를 찾아내 
            // 실시간으로 캔버스에 프레임을 그려 넣습니다.
            const response = await fetch(streamUrl);
            if (!response.body) return;
            const reader = response.body.getReader();
            let buffer = new Uint8Array(0);

            while (true) {
                const { value, done } = await reader.read();
                if (done) break;

                let newBuffer = new Uint8Array(buffer.length + value.length);
                newBuffer.set(buffer);
                newBuffer.set(value, buffer.length);
                buffer = newBuffer;

                while (true) {
                    let start = -1; let end = -1;
                    // JPEG 바이너리 시그니처 검색
                    for (let i = 0; i < buffer.length - 1; i++) {
                        if (buffer[i] === 0xFF && buffer[i + 1] === 0xD8) { start = i; break; }
                    }
                    if (start !== -1) {
                        for (let i = start; i < buffer.length - 1; i++) {
                            if (buffer[i] === 0xFF && buffer[i + 1] === 0xD9) { end = i + 2; break; }
                        }
                    }

                    if (start !== -1 && end !== -1 && end > start) {
                        const jpegData = buffer.slice(start, end);
                        buffer = buffer.slice(end);

                        const blob = new Blob([jpegData], { type: 'image/jpeg' });
                        createImageBitmap(blob).then(bitmap => {
                            if (recordCanvas.width !== bitmap.width || recordCanvas.height !== bitmap.height) {
                                recordCanvas.width = bitmap.width; recordCanvas.height = bitmap.height;
                            }
                            ctx.drawImage(bitmap, 0, 0, recordCanvas.width, recordCanvas.height);
                        }).catch(e => console.log("프레임 파싱 에러 방지:", e));
                    } else {
                        // 메모리 릭(Leak) 방지를 위한 버퍼 청소
                        if (buffer.length > 5000000) buffer = buffer.slice(-1000000);
                        break;
                    }
                }
            }
        } catch (err) { console.error("MJPEG Stream Error:", err); }
    }

    startMJPEGDecoder();

    // [구현 내용] MediaRecorder API를 이용한 타임랩스 원본 화면 녹화
    function startScreenRecording() {
        console.log("🎥 [녹화 시스템] 녹화 시작!");
        recordedChunks = [];

        const feedWidth = videoFeed.videoWidth || 1920;
        const feedHeight = videoFeed.videoHeight || 1080;
        recordCanvas.width = feedWidth;
        recordCanvas.height = feedHeight;

        isRecording = true;

        // 투명 캔버스에서 초당 30프레임으로 화면을 스트리밍합니다.
        const stream = recordCanvas.captureStream(30);

        try {
            // 브라우저 호환성을 위해 webm 포맷으로 지정
            const options = { mimeType: 'video/webm' };
            mediaRecorder = new MediaRecorder(stream, options);

            // 데이터 조각이 떨어질 때마다 배열에 저장
            mediaRecorder.ondataavailable = (event) => {
                if (event.data && event.data.size > 0) {
                    recordedChunks.push(event.data);
                }
            };

            // 녹화가 종료되면 Blob 객체로 묶어 백엔드(Flask)로 전송
            mediaRecorder.onstop = async () => {
                // 데이터 손실을 막기 위해 500ms 대기 후 처리
                setTimeout(async () => {
                    const blob = new Blob(recordedChunks, { type: 'video/webm' });
                    if (blob.size > 0) {
                        await uploadVideoToBackend(blob);
                    }
                }, 500);
            };

            mediaRecorder.start(500); // 500ms마다 데이터 조각(chunk) 생성

        } catch (err) {
            console.error("❌ 레코더 초기화 에러:", err);
        }
    }

    async function uploadVideoToBackend(blob) {
        if (encodingOverlay) encodingOverlay.style.display = 'flex'; // 인코딩 UI 표시
        const formData = new FormData(); formData.append('video', blob, 'timelapse.webm');
        try {
            const response = await fetch('/save_video', { method: 'POST', body: formData });
            if (response.ok) {
                const result = await response.json();
                if (result.status === 'success') {
                    sessionStorage.setItem('savedVideoUrl', result.file);
                }
            }
            window.location.href = '/result';
        } catch (error) { window.location.href = '/result'; }
    }

    function finalizeSession() {
        if (isRecording && mediaRecorder && mediaRecorder.state !== 'inactive') {
            mediaRecorder.stop(); isRecording = false;
        } else { window.location.href = '/result'; }
    }

    // 🎯 [구현 내용] 4:5 비율 크롭 도우미 알고리즘
    // html2canvas의 object-fit 속성 미지원 문제를 해결하기 위해, 원본 이미지 정중앙을 4:5(0.8) 비율로 잘라내는 수동 연산 함수입니다.
    function getCropped4To5DataUrl(sourceCanvas) {
        const W = sourceCanvas.width;
        const H = sourceCanvas.height;
        const targetRatio = 0.8; // 4:5 비율

        let cropWidth, cropHeight, cropX, cropY;

        if (W / H > targetRatio) {
            cropHeight = H;
            cropWidth = H * targetRatio;
            cropX = (W - cropWidth) / 2;
            cropY = 0;
        } else {
            cropWidth = W;
            cropHeight = W / targetRatio;
            cropX = 0;
            cropY = (H - cropHeight) / 2;
        }

        const tempCanvas = document.createElement('canvas');
        tempCanvas.width = cropWidth;
        tempCanvas.height = cropHeight;
        const tempCtx = tempCanvas.getContext('2d');

        tempCtx.drawImage(sourceCanvas, cropX, cropY, cropWidth, cropHeight, 0, 0, cropWidth, cropHeight);
        return tempCanvas.toDataURL('image/jpeg', 0.95);
    }

    // 🎯 [구현 내용] 로봇 촬영 트리거 폴링(Polling) 로직
    // Firebase의 /capture.json 값을 200ms 주기로 계속 확인하다가 true로 바뀌면 촬영을 진행합니다.
    let captureCount = 0;
    const maxCaptures = 2; // 총 2장 촬영
    let isCapturing = false;
    let lastCaptureFlag = false;
    const FIREBASE_CAPTURE_URL = "https://rokey-coop2-default-rtdb.asia-southeast1.firebasedatabase.app/capture.json";

    async function pollCaptureCommand() {
        if (captureCount >= maxCaptures || !isRecording) return; 

        try {
            const response = await fetch(FIREBASE_CAPTURE_URL);
            const captureFlag = await response.json();

            // False -> True 로 바뀌는 엣지(Edge) 순간에만 감지
            if (captureFlag === true && lastCaptureFlag === false) {
                if (!isCapturing) {
                    executeCapture();
                }
            }
            lastCaptureFlag = captureFlag === true;
        } catch (err) {
            console.error("Firebase 통신 에러 (capture):", err);
        }

        setTimeout(pollCaptureCommand, 200);
    }

    // [구현 내용] 카운트다운 애니메이션 및 캡처 전처리
    function executeCapture() {
        isCapturing = true; // Mutex Lock: 촬영 시퀀스 중복 방지
        console.log(`📸 [${captureCount + 1}/${maxCaptures}] 3초 카운트다운 시작!`);

        let count = 3;

        // 팝핑되는 커다란 카운트다운 UI DOM 생성
        const countEl = document.createElement('div');
        countEl.style.position = 'fixed';
        countEl.style.top = '50%';
        countEl.style.left = '50%';
        countEl.style.transform = 'translate(-50%, -50%)';
        countEl.style.fontSize = '25rem';
        countEl.style.fontWeight = '800';
        countEl.style.color = '#DEFF9A';
        countEl.style.textShadow = '0 0 50px rgba(222, 255, 154, 0.4), 0 10px 30px rgba(0,0,0,0.8)';
        countEl.style.zIndex = '9998';
        countEl.style.fontFamily = "'Urbanist', sans-serif";
        countEl.style.pointerEvents = 'none';
        countEl.style.transition = 'transform 0.15s cubic-bezier(0.175, 0.885, 0.32, 1.275)';
        document.body.appendChild(countEl);

        const tick = () => {
            if (count > 0) {
                playSound(count.toString()); // 로봇 음성 사운드

                countEl.textContent = count;
                // 마이크로 애니메이션: 커졌다가 작아지는 효과
                countEl.style.transform = 'translate(-50%, -50%) scale(1.15)';
                setTimeout(() => {
                    countEl.style.transform = 'translate(-50%, -50%) scale(1)';
                }, 150);

                count--;
                setTimeout(tick, 1000);
            } else {
                document.body.removeChild(countEl);
                takePicture(); // 캡처 시작
            }
        };

        tick();
    }

    // [구현 내용] 실제 사진 캡처 및 필터 요청
    function takePicture() {
        playSound('shutter');

        // 하얀 화면 플래시 이펙트
        const flash = document.createElement('div');
        flash.style.position = 'fixed';
        flash.style.top = '0'; flash.style.left = '0';
        flash.style.width = '100vw'; flash.style.height = '100vh';
        flash.style.backgroundColor = 'white';
        flash.style.zIndex = '9999';
        flash.style.transition = 'opacity 0.4s ease-out';
        document.body.appendChild(flash);

        // 현재 캔버스(영상 프레임)를 4:5 비율로 잘라 Base64 데이터로 반환
        const dataUrl = getCropped4To5DataUrl(recordCanvas);

        setTimeout(() => { flash.style.opacity = '0'; }, 100);
        setTimeout(() => { document.body.removeChild(flash); }, 500);

        captureCount++;

        // 백엔드로 원본 캡처 이미지를 넘겨 OpenCV 뷰티 필터(피부 보정)를 적용받음
        fetch('/save_capture', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ image: dataUrl })
        }).then(res => res.json()).then(data => {
            console.log("✅ 뷰티 필터 적용 및 캡처 서버 저장 성공!");

            // 뷰티 필터가 적용된 이미지를 세션 스토리지에 누적 저장
            let savedImages = JSON.parse(sessionStorage.getItem('capturedImages')) || [];
            savedImages.push(data.filtered_image || dataUrl); // 서버 응답 없을 시 원본 보존
            sessionStorage.setItem('capturedImages', JSON.stringify(savedImages));

            // 총 2장이 찍혔으면 세션을 닫고 결과 페이지로 라우팅
            if (captureCount >= maxCaptures) {
                setTimeout(() => {
                    clearInterval(timerInterval);
                    finalizeSession();
                }, 1000);
            } else {
                setTimeout(() => { isCapturing = false; }, 1000);
            }
        }).catch(err => {
            console.error("❌ 캡처 서버 저장 실패:", err);
            let savedImages = JSON.parse(sessionStorage.getItem('capturedImages')) || [];
            savedImages.push(dataUrl);
            sessionStorage.setItem('capturedImages', JSON.stringify(savedImages));

            if (captureCount >= maxCaptures) {
                setTimeout(() => { clearInterval(timerInterval); finalizeSession(); }, 1000);
            } else {
                setTimeout(() => { isCapturing = false; }, 1000);
            }
        });
    }

    // [구현 내용] 타임라인 바 및 제한 시간 타이머 로직
    function startSessionTimer() {
        startScreenRecording();
        pollCaptureCommand(); // Firebase 지속 모니터링 시작
        timerInterval = setInterval(() => {
            timeLeft--;
            if (timerText) {
                timerText.classList.add('tick-active'); timerText.textContent = timeLeft;
                setTimeout(() => { timerText.classList.remove('tick-active'); }, 150);
            }
            if (timelineBar) { timelineBar.style.width = `${(timeLeft / 40) * 100}%`; }
            
            // 타임아웃 직전 시각적 경고(빨간색 점멸)
            if (timeLeft <= 5 && timerText) {
                timerText.style.color = "#ff4d4d";
                if (timelineBar) { timelineBar.style.background = "#ff4d4d"; timelineBar.style.boxShadow = "0 0 15px #ff4d4d"; }
            }
            if (timeLeft <= 0) { clearInterval(timerInterval); finalizeSession(); }
        }, 1000);
    }

    startSessionTimer();
});