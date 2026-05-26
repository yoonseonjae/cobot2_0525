# robot_control_07.py
import os
import time
import sys
import json
import threading
from scipy.spatial.transform import Rotation
import numpy as np
import rclpy
import rclpy.executors
from rclpy.node import Node
import DR_init

from od_msg.srv import SrvDepthPosition
from std_srvs.srv import Trigger
from std_msgs.msg import Bool, String
from ament_index_python.packages import get_package_share_directory
try:
    from robot_control.onrobot import RG
except ImportError:
    from onrobot import RG

# Firebase 클라이언트 임포트
sys.path.append(os.path.expanduser('~/cobot2_0525/robot'))
try:
    from firebase_client import get_node, update_node, patch_node
except ImportError:
    pass

package_path = get_package_share_directory("pick_and_place_voice")

# for single robot
ROBOT_ID = "dsr01"
ROBOT_MODEL = "m0609"
VELOCITY, ACC = 60, 60
BUCKET_POS = [8.12, 2.06, 89.98, 93.83, -98.11, 1.09]
JOBSERVATION_POS = [-154.26, 2.99, 56.17, -4.67, 120.75, 111.23]
JHOME_POS = [0, 0, 90, 0, 90, 0]
JPICKUP_POS = [-85.38, -25.32, 108.59, -5.97, 49.22, 7.32]
GRIPPER_NAME = "rg2"
TOOLCHARGER_IP = "192.168.1.1"
TOOLCHARGER_PORT = "502"

# 객체별 Z축 offset 설정 (필요에 따라 값을 수정하세요)
TARGET_Z_OFFSETS = {
    "black": -33.0,
    "crown": -33.0,
    "gun": -47.0,
    "hat": -35.0,   # 모자 눕혔을 때
    "pink": -33.0,
    "wand": -37.0,
    "default": -35.0
}
MIN_DEPTH = 2.0

# 객체별 Y축 offset 설정 (필요에 따라 값을 수정하세요)
TARGET_Y_OFFSETS = {
    "gun": 0.0,    # 총을 집을 때 y축 방향으로 이동
    "default": 0.0
}

# 객체별 X축 offset 설정 (필요에 따라 값을 수정하세요)
TARGET_X_OFFSETS = {
    "gun": -10.0,    # 총을 집을 때 x축 방향으로 이동
    "default": 0.0
}

# API imports will be done inside main() per guidelines.

########### Gripper Setup ############

gripper = RG(GRIPPER_NAME, TOOLCHARGER_IP, TOOLCHARGER_PORT)

########### Robot phase tracker (safety reset_home에서 참조) ############
# 대시보드의 '처음으로' 동작 분기 조건:
#   - gripper_closed=True 이고 phase가 'PICKUP_*'(=물건 집고 있거나 외력 대기 중)이면
#     스캔모드 → 마지막 픽 좌표 +5cm → 그리퍼 열고 → 홈
robot_phase = {
    "phase": "INIT",            # INIT/IDLE/SCAN/PICK_APPROACH/PICK_GRASP/PICK_LIFTED/PICK_WAIT_FORCE/DROP/HOME
    "last_pick_pos": None,      # [x,y,z,rx,ry,rz] - close_gripper 직후의 grasp 좌표
    "gripper_closed": False,
    "paused": False,            # 안전정지/비상정지 시 외력 체크와 후속 동작 차단
    "reset_home_event": threading.Event(),
}

########### Robot Controller ############

