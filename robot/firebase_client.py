import requests
import socket
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("FirebaseClient")

BASE_URL = "https://rokey-coop2-default-rtdb.asia-southeast1.firebasedatabase.app"

def get_local_ip():
    """자신의 로컬 네트워크(Wi-Fi 등) IP를 반환합니다."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # 구글 퍼블릭 DNS 서버에 더미 연결 시도하여 라우팅된 로컬 IP 추출
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception as e:
        logger.error(f"IP 파악 실패: {e}")
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

def update_node(path, data):
    """
    Firebase 특정 경로의 데이터를 PUT으로 덮어씁니다.
    path: 예) '/start.json', '/tool.json'
    """
    url = f"{BASE_URL}{path}"
    try:
        response = requests.put(url, json=data, timeout=2)
        response.raise_for_status()
        # logger.info(f"[Firebase PUT] {path} <- {data}")
        return True
    except requests.RequestException as e:
        logger.error(f"[Firebase Error] PUT {path} 실패: {e}")
        return False

def patch_node(path, data):
    """
    Firebase 특정 경로의 데이터를 PATCH로 업데이트합니다. (기존 데이터 유지, 전달된 키만 갱신)
    """
    url = f"{BASE_URL}{path}"
    try:
        response = requests.patch(url, json=data, timeout=2)
        response.raise_for_status()
        # logger.info(f"[Firebase PATCH] {path} <- {data}")
        return True
    except requests.RequestException as e:
        logger.error(f"[Firebase Error] PATCH {path} 실패: {e}")
        return False

def get_node(path):
    """
    Firebase 특정 경로의 데이터를 GET으로 읽어옵니다.
    """
    url = f"{BASE_URL}{path}"
    try:
        response = requests.get(url, timeout=2)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logger.error(f"[Firebase Error] GET {path} 실패: {e}")
        return None
