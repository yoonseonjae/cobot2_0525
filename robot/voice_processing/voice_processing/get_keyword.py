# ros2 service call /get_keyword std_srvs/srv/Trigger "{}"

import os
import sys
import rclpy
import pyaudio
from rclpy.node import Node
from std_msgs.msg import Bool

from ament_index_python.packages import get_package_share_directory
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain.prompts import PromptTemplate  # d2 이거를 langchain_core로 바꿈
# from langchain.chains import LLMChain

from std_srvs.srv import Trigger
from voice_processing.MicController import MicController, MicConfig

from voice_processing.wakeup_word import WakeupWord
from voice_processing.stt import STT

sys.path.append(os.path.expanduser('~/cobot2_0525/robot'))
try:
    from firebase_client import update_node
except ImportError as e:
    print(f"firebase_client import error: {e}")

############ Package Path & Environment Setting ############

#----------------------------------------------------------------
# current_dir = os.getcwd()
# package_path = get_package_share_directory("pick_and_place_voice")

# env_path = "/home/rokey/cobot_ws/src/cobot2_ws/pick_and_place_voice/resource/.env"
# load_dotenv(dotenv_path=env_path)
# is_load = load_dotenv(dotenv_path=os.path.join(f"{package_path}/resource/.env"))
# openai_api_key = os.getenv("OPENAI_API_KEY")
#-----------------------------------------------------------------

PACKAGE_NAME = "voice_processing"
PACKAGE_PATH = get_package_share_directory(PACKAGE_NAME)
RESOURCE_PATH = os.path.join(PACKAGE_PATH, "resource")
ENV_PATH = os.path.join(RESOURCE_PATH, ".env")
load_dotenv(dotenv_path=ENV_PATH)
openai_api_key = os.getenv("OPENAI_API_KEY")

############ AI Processor ############
# class AIProcessor:
#     def __init__(self):



############ GetKeyword Node ############
class GetKeyword(Node):
    def __init__(self):

        print(PACKAGE_PATH, RESOURCE_PATH, ENV_PATH)


        self.llm = ChatOpenAI(
            model="gpt-4o", temperature=0.5, openai_api_key=openai_api_key
        )

