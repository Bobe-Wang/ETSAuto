import warnings
import os
import sys
import time
import cv2
import numpy as np
from concurrent.futures import ThreadPoolExecutor

warnings.filterwarnings('ignore')
current_path = os.path.dirname(os.path.abspath(__file__))
project_path = os.path.abspath(os.path.join(current_path, '..'))
sys.path.insert(0, project_path)
from Perception.LaneDetection.lanedetector import Bev_Lanedet
from Perception.Screen.grab_screen import ScreenGraber
from Perception.Navigation.Navigation_Process import nav_process
from Common.iodata import load_pkl, save_pkl

nav_line = None
lane_path = os.path.abspath(os.path.join(project_path, 'weights/ep049.onnx'))
lanedet = Bev_Lanedet(lane_path)
screengraber = ScreenGraber()
fps = 0.05
fps_list = []
im0 = screengraber.update()

i = 0
while True:
    t0 = time.time()
    option_dict = load_pkl(os.path.join(project_path, 'temp/option.pkl'))

    pool = ThreadPoolExecutor(max_workers=3)
    thread1 = pool.submit(lanedet.infer, im0)
    thread2 = pool.submit(screengraber.update)
    # thread3 = pool.submit(nav_process, cv2.cvtColor(im0[610:740, 580:780, :], cv2.COLOR_RGB2BGR))
    im0 = thread2.result()
    # nav_line = thread3.result()
    pool.shutdown()

    '''
    bevmap = np.zeros((300, 120))
    if len(nav_line):
        for nav_pt in nav_line:
            cv2.circle(bevmap, (60 + int(nav_pt[1]*6), 300-int(nav_pt[0]*6)), radius=1, color=(100, 100, 100),
                       thickness=-1)
    cv2.imshow('bevmap', bevmap)
    '''
    t1 = time.time()
    fps = t1 - t0
    if len(fps_list) == 10:
        fps_list.pop(0)
    fps_list.append(fps*1000)
    print('fps', fps)

    if option_dict is not None and option_dict['power'] == 0:
        cv2.destroyAllWindows()
        time.sleep(0.1)
        break
