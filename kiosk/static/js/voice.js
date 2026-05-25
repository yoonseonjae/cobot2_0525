// csg@csg-com:~/doocut_ws/static/js/voice.js
document.addEventListener('DOMContentLoaded', () => {
    // 🎵 BGM: 이전 음악 이어 재생
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

    // 텍스트 엘리먼트 가져오기
    const typeText1 = document.getElementById('typeText1');
    const typeText2 = document.getElementById('typeText2');
    const voiceLoader = document.getElementById('voiceLoader');
    const voiceScreen = document.getElementById('voiceScreen');

    // 출력할 문장
    const text1 = "안녕하세요.";
    const text2 = "사진 컨셉을 말씀해주세요.";

    // 타이핑 속도 조절
    const typingSpeed = 100;
    const lineDelay = 800; // 첫 번째 문장 끝나고 두 번째 문장 시작 전 딜레이

    function typeWriter(element, text, speed) {
        return new Promise((resolve) => {
            let i = 0;
            element.innerHTML = '';

            function type() {
                if (i < text.length) {
                    element.innerHTML += text.charAt(i);
                    i++;
                    setTimeout(type, speed);
                } else {
                    resolve();
                }
            }
            type();
        });
    }

    async function startSequence() {
        // 1. 처음 페이지 로딩 후 약간 대기 (자연스러운 시작을 위해)
        await new Promise(r => setTimeout(r, 500));

        // 🎵 나레이션 재생 ("안녕하세요. 사진 컨셉을 말씀해주세요.")
        let narration = new Audio('/sound/vox/나레이션_01.mp3');
        narration.play().catch(e => console.log('Narration play error:', e));

        // 2. "안녕하세요." 타이핑
        await typeWriter(typeText1, text1, typingSpeed);

        // 커서 깜빡임 제거
        typeText1.classList.add('done');

        // 3. 딜레이
        await new Promise(r => setTimeout(r, lineDelay));

        // 4. "사진 컨셉을 말씀해주세요." 타이핑
        await typeWriter(typeText2, text2, typingSpeed);

        // 두 번째 문장 끝난 후 약간 대기
        await new Promise(r => setTimeout(r, 800));

        // 5. 로딩 (파동 애니메이션) 나타나기
        voiceLoader.style.opacity = '1';

        // 🎵 "듣고 있습니다" 나올 때 효과음 재생
        let voiceEffect = new Audio('/sound/soundeffect/voice_effect.mp3');
        voiceEffect.play().catch(e => console.log('Voice effect play error:', e));

        // 🎵 "듣고 있습니다" 상태에서 BGM 확 끄지 않고 소리만 줄이기
        if (currentBGM) {
            currentBGM.volume = 0.2; // 볼륨을 20%로 낮춤
        }

        // ----------------------------------------------------
        // [🎯 신규 추가: 실시간 컨셉 및 소품 수거 플래그 폴링 & UI 매핑]
        // ----------------------------------------------------

        let proceed = false;
        let activeConcept = null;

        const FIREBASE_VOICE_OK_URL = "https://rokey-coop2-default-rtdb.asia-southeast1.firebasedatabase.app/voice_ok.json";
        const FIREBASE_CONCEPT_URL = "https://rokey-coop2-default-rtdb.asia-southeast1.firebasedatabase.app/concept.json";
        const FIREBASE_TOOL_URL = "https://rokey-coop2-default-rtdb.asia-southeast1.firebasedatabase.app/tool.json";

        const CONCEPT_METADATA = {
            birthday: {
                title: "생일 파티 컨셉",
                engTitle: "Birthday Party",
                themeClass: "theme-birthday",
                bodyBgClass: "theme-birthday-bg",
                tools: [
                    { index: "hat", name: "생일 꼬깔모자", engName: "Party Hat", icon: "🎂" },
                    { index: "pink", name: "핑크 소품", engName: "Pink Prop", icon: "🌸" }
                ]
            },
            princess: {
                title: "공주 컨셉",
                engTitle: "Princess Theme",
                themeClass: "theme-princess",
                bodyBgClass: "theme-princess-bg",
                tools: [
                    { index: "crown", name: "티아라 왕관", engName: "Princess Crown", icon: "👑" },
                    { index: "wand", name: "마법 요술봉", engName: "Magic Wand", icon: "🪄" }
                ]
            },
            beach: {
                title: "해변 컨셉",
                engTitle: "Beach Theme",
                themeClass: "theme-beach",
                bodyBgClass: "theme-beach-bg",
                tools: [
                    { index: "black", name: "선글라스", engName: "Sunglasses", icon: "🕶️" },
                    { index: "gun", name: "장난감 물총", engName: "Water Gun", icon: "🔫" }
                ]
            }
        };

        const goToFrame = () => {
            if (proceed) return;
            proceed = true;
            window.location.href = '/frame';
        };

        // 소품 수거 상태(tool.json) 실시간 폴링 엔진
        const pollToolStatus = async () => {
            if (proceed || !activeConcept) return;
            try {
                const response = await fetch(FIREBASE_TOOL_URL);
                const toolData = await response.json();
                if (toolData) {
                    const meta = CONCEPT_METADATA[activeConcept];
                    meta.tools.forEach(tool => {
                        const isReady = toolData[tool.index] === true;
                        const cardEl = document.getElementById(`tool-${tool.index}`);
                        const statusEl = document.getElementById(`status-${tool.index}`);
                        if (cardEl && isReady) {
                            if (!cardEl.classList.contains('ready')) {
                                cardEl.classList.add('ready');
                                if (statusEl) statusEl.textContent = "전달 완료";
                                console.log(`🎁 [소품 체크] ${tool.name} (index: ${tool.index}) 전달 완료 확인!`);

                                // 🎵 소품 전달 완료 시 ok 사운드 재생
                                let okEffect = new Audio('/sound/soundeffect/ok.mp3');
                                okEffect.play().catch(e => console.log('ok effect error:', e));
                            }
                        }
                    });
                }
            } catch (err) {
                console.error("Firebase 통신 에러 (tool):", err);
            }
            setTimeout(pollToolStatus, 500);
        };

        // 컨셉 감지(concept.json) 폴링 엔진
        const pollConcept = async () => {
            if (proceed) return;
            try {
                const response = await fetch(FIREBASE_CONCEPT_URL);
                const conceptVal = await response.json();

                // 유효한 컨셉이 입력되었고, 아직 처리되지 않은 경우
                if (conceptVal && CONCEPT_METADATA[conceptVal] && !activeConcept) {
                    activeConcept = conceptVal;
                    console.log(`🎤 [컨셉 감지 완료] 선택된 컨셉: ${conceptVal}`);

                    // 🎵 컨셉 감지 시 새로운 음악 틀기
                    if (currentBGM) currentBGM.pause();
                    let conceptMusic = 'bgm/main.mp3';
                    currentBGM = new Audio(`/sound/${conceptMusic}`);
                    currentBGM.loop = true;
                    currentBGM.play().catch(e => console.log(e));
                    sessionStorage.setItem('bgm_track', conceptMusic);
                    sessionStorage.setItem('bgm_time', '0');

                    // 🎵 컨셉 화면 진입 시 go 사운드 후 나레이션 재생
                    let goEffect = new Audio('/sound/soundeffect/go.mp3');
                    goEffect.play().catch(e => console.log('go effect error:', e));

                    // go 사운드가 끝난 직후 나레이션_02 재생
                    goEffect.onended = () => {
                        let narration2 = new Audio('/sound/vox/나레이션_02.mp3');
                        narration2.play().catch(e => console.log('Narration 2 error:', e));
                    };

                    const meta = CONCEPT_METADATA[conceptVal];

                    // 1. 기존의 음성 인식 대기 UI 숨기기
                    voiceLoader.style.opacity = '0';
                    setTimeout(() => { voiceLoader.style.display = 'none'; }, 500);

                    document.querySelector('.voice-text-container').style.opacity = '0';
                    setTimeout(() => { document.querySelector('.voice-text-container').style.display = 'none'; }, 500);

                    // 2. 새로운 컨셉 및 소품 카드 UI 구성 및 노출
                    const container = document.getElementById('conceptDisplayContainer');
                    const titleEl = document.getElementById('conceptTitle');
                    const tagEl = document.getElementById('conceptTag');
                    const gridEl = document.getElementById('toolsGrid');

                    tagEl.textContent = meta.engTitle;
                    titleEl.textContent = meta.title;

                    gridEl.innerHTML = meta.tools.map(tool => `
                        <div class="tool-card" id="tool-${tool.index}">
                            <div class="tool-icon">${tool.icon}</div>
                            <div class="tool-info">
                                <span class="tool-name">${tool.name}</span>
                                <span class="tool-eng-name">${tool.engName}</span>
                                <span class="tool-status-badge" id="status-${tool.index}">로봇이 준비 중</span>
                            </div>
                        </div>
                    `).join('');

                    // 3. 컨셉 테마 및 배경 스타일 적용
                    voiceScreen.className = 'screen-overlay';
                    voiceScreen.classList.add(meta.themeClass);
                    document.body.className = '';
                    document.body.classList.add(meta.bodyBgClass);

                    // 컨셉 박스 노출
                    container.style.display = 'flex';

                    // 4. 소품 폴링 기동
                    pollToolStatus();
                }
            } catch (err) {
                console.error("Firebase 통신 에러 (concept):", err);
            }

            if (!activeConcept) {
                setTimeout(pollConcept, 500);
            }
        };

        // 전체 완료 및 촬영 진행 대기 폴링 엔진 (기존 voice_ok 연동 유지)
        const pollVoiceOk = async () => {
            if (proceed) return;
            try {
                const response = await fetch(FIREBASE_VOICE_OK_URL);
                const voiceOk = await response.json();
                if (voiceOk === true) {
                    console.log("🎤 [시퀀스 완료] voice_ok = true 감지. 다음 단계로 매끄럽게 전환합니다.");
                    goToFrame();
                    return;
                }
            } catch (err) {
                console.error("Firebase 통신 에러 (voice_ok):", err);
            }
            setTimeout(pollVoiceOk, 500);
        };

        // 폴링 엔진 전면 구동
        pollConcept();
        pollVoiceOk();
    }

    // 시퀀스 시작
    startSequence();
});
