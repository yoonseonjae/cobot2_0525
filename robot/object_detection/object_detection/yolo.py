########## YoloModel ##########
import os
import json
import time
import cv2  # 🔥 OpenCV 라이브러리 추가
from collections import Counter

import rclpy
from ament_index_python.packages import get_package_share_directory
from ultralytics import YOLO
import numpy as np


PACKAGE_NAME = "object_detection"
PACKAGE_PATH = get_package_share_directory(PACKAGE_NAME)

YOLO_MODEL_FILENAME = "260519_best.pt"
YOLO_CLASS_NAME_JSON = "class_name_tool.json"

YOLO_MODEL_PATH = os.path.join(PACKAGE_PATH, "resource", YOLO_MODEL_FILENAME)
YOLO_JSON_PATH = os.path.join(PACKAGE_PATH, "resource", YOLO_CLASS_NAME_JSON)


class YoloModel:
    def __init__(self):
        self.model = YOLO(YOLO_MODEL_PATH)
        # JSON 대신 모델 내장 클래스명 사용 → best.pt의 학습 순서와 항상 일치
        self.reversed_class_dict = {v: k for k, v in self.model.names.items()}
        print(f"[YoloModel] class map: {self.model.names}")
        
    def get_frames(self, img_node, duration=1.0):
        """get frames while target_time"""
        end_time = time.time() + duration
        frames = {}

        while time.time() < end_time:
            rclpy.spin_once(img_node)
            frame = img_node.get_color_frame()
            stamp = img_node.get_color_frame_stamp()
            if frame is not None:
                frames[stamp] = frame
            time.sleep(0.01)

        if not frames:
            print("No frames captured in %.2f seconds", duration)

        print("%d frames captured", len(frames))
        return list(frames.values())

    def get_best_detection(self, img_node, target):
        rclpy.spin_once(img_node)
        frames = self.get_frames(img_node)
        if not frames:  # Check if frames are empty
            return None

        results = self.model(frames, verbose=False)
        print("classes: ")
        print(results[0].names)
        # 🔥 여기서부터 추가 (YOLO 인식 화면 띄우기)
        # 여러 프레임 중 가장 마지막 프레임의 결과를 시각화합니다.
        annotated_frame = results[-1].plot()  # Bounding Box가 그려진 이미지 배열 생성
        cv2.imshow("YOLO Vision Debug", annotated_frame)  # 창 이름 설정 및 화면 출력
        cv2.waitKey(1)  # 1ms 대기 (이 코드가 있어야 창이 정상적으로 업데이트 됨)
        detections = self._aggregate_detections(results)
        label_id = self.reversed_class_dict[target]
        print("label_id: ", label_id)
        print("detections: ", detections)

        matches = [d for d in detections if d["label"] == label_id]
        if not matches:
            print("No matches found for the target label.")
            return None, None, None
        best_det = max(matches, key=lambda x: x["score"])
        return best_det["box"], best_det["keypoint"], best_det["score"]

    def _aggregate_detections(self, results, confidence_threshold=0.5, iou_threshold=0.5):
        """
        Fuse raw detection boxes across frames using IoU-based grouping
        and majority voting for robust final detections.
        """
        raw = []
        for res in results:
            has_kps = hasattr(res, 'keypoints') and res.keypoints is not None
            boxes = res.boxes.xyxy.tolist()
            confs = res.boxes.conf.tolist()
            clss = res.boxes.cls.tolist()
            kps_data = res.keypoints.data.tolist() if has_kps else [None] * len(boxes)
            
            for box, score, label, kp_list in zip(boxes, confs, clss, kps_data):
                if score >= confidence_threshold:
                    valid_kp = None
                    if kp_list is not None:
                        # 💡 [핵심 파라미터] 로봇이 잡으러 갈 대상 키포인트 인덱스 번호를 지정합니다!
                        class_name = self.model.names.get(int(label), "")
                        if class_name.lower() in ("hat", "gun"):
                            target_kp_idx = 0
                        else:
                            target_kp_idx = 1
                        
                        if len(kp_list) > target_kp_idx:
                            target_kp = kp_list[target_kp_idx]
                            if target_kp[2] > 0.5:  # 신뢰도가 0.5 이상일 때만 유효 좌표로 인정
                                valid_kp = (target_kp[0], target_kp[1])
                                
                        # 💡 [방향 제어(Orientation Vectoring)를 위한 사전 안내]
                        # 향후 손목 회전(Rx, Ry, Rz)을 위해 2개의 점이 필요하다면 아래처럼 점을 모아야 합니다.
                        # valid_kps = [ (kp[0], kp[1]) for kp in kp_list if kp[2] > 0.5 ]
                        # (단, 이 경우 detection.py 및 ROS 서비스 메시지 형식도 함께 수정되어야 합니다.)
                    raw.append({"box": box, "score": score, "label": int(label), "keypoint": valid_kp})

        final = []
        used = [False] * len(raw)

        for i, det in enumerate(raw):
            if used[i]:
                continue
            group = [det]
            used[i] = True
            for j, other in enumerate(raw):
                if not used[j] and other["label"] == det["label"]:
                    if self._iou(det["box"], other["box"]) >= iou_threshold:
                        group.append(other)
                        used[j] = True

            boxes = np.array([g["box"] for g in group])
            scores = np.array([g["score"] for g in group])
            labels = [g["label"] for g in group]
            kps = [g["keypoint"] for g in group if g["keypoint"] is not None]
            
            avg_kp = None
            if kps:
                avg_kp = np.array(kps).mean(axis=0).tolist()

            final.append(
                {
                    "box": boxes.mean(axis=0).tolist(),
                    "score": float(scores.mean()),
                    "label": Counter(labels).most_common(1)[0][0],
                    "keypoint": avg_kp,
                }
            )

        return final

    def _iou(self, box1, box2):
        """
        Compute Intersection over Union (IoU) between two boxes [x1, y1, x2, y2].
        """
        x1, y1 = max(box1[0], box2[0]), max(box1[1], box2[1])
        x2, y2 = min(box1[2], box2[2]), min(box1[3], box2[3])
        inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
        area1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
        area2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
        union = area1 + area2 - inter
        return inter / union if union > 0 else 0.0
