# 인생두컷 — 협동로봇 포토부스

Doosan M0609 협동로봇과 음성/제스처 인식을 활용한 인터랙티브 포토부스 시스템.

```
사용자 음성 "공주 컨셉" → GPT-4o로 컨셉/소품 추출
   → 로봇이 해당 소품(왕관, 요술봉) 픽앤플레이스
   → 손동작(상하좌우/줌/따봉)으로 카메라 제어
   → 사진 2장 + 3배속 타임랩스 영상 생성
   → QR로 다운로드
```

---

## 시스템 구성

**2대의 PC가 같은 WiFi(또는 같은 공유기)에 연결되어 있고, 그 위에서 Firebase Realtime DB로 신호를 주고받습니다.**

| PC | 역할 | 폴더 |
|---|---|---|
| 키오스크 PC | 사용자 UI (Flask 웹앱) | `kiosk/` |
| 메인 제어 PC | ROS2 + 로봇 제어 + AI | `robot/` |

---

## 사전 설치 요구사항

### 공통
- Ubuntu 22.04
- Python 3.10+
- Git

### 키오스크 PC
- Firefox (키오스크 모드 자동 실행)
- FFmpeg (3배속 영상 인코딩)
- Python 패키지:
  ```bash
  pip install flask requests opencv-python numpy
  ```

### 메인 제어 PC
- ROS2 Humble
- Doosan robot ROS2 패키지 의존성
- Intel RealSense SDK 2 + ROS2 wrapper (`realsense2_camera`)
- Python 패키지:
  ```bash
  pip install ultralytics mediapipe scipy openai openai-whisper \
              pyaudio sounddevice tflite-runtime \
              flask flask-cors firebase-admin requests \
              python-dotenv opencv-python numpy
  ```

---

## 필수 파일 (git에 포함되지 않음)

`.gitignore` 처리되어 있어 클론 후 직접 준비해야 합니다.

| 파일 | 위치 | 설명 |
|---|---|---|
| `.env` | `robot/voice_processing/resource/.env` | `OPENAI_API_KEY` 키 입력 |
| `safety_best.pt` | `robot/safety_monitor/resource/safety_best.pt` | 안전감지용 YOLO 모델 (별도 학습/제공 필요) |

`.env` 준비:
```bash
cp robot/voice_processing/resource/.env.example robot/voice_processing/resource/.env
# 그다음 OPENAI_API_KEY 값 입력
```

---

## 설치 및 빌드

### 키오스크 PC
```bash
git clone https://github.com/yoonseonjae/cobot2_0525.git
cd cobot2_0525/kiosk
# Python 의존성은 위에서 pip install
```

### 메인 제어 PC
```bash
git clone https://github.com/yoonseonjae/cobot2_0525.git
cd cobot2_0525/robot
colcon build --symlink-install
source install/setup.bash
# 매 터미널마다 source 필요
```

---

## 실행 방법

### 키오스크 PC (터미널 1개)

```bash
cd cobot2_0525/kiosk
python3 app.py
```
→ Firefox가 자동으로 키오스크 모드(`http://localhost:5000`)로 띄움

---

### 메인 제어 PC (터미널 7개)

> **순서 중요**: ① → ② → ③ 까지 띄운 뒤 나머지 실행

먼저 모든 터미널에서:
```bash
cd cobot2_0525/robot
source install/setup.bash
```

| # | 명령 | 역할 |
|---|------|------|
| ① | `ros2 launch dsr_bringup2 dsr_bringup2_rviz.launch.py mode:=real host:=<로봇IP>` | Doosan 로봇 bringup (사용자 alias: `robodon`) |
| ② | `ros2 launch realsense2_camera rs_launch.py align_depth.enable:=true` | RealSense 카메라 (사용자 alias: `realsense`) |
| ③ | `ros2 run pick_and_place_voice robot_control_07` | 메인 픽앤플레이스 컨트롤러 |
| ④ | `ros2 run voice_processing get_keyword` | 음성→GPT-4o 키워드 추출 |
| ⑤ | `ros2 run object_detection object_detection` | YOLO + 깊이 → 3D 좌표 |
| ⑥ | `ros2 run take_picture robot_control_node_05` | 제스처 → 로봇 이동 |
| ⑦ | `ros2 run take_picture gesture_camera_node_08` | 제스처 인식 + 영상 스트리밍 (Flask :5000) |