class RobotController(Node):
    def __init__(self):
        super().__init__("pick_and_place")
        
        self.task_complete_pub = self.create_publisher(Bool, f"/{ROBOT_ID}/task_complete", 10)
        
        self.init_robot()

        self.get_position_client = self.create_client(
            SrvDepthPosition, "/get_3d_position"
        )
        while not self.get_position_client.wait_for_service(timeout_sec=3.0):
            self.get_logger().info("Waiting for get_depth_position service...")
        self.get_position_request = SrvDepthPosition.Request()

        self.get_keyword_client = self.create_client(Trigger, "/get_keyword")
        while not self.get_keyword_client.wait_for_service(timeout_sec=3.0):
            self.get_logger().info("Waiting for get_keyword service...")
        self.get_keyword_request = Trigger.Request()

    def get_robot_pose_matrix(self, x, y, z, rx, ry, rz):
        R = Rotation.from_euler("ZYZ", [rx, ry, rz], degrees=True).as_matrix()
        T = np.eye(4)
        T[:3, :3] = R
        T[:3, 3] = [x, y, z]
        return T

    def transform_to_base(self, camera_coords, gripper2cam_path, robot_pos):
        gripper2cam = np.load(gripper2cam_path)
        coord = np.append(np.array(camera_coords), 1)

        x, y, z, rx, ry, rz = robot_pos
        base2gripper = self.get_robot_pose_matrix(x, y, z, rx, ry, rz)

        base2cam = base2gripper @ gripper2cam
        td_coord = np.dot(base2cam, coord)

        return td_coord[:3]

    def robot_control(self):
        target_list = []
        self.get_logger().info("call get_keyword service")
        self.get_logger().info("say 'Hello Rokey' and speak what you want to pick up")
        get_keyword_future = self.get_keyword_client.call_async(self.get_keyword_request)
        rclpy.spin_until_future_complete(self, get_keyword_future)
        
        if get_keyword_future.result().success:
            get_keyword_result = get_keyword_future.result()
            target_list = get_keyword_result.message.split()

            # 1. 모든 타겟을 한 번에 스캔하기 위해 관측 위치(JOBSERVATION_POS)로 이동
            self.get_logger().info("[DEBUG] 물체 스캔을 위해 관측 좌표로 이동합니다.")
            movej(posj(JOBSERVATION_POS), vel=VELOCITY, acc=ACC)
            mwait()
            
            # 로봇 팔 진동 안정화 및 카메라 자동 초점/노출 조절을 위해 2초 대기
            self.get_logger().info("[DEBUG] 카메라 안정화를 위해 2초 대기합니다.")
            time.sleep(2.0)
            
            # 2. 모든 타겟의 3D 좌표를 미리 계산하여 저장
            target_positions = {}
            for target in target_list:
                self.get_logger().info(f"[DEBUG] '{target}' 대상 좌표 탐색 중...")
                target_pos = self.get_target_pos(target)
                if target_pos is not None:
                    target_positions[target] = target_pos
                    self.get_logger().info(f"[DEBUG] '{target}' 좌표: {target_pos}")
                else:
                    self.get_logger().warn(f"No target position found for {target}")

            # 3. 계산된 좌표를 바탕으로 순차적으로 파지 작업 수행
            is_first_target = True
            for target in target_list:
                if target in target_positions:
                    target_pos = target_positions[target]
                    
                    # 첫 번째 타겟이 아닌 경우(즉, JHOME_POS에서 출발하는 경우), 안전한 궤적을 위해 관측 위치를 경유
                    if not is_first_target:
                        self.get_logger().info("[DEBUG] 안전한 궤적을 위해 관측 좌표를 형식상 경유합니다.")
                        movej(posj(JOBSERVATION_POS), vel=VELOCITY, acc=ACC)
                        mwait()
                    
                    self.get_logger().info(f"[DEBUG] '{target}' 잡으러 이동 (좌표: {target_pos})")

                    # 물체를 집고 홈(JHOME_POS)으로 이동 (놓지는 않음)
                    self.pick_and_place_target(target_pos)

                    # 외력을 감지하면 물체를 놓고 잠시 대기
                    self.wait_and_drop(target)

                    # RESET_HOME으로 인해 홈 복귀가 완료되었다면 현 사이클 종료
                    if robot_phase.get("phase") == "HOME":
                        self.get_logger().warn("RESET_HOME 후 사이클 종료, 다음 명령 대기")
                        return

                    is_first_target = False
                    
            # 반복문 종료: 모든 타겟을 처리했으므로 사진 찍는 위치(BUCKET_POS)로 이동
            self.get_logger().info("모든 탐색 완료, 최종 목적지(BUCKET_POS)로 이동합니다.")
            movej(posj(BUCKET_POS), vel=VELOCITY, acc=ACC)
            mwait()
            
            # Firebase에 픽앤플레이스 완료 신호 전송
            try:
                update_node("/voice_ok.json", True)
                self.get_logger().info("Firebase /voice_ok.json = True 전송")
            except Exception:
                pass

            # 2. 모든 작업이 끝났음을 알리는 트리거 발행
            self.get_logger().info("모든 작업 완료! 제스처 모드로 제어권을 넘깁니다.")
            msg = Bool()
            msg.data = True
            self.task_complete_pub.publish(msg)
            
            # 메시지가 구독자들에게 확실히 전달될 수 있도록 잠시 대기
            time.sleep(1.0)
            
            # 3. 로봇 제어 권한(1:1 연결)을 제스처 코드에게 넘겨주기 위해 노드 안전 종료
            self.get_logger().info("제스처 노드 실행을 위해 이 노드를 종료합니다.")
            self.destroy_node() # 노드 자원 해제
            rclpy.shutdown()    # ROS 통신 종료
            sys.exit(0)         # 파이썬 스크립트 정상 종료

        else:
            self.get_logger().warn(f"{get_keyword_result.message}")
            return

    def wait_and_drop(self, target):
        """
        로봇이 홈 위치에 도착한 뒤, 외력을 감지하면 그리퍼를 열고 다음 동작으로 넘어가는 함수
        """
        self.get_logger().info("Step 3: Waiting for X/Y-axis impact (Base frame)...")
        robot_phase["phase"] = "PICK_WAIT_FORCE"

        while rclpy.ok():
            # 안전 reset_home 이벤트가 들어오면 외력 대기 중단 + 복귀 시퀀스 완료까지 대기
            if robot_phase["reset_home_event"].is_set():
                self.get_logger().warn("RESET_HOME 이벤트 감지 → 외력 대기 중단, 복귀 완료까지 대기")
                while robot_phase["reset_home_event"].is_set() and rclpy.ok():
                    time.sleep(0.2)
                return
            # paused 상태이면 외력 체크 자체를 건너뜀 (안전정지/비상정지 중에는 그리퍼가 외력으로 열리면 안 됨)
            if robot_phase.get("paused"):
                time.sleep(0.2)
                continue
            ret_x = check_force_condition(DR_AXIS_X, min=10, max=50, ref=DR_BASE)
            ret_y = check_force_condition(DR_AXIS_Y, min=10, max=50, ref=DR_BASE)

            if ret_x == 0 or ret_y == 0:
                self.get_logger().info("Impact detected! Dropping the object.")
                break
            time.sleep(0.1) # 제어기에 무리가 가지 않도록 time.sleep(0.1) 사용 (권장)

        self.get_logger().info("Step 4: Opening gripper...")
        gripper.open_gripper()
        robot_phase["gripper_closed"] = False
        robot_phase["phase"] = "DROP"

        # 그리퍼가 완전히 열릴 때까지 상태 확인하며 대기
        while gripper.get_status()[0]:
            time.sleep(0.5)

        try:
            patch_node("/tool.json", {target: True})
            self.get_logger().info(f"Firebase /tool.json 업데이트: {target} = True")
        except Exception:
            pass

        self.get_logger().info("물체를 놓았습니다. 1.5초 대기합니다.")
        time.sleep(1.5) # 외력 감지 후 다음 장소로 이동하기 전 잠깐의 딜레이

    def get_target_pos(self, target):
        self.get_position_request.target = target
        self.get_logger().info("call depth position service with object_detection node")
        get_position_future = self.get_position_client.call_async(
            self.get_position_request
        )
        rclpy.spin_until_future_complete(self, get_position_future)

        if get_position_future.result():
            result = get_position_future.result().depth_position.tolist()
            self.get_logger().info(f"Received depth position: {result}")
            if sum(result) == 0:
                print("No target position")
                return None

            gripper2cam_path = os.path.join(
                package_path, "resource", "T_gripper2camera.npy"
            )
            robot_posx = get_current_posx()[0]
            td_coord = self.transform_to_base(result, gripper2cam_path, robot_posx)

            if td_coord[2] and sum(td_coord) != 0:
                x_offset = TARGET_X_OFFSETS.get(target, TARGET_X_OFFSETS["default"])
                td_coord[0] += x_offset
                
                y_offset = TARGET_Y_OFFSETS.get(target, TARGET_Y_OFFSETS["default"])
                td_coord[1] += y_offset
                
                z_offset = TARGET_Z_OFFSETS.get(target, TARGET_Z_OFFSETS["default"])
                td_coord[2] += z_offset
                td_coord[2] = max(td_coord[2], MIN_DEPTH)

            target_pos = list(td_coord[:3]) + robot_posx[3:]
            target_pos = [float(val) for val in target_pos]
        return target_pos

    def init_robot(self):
        # 1. 홈 좌표(JHOME_POS)에서 대기하며 /start.json 모니터링
        self.get_logger().info("로봇 초기화: 홈 위치로 이동하여 대기합니다.")
        robot_phase["phase"] = "HOME"
        movej(posj(JHOME_POS), vel=VELOCITY, acc=ACC)
        gripper.open_gripper()
        robot_phase["gripper_closed"] = False
        mwait()
        
        self.get_logger().info("웹 키오스크의 /start.json=true 신호를 기다립니다...")
        while rclpy.ok():
            try:
                if get_node("/start.json") is True:
                    self.get_logger().info("시작 신호 수신! 스캔 장소로 이동합니다.")
                    break
            except Exception:
                pass
            time.sleep(1.0)

        # 시작 신호를 받으면 관측 좌표로 이동
        movej(posj(JOBSERVATION_POS), vel=VELOCITY, acc=ACC)
        mwait()

    def pick_and_place_target(self, target_pos):
        # 1. 물체 수직 상단 150mm (15cm) 접근 위치(Approach Pose) 계산
        approach_pos = target_pos[0:2] + [target_pos[2] + 150] + target_pos[3:]

        # 2. 물체 수직 상단으로 이동
        self.get_logger().info(f"[DEBUG] 물체 수직 상단(Approach 위치, 15cm)으로 하강합니다.")
        robot_phase["phase"] = "PICK_APPROACH"
        movel(posx(approach_pos), vel=VELOCITY, acc=ACC)
        mwait()

        # 3. 수직 상단에서 1초간 대기하며 흔들림 방지 및 정지
        self.get_logger().info(f"[DEBUG] 흔들림 방지를 위해 1초 대기 중...")
        time.sleep(1.0)

        # 4. 정지 상태에서 물체 위치로 수직 하강만 수행
        self.get_logger().info(f"[DEBUG] 물체 파지를 위해 수직 하강합니다.")
        movel(posx(target_pos), vel=VELOCITY, acc=ACC)
        mwait()

        # 5. 그리퍼 닫기
        robot_phase["phase"] = "PICK_GRASP"
        gripper.close_gripper()
        while gripper.get_status()[0]:
            time.sleep(0.5)
        mwait()
        # 그리퍼 닫힘 + 마지막 픽 좌표 기억 (reset_home에서 사용)
        robot_phase["gripper_closed"] = True
        robot_phase["last_pick_pos"] = list(target_pos)

        # 6. 물체를 잡은 뒤 다시 150mm(15cm) 수직 상승
        self.get_logger().info(f"[DEBUG] 물체를 잡고 15cm 수직 상승합니다.")
        pick_up_pos = target_pos[0:2] + [target_pos[2] + 150] + target_pos[3:]
        movel(posx(pick_up_pos), vel=VELOCITY, acc=ACC)
        mwait()

        # [수정] 15cm 상승 동작이 무시되거나 홈 이동과 겹치지 않도록 상승 직후 0.5초 대기
        time.sleep(0.5)
        robot_phase["phase"] = "PICK_LIFTED"

        # 7. 물품 수령 위치(JPICKUP_POS)로 이동
        self.get_logger().info(f"[DEBUG] 물체를 들고 수령 위치(JPICKUP_POS)로 이동합니다.")
        movej(posj(JPICKUP_POS), vel=VELOCITY, acc=ACC)
        mwait()
        
        # 이전 8번 단계(그리퍼 열어 물체 놓기)는 삭제됨. 이제 wait_and_drop 에서 수행.

    def execute_reset_home(self):
        """
        대시보드 '처음으로' 트리거 시 실행되는 복구 시퀀스.
        조건:
          - gripper_closed=True 이고 phase가 PICK_GRASP / PICK_LIFTED / PICK_WAIT_FORCE면
            → 마지막 픽 좌표 위 5cm로 스캔 모드 이동 → 그리퍼 열기 → 홈
          - 아니면 단순히 그리퍼 열고 홈으로
        """
        last_pos = robot_phase.get("last_pick_pos")
        in_pickup = robot_phase.get("phase") in ("PICK_GRASP", "PICK_LIFTED", "PICK_WAIT_FORCE")
        holding   = bool(robot_phase.get("gripper_closed")) and last_pos is not None and in_pickup

        self.get_logger().warn(
            f"[RESET_HOME] 시작 (holding={holding}, phase={robot_phase.get('phase')})")

        try:
            if holding:
                # 마지막 픽 좌표에서 z축으로 +5cm (=50mm) 위 지점으로 이동 (스캔 모드 자세 유지)
                above = [last_pos[0], last_pos[1], last_pos[2] + 50] + list(last_pos[3:])
                self.get_logger().warn(f"[RESET_HOME] 마지막 픽 좌표 +5cm 위로 이동: {above}")
                movel(posx(above), vel=VELOCITY, acc=ACC)
                mwait()
                self.get_logger().warn("[RESET_HOME] 그리퍼 완전 개방")
                gripper.open_gripper()
                while gripper.get_status()[0]:
                    time.sleep(0.3)
                robot_phase["gripper_closed"] = False
            else:
                # 그냥 그리퍼 안전하게 열기
                gripper.open_gripper()
                while gripper.get_status()[0]:
                    time.sleep(0.3)
                robot_phase["gripper_closed"] = False

            # 홈으로 복귀
            self.get_logger().warn("[RESET_HOME] JHOME_POS로 복귀")
            movej(posj(JHOME_POS), vel=VELOCITY, acc=ACC)
            mwait()
            robot_phase["phase"] = "HOME"
            robot_phase["last_pick_pos"] = None
        except Exception as e:
            self.get_logger().error(f"[RESET_HOME] 실패: {e}")
        finally:
            robot_phase["reset_home_event"].clear()


