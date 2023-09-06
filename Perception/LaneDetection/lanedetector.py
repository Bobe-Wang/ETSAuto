import numpy as np
import cv2
import os
import time
import sys
import math
import onnxruntime
import albumentations as A


current_path = os.path.dirname(os.path.abspath(__file__))
project_path = os.path.abspath(os.path.join(current_path, '../..'))
sys.path.insert(0, project_path)
from Perception.LaneDetection.lib.postprocess import sigmoid, bev_instance2points
from Perception.LaneDetection.lib.cluster import embedding_post
from Perception.LaneDetection.lib.normalize import horizontal_rounding, get_skeleton
from Common.iodata import save_pkl


class Bev_Lanedet(object):
    def __init__(self, onnx_path):
        self.session = onnxruntime.InferenceSession(onnx_path, providers=['CUDAExecutionProvider',
                                                                          'CPUExecutionProvider'])
        self.input_name = self.session.get_inputs()[0].name
        self.output0_name = self.session.get_outputs()[0].name
        self.output1_name = self.session.get_outputs()[1].name
        self.output2_name = self.session.get_outputs()[2].name
        self.output3_name = self.session.get_outputs()[3].name

        self.input_shape = (240, 360)
        self.x_range = (3, 53)
        self.y_range = (-6, 6)
        self.meter_per_pixel = 0.5
        self.bev_shape = (
            int((self.x_range[1] - self.x_range[0]) / self.meter_per_pixel), int((self.y_range[1] - self.y_range[0]) / self.meter_per_pixel))
        self.trans_image = A.Compose([A.Resize(height=self.input_shape[0], width=self.input_shape[1]),
                                      A.Normalize()])

        self.post_conf = -0.7  # Minimum confidence on the segmentation map for clustering
        self.post_emb_margin = 6.0  # embeding margin of different clusters
        self.post_min_cluster_size = 15  # The minimum number of points in a cluster

        self.lane_width = 3.6  # 初始道路宽度

    def preprocess(self, img):
        img = img[50:640, :, :]
        transformed = self.trans_image(image=img)
        img = transformed["image"]
        img = np.expand_dims(img.transpose(2, 0, 1), axis=0)
        return img

    def line_completing(self, lines_temp):
        # 确认左右车道
        line_l = None
        line_r = None
        line_ll = None
        line_rr = None
        
        for i in range(len(lines_temp)):
            if lines_temp[i][0, 1] >= -self.lane_width * 2 and lines_temp[i][0, 1] < -self.lane_width:
                line_ll = lines_temp[i]
            elif lines_temp[i][0, 1] >= -self.lane_width and lines_temp[i][0, 1] < 0:
                line_l = lines_temp[i]
            elif lines_temp[i][0, 1] >= 0 and lines_temp[i][0, 1] < self.lane_width:
                line_r = lines_temp[i]
            elif lines_temp[i][0, 1] >= self.lane_width and lines_temp[i][0, 1] <= self.lane_width * 2:
                line_rr = lines_temp[i]

        if line_l is None and line_r is not None:
            line_l = line_r - [0, self.lane_width]
        elif line_l is not None and line_r is None:
            line_r = line_l + [0, self.lane_width]
        elif line_l is not None and line_r is not None:
            if line_r[0, 1] - line_l[0, 1] >= self.lane_width * 1.2:
                if abs(line_l[0, 1]) >= abs(line_r[0, 1]):
                    line_l = line_r - [0, self.lane_width]
                else:
                    line_r = line_l + [0, self.lane_width]
            # 确认车道宽度
            widths = []
            width_i = None
            for i in range(110):
                pt_l = line_l[np.where(line_l == i / 2)[0]]
                pt_r = line_r[np.where(line_r == i / 2)[0]]
                if len(pt_l) and len(pt_r):
                    width_i = abs(pt_l[0, 1] - pt_r[0, 1])
                    widths.append(width_i)

                elif len(pt_l) and len(pt_r) == 0:
                    if width_i is not None:
                        pt_r = pt_l + [[0, width_i]]
                    else:
                        pt_r = pt_l + [[0, self.lane_width]]
                    line_r = np.concatenate((line_r, pt_r), axis=0)

                elif len(pt_l) == 0 and len(pt_r):
                    if width_i is not None:
                        pt_l = pt_r - [[0, width_i]]
                    else:
                        pt_l = pt_r - [[0, self.lane_width]]
                    line_l = np.concatenate((line_l, pt_l), axis=0)

            widths = np.array(widths)
            if len(widths):
                width_avg = np.average(widths)
                if abs(self.lane_width - width_avg) <= 0.2 and width_avg <= 3.8:
                    self.lane_width = (self.lane_width + width_avg) / 2
                else:
                    self.lane_width = width_avg
            
        if line_l is not None:
            if line_ll is not None:
                line_ll = line_l - [0, self.lane_width]
            if line_rr is not None:
                line_rr = line_r + [0, self.lane_width]

        if self.lane_width > 3.8:
            self.lane_width = 3.8
        elif self.lane_width < 3.5:
            self.lane_width = 3.5

        if line_l is not None:
            line_l = line_l[np.lexsort(line_l[:, ::-1].T)]
            line_r = line_r[np.lexsort(line_r[:, ::-1].T)]
        return line_l, line_r, line_ll, line_rr

    def infer(self, img):
        img = self.preprocess(img)
        pred_ = self.session.run([self.output0_name,
                                  self.output1_name,
                                  self.output2_name,
                                  self.output3_name,
                                  ], {self.input_name: img})
        seg = pred_[0]
        embedding = pred_[1]
        offset_y = sigmoid(pred_[2])

        prediction = (seg, embedding)
        canvas, ids = embedding_post(prediction, self.post_conf, emb_margin=self.post_emb_margin,
                                     min_cluster_size=self.post_min_cluster_size)
        offset_y = offset_y[0][0]
        lines = bev_instance2points(canvas, max_x=self.x_range[1],
                                    meter_per_pixal=(self.meter_per_pixel, self.meter_per_pixel),
                                    offset_y=offset_y)

        lines_temp = []  # 横轴取整
        for line in lines:
            line_temp = horizontal_rounding(line)
            lines_temp.append(line_temp)

        line_l, line_r, line_ll, line_rr = self.line_completing(lines_temp)  # 车道线补全

        line_m = get_skeleton(line_l, line_r)  # 计算道路骨架

        self.publish(line_l, line_r, line_ll, line_rr, line_m)
    
    def publish(self, line_l, line_r, line_ll, line_rr, line_m):
        lane_dict = {'line_l': line_l, 'line_r': line_r, 
                     'line_ll': line_ll, 'line_rr': line_rr, 
                     'line_m': line_m, 'lane_width': self.lane_width}
        save_pkl(os.path.join(project_path, 'temp/line.pkl'), lane_dict)
