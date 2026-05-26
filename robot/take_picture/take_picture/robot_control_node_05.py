import sys
import os
import time
import json
import rclpy
from rclpy.node import Node
from std_msgs.msg import String, Bool

sys.path.append(os.path.expanduser('~/cobot2_0525/robot'))
try:
    from firebase_client import get_node
except ImportError:
    pass

# ============================================================
# DSR_ROBOT2 / DR_init 경로 설정
# ============================================================
DSR_SITE_PACKAGES_PATH = "/home/jeyu/cobot_ws/install/dsr_common2/lib/python3.10/site-packages"
if DSR_SITE_PACKAGES_PATH in sys.path:
    sys.path.remove(DSR_SITE_PACKAGES_PATH)
sys.path.insert(0, DSR_SITE_PACKAGES_PATH)

import DR_init
sys.modules["DR_init"] = DR_init

ROBOT_ID = "dsr01"
ROBOT_MODEL = "m0609"

class RobotControlNode(Node):
    def __init__(self):
        super().__init__("gesture_robot_control_node", namespace=ROBOT_ID)

        # 💡 상태 변수
        self.is_moving = False
        self.current_command = None 

        self.sub_cmd = self.create_subscription(
            String,
            f"/{ROBOT_ID}/gesture_cmd",
            self.gesture_callback,
            10
        )
        
        self.sub_safety = self.create_subscription(
            String,
            f"/{ROBOT_ID}/safety_cmd",
            self.safety_callback,
            10
        )
        
        # 💡 작업 완료 신호 구독
        self.task_completed = False
        self.task_sub = self.create_subscription(
            Bool,
            f"/{ROBOT_ID}/task_complete",
            self.task_callback,
            10
        )
        self.get_logger().info("✅ 제스처 로봇 노드 대기 중 (음성 픽앤플레이스 완료 대기)...")

    def task_callback(self, msg):
        if msg.data and not self.task_completed:
            self.task_completed = True
            self.get_logger().info("🚀 픽앤플레이스 완료 트리거 수신! 로봇 제어권을 인계받습니다.")

    def safety_callback(self, msg):
        try:
            data = json.loads(msg.data)
            cmd = data.get('cmd', '')
        except Exception:
            cmd = msg.data.strip()
            
        if cmd == 'RESET_HOME':
            self.get_logger().warn("🚨 안전 명령 RESET_HOME 수신! 홈으로 강제 복귀합니다.")
            self.current_command = "RESET_HOME"

    def gesture_callback(self, msg):
        command = msg.data
        
        # 💡 로봇이 이동 중이거나(두산 함수 실행 중), 이미 명령이 예약되어 있다면 무시
        if self.is_moving or self.current_command is not None:
            return
            
        # 이동 중이 아닐 때만 명령을 받아들임
        self.current_command = command
        self.get_logger().info(f"📥 명령 접수: {command}")

    def initialize_robot(self):
        # 💡 지연 연결: 음성 노드가 완전히 종료된 후 로봇 제어권 연결을 시도하도록 위치 변경
        setattr(DR_init, "__dsr__id", ROBOT_ID)
        setattr(DR_init, "__dsr__model", ROBOT_MODEL)
        setattr(DR_init, "__dsr__node", self)

        from DSR_ROBOT2 import (
            set_robot_mode, movel, movej,
            ROBOT_MODE_MANUAL, ROBOT_MODE_AUTONOMOUS,
            DR_MV_MOD_REL, DR_BASE
        )
        self.set_robot_mode = set_robot_mode
        self.dsr_movel = movel
        self.dsr_movej = movej
        self.ROBOT_MODE_MANUAL = ROBOT_MODE_MANUAL
        self.ROBOT_MODE_AUTONOMOUS = ROBOT_MODE_AUTONOMOUS
        self.DR_MV_MOD_REL = DR_MV_MOD_REL
        self.DR_BASE = DR_BASE

        self.is_moving = True
        try:
            self.set_robot_mode(self.ROBOT_MODE_MANUAL)
            time.sleep(0.5)
            self.set_robot_mode(self.ROBOT_MODE_AUTONOMOUS)
            time.sleep(1.0)
            
            self.get_logger().info("🤖 로봇 초기 위치로 이동...")
            INIT_JOINT_POS = [8.12, 2.06, 89.98, 93.83, -98.11, 1.09] 
            
            # 💡 dsr_movej가 알아서 통신망을 잡고 이동을 끝낼 때까지 대기합니다.
            self.dsr_movej(INIT_JOINT_POS, vel=40, acc=40)
            self.get_logger().info("✅ 로봇 초기화 완료. 명령 대기 중!")
        except Exception as e:
            self.get_logger().error(f"❌ 로봇 초기화 실패: {e}")
        finally:
            self.is_moving = False
            self.current_command = None # 찌꺼기 명령 초기화

    def execute_movement(self, command):
        self.is_moving = True
        self.get_logger().info(f"🚀 실행 시작: {command}")
        
        dx, dy, dz = 0.0, 0.0, 0.0
        if command == "RIGHT": dx = 100.0
        elif command == "LEFT": dx = -100.0
        elif command == "UP": dz = 100.0
        elif command == "DOWN": dz = -100.0
        elif command == "ZOOM_IN": dy = -100.0
        elif command == "ZOOM_OUT": dy = 100.0

        try:
            rel_posx = [dx, dy, dz, 0.0, 0.0, 0.0]
            # 💡 dsr_movel 역시 알아서 통신망을 잡고 안전하게 이동을 수행합니다.
            self.dsr_movel(rel_posx, vel=50, acc=50, ref=self.DR_BASE, mod=self.DR_MV_MOD_REL)
            self.get_logger().info("✅ 이동 완료!")
        except Exception as e:
            self.get_logger().error(f"❌ 이동 실패: {e}")
        finally:
            self.is_moving = False
            self.current_command = None