class SafetyCommandNode(Node):
    """
    /dsr01/safety_cmd 구독 전용 노드.
    별도 스레드/executor로 spin하므로 메인 컨트롤러의 service-wait과 충돌하지 않음.
    실제 모션 실행은 robot_phase['reset_home_event']로 메인 스레드에 위임한다.
    """
    def __init__(self):
        super().__init__('robot_safety_cmd_listener')
        self.sub = self.create_subscription(
            String, f'/{ROBOT_ID}/safety_cmd', self._on_cmd, 10)
        self.get_logger().info('[SafetyCmdListener] /{}/safety_cmd 구독 시작'.format(ROBOT_ID))

    def _on_cmd(self, msg: String):
        try:
            data = json.loads(msg.data)
            cmd = data.get('cmd', '')
        except Exception:
            cmd = msg.data.strip()
        self.get_logger().warn(f'[SafetyCmdListener] cmd 수신: {cmd}')
        if cmd == 'PAUSE':
            robot_phase["paused"] = True
        elif cmd == 'RESUME':
            robot_phase["paused"] = False
        elif cmd == 'RESET_HOME':
            # 복귀 시퀀스 실행 전에 paused 해제 (motion이 통과되도록)
            robot_phase["paused"] = False
            robot_phase["reset_home_event"].set()


