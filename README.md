# 인생두컷 — 협동로봇 포토부스

Doosan M0609 협동로봇과 음성/제스처 인식을 활용한 인터랙티브 포토부스 시스템.

사용자 음성 "공주 컨셉" → GPT-4o로 컨셉/소품 추출
   → 로봇이 해당 소품(왕관, 요술봉) 픽앤플레이스
   → 손동작(상하좌우/줌/따봉)으로 카메라 제어
   → 사진 2장 + 3배속 타임랩스 영상 생성
   → QR로 다운로드

---

## 🛠 기술 스택

### 하드웨어
| 장비 | 역할 |
|---|---|
| **Doosan M0609** | 6축 협동로봇. 픽앤플레이스, 제스처 기반 카메라 추적, 외력 감지로 소품 전달 |
| **OnRobot RG2 그리퍼** | 소품 파지. Modbus TCP(192.168.1.1:502)로 제어 |
| **Intel RealSense D435i** | 컬러 + Depth 정합 영상. YOLO 검출 → 3D 좌표 변환, 제스처 줌 거리 계산 |
| **Logitech C270 (USB 웹캠)** | 상단뷰 안전 감시 카메라 (safety_monitor 입력) |

### 로봇 제어 / 미들웨어
* **ROS2 Humble**: 전체 노드 통신 (토픽 / 서비스 / 액션)
* **Doosan ROS2 패키지 (`doosan-robot2`)**: `dsr_bringup2`, `dsr_msgs2`, `DSR_ROBOT2` Python API
* **두산 DRL API**: `movej` / `movel` 동기 모션, `check_force_condition`으로 외력 기반 드롭 트리거, `MovePause` / `MoveResume` / `SetRobotControl(2|3)` 서비스로 안전정지·서보꺼짐 복구
* **realsense2_camera**: `/camera/camera/color/image_raw/compressed`, `/camera/camera/aligned_depth_to_color/image_raw` 토픽 발행

### AI / 비전
* **YOLOv8 (Ultralytics)**: 커스텀 가중치 운영 (`260519_best.pt` 소품 검출, `safety_best.pt` 안전 감시용 사람/로봇 세그멘테이션)
* **MediaPipe Hands**: 단일 손 21개 랜드마크. 따봉 / 검지만 펴기 / 손바닥 펴기 3종 제스처 분류
* **OpenAI GPT-4o & Whisper**: LangChain 기반 컨셉/소품 키워드 추출 및 한국어 STT
* **OpenWakeWord**: 커스텀 웨이크워드 인식 ("Hello Rokey")
* **OpenCV**: 이미지 뷰티 필터 적용 및 MJPEG 스트림 파싱

### 백엔드 & 프론트엔드
* **Python 3.10 / Flask / Firebase RTDB**: 키오스크 ↔ 로봇 PC 신호 동기화 및 영상 스트리밍
* **FFmpeg**: WebM 원본 → 3배속 H.264 MP4 타임랩스 인코딩
* **HTML5 / CSS3 / JS & Firefox Kiosk Mode**: 사용자 UI 및 MediaRecorder API 기반 백그라운드 녹화

---

## 🏗 시스템 아키텍처

본 시스템은 **2대의 PC가 같은 WiFi 공유기 망에 연결**되어 동작하며, 그 위에서 **Firebase Realtime Database가 두 PC를 느슨하게 동기화**하는 구조입니다. 로봇 하드웨어는 모두 로봇 제어 PC에 **유선(이더넷/USB)으로 직결**되어 있어, WiFi가 끊겨도 로봇 자체의 제어 안정성은 영향을 받지 않습니다.

### 네트워크 계층 (3-tier)
| 계층 | 매체 | 연결 대상 | 용도 |
|---|---|---|---|
| **외부 인터넷** | 인터넷 (HTTPS) | 모든 PC ↔ Firebase | 키오스크와 로봇 PC가 작은 신호(시작/종료/컨셉/도구/캡처 등)를 비동기로 주고받는 버스 |
| **WiFi LAN** | 같은 공유기 망 | 키오스크 PC ↔ 로봇 PC | 키오스크가 로봇 PC의 `:5000/video_feed`에서 MJPEG 영상 수신 및 대시보드 통신 |
| **유선 / USB** | 이더넷, USB | 로봇 제어 PC ↔ 하드웨어 | 로봇팔, RG2 그리퍼, 카메라 등 제어 하드웨어 직결 |

