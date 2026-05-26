import os
import json
import time
import threading
import numpy as np
import cv2
from flask import Flask, render_template, Response, jsonify, request

import rclpy
from rclpy.node import Node
from std_msgs.msg import String, Bool
from sensor_msgs.msg import CompressedImage, Image
from rcl_interfaces.msg import Log
from cv_bridge import CvBridge

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

        self.latest_frame = None

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

    def trigger_estop(self):
        msg = String()
        msg.data = "STOP"
        self.pub_estop.publish(msg)
        add_log("SAFETY", "EMERGENCY STOP TRIGGERED", "")

ros_node = None

def ros_spin_thread():
    global ros_node
    rclpy.init(args=None)
    ros_node = DashboardNode()
    rclpy.spin(ros_node)
    ros_node.destroy_node()
    rclpy.shutdown()

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
    return jsonify(system_state)

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
    
    # Start Firebase Polling thread
    threading.Thread(target=fb_poll_thread, daemon=True).start()
    
    # Start Flask
    app.run(host='0.0.0.0', port=5001, debug=False, threaded=True)
