import time
import cv2
import os
import sys
import numpy as np
import onnxruntime

current_path = os.path.dirname(os.path.abspath(__file__))
project_path = os.path.abspath(os.path.join(current_path, '../..'))
sys.path.insert(0, project_path)
from Common.iodata import save_pkl
from Perception.ObjectDetection.lib.utils import xywh2xyxy,  multiclass_nms
from Perception.ObjectDetection.lib.transform import Cam_Transform


class YOLOv8:
    def __init__(self, path):
        self.session = onnxruntime.InferenceSession(path, providers=['CUDAExecutionProvider',
                                                                     'CPUExecutionProvider'])
        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name
        self.conf_threshold = 0.5
        self.iou_threshold = 0.5
        self.input_shape = (768, 1360)
        self.size = (640, 640)
        self.classes = ['car', 'bus', 'truck', 'tl_green', 'tl_red', 'tl_yellow']
        self.tracks_list = [{0: []}, {0: []}, {0: []}]
        self.cam = Cam_Transform()
        self.bev_range = np.array([[0, 50], [-6, 6]])
        self.bev_size = (50, 12)

    def infer(self, img):
        img = self.preprocess(img)
        outputs = self.session.run([self.output_name], {self.input_name: img})
        objects = self.process_output(outputs)
        self.publish(objects)

    def preprocess(self, img):
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img = cv2.resize(img, (self.size[1], self.size[0]))
        img = img / 255.0
        img = img.transpose(2, 0, 1)
        img = np.expand_dims(img, axis=0).astype(np.float32)
        return img

    def process_output(self, output):
        predictions = np.squeeze(output[0]).T
        scores = np.max(predictions[:, 4:], axis=1)
        predictions = predictions[scores > self.conf_threshold, :]
        scores = scores[scores > self.conf_threshold]
        if len(scores) == 0:
            return None
        class_ids = np.argmax(predictions[:, 4:], axis=1)
        boxes = self.extract_boxes(predictions)
        indices = multiclass_nms(boxes, scores, class_ids, self.iou_threshold)
        boxes, scores, class_ids = boxes[indices], scores[indices], class_ids[indices]
        objects = []
        objects_ids = []
        objects_scores = []
        for i in range(len(class_ids)):
            if class_ids[i] in [0, 1, 2]:
                objects.append(boxes[i])
                objects_ids.append(class_ids[i])
                objects_scores.append(scores[i])
        objects = np.array(objects)
        objects_ids = np.array(objects_ids)

        objects = np.hstack(((objects[:, 2:3] + objects[:, 0:1])/2, objects[:, 3:4]))
        objects_bev = self.cam.pixel_to_world(objects)
        for i in reversed(range(len(objects_bev))):
            if objects_bev[i, 0] < self.bev_range[0, 0] or objects_bev[i, 0] >= self.bev_range[0, 1] or objects_bev[i, 1] < self.bev_range[1, 0] or objects_bev[i, 1] >= self.bev_range[1, 1]:
                objects_bev = np.delete(objects_bev, i, axis=0)
                objects_ids = np.delete(objects_ids, i, axis=0)
        objects = np.concatenate((objects_bev, objects_ids.reshape(objects_bev.shape[0], 1)), axis=1)
        objects = np.array(objects)
        return objects

    def extract_boxes(self, predictions):
        boxes = predictions[:, :4]
        boxes = self.rescale_boxes(boxes)
        boxes = xywh2xyxy(boxes)
        return boxes

    def rescale_boxes(self, boxes):
        input_shape = np.array([self.size[1], self.size[0], self.size[1], self.size[0]])
        boxes = np.divide(boxes, input_shape, dtype=np.float32)
        boxes *= np.array([self.input_shape[1], self.input_shape[0], self.input_shape[1], self.input_shape[0]])
        return boxes
    
    def image_to_bev(self, objects):
        if objects is not None:
             objects_bev = self.transform.pixel_to_world(objects)
             for i in reversed(range(len(objects_bev))):
                 if objects_bev[i, 0] < self.bev_range[0, 0] or objects_bev[i, 0] >= self.bev_range[0, 1] or objects_bev[i, 1] < self.bev_range[1, 0] or objects_bev[i, 1] >= self.bev_range[1, 1]:
                     objects_bev = np.delete(objects_bev, i, axis=0)
        else:
            objects_bev = None
        return objects_bev
    
    def publish(self, objects):
        dets_dict = {'objects': objects}
        save_pkl(os.path.join(project_path, 'temp/dets.pkl'), dets_dict)

                 