---

## 🧩 ROS2 노드 그래프 및 제어 구조

본 시스템은 `dsr01` 네임스페이스 아래에서 동작하며, 사이클은 크게 3단계로 흘러갑니다:
`Phase 1 (음성) → Phase 2 (픽앤플레이스) → Phase 3 (제스처 촬영)` (상시 동작: 안전 모니터링)

각 단계는 `/dsr01/task_complete` 토픽으로 다음 단계에 **로봇 제어권을 인계**합니다. 동시에 두 노드가 로봇 API를 호출하면 충돌하므로, 의도적으로 직렬화한 구조입니다.

### 메인 컨트롤러 내부 구조 (음성 단계 마더보드)
`pick_and_place_voice/robot_control_07.py`의 `voice_robot_control_node`는 본 시스템의 마더보드 역할을 합니다. 단일 노드 안에 4개의 동시 실행 워커가 돌며, `robot_phase` 딕셔너리를 통해 서로의 안전·복구 상태를 공유합니다:
* **메인 루프**: 음성 인식 → 소품 스캔 → 픽앤플레이스 → 제어권 인계 시나리오 실행
* **SafetyCmd 리스너**: `/dsr01/safety_cmd` 구독하여 PAUSE / RESUME / RESET_HOME 반영
* **Reset 감시**: 데몬 스레드로 대기하다가 `execute_reset_home()` 호출 (충돌 회피)
* **모션 실행기**: DSR_API (`movej`, `movel`, `check_force_condition`) 호출

### 제스처 단계 컨트롤러 (촬영 단계 마더보드)
`take_picture/robot_control_node_05.py`의 `gesture_robot_control_node`는 음성 단계가 끝난 뒤 제어권을 인계받는 두 번째 마더보드입니다.
* **대기 루프**: `task_completed` 플래그가 True가 될 때까지 DSR_API 접근 제한
* **상대 이동**: `gesture_cmd` 토픽 수신 시 `movel(rel_posx, ref=DR_BASE, mod=DR_MV_MOD_REL)`로 ±100mm 미세 이동
* **종료 처리**: Firebase `/end.json = true` 감지 시 JHOME_POS 복귀 후 종료

---

## 시스템 구성 및 실행 방법

*(이하 기존 README의 '사전 설치 요구사항', '설치 및 빌드', '실행 방법', '폴더 구조', '알려진 이슈' 내용 유지)*

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
- ROS2 Humble (Host PC)
- Doosan robot ROS2 패키지 의존성
- Intel RealSense SDK 2 + ROS2 wrapper (`realsense2_camera`)
- **Docker & Docker Compose** (객체 인식 AI 노드 격리용)
- ROS2 시스템 패키지 (Host PC용):
  ```bash
  sudo apt install ros-humble-cv-bridge \
                   ros-humble-realsense2-camera \
                   ros-humble-image-transport-plugins \
                   ros-humble-compressed-image-transport \
                   ros-humble-rmw-cyclonedds-cpp ros-humble-cyclonedds
  ```
- Python 패키지 (`developer_dashboard` 등 로컬 노드용):
  ```bash
  pip install mediapipe scipy openai openai-whisper \
              pyaudio sounddevice tflite-runtime \
              flask flask-cors firebase-admin requests \
              python-dotenv opencv-python numpy
  ```
*(주의: `ultralytics` 등 무거운 딥러닝 패키지는 의존성 충돌 방지를 위해 Docker 내부에서만 설치/실행합니다.)*

---

## 필수 파일