def main(args=None):
    global movej, movel, get_current_posx, mwait, trans, wait, check_force_condition, DR_AXIS_X, DR_AXIS_Y, DR_BASE, posx, posj
    
    DR_init.__dsr__id = ROBOT_ID
    DR_init.__dsr__model = ROBOT_MODEL
    rclpy.init(args=args)
    dsr_node = rclpy.create_node("voice_robot_control_node", namespace=ROBOT_ID)
    DR_init.__dsr__node = dsr_node

    try:
        from DSR_ROBOT2 import (
            movej, movel, get_current_posx, mwait, trans,
            wait, check_force_condition, DR_AXIS_X, DR_AXIS_Y, DR_BASE
        )
        from DR_common2 import posx, posj
    except ImportError as e:
        print(f"Error importing DSR_ROBOT2: {e}")
        return

    node = RobotController()

    # 안전 명령 리스너 노드 (별도 executor + 데몬 스레드에서 spin)
    safety_node = SafetyCommandNode()
    safety_executor = rclpy.executors.SingleThreadedExecutor()
    safety_executor.add_node(safety_node)
    safety_thread = threading.Thread(target=safety_executor.spin, daemon=True)
    safety_thread.start()

    # reset_home_event 감시 스레드 (메인 컨트롤러 노드 컨텍스트에서 실행되어야 motion API 사용 가능)
    def _reset_watcher():
        while rclpy.ok():
            if robot_phase["reset_home_event"].wait(timeout=0.5):
                try:
                    node.execute_reset_home()
                except Exception as e:
                    node.get_logger().error(f"[reset_watcher] {e}")
    threading.Thread(target=_reset_watcher, daemon=True).start()

    try:
        while rclpy.ok():
            node.robot_control()
    except SystemExit:
        pass
    except KeyboardInterrupt:
        node.get_logger().info("사용자에 의해 중단되었습니다.")
    finally:
        try:
            safety_executor.shutdown()
        except Exception:
            pass
        if rclpy.ok():
            rclpy.shutdown()
        try:
            node.destroy_node()
            safety_node.destroy_node()
        except:
            pass


if __name__ == "__main__":
    main()
