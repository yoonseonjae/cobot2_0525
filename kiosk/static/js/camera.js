// csg@csg-com:~/doocut_ws/static/js/camera.js
document.addEventListener('DOMContentLoaded', () => {
    // 🎵 BGM: 컨셉 음악 이어 재생
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

    document.addEventListener('contextmenu', e => e.preventDefault());
    document.addEventListener('dragstart', e => e.preventDefault());
    sessionStorage.removeItem('capturedImages');

    const videoFeed = document.getElementById('realsenseFeed');
    const timerText = document.getElementById('timerText');
    const timelineBar = document.getElementById('timelineBar');
    const encodingOverlay = document.getElementById('encodingOverlay');

    // 🔊 사운드 객체 미리 생성 및 로드 (첫 재생 시 지연 방지)
    const PRELOADED_SOUNDS = {
        '3': new Audio('/static/sounds/robot_3.mp3'),
        '2': new Audio('/static/sounds/robot_2.mp3'),
        '1': new Audio('/static/sounds/robot_1.mp3'),
        'shutter': new Audio('/sound/soundeffect/shutter.mp3')
    };

    // 브라우저가 가능하면 미리 다운로드하도록 설정
    Object.values(PRELOADED_SOUNDS).forEach(audio => {
        audio.preload = 'auto';
        audio.load();
    });

    function playSound(name) {
        const audio = PRELOADED_SOUNDS[name];
        if (audio) {
            audio.currentTime = 0; // 재생 위치 초기화
            audio.play().catch(e => console.warn(`Audio '${name}' blocked/failed:`, e));
        }
    }

    // 🎯 [NEW] Firebase에서 로봇 PC의 동적 IP를 가져오기 위한 URL
    const FIREBASE_ROBOT_IP_URL = "https://rokey-coop2-default-rtdb.asia-southeast1.firebasedatabase.app/robot_ip.json";
    let streamUrl = "";
    // Firefox의 MJPEG 캔버스 캡처 버그(첫 프레임 정지)를 우회하기 위해 직접 스트림을 파싱합니다.

    let timeLeft = 40;
    let timerInterval = null;
    let mediaRecorder = null;
    let recordedChunks = [];
    let isRecording = false;

    const recordCanvas = document.createElement('canvas');
    // Firefox에서 captureStream()이 정지되는 버그를 방지하기 위해 캔버스를 DOM에 추가하되 보이지 않게 처리
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

            // 🎯 [NEW] 화면 표시용(UI 포함) 스트림 직접 연결
            videoFeed.src = `http://${remoteIp}:5000/video_feed`;

            // 🎯 [NEW] 녹화 및 캡처용(UI 없음) 원본 스트림 파싱
            streamUrl = `http://${remoteIp}:5000/clean_feed`;

            // 2. 스트림 연결
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
                            // 화면 표시용 videoFeed 업데이트 로직은 삭제, recordCanvas에만 항상 최신 프레임을 그림
                            if (recordCanvas.width !== bitmap.width || recordCanvas.height !== bitmap.height) {
                                recordCanvas.width = bitmap.width; recordCanvas.height = bitmap.height;
                            }
                            ctx.drawImage(bitmap, 0, 0, recordCanvas.width, recordCanvas.height);
                        }).catch(e => console.log("프레임 파싱 에러 방지:", e));
                    } else {
                        if (buffer.length > 5000000) buffer = buffer.slice(-1000000);
                        break;
                    }
                }
            }
        } catch (err) { console.error("MJPEG Stream Error:", err); }
    }

    startMJPEGDecoder();

    // csg@csg-com:~/doocut_ws/static/js/camera.js 일부 수정
    function startScreenRecording() {
        console.log("🎥 [녹화 시스템] 녹화 시작!");

        // 🎯 [중요] 녹화 시작 전 배열 초기화 필수!
        recordedChunks = [];

        const feedWidth = videoFeed.videoWidth || 1920;
        const feedHeight = videoFeed.videoHeight || 1080;
        recordCanvas.width = feedWidth;
        recordCanvas.height = feedHeight;

        isRecording = true;

        const stream = recordCanvas.captureStream(30);

        try {
            // 브라우저 호환성을 위해 mimeType 지정 (코덱 지정 시 일부 브라우저에서 에러 발생할 수 있으므로 webm만 지정)
            const options = { mimeType: 'video/webm' };
            mediaRecorder = new MediaRecorder(stream, options);

            // 🎯 [핵심 추가] 데이터 조각이 생성될 때마다 배열에 차곡차곡 쌓아야 합니다!
            mediaRecorder.ondataavailable = (event) => {
                if (event.data && event.data.size > 0) {
                    recordedChunks.push(event.data);
                    console.log(`📡 녹화 조각 수신: ${event.data.size} bytes`);
                }
            };

            // camera.js 수정
            mediaRecorder.onstop = async () => {
                // 🎯 녹화 종료 직후 데이터를 확실하게 확보하기 위해 500ms 대기
                setTimeout(async () => {
                    const blob = new Blob(recordedChunks, { type: 'video/webm' });
                    console.log(`📦 최종 생성된 Blob 크기: ${blob.size} bytes`);
                    if (blob.size > 0) {
                        await uploadVideoToBackend(blob);
                    } else {
                        console.error("❌ 녹화된 데이터가 없습니다.");
                    }
                }, 500);
            };

            mediaRecorder.start(500); // 500ms마다 데이터 조각 생성하여 안전하게 저장

        } catch (err) {
            console.error("❌ 레코더 초기화 에러:", err);
        }
    }

    async function uploadVideoToBackend(blob) {
        if (encodingOverlay) encodingOverlay.style.display = 'flex';
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

    // 🎯 [NEW] 4:5 비율 크롭 도우미 함수 (html2canvas의 object-fit 미지원 버그 우회)
    function getCropped4To5DataUrl(sourceCanvas) {
        const W = sourceCanvas.width;
        const H = sourceCanvas.height;
        const targetRatio = 0.8; // 4:5

        let cropWidth, cropHeight, cropX, cropY;

        if (W / H > targetRatio) {
            // 원본이 4:5보다 가로로 넓은 경우 (일반적인 16:9 등)
            cropHeight = H;
            cropWidth = H * targetRatio;
            cropX = (W - cropWidth) / 2;
            cropY = 0;
        } else {
            // 원본이 4:5보다 세로로 긴 경우
            cropWidth = W;
            cropHeight = W / targetRatio;
            cropX = 0;
            cropY = (H - cropHeight) / 2;
        }

        const tempCanvas = document.createElement('canvas');
        tempCanvas.width = cropWidth;
        tempCanvas.height = cropHeight;
        const tempCtx = tempCanvas.getContext('2d');

        // 중앙 영역을 잘라내어 그리기
        tempCtx.drawImage(sourceCanvas, cropX, cropY, cropWidth, cropHeight, 0, 0, cropWidth, cropHeight);
        return tempCanvas.toDataURL('image/jpeg', 0.95);
    }

    // 🎯 [NEW] Firebase 실시간 /capture.json 폴링 및 촬영 로직
    let captureCount = 0;
    const maxCaptures = 2; // 총 2장 촬영
    let isCapturing = false;
    let lastCaptureFlag = false;
    const FIREBASE_CAPTURE_URL = "https://rokey-coop2-default-rtdb.asia-southeast1.firebasedatabase.app/capture.json";

    async function pollCaptureCommand() {
        if (captureCount >= maxCaptures || !isRecording) return; // 녹화 중지 또는 2장 촬영 완료 시 중단

        try {
            const response = await fetch(FIREBASE_CAPTURE_URL);
            const captureFlag = await response.json();

            // False -> True 로 바뀌는 순간 감지
            if (captureFlag === true && lastCaptureFlag === false) {
                if (!isCapturing) {
                    executeCapture();
                }
            }
            lastCaptureFlag = captureFlag === true;
        } catch (err) {
            console.error("Firebase 통신 에러 (capture):", err);
        }

        setTimeout(pollCaptureCommand, 200); // 200ms 단위로 빠르게 체크
    }

    function executeCapture() {
        isCapturing = true; // 🎯 촬영 시퀀스 진입 즉시 락을 걸어 중복 신호 원천 차단
        console.log(`📸 [${captureCount + 1}/${maxCaptures}] 3초 카운트다운 시작!`);

        let count = 3;

        // 프리미엄 카운트다운 UI 생성
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
                // 🔊 로봇 음성 카운트다운 사운드 재생
                playSound(count.toString());

                countEl.textContent = count;
                // 팝핑 마이크로 애니메이션
                countEl.style.transform = 'translate(-50%, -50%) scale(1.15)';
                setTimeout(() => {
                    countEl.style.transform = 'translate(-50%, -50%) scale(1)';
                }, 150);

                count--;
                setTimeout(tick, 1000);
            } else {
                // 카운트다운 종료 후 캡처 진행
                document.body.removeChild(countEl);
                takePicture();
            }
        };

        tick();
    }

    function takePicture() {
        console.log(`📸 화면 캡처 찰칵!`);

        // 🔊 카메라 셔터(찰칵) 사운드 재생
        playSound('shutter');

        // 플래시 효과 UI
        const flash = document.createElement('div');
        flash.style.position = 'fixed';
        flash.style.top = '0'; flash.style.left = '0';
        flash.style.width = '100vw'; flash.style.height = '100vh';
        flash.style.backgroundColor = 'white';
        flash.style.zIndex = '9999';
        flash.style.transition = 'opacity 0.4s ease-out';
        document.body.appendChild(flash);

        // 현재 recordCanvas 화면 캡처 및 4:5 크롭 적용
        const dataUrl = getCropped4To5DataUrl(recordCanvas);

        // 플래시 서서히 끄기
        setTimeout(() => { flash.style.opacity = '0'; }, 100);
        setTimeout(() => { document.body.removeChild(flash); }, 500);

        captureCount++;

        // 2. 서버 백엔드로 전송하여 OpenCV 뷰티 필터를 적용받고 저장
        fetch('/save_capture', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ image: dataUrl })
        }).then(res => res.json()).then(data => {
            console.log("✅ 뷰티 필터 적용 및 캡처 서버 저장 성공!");

            // 1. 서버에서 반환받은 뽀샤시 처리된 이미지를 세션 스토리지에 저장 (last.js 출력용)
            let savedImages = JSON.parse(sessionStorage.getItem('capturedImages')) || [];
            savedImages.push(data.filtered_image || dataUrl); // 서버 에러 시 원본 보존
            sessionStorage.setItem('capturedImages', JSON.stringify(savedImages));

            // 만약 2장을 모두 찍었다면 녹화 종료 후 결과 페이지 이동
            if (captureCount >= maxCaptures) {
                console.log("🎉 2장 모두 촬영 완료. 1초 뒤 세션을 종료합니다.");
                setTimeout(() => {
                    clearInterval(timerInterval);
                    finalizeSession();
                }, 1000);
            } else {
                // 중복 촬영 방지 락 해제
                setTimeout(() => { isCapturing = false; }, 1000);
            }
        }).catch(err => {
            console.error("❌ 캡처 서버 저장 실패:", err);
            // 통신 에러 시 원본이라도 보존
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

    function startSessionTimer() {
        startScreenRecording();
        pollCaptureCommand(); // 🎯 촬영 대기 시작
        timerInterval = setInterval(() => {
            timeLeft--;
            if (timerText) {
                timerText.classList.add('tick-active'); timerText.textContent = timeLeft;
                setTimeout(() => { timerText.classList.remove('tick-active'); }, 150);
            }
            if (timelineBar) { timelineBar.style.width = `${(timeLeft / 40) * 100}%`; }
            if (timeLeft <= 5 && timerText) {
                timerText.style.color = "#ff4d4d";
                if (timelineBar) { timelineBar.style.background = "#ff4d4d"; timelineBar.style.boxShadow = "0 0 15px #ff4d4d"; }
            }
            if (timeLeft <= 0) { clearInterval(timerInterval); finalizeSession(); }
        }, 1000);
    }

    startSessionTimer();
});