| 파일 | 위치 | 상태 | 설명 |
|---|---|---|---|
| `.env` | `robot/voice_processing/resource/.env` | git 제외 | `OPENAI_API_KEY` 입력 필요 |
| `260519_best.pt` | `robot/object_detection/resource/260519_best.pt` | git 포함 | object_detection YOLO 모델 |
| `safety_best.pt` | `robot/safety_monitor/resource/safety_best.pt` | git 포함 | 안전감지 YOLO 모델 |

`.env` 준비 (클론 후 1회):
```bash
cp robot/voice_processing/resource/.env.example robot/voice_processing/resource/.env
# OPENAI_API_KEY 값 입력
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

# 1. 로컬 환경 빌드
cd cobot2_0525/robot
colcon build --symlink-install
source install/setup.bash

# 2. 도커 환경(object_detection) 워크스페이스 분리 세팅
mkdir -p ~/ros2_ws/src
cp -r ~/cobot2_0525/robot/object_detection ~/ros2_ws/src/
cp -r ~/cobot2_0525/robot/od_msg ~/ros2_ws/src/
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

### 🐳 도커(Docker) 도입 배경
YOLOv8 기반의 `object_detection` 노드는 `ultralytics`, `numpy 2.x` 등 최신 딥러닝 라이브러리를 강제합니다. 이 라이브러리들을 로컬(Host PC)에 직접 설치할 경우, ROS2 Humble의 구버전 의존성(`matplotlib`, `cv_bridge`가 `numpy 1.x`를 요구하는 등)과 **심각한 버전 충돌**을 일으켜 카메라 작동 등 시스템 전체를 망가뜨리는 치명적인 버그가 발생합니다.
이를 해결하기 위해 가장 무거운 딥러닝 모듈인 **`object_detection` 노드만 도커 컨테이너로 완벽히 격리**하고, 나머지 가벼운 하드웨어 제어 노드들은 로컬에서 실행하는 **'하이브리드 구조'**를 채택했습니다.

---

### 메인 제어 PC (필수 터미널 7개 + 선택 2개)

> **순서 중요**: ① → ② → ③ 까지 띄운 뒤 나머지 실행

로컬 터미널(①~④, ⑥~⑧) 공통 사전 작업:
```bash
cd ~/cobot2_0525/robot
source install/setup.bash
```

#### 필수 (터미널 1~7)
| # | 환경 | 명령 | 역할 |
|---|------|------|------|
| ① | 로컬 | `ros2 launch dsr_bringup2 dsr_bringup2_rviz.launch.py mode:=real host:=<로봇IP>` | Doosan 로봇 bringup (alias: `roboton`) |
| ② | 로컬 | `ros2 launch realsense2_camera rs_launch.py align_depth.enable:=true` | RealSense 카메라 (alias: `realsense`) |
| ③ | 로컬 | `ros2 run pick_and_place_voice robot_control_07` | 메인 픽앤플레이스 컨트롤러 |
| ④ | 로컬 | `ros2 run voice_processing get_keyword` | 음성→GPT-4o 키워드 추출 |
| ⑤ | **도커** | *(아래 ⑤번 터미널 도커 전용 실행 가이드 참조)* | YOLO + 깊이 → 3D 좌표 |
| ⑥ | 로컬 | `ros2 run take_picture robot_control_node_05` | 제스처 → 로봇 이동 |
| ⑦ | 로컬 | `ros2 run take_picture gesture_camera_node_08` | 제스처 인식 + 영상 스트리밍 (Flask `:5000`) |

#### ⑤번 터미널: AI 컨테이너(도커) 전용 실행 가이드
도커용 ⑤번 터미널은 아래 명령어를 통해 기동하고 내부에서 셋업합니다.

```bash
# 1. Host PC에서 도커 기동 (X11 권한 허용 포함)
xhost +local:root
docker run -it --name object_detection_container --network host \
  -e DISPLAY=$DISPLAY \
  -e QT_X11_NO_MITSHM=1 \
  -e RMW_IMPLEMENTATION=rmw_cyclonedds_cpp \
  -e ROS_DOMAIN_ID=60 \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  -v /dev/video0:/dev/video0 \
  -v ~/ros2_ws:/home/ros2_ws \
  osrf/ros:humble-desktop bash

