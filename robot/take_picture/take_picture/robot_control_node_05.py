import sys
import os
import time
import json
import threading
import requests
import rclpy
from rclpy.node import Node
from std_msgs.msg import String, Bool

sys.path.append(os.path.expanduser('~/cobot2_0525/robot'))
try:
    from firebase_client import get_node
except ImportError:
    pass

FIREBASE_BASE = "https://rokey-coop2-default-rtdb.asia-southeast1.firebasedatabase.app"

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

        # 안전모드 상태 (대시보드 발행 /dsr01/safety_cmd로 갱신)
        self.paused = False
        self.reset_home_pending = False

        self.sub_cmd = self.create_subscription(
            String,
            f"/{ROBOT_ID}/gesture_cmd",
            self.gesture_callback,
            10
        )

        # 안전 명령 구독 (PAUSE/RESUME/RESET_HOME)
        self.sub_safety = self.create_subscription(
            String,
            f"/{ROBOT_ID}/safety_cmd",
            self.safety_cmd_callback,
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

    def safety_cmd_callback(self, msg: String):
        try:
            data = json.loads(msg.data)
            cmd = data.get("cmd", "")
        except Exception:
            cmd = msg.data.strip()
        self.get_logger().warn(f"🛡️ [SafetyCmd] 수신: {cmd}")
        if cmd == "PAUSE":
            self.paused = True
            # 대기 중인 명령 폐기 (정지 중에 큐된 동작이 풀리지 않도록)
            self.current_command = None
        elif cmd == "RESUME":
            self.paused = False
        elif cmd == "RESET_HOME":
            self.paused = False
            self.current_command = None
            self.reset_home_pending = True

    def task_callback(self, msg):
        if msg.data and not self.task_completed:
            self.task_completed = True
            # voice phase 동안 들어왔을 수 있는 stale 플래그 초기화
            self.reset_home_pending = False
            self.paused = False
            self.get_logger().info("🚀 픽앤플레이스 완료 트리거 수신! 로봇 제어권을 인계받습니다.")

    def gesture_callback(self, msg):
        command = msg.data

        # 안전정지/비상정지 상태이면 제스처 명령 자체를 무시
        if self.paused:
            self.get_logger().info(f"🛡️ 안전모드 — 제스처 명령 무시: {command}")
            return

        # 💡 로봇이 이동 중이거나(두산 함수 실행 중), 이미 명령이 예약되어 있다면 무시
        if self.is_moving or self.current_command is not None:
            return

        # 이동 중이 아닐 때만 명령을 받아들임
        self.current_command = command
        self.get_logger().info(f"📥 명령 접수: {command}")

    def execute_reset_home(self):
        """대시보드 '처음으로' 트리거 시 즉시 HOME으로 복귀."""
        self.is_moving = True
        try:
            self.get_logger().warn("🔁 [RESET_HOME] HOME 좌표로 즉시 복귀")
            HOME_POS = [0, 0, 90, 0, 90, 0]
            self.dsr_movej(HOME_POS, vel=60, acc=60)
            self.get_logger().warn("✅ [RESET_HOME] HOME 복귀 완료")
            # Firebase 클라우드 리셋
            try:
                payload = [
                    ("start", False), ("end", False), ("voice_ok", False),
                    ("concept", ""), ("capture", False),
                    ("tool", {"black": False, "crown": False, "gun": False,
                              "hat": False, "pink": False, "wand": False}),
                ]
                for key, val in payload:
                    requests.put(f"{FIREBASE_BASE}/{key}.json", json=val, timeout=2)
                self.get_logger().warn("🛑 [RESET_HOME] Firebase 플래그 전체 리셋 완료")
            except Exception as e:
                self.get_logger().error(f"[RESET_HOME] Firebase 리셋 실패: {e}")
        except Exception as e:
            self.get_logger().error(f"[RESET_HOME] 실패: {e}")
        finally:
            self.is_moving = False
            self.current_command = None
            self.reset_home_pending = False

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

            # RESET_HOME 요청이 들어왔으면 우선 처리 (모든 일을 멈추고 HOME으로)
            if node.reset_home_pending:
                node.execute_reset_home()
                continue

            # 안전모드(일시정지/비상정지) 상태이면 아무 동작도 하지 않고 대기
            if node.paused:
                time.sleep(0.1)
                continue

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
                # 로봇을 이동시킵니다!
                node.execute_movement(node.current_command)
                
    except KeyboardInterrupt:
        node.get_logger().info("프로그램을 종료합니다.")
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == "__main__":
    main()
