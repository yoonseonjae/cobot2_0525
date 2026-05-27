import os
import json
import time
import threading
from collections import deque
import numpy as np
import cv2
from flask import Flask, render_template, Response, jsonify, request

import rclpy
from rclpy.node import Node
from std_msgs.msg import String, Bool
from sensor_msgs.msg import CompressedImage, Image
from rcl_interfaces.msg import Log
from cv_bridge import CvBridge

try:
    from dsr_msgs2.srv import (
        MovePause, MoveResume, MoveStop,
        GetRobotState, SetRobotControl,
    )
    _DSR_SRV_OK = True
except Exception:
    _DSR_SRV_OK = False

# Doosan SetRobotControl 명령 상수 (문서 기준)
DSR_CTRL_RESET_SAFE_STOP = 2   # 노란불(SAFE_STOP) 리셋 → 즉시 STANDBY
DSR_CTRL_RESET_SAFE_OFF  = 3   # 서보꺼짐(SAFE_OFF) 리셋 → 서보 ON, 약 3초 소요

import requests

# Stage 정의 (순서 = 진행 순서)
STAGES = ["RECOGNIZE", "PICKUP", "CAPTURE", "COMPLETE"]
STAGE_LABELS = {
    "IDLE":      "대기",
    "RECOGNIZE": "인식",
    "PICKUP":    "픽업",
    "CAPTURE":   "촬영",
    "COMPLETE":  "완료",
}

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True

ROBOT_ID = "dsr01"
FIREBASE_BASE = "https://rokey-coop2-default-rtdb.asia-southeast1.firebasedatabase.app"

# ── Safety mode 임계값 ──
SAFETY_FRAME_WINDOW_SEC = 2.0
SAFETY_FRAME_THRESHOLD  = 10
RESUME_COUNTDOWN_SEC    = 5.0
ROBOT_STATE_POLL_SEC    = 0.5
DSR_STATE_STANDBY        = 1
DSR_STATE_SAFE_OFF       = 3
DSR_STATE_SAFE_STOP      = 5
DSR_STATE_EMERGENCY_STOP = 6
DSR_STATE_SAFE_STOP2     = 9
DSR_STATE_SAFE_OFF2      = 10
# 노란불 = 보호 정지 (소프트웨어 리셋으로 복구 가능)
COLLISION_SAFE_STOP_STATES = {DSR_STATE_SAFE_STOP, DSR_STATE_SAFE_STOP2}
# 빨간불 = 서보꺼짐/비상정지 (사람 개입 또는 서보 재기동 필요)
COLLISION_EMERGENCY_STATES = {DSR_STATE_SAFE_OFF, DSR_STATE_EMERGENCY_STOP, DSR_STATE_SAFE_OFF2}

# /safety_image 토픽 최신 프레임 (JPEG bytes)
_safety_lock = threading.Lock()
_latest_safety_jpeg: bytes | None = None

# Global state for dashboard
system_state = {
    "robot_status": "ONLINE",
    "db_status": "CONNECTING",
    "current_stage": "IDLE",
    "stage_label": STAGE_LABELS["IDLE"],
    "stages_order": STAGES,
    "stage_labels": STAGE_LABELS,
    "mission": {
        "scene": "-",
        "task": "-",
        "state": "-",
        "picked": 0,
    },
    "health": 100,
    "joints": {"j1": 0.0, "j2": 0.0, "j3": 0.0, "j4": 0.0, "j5": 0.0, "j6": 0.0},
    "logs": [],
    "rtdb": {}
}

# 사이클 내부에서 일시적으로 유지되는 상태
_cycle_flags = {
    "task_complete": False,   # /dsr01/task_complete 한 번이라도 수신했나
}

# ── Safety mode 상태머신 ──
safety_mode_state = {
    "mode": "NORMAL",         # NORMAL / SAFETY_PAUSE / EMERGENCY
    "source": None,           # VISION / COLLISION / BUTTON / EMERGENCY_STATE
    "countdown_end": None,
    "last_alert": "CLEAR",
    "last_robot_state": -1,
    "message": "",
}
_safety_lock_mode = threading.Lock()
_safety_frame_log: deque = deque()