def main(args=None):
    rclpy.init(args=args)
    node = RobotControlNode()

    try:
        # 1. 픽앤플레이스 작업이 끝날 때까지 대기
        while rclpy.ok() and not node.task_completed:
            rclpy.spin_once(node, timeout_sec=0.1)
            
        if not rclpy.ok():
            return
            
        # 2. 트리거를 받은 직후 로봇 초기화 (제어권 획득)
        node.initialize_robot()
        
        # 3. 메인 무한 루프
        while rclpy.ok():
            # 통신망을 아주 잠깐(0.01초) 열어서 명령이 왔는지 확인합니다.
            rclpy.spin_once(node, timeout_sec=0.01)
            
            # Firebase에서 /end.json 감지
            try:
                if get_node("/end.json") is True:
                    node.get_logger().info("🛑 Firebase /end.json = True 감지! 즉시 HOME으로 복귀합니다.")
                    node.current_command = None
                    HOME_POS = [0, 0, 90, 0, 90, 0] 
                    node.dsr_movej(HOME_POS, vel=60, acc=60)
                    node.get_logger().info("✅ HOME 복귀 완료! 다음 세션을 대기하기 위해 프로세스를 종료합니다.")
                    break
            except Exception:
                pass
            
            # 찰나의 순간에 새로운 명령이 접수되었다면?
            if node.current_command:
                if node.current_command == "RESET_HOME":
                    node.current_command = None
                    node.get_logger().info("✅ RESET_HOME 실행: HOME 위치로 이동합니다.")
                    try:
                        HOME_POS = [0, 0, 90, 0, 90, 0] 
                        node.dsr_movej(HOME_POS, vel=60, acc=60)
                    except Exception as e:
                        node.get_logger().error(f"❌ HOME 복귀 중 예외 발생 (PAUSE 상태일 수 있음): {e}")
                    break
                else:
                    # 로봇을 이동시킵니다!
                    node.execute_movement(node.current_command)
                
    except KeyboardInterrupt:
        node.get_logger().info("프로그램을 종료합니다.")
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == "__main__":
    main()
