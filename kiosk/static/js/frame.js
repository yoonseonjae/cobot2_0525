// csg@csg-com:~/doocut_ws/static/js/frame.js 전체 수정본
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

    const framePreview = document.getElementById('framePreview');
    const colorButtons = document.querySelectorAll('.color-picker-group .color-btn');
    const btnCustomBgTrigger = document.getElementById('btnCustomBgTrigger');
    const customBgInput = document.getElementById('customBgInput');

    // 🎯 세션 상태 관리를 위한 임시 변수 파라미터 셋업
    let selectedColorParam = 'pink'; // 초기 디폴트 파라미터
    let customBgDataUrlParam = 'none';

    // 1. 배경 색상 선택 및 프리뷰 클래스 매핑 시스템
    colorButtons.forEach(button => {
        button.addEventListener('click', (e) => {
            if (!e.target.classList.contains('custom-bg-btn')) {
                framePreview.style.backgroundImage = 'none';
                customBgDataUrlParam = 'none'; // 커스텀 이미지 상태 클리어
                if(customBgInput) customBgInput.value = ''; 
            }

            colorButtons.forEach(btn => btn.classList.remove('active'));
            e.target.classList.add('active');

            framePreview.className = 'frame-preview'; 
            const selectedColor = e.target.dataset.color;
            if (selectedColor) {
                framePreview.classList.add(selectedColor);
                selectedColorParam = selectedColor; // 🎯 선택한 색상 플래그 업데이트
            }
        });
    });

    // 2. 커스텀 이미지 업로드 스트림 로직
    if (btnCustomBgTrigger && customBgInput) {
        btnCustomBgTrigger.addEventListener('click', () => {
            customBgInput.click();
        });

        customBgInput.addEventListener('change', (e) => {
            const file = e.target.files[0]; 
            if (file) {
                const reader = new FileReader(); 
                reader.onload = (event) => {
                    framePreview.className = 'frame-preview'; 
                    framePreview.style.backgroundImage = `url('${event.target.result}')`;
                    
                    customBgDataUrlParam = event.target.result; // 🎯 커스텀 이미지 바이너리 주입
                    selectedColorParam = 'custom'; // 색상 모드는 커스텀으로 우회
                    
                    colorButtons.forEach(btn => btn.classList.remove('active'));
                    btnCustomBgTrigger.classList.add('active');
                };
                reader.readAsDataURL(file);
            }
        });
    }

    // 3. 네비게이션 액션 (다음 단계로 이동할 때 파라미터를 세션에 영구 각인)
    document.getElementById('btnNext').addEventListener('click', () => {
        sessionStorage.setItem('chosenFrameColor', selectedColorParam);
        sessionStorage.setItem('chosenCustomBg', customBgDataUrlParam);
        
        console.log("💾 프레임 디자인 설정 파라미터 세션 백업 완료:", selectedColorParam);
        window.location.href = '/camera'; 
    });

    // 4. 타이머 카운트다운 함수
    let time = 120; 
    const timerElement = document.getElementById('timer');
    
    const countdown = setInterval(() => {
        let min = parseInt(time / 60);
        let sec = time % 60;
        if(timerElement) {
            timerElement.textContent = `${min.toString().padStart(2, '0')}:${sec.toString().padStart(2, '0')}`;
        }
        
        if (time <= 0) {
            clearInterval(countdown);
            alert('시간이 초과되어 메인화면으로 이동합니다.');
            window.location.href = '/';
        }
        time--;
    }, 1000);
});