def _fb_sync_safety_mode(mode: str, message: str):
    """Firebase /safety_mode.json에 모드 동기화 (키오스크 UI에 통보)."""
    def _do():
        try:
            requests.put(f"{FIREBASE_BASE}/safety_mode.json",
                         json={"mode": mode, "message": message}, timeout=2)
        except Exception:
            pass
    threading.Thread(target=_do, daemon=True).start()

def _set_safety_mode(mode: str, source, message: str = ""):
    """안전모드 전환 + 로봇/키오스크 통보. _safety_lock_mode를 잡은 상태에서 호출."""
    prev = safety_mode_state["mode"]
    safety_mode_state["mode"] = mode
    safety_mode_state["source"] = source
    safety_mode_state["message"] = message
    if mode == "NORMAL":
        safety_mode_state["countdown_end"] = None
    if prev != mode:
        add_log("SAFETY", f"{prev} → {mode} (source={source}) {message}", "INFO")
        if ros_node is not None:
            if mode == "NORMAL":
                ros_node.publish_safety_cmd("RESUME")
            else:
                ros_node.publish_safety_cmd("PAUSE")
        _fb_sync_safety_mode(mode, message)

def fb_get(url):
    try:
        r = requests.get(url, timeout=2)
        return r.json()
    except Exception:
        return None

def add_log(category, message, confidence=""):
    timestamp = time.strftime("[%H:%M:%S]")
    log_entry = {"time": timestamp, "category": category, "message": message, "confidence": confidence}
    system_state["logs"].insert(0, log_entry)
    # Keep only last 20 logs
    if len(system_state["logs"]) > 20:
        system_state["logs"].pop()

