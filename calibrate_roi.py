"""
ROI标定工具 — 交互式绘制车道掩膜 + 多段折线绊线
用法: python calibrate_roi.py --camera south

操作:
  1. 左键添加车道掩膜(lane_mask)多边形顶点, 右键闭合
  2. 按'a'画绊线A(进入线): 左键多点形成折线, 右键完成
  3. 按'b'画绊线B(计数线): 左键多点形成折线, 右键完成
  4. 按'z'画排除区多边形(可选), 右键闭合
  5. 按's'保存, 'r'重置, 'backspace'撤销最后一点, 'q'退出
"""
import argparse
import cv2
import yaml
import os
import sys
import numpy as np
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent


class ROICalibrator:
    """交互式标定器 — lane_mask + tripwire"""

    MODE_LANE = "lane_mask"       # 画车道多边形
    MODE_WIRE_A = "tripwire_a"    # 画绊线A
    MODE_WIRE_B = "tripwire_b"    # 画绊线B
    MODE_EXCLUSION = "exclusion"  # 画排除区

    def __init__(self, video_path, camera_name):
        self.cap = cv2.VideoCapture(video_path)
        if not self.cap.isOpened():
            raise FileNotFoundError(f"无法打开视频: {video_path}")

        self.camera_name = camera_name
        ret, self.frame = self.cap.read()
        if not ret:
            raise RuntimeError("无法读取视频帧")
        self.cap.release()

        self.h, self.w = self.frame.shape[:2]
        self.frame = cv2.resize(self.frame, (1280, int(1280 * self.h / self.w)))
        self.display_h, self.display_w = self.frame.shape[:2]

        # 标定数据
        self.lane_mask = []        # 车道掩膜顶点
        self.lane_closed = False   # 多边形是否闭合
        self.tripwire_a = []       # [p1, p2]
        self.tripwire_b = []       # [p1, p2]
        self.exclusion_zones = []  # 排除区列表
        self.current_exclusion = []

        self.mode = self.MODE_LANE
        self.temp_point = None

        # 加载已有配置(如果存在)
        self._load_existing_config()

        cv2.namedWindow("ROI Calibrator", cv2.WINDOW_NORMAL)
        cv2.setMouseCallback("ROI Calibrator", self._mouse_callback)

        loaded = "已加载" if self.lane_closed else "未找到"
        print(f"\n{'='*60}")
        print(f"   ROI标定工具 — 相机: {camera_name} ({loaded}已有配置)")
        print(f"{'='*60}")
        print("操作说明:")
        print("  左键: 添加顶点 (绊线模式支持多点折线)")
        print("  右键: 完成当前折线/闭合多边形")
        print("  'a': 切换到绊线A模式(进入线)")
        print("  'b': 切换到绊线B模式(计数线)")
        print("  'z': 切换到排除区模式")
        print("  'l': 切换回车道掩膜模式")
        print("  Backspace: 撤销最后一点")
        print("  's': 保存配置 / 'r': 重置全部 / 'q': 退出")
        print(f"  显示分辨率: {self.display_w}x{self.display_h}")
        print(f"  保存坐标自动归一化到原始分辨率")
        print(f"{'='*60}\n")

    def _from_norm(self, nx, ny):
        """归一化坐标 → 显示坐标"""
        return int(nx * self.display_w), int(ny * self.display_h)

    def _to_norm(self, x, y):
        """显示坐标 → 归一化坐标"""
        return round(x / self.display_w, 4), round(y / self.display_h, 4)

    def _load_existing_config(self):
        config_file = SCRIPT_DIR / "config/camera_roi.yaml"
        if not config_file.exists():
            return
        with open(config_file, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        cfg = config.get("cameras", {}).get(self.camera_name)
        if not cfg:
            return

        # 加载lane_mask
        lm = cfg.get("lane_mask", [])
        if lm and len(lm) >= 6:
            pts = [(int(lm[i] * self.display_w), int(lm[i+1] * self.display_h))
                   for i in range(0, len(lm), 2)]
            self.lane_mask = pts
            self.lane_closed = True

        # 加载tripwire_a (支持折线: 任意偶数个归一化坐标)
        twa = cfg.get("tripwire_a", [])
        if twa and len(twa) >= 4 and len(twa) % 2 == 0:
            self.tripwire_a = [self._from_norm(twa[i], twa[i+1])
                              for i in range(0, len(twa), 2)]

        # 加载tripwire_b (支持折线)
        twb = cfg.get("tripwire_b", [])
        if twb and len(twb) >= 4 and len(twb) % 2 == 0:
            self.tripwire_b = [self._from_norm(twb[i], twb[i+1])
                              for i in range(0, len(twb), 2)]

        # 加载exclusion_zones
        for zone in cfg.get("exclusion_zones", []):
            poly = zone.get("poly", [])
            if poly:
                pts = [(int(poly[i] * self.display_w),
                        int(poly[i+1] * self.display_h))
                       for i in range(0, len(poly), 2)]
                self.exclusion_zones.append(pts)

    def _mouse_callback(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            if self.mode == self.MODE_LANE and not self.lane_closed:
                self.lane_mask.append((x, y))
                nx, ny = self._to_norm(x, y)
                print(f"  lane_mask顶点{len(self.lane_mask)}: ({nx}, {ny})")
            elif self.mode == self.MODE_WIRE_A:
                self.tripwire_a.append((x, y))
                nx, ny = self._to_norm(x, y)
                print(f"  tripwire_a 顶点{len(self.tripwire_a)}: ({nx}, {ny})")
            elif self.mode == self.MODE_WIRE_B:
                self.tripwire_b.append((x, y))
                nx, ny = self._to_norm(x, y)
                print(f"  tripwire_b 顶点{len(self.tripwire_b)}: ({nx}, {ny})")
            elif self.mode == self.MODE_EXCLUSION:
                self.current_exclusion.append((x, y))
                nx, ny = self._to_norm(x, y)
                print(f"  exclusion顶点{len(self.current_exclusion)}: ({nx}, {ny})")

        elif event == cv2.EVENT_RBUTTONDOWN:
            if self.mode == self.MODE_LANE and len(self.lane_mask) >= 3:
                self.lane_closed = True
                print("  lane_mask闭合! 按'a'切换到绊线A")
            elif self.mode == self.MODE_WIRE_A and len(self.tripwire_a) >= 2:
                print(f"  tripwire_a完成! ({len(self.tripwire_a)}点折线) 按's'保存")
            elif self.mode == self.MODE_WIRE_B and len(self.tripwire_b) >= 2:
                print(f"  tripwire_b完成! ({len(self.tripwire_b)}点折线) 按's'保存")
            elif self.mode == self.MODE_EXCLUSION and len(self.current_exclusion) >= 3:
                self.exclusion_zones.append(self.current_exclusion[:])
                print(f"  exclusion闭合! 共{len(self.exclusion_zones)}个排除区")
                self.current_exclusion = []

    def run(self):
        print("开始标定...\n")

        while True:
            display = self.frame.copy()

            # 绘制车道掩膜
            if len(self.lane_mask) >= 2:
                pts = np.array(self.lane_mask, np.int32)
                if self.lane_closed:
                    overlay = display.copy()
                    cv2.fillPoly(overlay, [pts], (0, 255, 0))
                    display = cv2.addWeighted(display, 0.7, overlay, 0.3, 0)
                    cv2.polylines(display, [pts], True, (0, 255, 0), 2)
                else:
                    cv2.polylines(display, [pts], False, (0, 255, 255), 2)
            for p in self.lane_mask:
                cv2.circle(display, p, 4, (0, 255, 0), -1)

            # 绘制绊线A (多段折线)
            if len(self.tripwire_a) >= 2:
                pts_a = np.array(self.tripwire_a, np.int32)
                cv2.polylines(display, [pts_a], False, (0, 255, 255), 2)
                cv2.putText(display, "ENTRY A", self.tripwire_a[0],
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
            for p in self.tripwire_a:
                cv2.circle(display, p, 5, (0, 200, 200), -1)

            # 绘制绊线B (多段折线)
            if len(self.tripwire_b) >= 2:
                pts_b = np.array(self.tripwire_b, np.int32)
                cv2.polylines(display, [pts_b], False, (0, 0, 255), 2)
                cv2.putText(display, "COUNT B", self.tripwire_b[0],
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
            for p in self.tripwire_b:
                cv2.circle(display, p, 5, (0, 0, 200), -1)

            # 绘制当前排除区
            if len(self.current_exclusion) >= 2:
                cv2.polylines(display, [np.array(self.current_exclusion, np.int32)],
                              False, (0, 255, 255), 1)
            for i, zone in enumerate(self.exclusion_zones):
                if len(zone) >= 2:
                    cv2.polylines(display, [np.array(zone, np.int32)],
                                  True, (0, 0, 255), 1)

            # 状态栏
            mode_names = {self.MODE_LANE: "车道掩膜 lane_mask", self.MODE_WIRE_A: "绊线A(进入线)",
                          self.MODE_WIRE_B: "绊线B(计数线)", self.MODE_EXCLUSION: "排除区"}
            status = f"Mode: {mode_names[self.mode]} | Camera: {self.camera_name}"
            cv2.putText(display, status, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)

            # 状态清单
            y = 50
            checks = [
                f"lane_mask: {'OK' if self.lane_closed else '...'} ({len(self.lane_mask)}pts)",
                f"tripwire_a: {'OK' if len(self.tripwire_a)>=2 else '...'} ({len(self.tripwire_a)}pts)",
                f"tripwire_b: {'OK' if len(self.tripwire_b)>=2 else '...'} ({len(self.tripwire_b)}pts)",
                f"exclusion: {len(self.exclusion_zones)} zones",
            ]
            for c in checks:
                cv2.putText(display, c, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)
                y += 18

            cv2.imshow("ROI Calibrator", display)
            key = cv2.waitKey(20) & 0xFF

            if key == ord('q'):
                break
            elif key == ord('a'):
                self.mode = self.MODE_WIRE_A
                self.tripwire_a = []
                print(">>> 绊线A: 左键多点画折线, 右键完成 (已清除旧线)")
            elif key == ord('b'):
                self.mode = self.MODE_WIRE_B
                self.tripwire_b = []
                print(">>> 绊线B: 左键多点画折线, 右键完成 (已清除旧线)")
            elif key == ord('z'):
                self.mode = self.MODE_EXCLUSION
                self.current_exclusion = []
                print(">>> 切换到排除区: 左键画顶点, 右键闭合")
            elif key == ord('l'):
                self.mode = self.MODE_LANE
                print(">>> 切换回车道掩膜模式")
            elif key == 8:  # Backspace
                self._undo_last_point()
            elif key == ord('s'):
                self._save_config()
            elif key == ord('r'):
                self.lane_mask = []
                self.lane_closed = False
                self.tripwire_a = []
                self.tripwire_b = []
                self.exclusion_zones = []
                self.current_exclusion = []
                self.mode = self.MODE_LANE
                print(">>> 已重置全部")

        cv2.destroyAllWindows()

    def _undo_last_point(self):
        if self.mode == self.MODE_LANE and self.lane_mask:
            p = self.lane_mask.pop()
            print(f"  撤销 lane_mask 顶点 ({len(self.lane_mask)} pts)")
        elif self.mode == self.MODE_WIRE_A and self.tripwire_a:
            p = self.tripwire_a.pop()
            print(f"  撤销 tripwire_a 顶点 ({len(self.tripwire_a)} pts)")
        elif self.mode == self.MODE_WIRE_B and self.tripwire_b:
            p = self.tripwire_b.pop()
            print(f"  撤销 tripwire_b 顶点 ({len(self.tripwire_b)} pts)")
        elif self.mode == self.MODE_EXCLUSION and self.current_exclusion:
            p = self.current_exclusion.pop()
            print(f"  撤销 exclusion 顶点 ({len(self.current_exclusion)} pts)")

    def _save_config(self):
        if not self.lane_closed:
            print("!!! lane_mask未完成, 请右键闭合多边形")
            return
        if len(self.tripwire_a) < 2:
            print("!!! tripwire_a未完成, 至少需要2个点")
            return
        if len(self.tripwire_b) < 2:
            print("!!! tripwire_b未完成, 至少需要2个点")
            return

        # 归一化
        lane_norm = [float(v) for p in self.lane_mask
                     for v in self._to_norm(p[0], p[1])]
        twa_norm = [float(v) for p in self.tripwire_a
                    for v in self._to_norm(p[0], p[1])]
        twb_norm = [float(v) for p in self.tripwire_b
                    for v in self._to_norm(p[0], p[1])]

        excl_list = []
        for zone in self.exclusion_zones:
            zn = [float(v) for p in zone for v in self._to_norm(p[0], p[1])]
            excl_list.append({"poly": zn, "name": "exclusion"})

        config_file = SCRIPT_DIR / "config/camera_roi.yaml"
        if os.path.exists(config_file):
            with open(config_file, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
        else:
            config = {"cameras": {}, "anomaly": {"wrong_way_angle_tolerance": 50}}

        if "cameras" not in config:
            config["cameras"] = {}

        config["cameras"][self.camera_name] = {
            "lane_mask": lane_norm,
            "tripwire_a": twa_norm,
            "tripwire_b": twb_norm,
            "exclusion_zones": excl_list,
        }

        with open(config_file, 'w', encoding='utf-8') as f:
            yaml.safe_dump(config, f, allow_unicode=True, default_flow_style=False)

        print(f"\n  CONFIG SAVED -> {config_file}")
        print(f"  lane_mask: {lane_norm}")
        print(f"  tripwire_a: {twa_norm}")
        print(f"  tripwire_b: {twb_norm}")
        print(f"  exclusion_zones: {len(excl_list)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ROI标定工具 - lane_mask + tripwire")
    parser.add_argument("--camera", type=str, required=True,
                        choices=["south", "north", "east"],
                        help="相机名称")
    parser.add_argument("--video", type=str, default=None,
                        help="视频路径(可选)")
    args = parser.parse_args()

    if args.video:
        video_path = args.video
    else:
        video_dir = SCRIPT_DIR.parent / "resources"
        camera_map = {"south": "南进口", "north": "北进口", "east": "东进口"}
        prefix = camera_map[args.camera]
        for f in video_dir.glob(f"{prefix}*.mp4"):
            video_path = str(f)
            break
        else:
            print(f"错误: 未找到{prefix}的视频文件 (搜索路径: {video_dir})")
            sys.exit(1)

    calib = ROICalibrator(video_path, args.camera)
    calib.run()
