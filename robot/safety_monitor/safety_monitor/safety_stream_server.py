#!/usr/bin/env python3
"""
safety_stream_server.py
=======================
safety_monitor 노드의 처리된 영상을 대시보드로 스트리밍하는 Flask 서버.

실행:
  ros2 run safety_monitor safety_stream_server
  또는
  python3 safety_stream_server.py

엔드포인트:
  GET  http://localhost:5001/safety_feed  → MJPEG 스트림 (대시보드에 표시)
  POST http://localhost:5001/set_zone     → JSON {"polygon": [[x1,y1],...]} 수신

안전구역 설정 흐름:
  1. 대시보드에서 구역 클릭 → POST /set_zone
  2. 이 서버가 /safety_zone_update ROS 토픽으로 전달
  3. safety_monitor 노드가 폴리곤 적용
"""

import io
import json
import threading
import numpy as np
import cv2

from flask import Flask, Response, request, jsonify
from flask_cors import CORS

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import String
from cv_bridge import CvBridge

# ── Flask 앱 ──────────────────────────────────────────────────────────────────
app = Flask(__name__)
CORS(app)   # 대시보드(다른 포트)에서 접근 허용

# 공유 프레임 버퍼 (thread-safe)
_frame_lock  = threading.Lock()
_latest_frame: bytes | None = None   # JPEG bytes

# ROS 노드 (글로벌)
_ros_node: Node | None = None


class SafetyStreamNode(Node):
    """
    /safety_image 토픽을 구독하여 최신 프레임을 버퍼에 저장.
    /safety_zone_update 토픽으로 존 폴리곤을 전달.
    """
    def __init__(self):
        super().__init__('safety_stream_server')
        self.bridge = CvBridge()

        self.img_sub = self.create_subscription(
            Image, '/safety_image', self._image_cb, 1)

        self.zone_pub = self.create_publisher(
            String, '/safety_zone_update', 10)

        self.get_logger().info(
            '[SafetyStreamServer] 노드 시작 — /safety_image 구독 중')

    def _image_cb(self, msg: Image):
        global _latest_frame
        try:
            frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
            _, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
            with _frame_lock:
                _latest_frame = buf.tobytes()
        except Exception as e:
            self.get_logger().warn(f'[SafetyStreamServer] 이미지 변환 실패: {e}')

    def publish_zone(self, polygon_px: list):
        """픽셀 좌표 폴리곤을 /safety_zone_update 토픽으로 전달."""
        msg = String()
        msg.data = json.dumps({'polygon': polygon_px})
        self.zone_pub.publish(msg)
        self.get_logger().info(
            f'[SafetyStreamServer] zone 전달: {len(polygon_px)}개 꼭짓점')


# ── Flask 라우트 ──────────────────────────────────────────────────────────────

def _generate_frames():
    """MJPEG 스트림 제너레이터."""
    # 기본 no-signal 프레임 생성
    no_signal = np.zeros((240, 320, 3), dtype=np.uint8)
    cv2.putText(no_signal, 'No Signal', (60, 120),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (80, 80, 80), 2)
    _, ns_buf = cv2.imencode('.jpg', no_signal)
    no_signal_bytes = ns_buf.tobytes()

    while True:
        with _frame_lock:
            frame_bytes = _latest_frame if _latest_frame else no_signal_bytes

        yield (
            b'--frame\r\n'
            b'Content-Type: image/jpeg\r\n\r\n'
            + frame_bytes +
            b'\r\n'
        )


@app.route('/safety_feed')
def safety_feed():
    """MJPEG 비디오 스트림 엔드포인트."""
    return Response(
        _generate_frames(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )


@app.route('/set_zone', methods=['POST'])
def set_zone():
    """
    대시보드에서 안전구역 폴리곤을 수신 → ROS 토픽으로 전달.
    Body: {"polygon": [[x1,y1],[x2,y2],...]}  (픽셀 좌표)
    """
    global _ros_node
    try:
        data = request.get_json()
        polygon = data.get('polygon', [])
        if len(polygon) < 3 and len(polygon) != 0:
            return jsonify({'ok': False, 'error': 'polygon must have >= 3 points or be empty'}), 400

        if _ros_node:
            _ros_node.publish_zone(polygon)

        return jsonify({'ok': True, 'points': len(polygon)})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'has_frame': _latest_frame is not None})


# ── main ──────────────────────────────────────────────────────────────────────

def main(args=None):
    global _ros_node

    rclpy.init(args=args)
    _ros_node = SafetyStreamNode()

    # ROS2 스핀 스레드
    spin_thread = threading.Thread(
        target=lambda: rclpy.spin(_ros_node), daemon=True)
    spin_thread.start()

    # Flask 서버 (메인 스레드)
    print('[SafetyStreamServer] Flask 서버 시작: http://0.0.0.0:5001')
    print('  스트림 URL : http://localhost:5001/safety_feed')
    print('  zone  URL  : POST http://localhost:5001/set_zone')
    app.run(host='0.0.0.0', port=5001, threaded=True)

    _ros_node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()