class DashboardNode(Node):
    def __init__(self):
        super().__init__('developer_dashboard_node')
        self.bridge = CvBridge()

        # safety_monitor가 발행하는 어노테이션 이미지(/safety_image) 구독
        # → /video_feed 엔드포인트에서 그대로 MJPEG으로 송출
        self.sub_safety_image = self.create_subscription(
            Image,
            '/safety_image',
            self.safety_image_callback,
            10,
        )

        # Subscriptions
        self.sub_gesture = self.create_subscription(
            CompressedImage,
            f'/{ROBOT_ID}/gesture_view/compressed',
            self.gesture_callback,
            10
        )
        self.sub_robot_state = self.create_subscription(
            String,
            f'/{ROBOT_ID}/current_stage',
            self.robot_state_callback,
            10
        )
        self.sub_gesture_cmd = self.create_subscription(
            String,
            f'/{ROBOT_ID}/gesture_cmd',
            self.gesture_cmd_callback,
            10
        )
        self.sub_rosout = self.create_subscription(
            Log,
            '/rosout',
            self.rosout_callback,
            100
        )
        # robot_control_07이 픽앤플레이스 끝나면 한 번 publish → CAPTURE 단계 전환 트리거
        self.sub_task_complete = self.create_subscription(
            Bool,
            f'/{ROBOT_ID}/task_complete',
            self.task_complete_callback,
            10,
        )

        # Publisher for Safety Control
        self.pub_estop = self.create_publisher(String, f'/{ROBOT_ID}/emergency_stop', 10)

        # Safety zone update publisher (safety_monitor가 /safety_zone_update 구독)
        self.pub_safety_zone = self.create_publisher(String, '/safety_zone_update', 10)

        # ── Safety mode subscriptions / publisher / Doosan service clients ─
        self.sub_safety_state = self.create_subscription(
            String, '/safety_state', self.safety_state_callback, 30)
        self.sub_safety_alert = self.create_subscription(
            String, '/safety_alert', self.safety_alert_callback, 10)
        self.pub_safety_cmd = self.create_publisher(
            String, f'/{ROBOT_ID}/safety_cmd', 10)

        self.cli_pause = self.cli_resume = self.cli_stop = None
        self.cli_state = self.cli_setctl = None
        if _DSR_SRV_OK:
            self.cli_pause  = self.create_client(MovePause,       f'/{ROBOT_ID}/motion/move_pause')
            self.cli_resume = self.create_client(MoveResume,      f'/{ROBOT_ID}/motion/move_resume')
            self.cli_stop   = self.create_client(MoveStop,        f'/{ROBOT_ID}/motion/move_stop')
            self.cli_state  = self.create_client(GetRobotState,   f'/{ROBOT_ID}/system/get_robot_state')
            # 문서 기준 정식 복구 서비스: 노란불/서보꺼짐을 실제로 리셋함
            self.cli_setctl = self.create_client(SetRobotControl, f'/{ROBOT_ID}/system/set_robot_control')

        self.latest_frame = None

    # ── Safety state handlers ──────────────────────────────────────────

    def safety_state_callback(self, msg: String):
        state = msg.data
        now = time.time()
        with _safety_lock_mode:
            _safety_frame_log.append((now, state))
            while _safety_frame_log and now - _safety_frame_log[0][0] > SAFETY_FRAME_WINDOW_SEC:
                _safety_frame_log.popleft()
            self._evaluate_safety_transitions()

    def safety_alert_callback(self, msg: String):
        with _safety_lock_mode:
            safety_mode_state["last_alert"] = msg.data

    def _evaluate_safety_transitions(self):
        mode = safety_mode_state["mode"]
        stop_n  = sum(1 for _, s in _safety_frame_log if s == "STOP")
        clear_n = sum(1 for _, s in _safety_frame_log if s == "CLEAR")
        if mode == "NORMAL":
            if stop_n >= SAFETY_FRAME_THRESHOLD:
                _set_safety_mode("SAFETY_PAUSE", "VISION",
                                 f"STOP {stop_n}/{SAFETY_FRAME_THRESHOLD}f in {SAFETY_FRAME_WINDOW_SEC}s")
                self._call_pause()
        elif mode == "SAFETY_PAUSE":
            if clear_n >= SAFETY_FRAME_THRESHOLD and safety_mode_state["countdown_end"] is None:
                safety_mode_state["countdown_end"] = time.time() + RESUME_COUNTDOWN_SEC
                add_log("SAFETY", f"CLEAR 안정화 → {int(RESUME_COUNTDOWN_SEC)}s 후 재개", "INFO")
            if stop_n >= SAFETY_FRAME_THRESHOLD and safety_mode_state["countdown_end"] is not None:
                safety_mode_state["countdown_end"] = None
                add_log("SAFETY", "재개 카운트다운 취소 (STOP 재감지)", "WARN")

    # ── Doosan service helpers ─────────────────────────────────────────

    def _call_pause(self):
        if self.cli_pause and self.cli_pause.wait_for_service(timeout_sec=0.2):
            self.cli_pause.call_async(MovePause.Request())

    def _call_resume(self):
        if self.cli_resume and self.cli_resume.wait_for_service(timeout_sec=0.2):
            self.cli_resume.call_async(MoveResume.Request())

    def _call_stop(self, mode_int: int = 0):
        if self.cli_stop and self.cli_stop.wait_for_service(timeout_sec=0.2):
            req = MoveStop.Request(); req.stop_mode = mode_int
            self.cli_stop.call_async(req)

    def _call_set_robot_control(self, value: int, timeout_sec: float = 5.0) -> bool:
        """
        SetRobotControl 동기 호출. 문서 기준:
          value=2 → CONTROL_RESET_SAFE_STOP (노란불 즉시 해제, 즉시 STANDBY)
          value=3 → CONTROL_RESET_SAFE_OFF  (서보 ON, 브레이크 해제음 후 ~3초)
        실패 시 False 반환.
        """
        if not self.cli_setctl:
            return False
        if not self.cli_setctl.wait_for_service(timeout_sec=1.0):
            add_log("SAFETY", "set_robot_control 서비스 없음", "ERROR")
            return False
        req = SetRobotControl.Request(); req.robot_control = value
        fut = self.cli_setctl.call_async(req)
        start = time.time()
        # 호출은 supervisor thread에서 하므로 spin은 ros_spin_thread가 담당
        # future가 끝날 때까지 폴링만 함
        while not fut.done():
            if time.time() - start > timeout_sec:
                add_log("SAFETY", f"set_robot_control({value}) 응답 지연", "ERROR")
                return False
            time.sleep(0.05)
        try:
            res = fut.result()
            return bool(res and res.success)
        except Exception as e:
            add_log("SAFETY", f"set_robot_control({value}) 실패: {e}", "ERROR")
            return False

    def publish_safety_cmd(self, cmd: str, payload: dict | None = None):
        msg = String()
        msg.data = json.dumps({"cmd": cmd, "payload": payload or {}})
        self.pub_safety_cmd.publish(msg)
        add_log("SAFETY", f"robot cmd: {cmd}", "INFO")

    def publish_safety_zone(self, polygon_px: list):
        """폴리곤 픽셀 좌표(소스 이미지 기준)를 safety_monitor에 전달."""
        msg = String()
        msg.data = json.dumps({'polygon': polygon_px})
        self.pub_safety_zone.publish(msg)
        add_log("SAFETY", f"Zone updated ({len(polygon_px)} pts)", "")

    def safety_image_callback(self, msg: Image):
        global _latest_safety_jpeg
        try:
            frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
            ok, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ok:
                with _safety_lock:
                    _latest_safety_jpeg = buf.tobytes()
        except Exception as e:
            self.get_logger().warn(f'/safety_image 변환 실패: {e}')

    def gesture_callback(self, msg):
        pass
        # We can extract logs from here if needed
        # add_log("GESTURE", "V-SIGN DETECTED", "94%")
        pass

    def robot_state_callback(self, msg):
        # /dsr01/current_stage 토픽이 실제 publish되면 stage_label에 직접 반영
        if system_state.get("current_stage") != msg.data:
            add_log("SYSTEM", f"Stage topic: {msg.data}")

    def gesture_cmd_callback(self, msg):
        add_log("GESTURE", f"CMD: {msg.data}", "99%")

    def task_complete_callback(self, msg: Bool):
        if msg.data:
            _cycle_flags["task_complete"] = True
            add_log("SYSTEM", "task_complete=True → CAPTURE stage", "INFO")
        
    def rosout_callback(self, msg):
        # Filter noisy nodes if necessary, or just accept all INFO and above
        if msg.level >= 20: # INFO, WARN, ERROR, FATAL
            # msg.name is node name, msg.msg is the log string
            level_str = "INFO"
            if msg.level == 30: level_str = "WARN"
            elif msg.level >= 40: level_str = "ERROR"
            
            # Map node names to UI categories for styling
            cat = "SYSTEM"
            name_lower = msg.name.lower()
            if "object_detection" in name_lower or "yolo" in name_lower: cat = "OBJECT"
            elif "gesture" in name_lower: cat = "GESTURE"
            elif "voice" in name_lower: cat = "VOICE"
            elif "kiosk" in name_lower: cat = "FIREBASE"
            
            # Skip some very noisy system logs if desired, but for now we show all
            add_log(cat, msg.msg, level_str)

    def trigger_estop(self, source: str = "BUTTON"):
        """대시보드 비상정지 버튼 → EMERGENCY. 재개 가능하도록 move_pause 사용."""
        msg = String()
        msg.data = "STOP"
        self.pub_estop.publish(msg)
        if source == "BUTTON":
            self._call_pause()
        with _safety_lock_mode:
            _set_safety_mode("EMERGENCY", source, "비상정지 활성화")
            safety_mode_state["countdown_end"] = None
        add_log("SAFETY", f"EMERGENCY STOP ({source})", "")

    def request_resume_from_emergency(self):
        with _safety_lock_mode:
            if safety_mode_state["mode"] != "EMERGENCY":
                return False
            safety_mode_state["countdown_end"] = time.time() + RESUME_COUNTDOWN_SEC
            add_log("SAFETY", f"EMERGENCY 재개 카운트다운 ({int(RESUME_COUNTDOWN_SEC)}s)", "INFO")
            return True

    def request_reset_home(self):
        """비상정지 → '처음으로'. 문서 절차에 따라 state별로 복구한 뒤 RESET_HOME publish."""
        with _safety_lock_mode:
            last_st = safety_mode_state["last_robot_state"]

        # state 6 = 비상정지 버튼이 물리적으로 눌려 있는 상태 → 소프트웨어 복구 불가
        if last_st == DSR_STATE_EMERGENCY_STOP:
            add_log("SAFETY", "비상정지 버튼(E-Stop)이 눌려 있어 복구 불가. 펜던트에서 버튼을 돌려 해제하세요.", "ERROR")
            return False

        # 복구 시퀀스 실행 (motion pause 상태도 함께 풀림)
        ok = self._recover_robot(last_st)
        if not ok:
            add_log("SAFETY", "로봇 복구 실패 — RESET_HOME 진행 중단", "ERROR")
            return False

        # 클라우드 리셋 + 로봇 측 RESET_HOME 시퀀스 발동
        reset_all_firebase_flags()
        self.publish_safety_cmd("RESET_HOME")
        with _safety_lock_mode:
            _set_safety_mode("NORMAL", None, "RESET_HOME 발행 - 로봇 복귀 진행")
        return True

    # ── 핵심: 두산 문서 절차에 따른 state별 복구 ─────────────────────────
    def _recover_robot(self, last_state: int) -> bool:
        """
        문서 'how to restart when yellow&red light' 절차:
          - state 5 (SAFE_STOP, 노란불) : drl_stop → SetRobotControl(2)
          - state 3 (SAFE_OFF, 빨간불 서보꺼짐) : drl_stop → SetRobotControl(3) (3초 대기)
          - state 6 (EMERGENCY_STOP)   : 사람이 펜던트 버튼 돌려 해제해야 → 호출 시점에 6→3 전이 후 다시 진입
          - 그 외 : motion만 paused 상태일 수 있으므로 MoveResume
        """
        # 1) 스크립트 정지 (외력/잔여 모션 안전 확보) — DR_QSTOP_STO = 0
        self._call_stop(0)
        time.sleep(0.3)

        if last_state == DSR_STATE_SAFE_STOP or last_state == DSR_STATE_SAFE_STOP2:
            # 외력 제거를 위해 잠시 대기 (비전 CLEAR 이후라면 사람이 이미 빠진 상태)
            time.sleep(1.0)
            ok = self._call_set_robot_control(DSR_CTRL_RESET_SAFE_STOP)
            add_log("SAFETY", f"SetRobotControl(2) SAFE_STOP 리셋 → {'OK' if ok else 'FAIL'}", "INFO" if ok else "ERROR")
            time.sleep(1.0)
            return ok and self._wait_for_standby(timeout=3.0)

        if last_state == DSR_STATE_SAFE_OFF or last_state == DSR_STATE_SAFE_OFF2:
            ok = self._call_set_robot_control(DSR_CTRL_RESET_SAFE_OFF)
            add_log("SAFETY", f"SetRobotControl(3) SAFE_OFF 리셋(서보ON) → {'OK' if ok else 'FAIL'}", "INFO" if ok else "ERROR")
            # 문서: 브레이크 해제음 후 약 3초 소요
            time.sleep(3.0)
            return ok and self._wait_for_standby(timeout=3.0)

        # 그 외(state 1/2 등): motion만 paused일 수 있으므로 resume만
        self._call_resume()
        return True

    def _wait_for_standby(self, timeout: float = 3.0) -> bool:
        """robot_state가 STANDBY(1)로 복귀할 때까지 active polling."""
        start = time.time()
        while time.time() - start < timeout:
            st = self._get_robot_state_sync()
            if st == DSR_STATE_STANDBY:
                with _safety_lock_mode:
                    safety_mode_state["last_robot_state"] = st
                return True
            time.sleep(0.2)
        return False

    def _get_robot_state_sync(self, timeout: float = 1.0) -> int:
        """get_robot_state를 동기 호출 (실패 시 -1)."""
        if not self.cli_state or not self.cli_state.wait_for_service(timeout_sec=0.2):
            return -1
        fut = self.cli_state.call_async(GetRobotState.Request())
        start = time.time()
        while not fut.done():
            if time.time() - start > timeout:
                return -1
            time.sleep(0.05)
        try:
            res = fut.result()
            return int(res.robot_state)
        except Exception:
            return -1

    # ── 주기 처리: get_robot_state 폴링 + 카운트다운 만료 ───────────────

    def poll_robot_state_and_countdown(self):
        if self.cli_state and self.cli_state.wait_for_service(timeout_sec=0.05):
            fut = self.cli_state.call_async(GetRobotState.Request())
            fut.add_done_callback(self._on_robot_state_resp)
        with _safety_lock_mode:
            end = safety_mode_state["countdown_end"]
            mode = safety_mode_state["mode"]
            last_st = safety_mode_state["last_robot_state"]
            src = safety_mode_state["source"]
        if end is None or time.time() < end:
            return

        # 카운트다운 만료 → 실제 복구 시퀀스 실행
        with _safety_lock_mode:
            safety_mode_state["countdown_end"] = None

        if mode == "SAFETY_PAUSE":
            # vision 기반 일시정지면 robot_state가 1일 수 있음 → motion resume만
            # 충돌 기반이면 state 5 → SetRobotControl(2)
            if self._recover_robot(last_st):
                with _safety_lock_mode:
                    _set_safety_mode("NORMAL", None, "안전정지 해제 완료")
            else:
                add_log("SAFETY", "안전정지 자동 복구 실패 — 상태 유지", "ERROR")
                with _safety_lock_mode:
                    safety_mode_state["countdown_end"] = None  # 카운트다운 다시 시작 안 함

        elif mode == "EMERGENCY":
            # 비상정지 버튼이 아직 눌려있으면 (state 6) 복구 불가
            if last_st == DSR_STATE_EMERGENCY_STOP:
                add_log("SAFETY", "펜던트의 비상정지 버튼이 눌려 있음 — 물리적 해제 필요", "ERROR")
                return
            if self._recover_robot(last_st):
                with _safety_lock_mode:
                    _set_safety_mode("NORMAL", None, "비상정지 해제 완료")
            else:
                add_log("SAFETY", "비상정지 자동 복구 실패 — 펜던트/하드웨어 확인 필요", "ERROR")

    def _on_robot_state_resp(self, future):
        try:
            res = future.result()
            if res is None:
                return
            st = int(res.robot_state)
        except Exception:
            return
        with _safety_lock_mode:
            safety_mode_state["last_robot_state"] = st
            mode = safety_mode_state["mode"]
            if mode == "NORMAL":
                if st in COLLISION_EMERGENCY_STATES:
                    # state 6 / 3 / 10 모두 EMERGENCY
                    label = {DSR_STATE_EMERGENCY_STOP: "EMERGENCY_STOP(빨간불·E-Stop)",
                             DSR_STATE_SAFE_OFF:      "SAFE_OFF(서보꺼짐)",
                             DSR_STATE_SAFE_OFF2:     "SAFE_OFF2(STO)"}.get(st, str(st))
                    _set_safety_mode("EMERGENCY", "EMERGENCY_STATE",
                                     f"robot_state={st} {label}")
                elif st in COLLISION_SAFE_STOP_STATES:
                    _set_safety_mode("SAFETY_PAUSE", "COLLISION",
                                     f"robot_state={st} SAFE_STOP(노란불·충돌감지)")

