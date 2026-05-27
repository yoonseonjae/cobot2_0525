# 로봇 시스템 통신 아키텍처 (ROS2 Communication Diagram)

제공해주신 레퍼런스 이미지를 바탕으로, 현재 프로젝트(인생두컷)의 전체 통신 아키텍처를 표현한 다이어그램입니다. 메인 컨트롤러인 `robot_control_07.py`와 `robot_control_node_05.py`가 2개의 핵심 마더보드(Coordinator) 역할을 수행하는 구조를 명확히 담았습니다.

```mermaid
flowchart LR
    %% 통신 방식 범례
    %% 주황색: Topic, 초록색: Service, 파란색: Action, 보라색: REST API
    classDef default fill:#f9f9f9,stroke:#333,stroke-width:1px;
    classDef coord fill:#e1f5fe,stroke:#0277bd,stroke-width:2px;

    subgraph VOICE["VOICE USER INTERFACE"]
        direction LR
        STT["STT\n(Mic Input)"] --> GPT["GPT-4o\n(LLM Logic)"]
    end

    subgraph VISION["VISION (REALSENSE & WEBCAM)"]
        direction TB
        RS_C["Color Stream"]
        RS_D["Depth Stream"]
        WEB_C["Top-view Stream"]
    end

    subgraph IMG_PROC["IMAGE PROCESSOR (AI)"]
        direction TB
        YOLO["YOLOv8 + Transform\n(Object 3D Coord)"]
        GES["Gesture Classifier\n(Direction/Capture)"]
        SAFE["Safety Monitor\n(Zone Detection)"]
    end

    subgraph CLOUD["CLOUD / DB"]
        direction TB
        FB["Firebase RTDB\n(State Sync)"]
    end

    subgraph CTRL["ROS2 CONTROLLER (MAIN)"]
        direction TB
        TC1["Task Coordinator 1\n[Pick & Place]\n(robot_control_07)"]:::coord
        TC2["Task Coordinator 2\n[Gesture Control]\n(robot_control_05)"]:::coord
        MVR["Mover Engine & Gripper Logic\n(DSR API Wrapper)"]
        STAT["System Status & Safety\n(State Machine)"]
        
        TC1 --> MVR
        TC2 --> MVR
        STAT --> TC1
        STAT --> TC2
    end

    subgraph HW["HARDWARE (ROBOT/GRIPPER)"]
        direction TB
        ARM["M0609 Robot Arm"]
        GRP["RG2 Gripper"]
    end

    %% 내부 연결 (비전 -> AI)
    RS_C --> YOLO
    RS_D --> YOLO
    RS_C --> GES
    WEB_C --> SAFE

    %% 컴포넌트 간 외부 통신 (라벨에 통신 타입 명시)
    GPT -- "User Command [REST API]" --> FB
    FB -- "State Trigger [REST API]" --> TC1
    
    YOLO -- "Target Coord [Service]" --> TC1
    GES -- "Direction Cmd [Topic]" --> TC2
    SAFE -- "Safety Alert [Topic]" --> STAT
    
    TC1 -- "Task Complete [Topic]" --> TC2
    
    MVR -- "Motion Plan [Action/Service]" --> ARM
    MVR -- "Gripper Cmd [Service]" --> GRP
    
    ARM -- "Robot Status [Topic]" --> STAT

    %% 스타일 적용 팁:
    %% - Topic: 주로 스트림성 데이터 (영상, 제스처, 상태)
    %% - Service: 즉각적인 요청/응답 (3D 좌표 계산, 그리퍼 제어)
    %% - REST API: 인터넷을 통한 상태 동기화 (Firebase)
```