# 2. 도커 내부 진입 후 (최초 1회 수동 설치 및 빌드)
apt update && apt install -y python3-pip ros-humble-rmw-cyclonedds-cpp ros-humble-cyclonedds
pip3 install ultralytics opencv-python "numpy<2.0.0" "opencv-python==4.9.0.80"

cd /home/ros2_ws
colcon build
source install/setup.bash

# 3. 노드 실행
ros2 run object_detection object_detection
```

#### 선택 (터미널 8~9, 안전감지 + 개발자 대시보드)
| # | 명령 | 역할 |
|---|------|------|
| ⑧ | `ros2 run safety_monitor safety_monitor` | 상단뷰 USB 웹캠 + YOLO → `/safety_image` 토픽 발행 |
| ⑨ | `cd cobot2_0525/developer_dashboard && python3 app.py` | ROS 로그 / 상태 / `/safety_image` 영상 통합 대시보드 (`:5001`) |

> ※ `safety_stream_server`는 `developer_dashboard`로 통합되어 더 이상 실행하지 않습니다. 옛 명령(`ros2 run safety_monitor safety_stream_server`)을 같이 띄우면 포트 5001 충돌이 납니다.
>
> ※ ⑨ developer_dashboard는 ROS 환경이 source 되어 있어야 함 (`source /opt/ros/humble/setup.bash` + `source ~/cobot2_0525/robot/install/setup.bash`). ROS 빌드 환경과 같은 터미널에서 실행하는 게 가장 편합니다.

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
├── developer_dashboard/        # 개발자 대시보드 (Flask :5001, /safety_image 시각화 + ROS 로그)
│   ├── app.py
│   ├── templates/
│   └── static/
│
└── robot/                      # 메인 제어 PC (ROS2 워크스페이스)
    ├── firebase_client.py      # Firebase REST 공통 모듈
    ├── od_msg/                 # 커스텀 ROS2 서비스 정의
    ├── object_detection/       # YOLO + RealSense 3D 좌표
    ├── pick_and_place_voice/   # 픽앤플레이스 + Firebase 연동
    ├── voice_processing/       # STT + GPT-4o
    ├── take_picture/           # 제스처 카메라 + 로봇 이동
    ├── safety_monitor/         # 안전구역 감시 (YOLO → /safety_image 발행)
    └── doosan-robot2/          # Doosan 로봇 ROS2 패키지
```

---

## Git 제외 파일 목록 (.gitignore)

깃허브(GitHub) 원격 저장소에 올라가지 않고 로컬 머신에서만 유지되거나 런타임에 자동으로 생성되는 파일/폴더 경로입니다.

### 1. Kiosk (`kiosk/`)
- `kiosk/images/`: 런타임에 촬영된 캡처 원본 및 네컷 사진 결과물 보관
- `kiosk/video/`: 3배속 타임랩스 인코딩 영상(WebM, MP4) 보관
- `kiosk/firefox_profile/`: 미디어 자동 재생 권한 부여를 위해 런타임에 생성되는 Firefox 브라우저 임시 프로필
- `kiosk/static/images/`: 런타임에 생성/캐시되는 정적 이미지
- `kiosk/.vscode/`, `kiosk/__pycache__/`: IDE 환경 설정 및 파이썬 컴파일 캐시

### 2. Developer Dashboard (`developer_dashboard/`)
- `developer_dashboard/__pycache__/`: 파이썬 컴파일 캐시

### 3. Robot (`robot/`) 및 공통 시스템
- **`robot/voice_processing/resource/.env`**: OpenAI API Key 등 민감한 보안 인증 정보가 포함된 환경변수 파일 (보안상 제외)
- `robot/build/`, `robot/install/`, `robot/log/` (및 최상단 `build/`, `install/`, `log/`): ROS 2 `colcon build` 과정에서 생성되는 빌드 결과물 및 런타임 시스템 로그
- `robot/**/__pycache__/`: ROS 2 파이썬 패키지들(`doosan-robot2`, `object_detection`, `pick_and_place_voice`, `safety_monitor`, `take_picture`, `voice_processing` 등)의 컴파일 캐시

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