ros_node = None

def ros_spin_thread():
    global ros_node
    rclpy.init(args=None)
    ros_node = DashboardNode()
    rclpy.spin(ros_node)
    ros_node.destroy_node()
    rclpy.shutdown()

def safety_supervisor_thread():
    while True:
        try:
            if ros_node is not None:
                ros_node.poll_robot_state_and_countdown()
        except Exception:
            pass
        time.sleep(ROBOT_STATE_POLL_SEC)

def reset_all_firebase_flags():
    """kiosk와 동일한 클라우드 리셋."""
    base = FIREBASE_BASE
    payload = [
        (f"{base}/start.json",    False),
        (f"{base}/end.json",      False),
        (f"{base}/voice_ok.json", False),
        (f"{base}/concept.json",  ""),
        (f"{base}/capture.json",  False),
        (f"{base}/tool.json",     {"black": False, "crown": False, "gun": False,
                                   "hat": False, "pink": False, "wand": False}),
    ]
    ok = True
    for url, body in payload:
        try:
            requests.put(url, json=body, timeout=2)
        except Exception:
            ok = False
    _cycle_flags["task_complete"] = False
    add_log("SAFETY", f"클라우드 리셋 {'완료' if ok else '일부 실패'}", "INFO")
    return ok

def derive_stage(db_full: dict) -> str:
    """Firebase 상태 + task_complete 플래그로 4단계 stage 추론."""
    start_val = bool(db_full.get("start", False))
    end_val   = bool(db_full.get("end", False))
    concept   = db_full.get("concept", "") or ""
    voice_ok  = bool(db_full.get("voice_ok", False))

    if end_val:
        return "COMPLETE"
    if _cycle_flags["task_complete"]:
        return "CAPTURE"
    if voice_ok or concept:
        return "PICKUP"
    if start_val:
        return "RECOGNIZE"
    return "IDLE"


