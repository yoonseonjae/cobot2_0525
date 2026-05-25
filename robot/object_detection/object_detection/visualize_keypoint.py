import rclpy
import cv2
import json
import os
from ament_index_python.packages import get_package_share_directory
from ultralytics import YOLO
from std_msgs.msg import Bool
from object_detection.realsense import ImgNode

PACKAGE_PATH = get_package_share_directory("object_detection")
YOLO_MODEL_PATH = os.path.join(PACKAGE_PATH, "resource", "260519_best.pt")
YOLO_JSON_PATH = os.path.join(get_package_share_directory("object_detection"), "resource", "class_name_tool.json")


def main():
    rclpy.init()
    node = ImgNode()

    with open(YOLO_JSON_PATH, "r") as f:
        class_dict = json.load(f)  # {0: "drill", 1: "hammer", ...}

    model = YOLO(YOLO_MODEL_PATH)

    print("Press 'q' to quit.")

    is_task_completed = False

    def task_callback(msg):
        nonlocal is_task_completed
        if msg.data:
            is_task_completed = True
            print("Task complete signal received. Shutting down visualize_keypoint node.")

    # Subscriber 추가
    node.create_subscription(Bool, '/dsr01/task_complete', task_callback, 10)

    frame_count = 0

    while rclpy.ok() and not is_task_completed:
        rclpy.spin_once(node, timeout_sec=0.1)
        frame = node.get_color_frame()
        if frame is None:
            continue

        frame_count += 1
        # 3프레임 중 1번만 연산하고, 나머지 2프레임은 버려서 딜레이가 쌓이지 않도록 함 (Frame Skip)
        if frame_count % 3 != 0:
            continue

        # iou=0.45 옵션으로 겹치는 박스를 하나로 합치고, conf=0.6으로 확실한 것만 표시
        results = model(frame, verbose=False, conf=0.6, iou=0.45)
        
        # 안전한 접근을 위해 데이터가 존재하고 keypoints 속성이 있는지 확인합니다.
        if len(results) > 0 and hasattr(results[0], 'keypoints') and results[0].keypoints is not None:
            # zip 함수를 사용하여 박스 정보와 키포인트 리스트를 한 번에 매핑하여 가져옵니다.
            for box, score, label, kp_list in zip(
                results[0].boxes.xyxy.tolist(),
                results[0].boxes.conf.tolist(),
                results[0].boxes.cls.tolist(),
                results[0].keypoints.data.tolist()  # 각 객체별 키포인트 데이터 [x, y, conf] 구조
            ):
                # 객체 자체의 인식 신뢰도가 50% 미만이면 통과시킵니다.
                if score < 0.5:
                    continue
                
                # 1. 바운딩 박스 및 클래스 이름 시각화 (녹색)
                x1, y1, x2, y2 = map(int, box)
                name = class_dict.get(str(int(label)), str(int(label)))
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(frame, f"{name} {score:.2f}", (x1, y1 - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

                                # 2. 키포인트(Keypoints) 시각화 (빨간색 점과 번호)
                for idx, kp in enumerate(kp_list):
                    kx, ky, kconf = kp
                    # 키포인트 각각의 신뢰도 점수가 50% 이상인 확실한 점만 화면에 표기합니다.
                    if kconf > 0.5:
                        cv2.circle(frame, (int(kx), int(ky)), 5, (0, 0, 255), -1)
                        # 점 옆에 키포인트 번호(idx) 표시 (파란색 글씨)
                        cv2.putText(frame, str(idx), (int(kx) + 5, int(ky) - 5),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1)
                        
        else:
            # 만약 Pose 모델이 아닌 일반 검출 모델일 경우를 대비한 예외 처리 로직입니다.
            for box, score, label in zip(
                results[0].boxes.xyxy.tolist(),
                results[0].boxes.conf.tolist(),
                results[0].boxes.cls.tolist(),
            ):
                if score < 0.5:
                    continue
                x1, y1, x2, y2 = map(int, box)
                name = class_dict.get(str(int(label)), str(int(label)))
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(frame, f"{name} {score:.2f}", (x1, y1 - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        cv2.imshow("YOLO Detection", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cv2.destroyAllWindows()
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
