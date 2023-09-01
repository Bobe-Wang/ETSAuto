import os
import sys
import math
import numpy as np
current_path = os.path.dirname(os.path.abspath(__file__))
project_path = os.path.abspath(os.path.join(current_path, '../..'))
sys.path.insert(0, project_path)
from Control.optimizers.bazier_optimizer import point_on_bezier_curve
from Control.transform import update_trajectory
from Common.iodata import save_pkl
from Control.planregister import PlanRegister


defaut_change_distance = 30


class ChangeLane_Helper:
    def __init__(self):
        self.lane_change_state = 0
        self.trajectory_change = None
        self.change_distance = defaut_change_distance
        self.hist_lane_l = None
    
    def plan_change_start(self, trajectory, option_dict, lane_width):
        trajectory_theta = np.arctan((trajectory[3, 1] - trajectory[0, 1]) / (trajectory[3, 0] - trajectory[0, 0]))
        if option_dict['desire'] == 3:
            line_target = trajectory - [[-lane_width * np.sin(trajectory_theta), lane_width * np.cos(trajectory_theta)]]
        else:
            line_target = trajectory + [[-lane_width * np.sin(trajectory_theta), lane_width * np.cos(trajectory_theta)]]

        P0 = [0, 0]
        P1 = trajectory[5, :]
        P2 = line_target[5 + self.change_distance * 2, :]
        P3 = line_target[5 + self.change_distance * 2 + 5, :]

        a = 2 / 5
        Ay = P1[1]
        Ax = P1[0] + a * (P2[0] - P0[0])
        A = np.array([Ax, Ay])

        b = 2 / 5
        By = P2[1]
        Bx = P2[0] - b * (P3[0] - P1[0])
        B = np.array([Bx, By])

        ts = np.linspace(0, 1, self.change_distance * 2 + 1)

        Q = np.zeros((self.change_distance * 2 + 1, 2))
        for i, t in enumerate(ts):
            Q[i, :] = point_on_bezier_curve([P1, A, B, P2], t)
        self.trajectory_change = np.concatenate((trajectory[:5, :], Q), axis=0)

        pts_x = np.linspace(0, math.ceil(self.trajectory_change[-1, 0]), math.ceil(self.trajectory_change[-1, 0]) * 2 + 1)
        fit_m = np.polyfit(self.trajectory_change[:, 0], self.trajectory_change[:, 1], 3)
        pts_m_y = fit_m[0] * pts_x ** 3 + fit_m[1] * pts_x ** 2 + fit_m[2] * pts_x + fit_m[3]
        self.trajectory_change = np.concatenate((pts_x.reshape((-1, 1)), pts_m_y.reshape((-1, 1))), axis=1)

    def plan_change_subject(self, trajectory, line_l, lane_width, option_dict, condition_dict):
        self.trajectory_change = update_trajectory(self.trajectory_change, condition_dict)
        
        trajectory_theta = np.arctan((trajectory[3, 1] - trajectory[0, 1]) / (trajectory[3, 0] - trajectory[0, 0]))

        if option_dict['desire'] == 3:
            line_target = trajectory - [[-lane_width * np.sin(trajectory_theta), lane_width * np.cos(trajectory_theta)]]
        else:
            line_target = trajectory + [[-lane_width * np.sin(trajectory_theta), lane_width * np.cos(trajectory_theta)]]
        
        trajectory_total = np.vstack((self.trajectory_change[:-10, :], line_target[math.ceil(self.trajectory_change[-1, 0]) * 2 + 1:, :]))

        pts_x = np.linspace(0, math.ceil(self.trajectory_change[-1, 0]), math.ceil(self.trajectory_change[-1, 0]) * 2 + 1)
        
        fit_m = np.polyfit(trajectory_total[:, 0], trajectory_total[:, 1], 3)
        pts_m_y = fit_m[0] * pts_x ** 3 + fit_m[1] * pts_x ** 2 + fit_m[2] * pts_x + fit_m[3]
        self.trajectory_change = np.concatenate((pts_x.reshape((-1, 1)), pts_m_y.reshape((-1, 1))), axis=1)
        
        self.check_state(line_l, condition_dict)
    

    def check_state(self, line_l, condition_dict):
        if line_l is not None and len(line_l) >= 30:
            if self.hist_lane_l is None:
                self.hist_lane_l = line_l
            elif self.hist_lane_l is not None and abs(np.average(self.hist_lane_l[:20, 1]) - np.average(line_l[:20, 1])) >= 2:
                self.lane_change_state = 2
                self.hist_lane_l = None
            else:
                self.hist_lane_l = line_l
            if self.hist_lane_l is not None:
                self.hist_lane_l = update_trajectory(self.hist_lane_l, condition_dict)

    
    def plan_change_end(self, trajectory, condition_dict):
        self.trajectory_change = update_trajectory(self.trajectory_change, condition_dict)

        trajectory_total = np.vstack(([[-1, 0]], trajectory[-20:-10, :]))

        pts_x = np.linspace(0, math.ceil(self.trajectory_change[-1, 0]), math.ceil(self.trajectory_change[-1, 0]) * 2 + 1)
        
        fit_m = np.polyfit(trajectory_total[:, 0], trajectory_total[:, 1], 3)
        pts_m_y = fit_m[0] * pts_x ** 3 + fit_m[1] * pts_x ** 2 + fit_m[2] * pts_x + fit_m[3]
        self.trajectory_change = np.concatenate((pts_x.reshape((-1, 1)), pts_m_y.reshape((-1, 1))), axis=1)
        if abs(trajectory[5, 1]) <= 0.5:
            self.trajectory_change = None
            self.lane_change_state = 3

    def update(self, trajectory, line_l, plan_register, lane_width, option_dict, condition_dict):
        if option_dict['desire'] in [3, 4]:
            if self.trajectory_change is None and self.lane_change_state == 0:  # 辅助变道规划
                plan_register = PlanRegister()
                self.lane_change_state = 1
                self.plan_change_start(trajectory, option_dict, lane_width)

            elif self.trajectory_change is not None and self.lane_change_state == 1:
                self.plan_change_subject(trajectory, line_l, lane_width, option_dict, condition_dict)
            
            elif self.trajectory_change is not None and self.lane_change_state == 2:
                self.plan_change_end(trajectory, condition_dict)
                self.publish()

        elif option_dict['desire'] not in [3, 4]:
            self.trajectory_change = None
            self.lane_change_state = 0
            self.publish()

        return self.trajectory_change, plan_register

    def publish(self):
        states_dict = {'lane_change_state': self.lane_change_state}
        save_pkl(os.path.join(project_path, 'temp/states.pkl'), states_dict)

            