def fb_poll_thread():
    """Poll Firebase for events to show in AI Logs"""
    last_state = {
        "start": False, "end": False, "concept": "", "capture": False,
        "task": "", "r_state": "", "tools": {}, "stage": "IDLE",
    }
    while True:
        try:
            db_full = fb_get(f"{FIREBASE_BASE}/.json")
            if db_full is not None:
                system_state["db_status"] = "ONLINE"
                system_state["rtdb"] = db_full
                
                start_val = db_full.get("start", False)
                if start_val and not last_state["start"]:
                    add_log("FIREBASE", "User Triggered: START", "100%")
                last_state["start"] = start_val
                
                end_val = db_full.get("end", False)
                if end_val and not last_state["end"]:
                    add_log("FIREBASE", "User Triggered: END", "100%")
                last_state["end"] = end_val
                
                concept_val = db_full.get("concept", "")
                if concept_val and concept_val != last_state["concept"]:
                    add_log("FIREBASE", f"Concept Selected: {concept_val}", "100%")
                last_state["concept"] = concept_val
                
                capture_val = db_full.get("capture", False)
                if capture_val and not last_state["capture"]:
                    add_log("FIREBASE", "Capture Triggered", "100%")
                last_state["capture"] = capture_val
                
                # Check for Robot Status changes
                r_status = db_full.get("robot_status", {})
                current_task = r_status.get("current_task", "")
                if current_task and current_task != last_state["task"]:
                    add_log("SYSTEM", f"Task Changed: {current_task}", "INFO")
                last_state["task"] = current_task
                
                current_r_state = r_status.get("state", "")
                if current_r_state and current_r_state != last_state["r_state"]:
                    add_log("SYSTEM", f"Robot State: {current_r_state}", "INFO")
                last_state["r_state"] = current_r_state
                
                # Check for Prop/Tool changes
                tools = db_full.get("tool", {}) or {}
                for tool_name, is_picked in tools.items():
                    if is_picked and not last_state["tools"].get(tool_name, False):
                        add_log("OBJECT", f"Prop Delivered: {tool_name.upper()}", "100%")
                last_state["tools"] = tools

                # ── Stage 추론 + MISSION STATUS 실데이터 매핑 ──
                stage = derive_stage(db_full)
                if stage != last_state["stage"]:
                    add_log("SYSTEM", f"Stage: {last_state['stage']} → {stage}", "INFO")
                    last_state["stage"] = stage
                # 새 사이클 시작(=start가 false→true 또는 stage가 COMPLETE→다른값)되면 task_complete 플래그 리셋
                if (start_val and not end_val
                        and stage in ("IDLE", "RECOGNIZE")):
                    _cycle_flags["task_complete"] = False
                if not start_val and not end_val:
                    # 모든 플래그 false면 새 사이클 대기 상태 → 리셋
                    _cycle_flags["task_complete"] = False

                system_state["current_stage"] = stage
                system_state["stage_label"]   = STAGE_LABELS.get(stage, stage)

                # MISSION STATUS 매핑
                picked_count = sum(1 for v in tools.values() if v)
                if end_val:
                    mission_state = "DONE"
                elif start_val:
                    mission_state = "ACTIVE"
                else:
                    mission_state = "IDLE"
                system_state["mission"] = {
                    "scene":  concept_val or "-",
                    "task":   STAGE_LABELS.get(stage, "-"),
                    "state":  mission_state,
                    "picked": picked_count,
                }


        except Exception as e:
            system_state["db_status"] = "OFFLINE"
        time.sleep(1.0)