### 안전감지 (선택, 별도 터미널 2개)
| 터미널 | 명령 | 역할 |
|---|---|---|
| 8 | `ros2 run safety_monitor safety_monitor` | 상단뷰 USB 웹캠 안전구역 감시 |
| 9 | `ros2 run safety_monitor safety_stream_server` | 대시보드용 MJPEG 스트림 (`:5001/safety_feed`) |

---

## 동작 흐름 (요약)

1. **키오스크 PC** Flask 서버(`:5000`) 띄우고 키오스크 화면 표시
2. 사용자가 시작 버튼 → Firebase `/start.json = true`
3. **메인 PC** `robot_control_07`이 `/start.json` 감지 → 관측 위치로 이동
4. 사용자가 "Hello Rokey, 공주 컨셉" 음성 → `get_keyword` 서비스로 컨셉/도구 추출
5. `object_detection`에 3D 좌표 요청 → 로봇이 소품 픽앤플레이스
6. 작업 완료 → `/dsr01/task_complete = true` → 제스처 모드 전환
7. **키오스크 PC** `camera.js`가 메인 PC Flask(`:5000/video_feed`)에서 영상 받음
8. 사용자 손동작(상하좌우 = 로봇 이동, 따봉 = 촬영)
9. 2컷 촬영 후 3배속 타임랩스 인코딩 → 결과 페이지 QR 다운로드

---

## 통신 흐름

```
Firebase RTDB (인터넷만 되면 OK — 작은 신호용)
├── /start, /end, /voice_ok, /concept, /tool, /capture, /robot_ip
│
키오스크 PC ←─ Firebase ─→ 메인 PC
     │                          │
     └─── 같은 WiFi 내 HTTP ────┘
        키오스크가 메인PC :5000/video_feed (MJPEG) 수신
        ※ 두 PC가 같은 공유기에 연결돼 있어야 함
```

---

## 폴더 구조

```
cobot2_0525/
├── kiosk/                      # 키오스크 PC
│   ├── app.py                  # Flask 서버
│   ├── make_sounds.py
│   ├── sound/                  # BGM, 효과음, 나레이션
│   ├── static/                 # CSS, JS, 이미지
│   ├── templates/              # HTML
│   ├── images/                 # 런타임 촬영 사진 저장
│   └── video/                  # 런타임 타임랩스 영상 저장
│
└── robot/                      # 메인 제어 PC (ROS2 워크스페이스)
    ├── firebase_client.py      # Firebase REST 공통 모듈
    ├── od_msg/                 # 커스텀 ROS2 서비스 정의
    ├── object_detection/       # YOLO + RealSense 3D 좌표
    ├── pick_and_place_voice/   # 픽앤플레이스 + Firebase 연동
    ├── voice_processing/       # STT + GPT-4o
    ├── take_picture/           # 제스처 카메라 + 로봇 이동
    ├── safety_monitor/         # 안전구역 감시
    └── doosan-robot2/          # Doosan 로봇 ROS2 패키지
```

---

## 알려진 이슈

### 키오스크 영상이 검은화면으로 나오는 경우

증상: 키오스크 PC에서 카메라 영상은 안 뜨는데 제스처 인식(따봉 → 자동촬영)은 동작.

원인: 메인 PC IP가 Firebase `/robot_ip.json`에 잘못 등록되었거나 갱신되지 않음.

진단:
1. 브라우저로 `https://rokey-coop2-default-rtdb.asia-southeast1.firebasedatabase.app/robot_ip.json` 열기
2. 메인 PC에서 `hostname -I` 실행 → 두 값 비교
3. 키오스크 브라우저에서 `http://{Firebase IP}:5000/video_feed` 직접 접속해서 영상 확인

자세한 분리 진단은 개발자 문의.
