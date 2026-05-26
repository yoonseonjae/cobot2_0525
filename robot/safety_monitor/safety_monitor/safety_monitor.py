#!/usr/bin/env python3
"""
safety_monitor.py  (YOLO)
"""

import os
import json
import time
import threading
import numpy as np
import cv2
from scipy.spatial.distance import cdist
from ultralytics import YOLO

import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from sensor_msgs.msg import Image
from cv_bridge import CvBridge
from ament_index_python.packages import get_package_share_directory

# ── 클래스 ID (safety_best.pt 기준) ──────────────────────────────────────────
CLS_HUMAN  = 6
CLS_ROBOT  = 7


# ── 기본 상수 ─────────────────────────────────────────────────────────────────
CAMERA_INDEX   = 0
WARN_DIST_PX   = 200
STOP_DIST_PX   = 10
CONF_THRESHOLD = 0.45
CONFIRM_FRAMES = 3
CLEAR_FRAMES   = 5
FPS_TARGET     = 15

_PKG_SHARE = get_package_share_directory('safety_monitor')
ZONE_FILE          = os.path.join(_PKG_SHARE, 'resource', 'safety_zone.json')
DEFAULT_MODEL_PATH = os.path.join(_PKG_SHARE, 'resource', 'safety_best.pt')

# ── 색상 (BGR) ────────────────────────────────────────────────────────────────
COLOR_SAFE      = (0,   255,  80)
COLOR_WARN      = (0,   200, 255)
COLOR_STOP      = (0,    60, 255)
COLOR_ROBOT     = (255, 180,   0)
COLOR_HUMAN     = (0,    80, 255)