def generate_video_stream():
    """safety_monitor가 발행하는 /safety_image(YOLO bbox + 안전구역 오버레이)를 MJPEG으로 송출."""
    no_signal = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.putText(no_signal, "WAITING FOR /safety_image ...", (50, 240),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (100, 100, 100), 2)
    _, ns_buf = cv2.imencode('.jpg', no_signal)
    ns_bytes = ns_buf.tobytes()

    while True:
        with _safety_lock:
            frame_bytes = _latest_safety_jpeg if _latest_safety_jpeg else ns_bytes
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        time.sleep(0.033)  # ~30 fps

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/video_feed')
def video_feed():
    # cam 쿼리 파라미터는 하위 호환 위해 받지만 무시 (ROS /safety_image 토픽 단일 소스)
    return Response(generate_video_stream(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/telemetry')
def get_telemetry():
    with _safety_lock_mode:
        end = safety_mode_state["countdown_end"]
        remaining = max(0.0, end - time.time()) if end else 0.0
        sm = {
            "mode":      safety_mode_state["mode"],
            "source":    safety_mode_state["source"],
            "message":   safety_mode_state["message"],
            "countdown": round(remaining, 1),
            "last_alert":       safety_mode_state["last_alert"],
            "last_robot_state": safety_mode_state["last_robot_state"],
        }
    payload = dict(system_state)
    payload["safety_mode"] = sm
    return jsonify(payload)

@app.route('/api/safety/resume', methods=['POST'])
def safety_resume():
    if not ros_node:
        return jsonify({"ok": False, "error": "ROS node not running"}), 503
    return jsonify({"ok": ros_node.request_resume_from_emergency()})

@app.route('/api/safety/reset_home', methods=['POST'])
def safety_reset_home():
    if not ros_node:
        return jsonify({"ok": False, "error": "ROS node not running"}), 503
    return jsonify({"ok": ros_node.request_reset_home()})

@app.route('/api/logs/clear', methods=['POST'])
def clear_logs():
    system_state["logs"].clear()
    return jsonify({"ok": True})

@app.route('/api/estop', methods=['POST'])
def estop():
    if ros_node:
        ros_node.trigger_estop()
        return jsonify({"status": "E-STOP ACTIVATED"})
    return jsonify({"status": "ERROR", "message": "ROS Node not running"})

@app.route('/api/safety_zone', methods=['POST'])
def safety_zone():
    """
    Body: {"polygon": [[x1,y1], [x2,y2], ...]}  (소스 이미지 픽셀 좌표)
    빈 배열을 보내면 zone 해제.
    """
    if not ros_node:
        return jsonify({"ok": False, "error": "ROS node not running"}), 503
    try:
        data = request.get_json() or {}
        polygon = data.get('polygon', [])
        if polygon and len(polygon) < 3:
            return jsonify({"ok": False, "error": "polygon must have >= 3 points (or be empty)"}), 400
        # int 변환
        polygon = [[int(p[0]), int(p[1])] for p in polygon]
        ros_node.publish_safety_zone(polygon)
        return jsonify({"ok": True, "points": len(polygon)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

if __name__ == '__main__':
    # Start ROS2 thread
    threading.Thread(target=ros_spin_thread, daemon=True).start()

    # Wait briefly for ros_node init
    for _ in range(20):
        if ros_node is not None:
            break
        time.sleep(0.1)

    # Firebase polling
    threading.Thread(target=fb_poll_thread, daemon=True).start()

    # Safety supervisor (robot_state poll + countdown)
    threading.Thread(target=safety_supervisor_thread, daemon=True).start()

    # Start Flask
    app.run(host='0.0.0.0', port=5001, debug=False, threaded=True)
