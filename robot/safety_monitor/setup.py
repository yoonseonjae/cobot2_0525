from setuptools import find_packages, setup
import glob

package_name = 'safety_monitor'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/resource', glob.glob('resource/*')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='rokey',
    maintainer_email='rokey@todo.todo',
    description='USB webcam top-view safety zone monitor for Doosan M0609',
    license='Apache-2.0',
    extras_require={
        'test': ['pytest'],
    },
    entry_points={
        'console_scripts': [
            # 감지 노드 (OpenCV 창 포함 — 로컬 디버그용)
            'safety_monitor = safety_monitor.safety_monitor:main',
            # 영상 스트림 서버 (Flask MJPEG → 대시보드)
            'safety_stream_server = safety_monitor.safety_stream_server:main',
        ],
    },
)