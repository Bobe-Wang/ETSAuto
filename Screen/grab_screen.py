import numpy as np
import win32gui
import win32ui
import win32con
import os
import cv2


class ScreenGraber:
    def __init__(self):
        self.region = (0, 40, 1360, 807)
        self.image = None

    def update(self):
        hwin = win32gui.GetDesktopWindow()
        left, top, x2, y2 = self.region
        width = x2 - left + 1
        height = y2 - top + 1
        hwindc = win32gui.GetWindowDC(hwin)
        srcdc = win32ui.CreateDCFromHandle(hwindc)
        memdc = srcdc.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(srcdc, width, height)
        memdc.SelectObject(bmp)
        memdc.BitBlt((0, 0), (width, height), srcdc, (left, top), win32con.SRCCOPY)

        signedIntsArray = bmp.GetBitmapBits(True)
        self.image = np.frombuffer(signedIntsArray, dtype='uint8')
        self.image.shape = (height, width, 4)

        srcdc.DeleteDC()
        memdc.DeleteDC()
        win32gui.ReleaseDC(hwin, hwindc)
        win32gui.DeleteObject(bmp.GetHandle())
        return self.image

    def publish(self, project_path):
        if self.image is not None:
            np.save(os.path.join(project_path, "temp/screen.npy"), self.image)