# 나중에 단일 목적지 좌표 설정 예정
        prompt_content = """
            당신은 사용자의 문장에서 특정 도구(물건)와 목적지를 추출해야 합니다.

            <목표>
            - 문장에서 다음 리스트에 포함된 도구를 최대한 정확히 추출하세요.
            - 문장에 등장하는 도구의 목적지(어디로 옮기라고 했는지)도 함께 추출하세요.

            <도구 및 목적지 리스트>
            - 도구: pink, black, hat, wand, gun, crown, shovel
            - 목적지: pos1 (고정 단일 목적지)

            <출력 형식>
            - 반드시 "도구 / 목적지" 형태로만 출력하세요. 
            - 절대 대괄호나 추가적인 설명(예: "출력:", "결과:")을 텍스트에 포함하지 마세요.
            - 도구와 목적지는 각각 공백으로 구분
            - 도구가 없으면 앞쪽은 공백 없이 비우고, 목적지가 없으면 '/' 뒤는 공백 없이 비웁니다.

            <특수 규칙: 테마(Theme) 세트>
            - 사용자가 "해변" 또는 "해변가"와 관련된 맥락을 언급하면, 반드시 다음 두 가지 도구를 순서대로 출력하세요: black gun
            - 사용자가 "공주" 또는 "공주님"과 관련된 맥락(컨셉, 느낌 등)을 언급하면, 반드시 다음 두 가지 도구를 순서대로 출력하세요: wand crown
            - 사용자가 생일과 관련된 맥락(컨셉, 느낌 등)을 언급하면, 반드시 다음 두 가지 도구를 순서대로 출력하세요: hat pink
            - 사용자가 테마를 언급하거나 구체적인 목적지를 말하지 않은 경우, 기본적으로 목적지 부분에 pos1을 출력하세요.
            <예시>
            - 입력: "해변가를 배경으로 할거야"  
            출력: black gun / pos1

            - 입력: "공주님 느낌으로 꾸며줘"  
            출력: wand crown / pos1

            - 입력: "생일 느낌으로 꾸밀거야"  
            출력: hat pink / pos1

            <사용자 입력>
            "{user_input}"                
        """

        self.prompt_template = PromptTemplate(
            input_variables=["user_input"], template=prompt_content
        )
        self.lang_chain = self.prompt_template | self.llm
        # self.lang_chain = LLMChain(llm=self.llm, prompt=self.prompt_template)
        self.stt = STT(openai_api_key=openai_api_key)


        super().__init__("get_keyword_node")
        self.task_sub = self.create_subscription(Bool, '/dsr01/task_complete', self.task_callback, 10)
        # 오디오 설정
        mic_config = MicConfig(
            chunk=12000,
            rate=48000,
            channels=1,
            record_seconds=5,
            fmt=pyaudio.paInt16,
            device_index=10,
            buffer_size=24000,
        )
        self.mic_controller = MicController(config=mic_config)
        # self.ai_processor = AIProcessor()

        self.get_logger().info("MicRecorderNode initialized.")
        self.get_logger().info("wait for client's request...")
        self.get_keyword_srv = self.create_service(
            Trigger, "get_keyword", self.get_keyword
        )
        self.wakeup_word = WakeupWord(mic_config.buffer_size)

    def task_callback(self, msg):
        if msg.data:
            self.get_logger().info("Task complete signal received. Shutting down get_keyword node.")
            self.destroy_node()
            rclpy.shutdown()
            sys.exit(0)

    def extract_keyword(self, output_message):
            response = self.lang_chain.invoke({"user_input": output_message})
            result = response.content
            
            # 🔥 수정됨: GPT가 뱉은 날것의 문자열을 먼저 확인합니다.
            print(f"llm's raw response: '{result}'") 

            try:
                # '/' 기준으로 도구와 목적지 분리
                object_str, target_str = result.strip().split("/")
                
                object_list = object_str.split()
                target_list = target_str.split()
                
            except ValueError:
                # 혹시라도 GPT가 '/'를 안 줬을 때 멈추지 않도록 예외 처리
                print("경고: LLM 응답에 '/'가 포함되지 않았습니다.")
                object_list = []
                target_list = []

            print(f"object: {object_list}")
            print(f"target: {target_list}")
            
            # Firebase에 Concept(테마) 전송
            concept = ""
            if "black" in object_list or "gun" in object_list:
                concept = "beach"
            elif "wand" in object_list or "crown" in object_list:
                concept = "princess"
            elif "hat" in object_list or "pink" in object_list:
                concept = "birthday"
                
            if concept:
                try:
                    update_node("/concept.json", concept)
                    print(f"Firebase /concept.json = '{concept}' 전송")
                except Exception:
                    pass

            return object_list
    
    def get_keyword(self, request, response):  # 요청과 응답 객체를 받아야 함    # d2 이 함수 일부 수정함
        try:
            print("open stream")
            self.mic_controller.open_stream()
            self.wakeup_word.set_stream(self.mic_controller.stream)
        except OSError:
            self.get_logger().error("Error: Failed to open audio stream")
            self.get_logger().error("please check your device index")
            return None

        while not self.wakeup_word.is_wakeup():
            pass

        # 유효한 컨셉(해변/공주/생일)에 매핑되는 도구가 감지될 때까지 재시도.
        # - STT 결과가 비어 있음
        # - 도구 추출이 비어 있음
        # - 추출되었지만 어느 컨셉에도 매핑 안 됨 (예: 'shovel'만 감지)
        # 이런 경우 모두 STT를 다시 시도해 사용자가 다시 말할 수 있게 한다.
        CONCEPT_TRIGGERS = {"black", "gun", "wand", "crown", "hat", "pink"}
        keyword = []
        attempt = 0
        while True:
            attempt += 1
            self.get_logger().info(f"🎤 음성 인식 시도 #{attempt}")
            output_message = self.stt.speech2text()

            if not output_message or not output_message.strip():
                self.get_logger().warn(
                    "음성이 인식되지 않았습니다. '해변', '공주', '생일' 중 원하는 컨셉을 말씀해 주세요. (다시 듣는 중)"
                )
                continue

            keyword = self.extract_keyword(output_message)
            if any(k in CONCEPT_TRIGGERS for k in keyword):
                break  # 유효한 컨셉 감지 - 루프 종료

            self.get_logger().warn(
                f"컨셉을 알아듣지 못했어요 (인식 결과: '{output_message.strip()}'). "
                f"'해변', '공주', '생일' 중 하나로 다시 말씀해 주세요."
            )

        self.get_logger().warn(f"Detected tools: {keyword}")

        # 응답 객체 설정
        response.success = True
        response.message = " ".join(keyword)
        return response


def main():  # d2 메인문 일부 수정
    rclpy.init()
    node = GetKeyword()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
