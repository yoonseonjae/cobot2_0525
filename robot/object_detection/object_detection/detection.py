import sys
import numpy as np
import rclpy
from rclpy.node import Node
from typing import Any, Callable, Optional, Tuple
from std_msgs.msg import Bool

from ament_index_python.packages import get_package_share_directory
from od_msg.srv import SrvDepthPosition
from object_detection.realsense import ImgNode
from object_detection.yolo import YoloModel


PACKAGE_NAME = 'object_detection'
PACKAGE_PATH = get_package_share_directory(PACKAGE_NAME)


class ObjectDetectionNode(Node):
    def __init__(self, model_name = 'yolo'):
        super().__init__('object_detection_node')
        self.img_node = ImgNode()
        self.model = self._load_model(model_name)
        self.intrinsics = self._wait_for_valid_data(
            self.img_node.get_camera_intrinsic, "camera intrinsics"
        )
        self.create_service(
            SrvDepthPosition,
            'get_3d_position',
            self.handle_get_depth
        )
        self.task_sub = self.create_subscription(
            Bool,
            '/dsr01/task_complete',
            self.task_callback,
            10
        )
        self.get_logger().info("ObjectDetectionNode initialized.")

    def task_callback(self, msg):
        """작업 완료 신호를 받으면 노드를 종료합니다."""
        if msg.data:
            self.get_logger().info("Task complete signal received. Shutting down object detection node.")
            self.destroy_node()
            rclpy.shutdown()
            sys.exit(0)

    def _load_model(self, name):
        """모델 이름에 따라 인스턴스를 반환합니다."""
        if name.lower() == 'yolo':
            return YoloModel()
        raise ValueError(f"Unsupported model: {name}")

    def handle_get_depth(self, request, response):
        """클라이언트 요청을 처리해 3D 좌표를 반환합니다."""
        self.get_logger().info(f"Received request: {request}")
        coords = self._compute_position(request.target)
        response.depth_position = [float(x) for x in coords]
        return response

    def _compute_position(self, target):
        """이미지를 처리해 객체의 카메라 좌표를 계산합니다."""
        rclpy.spin_once(self.img_node)

        box, keypoint, score = self.model.get_best_detection(self.img_node, target)
        if box is None or score is None:
            self.get_logger().warn("No detection found.")
            return 0.0, 0.0, 0.0
        
        if keypoint is not None:
            cx, cy = map(int, keypoint)
            self.get_logger().info(f"Detection: box={box}, keypoint=({cx}, {cy}), score={score}")
        else:
            cx, cy = map(int, [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2])
            self.get_logger().info(f"Detection (No keypoint): box={box}, center=({cx}, {cy}), score={score}")
        cz = self._get_depth(cx, cy)
        if cz is None:
            self.get_logger().warn("Depth out of range.")
            return 0.0, 0.0, 0.0

        return self._pixel_to_camera_coords(cx, cy, cz)

    def _get_depth(self, x, y, window_size=5):
        """픽셀 좌표 주변 영역의 depth 값을 중앙값 필터링하여 노이즈 없이 안전하게 읽어옵니다."""
        frame = self._wait_for_valid_data(self.img_node.get_depth_frame, "depth frame")
        if frame is None or (isinstance(frame, np.ndarray) and not frame.any()):
            self.get_logger().warn("Invalid or empty depth frame received. Cannot calculate depth.")
            return None
            
        try:
            if not (0 <= y < frame.shape[0] and 0 <= x < frame.shape[1]):
                self.get_logger().warn(f"Coordinates ({x},{y}) out of bounds.")
                return None
                
            half = window_size // 2
            y_min = max(0, int(y) - half)
            y_max = min(frame.shape[0], int(y) + half + 1)
            x_min = max(0, int(x) - half)
            x_max = min(frame.shape[1], int(x) + half + 1)
            
            roi = frame[y_min:y_max, x_min:x_max]
            # 0이 아닌 유효한 depth 값만 추출 (다이소 장난감 반사 재질 노이즈 및 지나치게 가까운 10cm 미만 오류값 방어)
            valid_depths = roi[roi > 100]
            
            if len(valid_depths) == 0:
                self.get_logger().warn(f"No valid depth found near ({x},{y}).")
                return None
                
            # 💡 [핵심 방어 로직] 물체(요술봉 등)가 얇을 경우, 5x5 영역에 배경(테이블) 깊이가 많이 섞일 수 있습니다.
            # 중앙값(median)을 쓰면 자칫 테이블 바닥 깊이를 잡을 위험이 있으므로,
            # 유효한 값 중 '카메라에 더 가까운 쪽(상위 25%)'의 깊이를 채택하여 무조건 물체의 깊이를 잡도록 합니다.
            return float(np.percentile(valid_depths, 25))
        except Exception as e:
            self.get_logger().error(f"Error getting depth at ({x},{y}): {e}")
            return None

    def _wait_for_valid_data(self, getter, description, max_retries=30):
        """getter 함수가 유효한 데이터를 반환할 때까지 spin 하며 재시도합니다."""
        data = getter()
        retries = 0
        while data is None or (isinstance(data, np.ndarray) and not data.any()):
            rclpy.spin_once(self.img_node, timeout_sec=0.1)
            self.get_logger().info(f"Retry getting {description}.")
            data = getter()
            retries += 1
            if retries >= max_retries:
                self.get_logger().warn(f"Timeout: Failed to get valid {description} after {max_retries} retries.")
                break
        return data

    def _pixel_to_camera_coords(self, x, y, z):
        """픽셀 좌표와 intrinsics를 이용해 카메라 좌표계로 변환합니다."""
        fx = self.intrinsics['fx']
        fy = self.intrinsics['fy']
        ppx = self.intrinsics['ppx']
        ppy = self.intrinsics['ppy']
        return (
            (x - ppx) * z / fx,
            (y - ppy) * z / fy,
            z
        )


def main(args=None):
    rclpy.init(args=args)
    node = ObjectDetectionNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
