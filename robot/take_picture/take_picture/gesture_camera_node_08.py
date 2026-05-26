import math
import time
import numpy as np
import cv2
import mediapipe as mp
import sys
import os
import threading
from flask import Flask, Response
from flask_cors import CORS

sys.path.append(os.path.expanduser('~/cobot_ws/tonghap'))
try:
    from firebase_client import get_local_ip, update_node
except ImportError:
    pass

import rclpy
from rclpy.node import Node

app = Flask(__name__)
CORS(app)
latest_mjpeg_frame = None
latest_clean_mjpeg_frame = None

def generate_mjpeg():
    global latest_mjpeg_frame
    while True:
        if latest_mjpeg_frame is not None:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + latest_mjpeg_frame + b'\r\n')
        time.sleep(0.033)

def generate_clean_mjpeg():
    global latest_clean_mjpeg_frame
    while True:
        if latest_clean_mjpeg_frame is not None:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + latest_clean_mjpeg_frame + b'\r\n')
        time.sleep(0.033)

@app.route('/video_feed')
def video_feed():
    return Response(generate_mjpeg(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/clean_feed')
def clean_feed():
    return Response(generate_clean_mjpeg(), mimetype='multipart/x-mixed-replace; boundary=frame')

from sensor_msgs.msg import CompressedImage, Image
from std_msgs.msg import String, Bool
from cv_bridge import CvBridge

ROBOT_ID = "dsr01"
SAVE_DIR = "/home/jeyu/사진"

# 💡 UI 및 기능 상수
ICON_POSITIONS = {
    "UP":    (0.50, 0.15),
    "DOWN":  (0.50, 0.85),
    "LEFT":  (0.15, 0.50),
    "RIGHT": (0.85, 0.50),
}
HIT_RADIUS    = 0.12
DEBOUNCE_SEC  = 0.8
COOLDOWN_SEC  = 2.0     # 명령 발동 후 대기 시간

# 색상 프리셋
C_IDLE     = (70,  70,  70)
C_ACTIVE   = (0,  210, 165)
C_FIRED    = (255, 215,  40)
C_CURSOR   = (255, 255, 255)

# ==========================================
# 💡 손 모양 판별 함수들
# ==========================================
def is_thumbs_up(lm):
    return lm[4].y < lm[6].y and lm[4].y < lm[10].y

def is_index_only_extended(lm):
    index_up = lm[8].y < lm[6].y
    middle_down = lm[12].y > lm[10].y
    ring_down = lm[16].y > lm[14].y
    pinky_down = lm[20].y > lm[18].y
    return index_up and middle_down and ring_down and pinky_down

def is_open_hand(lm):
    index_up  = lm[8].y < lm[6].y
    middle_up = lm[12].y < lm[10].y
    ring_up   = lm[16].y < lm[14].y
    pinky_up  = lm[20].y < lm[18].y
    return index_up and middle_up and ring_up and pinky_up

def draw_icon(img, cx, cy, size, active, fired):
    col = C_FIRED if fired else (C_ACTIVE if active else C_IDLE)
    pts = np.array([[cx,cy-size],[cx+size,cy],[cx,cy+size],[cx-size,cy]], np.int32)
    overlay = img.copy()
    cv2.fillPoly(overlay, [pts], col)
    cv2.addWeighted(overlay, 0.4, img, 0.6, 0, img)
    cv2.polylines(img, [pts], True, col, 2 if (active or fired) else 1)

class CursorDetector:
    def __init__(self): self.last_fired = {}
    def update(self, ix, iy, cw, ch, now):
        hit_px = HIT_RADIUS * min(cw, ch)
        active = []
        for name, (rx, ry) in ICON_POSITIONS.items():
            if math.hypot(ix - int(rx * cw), iy - int(ry * ch)) < hit_px:
                active.append(name)
        event = None
        for name in active:
            if (now - self.last_fired.get(name, 0.0)) > DEBOUNCE_SEC:
                event = name
                self.last_fired[name] = now
                break
        return event, active

class GestureCameraNode(Node):
    def __init__(self):
        super().__init__("gesture_camera_node", namespace=ROBOT_ID)
        
        # ROS 통신 설정 (Publisher)
        self.pub_image = self.create_publisher(CompressedImage, f"/{ROBOT_ID}/gesture_view/compressed", 10)
        self.pub_cmd = self.create_publisher(String, f"/{ROBOT_ID}/gesture_cmd", 10)
        self.bridge = CvBridge()
        
        # 💡 [핵심 1] Realsense ROS 노드의 토픽 구독 (압축 컬러 + 원본 깊이)
        # QoS: 정수 depth=10 → RELIABLE. sensor_data(BEST_EFFORT)는 매칭은 되지만
        # 실제 수신이 안 되는 케이스가 humble에서 자주 발생해 RELIABLE로 고정.
        # message_filters 동기화는 RealSense color/depth timestamp 불일치로 매칭 실패가 잦아
        # 제거하고, depth는 latest 캐시 + color 콜백 단일 트리거로 변경.
        self.latest_depth_msg = None
        self.create_subscription(
            Image,
            '/camera/camera/aligned_depth_to_color/image_raw',
            self._depth_cb,
            10,
        )
        self.create_subscription(
            CompressedImage,
            '/camera/camera/color/image_raw/compressed',
            self._color_cb,
            10,
        )
        
        # 작업 완료 신호 구독
        self.task_completed = False
        self.task_sub = self.create_subscription(Bool, f"/{ROBOT_ID}/task_complete", self.task_callback, 10)
        
        # 변수 초기화
        self.mp_hands = mp.solutions.hands
        self.mp_draw = mp.solutions.drawing_utils
        self.hands = self.mp_hands.Hands(max_num_hands=1, min_detection_confidence=0.7)
        self.mode = "IDLE"
        self.global_cooldown = 0.0
        self.cursor_det = CursorDetector()
        self.fired_dir = ""
        self.fired_until = 0.0
        self.thumbs_up_active = False
        self.is_processing = False

        try:
            ip = get_local_ip()
            update_node("/robot_ip.json", ip)
            self.get_logger().info(f"🌐 Firebase에 로봇 IP({ip}) 등록 완료")
            update_node("/capture.json", False)
        except Exception as e:
            self.get_logger().error(f"Firebase 초기화 에러: {e}")
        
        self.get_logger().info("✅ 제스처 대기 모드 시작 - 로봇 작업이 끝날 때까지 대기합니다...")

    def task_callback(self, msg):
        if msg.data and not self.task_completed:
            self.task_completed = True
            self.get_logger().info("🚀 작업 완료 신호 수신! 제스처 카메라 분석을 시작합니다.")

    def _depth_cb(self, msg: Image):
        self.latest_depth_msg = msg

    def _color_cb(self, color_msg: CompressedImage):
        if self.latest_depth_msg is None:
            return
        self.camera_callback(color_msg, self.latest_depth_msg)

    def camera_callback(self, color_msg, depth_msg):
        # 로봇 작업이 안 끝났으면 카메라는 켜져 있어도 분석하지 않음
        if not self.task_completed:
            return
            
        # 💡 [최적화] 이전 프레임 처리 중이면 현재 밀려온 프레임은 버림 (Latency 누적 방지)
        if self.is_processing:
            return
        self.is_processing = True

        now = time.time()
        
        # 💡 [핵심 3] CompressedImage(압축 바이트 데이터)를 OpenCV 이미지(BGR)로 해독
        np_arr = np.frombuffer(color_msg.data, np.uint8)
        frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        
        # 깊이 이미지는 거리 데이터를 살리기 위해 16비트(16UC1) 원본으로 변환
        depth_frame = self.bridge.imgmsg_to_cv2(depth_msg, desired_encoding='16UC1')
        
        # 미러링을 위한 좌우 반전
        frame = cv2.flip(frame, 1)
        depth_frame = cv2.flip(depth_frame, 1)
        save_frame = frame.copy()
        
        ch, cw = frame.shape[:2]
        result = self.hands.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        
        command_to_send = None
        active_icons = []

        if result.multi_hand_landmarks:
            self.mp_draw.draw_landmarks(frame, result.multi_hand_landmarks[0], self.mp_hands.HAND_CONNECTIONS)
            lm = result.multi_hand_landmarks[0].landmark
            
            if self.mode == "IDLE":
                # ① 따봉 모드 (Firebase 트리거)
                if is_thumbs_up(lm):
                    if not self.thumbs_up_active and now > self.global_cooldown:
                        self.thumbs_up_active = True
                        try:
                            update_node("/capture.json", True)
                            self.get_logger().info("👍 따봉 감지: /capture.json = true 전송")
                        except Exception:
                            pass
                        self.global_cooldown = now + 4.0
                
                # ② 커서 모드 (상하좌우)
                elif is_index_only_extended(lm):
                    # 따봉 상태 해제 (따봉이 아니므로)
                    if self.thumbs_up_active:
                        self.thumbs_up_active = False
                        try:
                            update_node("/capture.json", False)
                            self.get_logger().info("✋ 따봉 해제: /capture.json = false 전송 (연속 촬영 대기)")
                        except Exception:
                            pass

                    ix, iy = int(lm[8].x * cw), int(lm[8].y * ch)
                    cv2.circle(frame, (ix, iy), 18, C_CURSOR, 2)
                    cv2.circle(frame, (ix, iy), 3, C_CURSOR, -1)
                    
                    if now > self.global_cooldown:
                        ev, active_icons = self.cursor_det.update(ix, iy, cw, ch, now)
                        if ev: 
                            command_to_send = ev
                            self.fired_dir = ev
                            self.fired_until = now + 1.0
                            self.global_cooldown = now + COOLDOWN_SEC

                # ③ 줌 모드 (손바닥 활짝)
                elif is_open_hand(lm) and now > self.global_cooldown:
                    # 따봉 상태 해제
                    if self.thumbs_up_active:
                        self.thumbs_up_active = False
                        try:
                            update_node("/capture.json", False)
                            self.get_logger().info("✋ 따봉 해제: /capture.json = false 전송 (연속 촬영 대기)")
                        except Exception:
                            pass

                    ix, iy = int(lm[9].x * cw), int(lm[9].y * ch)
                    cv2.circle(frame, (ix, iy), 12, (255, 0, 255), -1)
                    
                    if 0 <= ix < cw and 0 <= iy < ch:
                        # 💡 [최적화] 주변 11x11 픽셀 탐색 (NumPy 슬라이싱으로 파이썬 이중 for문 제거)
                        y1, y2 = max(0, iy - 5), min(ch, iy + 6)
                        x1, x2 = max(0, ix - 5), min(cw, ix + 6)
                        roi = depth_frame[y1:y2, x1:x2]
                        
                        # 에러 픽셀(0) 제외하고 50mm(5cm) ~ 2000mm(2m) 사이 정상값만 필터링
                        valid_d_mm = roi[(roi > 50) & (roi < 2000)]
                        
                        # 평균 거리를 구해서 기존 줌 로직 적용
                        if valid_d_mm.size > 0:
                            dist = np.mean(valid_d_mm) / 1000.0
                            cv2.putText(frame, f"Dist: {dist:.2f}m", (ix - 50, iy - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 0, 255), 2)
                            
                            # 35cm ~ 45cm 목표 유지
                            if dist > 0.45: 
                                command_to_send = "ZOOM_IN"
                                self.fired_dir = "ZOOM_IN"
                                self.fired_until = now + 1.0
                                self.global_cooldown = now + COOLDOWN_SEC
                            elif dist < 0.35: 
                                command_to_send = "ZOOM_OUT"
                                self.fired_dir = "ZOOM_OUT"
                                self.fired_until = now + 1.0
                                self.global_cooldown = now + COOLDOWN_SEC

                # 아무 제스처도 아닐 때 따봉 상태 해제
                else:
                    if self.thumbs_up_active:
                        self.thumbs_up_active = False
                        try:
                            update_node("/capture.json", False)
                            self.get_logger().info("✋ 따봉 해제: /capture.json = false 전송 (연속 촬영 대기)")
                        except Exception:
                            pass


        if now > self.fired_until:
            self.fired_dir = ""

        # UI 그리기
        ic = min(cw, ch) // 10
        for name, (rx, ry) in ICON_POSITIONS.items():
            draw_icon(frame, int(rx*cw), int(ry*ch), ic, name in active_icons, name == self.fired_dir)

        if self.fired_dir and self.mode == "IDLE":
            label = self.fired_dir.replace("_", " ")
            tw = cv2.getTextSize(label, cv2.FONT_HERSHEY_DUPLEX, 1.2, 2)[0][0]
            cv2.putText(frame, label, (cw//2 - tw//2, ch//2 + 10), cv2.FONT_HERSHEY_DUPLEX, 1.2, C_FIRED, 2, cv2.LINE_AA)

        if command_to_send:
            self.pub_cmd.publish(String(data=command_to_send))

        # 💡 [최적화] 메인 스레드를 블로킹하여 렉을 유발하는 cv2.imshow 제거 (로컬 디버그 창 제거)
        # cv2.imshow("Gesture Camera", frame)
        # cv2.waitKey(1)
        
        # 다시 화면을 압축해서 발행 (모니터링 용도 - 화질 80으로 낮춰서 인코딩 속도 향상)
        msg = CompressedImage()
        msg.header.stamp = self.get_clock().now().to_msg()
        
        # 1. 키오스크 화면용 (UI 포함된 프레임)
        _, enc_ui = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        msg.data = enc_ui.tobytes()
        self.pub_image.publish(msg)
        
        # 2. 키오스크 백그라운드 타임랩스 녹화용 (UI 100% 제거된 깨끗한 프레임)
        _, enc_clean = cv2.imencode('.jpg', save_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        
        # Flask MJPEG 스트림용 전역 변수 업데이트
        global latest_mjpeg_frame, latest_clean_mjpeg_frame
        latest_mjpeg_frame = msg.data
        latest_clean_mjpeg_frame = enc_clean.tobytes()
        
        # 처리가 끝났으므로 다음 프레임을 받을 수 있도록 플래그 해제
        self.is_processing = False

def run_flask():
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

def main(args=None):
    rclpy.init(args=args)
    
    # Flask 서버 백그라운드 구동
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    node = GestureCameraNode()
    try:
        # 무한 루프 대신 rclpy.spin을 통해 콜백이 자동으로 작동하도록 대기
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info("사용자에 의해 중단되었습니다.")
    finally:
        node.destroy_node()
        cv2.destroyAllWindows()
        rclpy.shutdown()

if __name__ == "__main__":
    main()