class SafetyMonitor(Node):
    """YOLO 안전 감지 노드."""

    def __init__(self):
        super().__init__('safety_monitor')

        # ── ROS 파라미터 ──
        self.declare_parameter('camera_index',   CAMERA_INDEX)
        self.declare_parameter('model_path',     DEFAULT_MODEL_PATH)
        self.declare_parameter('warn_dist_px',   WARN_DIST_PX)
        self.declare_parameter('stop_dist_px',   STOP_DIST_PX)
        self.declare_parameter('conf_threshold', CONF_THRESHOLD)
        self.declare_parameter('fps',            FPS_TARGET)
        self.declare_parameter('zone_file',      ZONE_FILE)

        self.cam_idx    = self.get_parameter('camera_index').value
        self.model_path = self.get_parameter('model_path').value
        self.warn_dist  = self.get_parameter('warn_dist_px').value
        self.stop_dist  = self.get_parameter('stop_dist_px').value
        self.conf_thr   = self.get_parameter('conf_threshold').value
        self.fps        = self.get_parameter('fps').value
        self.zone_file  = self.get_parameter('zone_file').value

        # ── 퍼블리셔 / 구독 ──
        self.alert_pub = self.create_publisher(String, '/safety_alert', 10)
        self.image_pub = self.create_publisher(Image,  '/safety_image', 10)
        self.bridge    = CvBridge()
        self.zone_sub  = self.create_subscription(
            String, '/safety_zone_update', self._zone_update_cb, 10)

        # ── YOLO 모델 로드 ──
        self.get_logger().info(f"[SafetyMonitor] YOLO 모델 로드: {self.model_path}")
        try:
            self.model = YOLO(self.model_path)
            self.get_logger().info(
                f"[SafetyMonitor] YOLO 로드 완료 | 클래스: {self.model.names}")
        except Exception as e:
            self.get_logger().error(f"[SafetyMonitor] YOLO 로드 실패: {e}")
            self.model = None

        # ── 안전구역 폴리곤 ──
        self.zone_polygon = None
        self._load_zone()

        # ── 상태 추적 ──
        self.current_state   = "CLEAR"
        self._detect_count   = 0
        self._clear_count    = 0
        self._last_pub_state = ""
        self._last_distance  = -1.0
        self._last_mode      = "none"

        # ── 카메라 ──
        self.cap = cv2.VideoCapture(self.cam_idx)
        if not self.cap.isOpened():
            self.get_logger().error(
                f"[SafetyMonitor] 카메라 {self.cam_idx} 열기 실패")
        else:
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            self.get_logger().info(f"[SafetyMonitor] 카메라 {self.cam_idx} 오픈")

        # ── 캡처 스레드 (유일한 카메라 reader. zone 설정은 developer_dashboard에서) ──
        self._running = True
        self._thread  = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

        self.get_logger().info(
            f"[SafetyMonitor] 초기화 완료 | WARN<{self.warn_dist}px  STOP<{self.stop_dist}px")

    # ── Zone 로드 / 저장 ──────────────────────────────────────────────────────

    def _load_zone(self):
        if not os.path.exists(self.zone_file):
            return
        try:
            with open(self.zone_file, 'r') as f:
                data = json.load(f)
            pts = np.array(data['polygon'], dtype=np.int32)
            if len(pts) >= 3:
                self.zone_polygon = pts
                self.get_logger().info(
                    f"[SafetyMonitor] 안전구역 로드: {len(pts)}개 꼭짓점")
        except Exception as e:
            self.get_logger().warn(f"[SafetyMonitor] zone 로드 실패: {e}")

    def _save_zone(self):
        if self.zone_polygon is None:
            return
        try:
            os.makedirs(os.path.dirname(self.zone_file), exist_ok=True)
            with open(self.zone_file, 'w') as f:
                json.dump({'polygon': self.zone_polygon.tolist()}, f)
        except Exception as e:
            self.get_logger().warn(f"[SafetyMonitor] zone 저장 실패: {e}")

    def _zone_update_cb(self, msg: String):
        try:
            data = json.loads(msg.data)
            pts  = np.array(data['polygon'], dtype=np.int32)
            if len(pts) >= 3:
                self.zone_polygon = pts
                self._save_zone()
        except Exception as e:
            self.get_logger().warn(f"[SafetyMonitor] zone 파싱 실패: {e}")

    def _find_contours(self, mask_bin: np.ndarray):
        contours, _ = cv2.findContours(
            mask_bin, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        return contours

    # ── 캡처 루프 ─────────────────────────────────────────────────────────────

    def _capture_loop(self):
        interval = 1.0 / self.fps
        while self._running and rclpy.ok():
            t0 = time.time()
            try:
                if not self.cap.isOpened():
                    time.sleep(0.5)
                    continue
                ret, frame = self.cap.read()
                if not ret:
                    time.sleep(0.05)
                    continue

                annotated, state = self._process_frame(frame)
                self._update_state(state)

                try:
                    img_msg = self.bridge.cv2_to_imgmsg(annotated, encoding='bgr8')
                    self.image_pub.publish(img_msg)
                except Exception:
                    pass
            except Exception as e:
                # 한 프레임 처리 실패가 스레드 전체를 죽이지 않도록 방어
                self.get_logger().warn(f"[SafetyMonitor] frame loop error (continuing): {e}")
                time.sleep(0.1)

            elapsed = time.time() - t0
            if elapsed < interval:
                time.sleep(interval - elapsed)

    # ── 핵심: YOLO + MediaPipe 추론 ───────────────────────────────────────────

    def _process_frame(self, frame: np.ndarray):
        h, w      = frame.shape[:2]
        annotated = frame.copy()

        if self.model is None:
            cv2.putText(annotated, "MODEL NOT LOADED",
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
            return annotated, "CLEAR"

        # ── 구역 마스크 생성 ──
        mask_zone = None
        if self.zone_polygon is not None and len(self.zone_polygon) >= 3:
            mask_zone = np.zeros((h, w), dtype=np.uint8)
            cv2.fillPoly(mask_zone, [self.zone_polygon], 255)

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # [1] YOLO 추론 → human / robot 마스크 외곽선 추출
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        results   = self.model(frame, verbose=False, conf=self.conf_thr)[0]
        boxes_xy  = results.boxes.xyxy.cpu().numpy() if results.boxes  else []
        confs     = results.boxes.conf.cpu().numpy() if results.boxes  else []
        cls_list  = results.boxes.cls.cpu().numpy()  if results.boxes  else []
        seg_masks = results.masks.data.cpu().numpy() if results.masks is not None else []

        human_boxes    = []
        robot_boxes    = []
        robot_contours = []
        human_contours = []

        for i, (box, conf, cls) in enumerate(zip(boxes_xy, confs, cls_list)):
            cls_id = int(cls)
            x1, y1, x2, y2 = map(int, box)
            cx, cy = (x1+x2)//2, (y1+y2)//2

            ctrs = []
            if i < len(seg_masks):
                mask_r = cv2.resize(seg_masks[i], (w, h))
                mask_b = (mask_r > 0).astype(np.uint8) * 255
                ctrs   = self._find_contours(mask_b)

            if cls_id == CLS_HUMAN:
                human_boxes.append((cx, cy, x1, y1, x2, y2, float(conf)))
                human_contours.extend(ctrs)
            elif cls_id == CLS_ROBOT:
                robot_boxes.append((cx, cy, x1, y1, x2, y2))
                robot_contours.extend(ctrs)

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # [2] 구역 내 사람 판단
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        persons_in_zone = []

        if mask_zone is not None:
            for hb in human_boxes:
                if mask_zone[hb[1], hb[0]] == 255:
                    persons_in_zone.append(('yolo', hb))
        else:
            for hb in human_boxes:
                persons_in_zone.append(('yolo', hb))

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # [3] 로봇 ↔ 사람 최단 거리 (YOLO)
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        min_dist          = float('inf')
        closest_person_pt = None
        closest_robot_pt  = None
        dist_mode         = "none"

        robot_pts_arr = None
        if robot_contours:
            pts = np.array([pt[0] for c in robot_contours for pt in c])
            if len(pts) > 0:
                robot_pts_arr = pts

        if robot_pts_arr is not None:
            # YOLO human 외곽선 기반
            if human_contours:
                hp_arr = np.array([pt[0] for c in human_contours for pt in c],
                                   dtype=np.float32)
                rp_arr = robot_pts_arr.astype(np.float32)
                if len(hp_arr) > 0:
                    dists = cdist(hp_arr, rp_arr)
                    idx   = np.unravel_index(np.argmin(dists), dists.shape)
                    d     = float(dists[idx])
                    if d < min_dist:
                        min_dist          = d
                        closest_person_pt = tuple(map(int, hp_arr[idx[0]]))
                        closest_robot_pt  = tuple(map(int, rp_arr[idx[1]]))
                        dist_mode         = "yolo"

        self._last_distance = min_dist if min_dist != float('inf') else -1.0
        self._last_mode     = dist_mode

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # [4] 상태 결정
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        raw_state = "CLEAR"
        if persons_in_zone:
            raw_state = "STOP" if min_dist <= self.stop_dist else "WARN"
        elif min_dist != float('inf'):
            if min_dist <= self.stop_dist:
                raw_state = "STOP"
            elif min_dist <= self.warn_dist:
                raw_state = "WARN"

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # [5] 시각화
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        state_color = (COLOR_SAFE if raw_state == "CLEAR"
                       else COLOR_WARN if raw_state == "WARN"
                       else COLOR_STOP)

        if mask_zone is not None:
            if raw_state != "CLEAR":
                overlay = annotated.copy()
                fill_c  = (0,40,180) if raw_state == "STOP" else (0,80,120)
                cv2.fillPoly(overlay, [self.zone_polygon], fill_c)
                alpha = 0.4 if raw_state == "WARN" else 0.55
                annotated = cv2.addWeighted(overlay, alpha, annotated, 1-alpha, 0)
            cv2.polylines(annotated, [self.zone_polygon], True, state_color, 2)
        else:
            cv2.putText(annotated, "NO ZONE SET (press D)",
                        (10, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,200,255), 1)

        for c in robot_contours:
            cv2.drawContours(annotated, [c], -1, COLOR_ROBOT, 2)
        for rb in robot_boxes:
            cv2.putText(annotated, "robot", (rb[2], rb[3]-6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, COLOR_ROBOT, 2)

        for c in human_contours:
            cv2.drawContours(annotated, [c], -1, COLOR_HUMAN, 1)
        for hb in human_boxes:
            cx, cy, x1, y1, x2, y2, conf = hb
            cv2.rectangle(annotated, (x1,y1), (x2,y2), COLOR_HUMAN, 1)
            cv2.putText(annotated, f"human {conf:.2f}", (x1, y1-6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, COLOR_HUMAN, 2)

        if closest_person_pt and closest_robot_pt:
            d  = min_dist
            lc = (COLOR_STOP if d <= self.stop_dist
                  else COLOR_WARN if d <= self.warn_dist
                  else (200, 200, 200))
            cv2.line(annotated, closest_person_pt, closest_robot_pt, lc, 2)
            mid = ((closest_person_pt[0]+closest_robot_pt[0])//2,
                   (closest_person_pt[1]+closest_robot_pt[1])//2)
            cv2.putText(annotated, f"{int(d)}px [{dist_mode}]", mid,
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, lc, 1)

        # HUD
        cv2.rectangle(annotated, (0,0), (w,42), (0,0,0), -1)
        dist_str = f"{int(self._last_distance)}px" if self._last_distance >= 0 else "N/A"
        hud = (f"SAFETY: {raw_state}  |  in_zone={len(persons_in_zone)}  |  "
               f"dist={dist_str}[{dist_mode}]")
        cv2.putText(annotated, hud, (8,27),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.52, state_color, 2)
        cv2.putText(annotated,
                    f"WARN<{self.warn_dist}px  STOP<{self.stop_dist}px",
                    (w-220, 27), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (100,100,100), 1)

        return annotated, raw_state

    # ── 상태 히스테리시스 & 퍼블리시 ─────────────────────────────────────────

    def _update_state(self, raw_state: str):
        if raw_state != "CLEAR":
            self._detect_count += 1
            self._clear_count   = 0
        else:
            self._clear_count  += 1
            self._detect_count  = 0

        prev = self.current_state

        if self._detect_count >= CONFIRM_FRAMES:
            self.current_state = raw_state
        elif self._clear_count >= CLEAR_FRAMES:
            self.current_state = "CLEAR"

        if self.current_state != self._last_pub_state:
            msg      = String()
            msg.data = self.current_state
            self.alert_pub.publish(msg)
            self._last_pub_state = self.current_state

            # rclpy 로거는 같은 호출 위치에서 severity를 바꿀 수 없으므로
            # if/elif/else로 호출 줄을 분리해야 함.
            log_msg = (f"[SafetyMonitor] {prev} → {self.current_state} "
                       f"(dist={int(self._last_distance)}px mode={self._last_mode})")
            if self.current_state == "CLEAR":
                self.get_logger().info(log_msg)
            elif self.current_state == "WARN":
                self.get_logger().warn(log_msg)
            else:
                self.get_logger().error(log_msg)

    def destroy_node(self):
        self._running = False
        if self.cap.isOpened():
            self.cap.release()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = SafetyMonitor()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()