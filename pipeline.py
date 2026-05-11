"""
可编程管线 — 供 GUI / CLI 调用
"""
import cv2
import time
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from src.detector import VehicleDetector, FramePrefetcher
from src.tracker import ByteTracker
from src.roi_filter import ROIFilter
from src.data_processor import DataProcessor
from src.visualizer import Visualizer

OUTPUT_DIR = Path(__file__).parent / "output"


def _find_codec():
    import tempfile
    for codec_name in ("avc1", "mp4v", "XVID", "H264"):
        fourcc = cv2.VideoWriter_fourcc(*codec_name)
        test_path = os.path.join(tempfile.gettempdir(), "_codec_test.mp4")
        writer = cv2.VideoWriter(test_path, fourcc, 1, (100, 100))
        if writer.isOpened():
            writer.release()
            try:
                os.remove(test_path)
            except Exception:
                pass
            return codec_name
    return "mp4v"


class PipelineRunner:
    """交通流检测管线 — 可编程调用"""

    def __init__(self, model_name="yolo11x.pt", confidence=0.10, iou=0.65,
                 device="cuda:0", batch_size=8, resize_width=2560,
                 sample_interval=3, output_fps=20, tracker_lost_buffer=70,
                 high_thresh=0.35, match_thresh=0.2, low_match_thresh=0.45,
                 min_hits=2, progress_callback=None):
        self.model_name = model_name
        self.confidence = confidence
        self.iou = iou
        self.device = device
        self.batch_size = batch_size
        self.resize_width = resize_width
        self.sample_interval = sample_interval
        self.output_fps = output_fps
        self.tracker_lost_buffer = tracker_lost_buffer
        self.high_thresh = high_thresh
        self.match_thresh = match_thresh
        self.low_match_thresh = low_match_thresh
        self.min_hits = min_hits
        self.progress_callback = progress_callback

    def run(self, video_path, tripwire_a=None, tripwire_b=None,
            lane_mask=None, exclusion_zones=None, output_dir=None,
            output_video=True, output_scale=1.0):
        """
        运行管线
        - video_path: 视频文件路径
        - tripwire_a: 归一化平铺坐标 [x1,y1,x2,y2,...]
        - tripwire_b: 归一化平铺坐标
        - lane_mask: 归一化平铺坐标
        - exclusion_zones: [{poly:[...], name:"..."}]
        - output_dir: 输出目录，默认 OUTPUT_DIR
        - output_video: 是否生成输出视频
        - output_scale: 输出视频缩放比例
        Returns: dict with stats, output_video, charts, csv
        """
        out_dir = Path(output_dir) if output_dir else OUTPUT_DIR
        out_dir.mkdir(parents=True, exist_ok=True)

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise FileNotFoundError(f"无法打开视频: {video_path}")

        total_f = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps_in = cap.get(cv2.CAP_PROP_FPS)
        orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        rw = min(self.resize_width, orig_w)
        rh = int(orig_h * rw / orig_w)
        si = self.sample_interval

        detector = VehicleDetector(self.model_name, self.confidence, self.iou,
                                   self.device, self.batch_size)
        tracker = ByteTracker(self.tracker_lost_buffer, self.high_thresh,
                              self.match_thresh, self.low_match_thresh,
                              self.min_hits)

        # ROI filter
        roi = ROIFilter(lane_mask or [], (0, 360), None, rw, rh)
        if lane_mask:
            roi.set_lane_mask(lane_mask)
        if tripwire_a and len(tripwire_a) >= 4 and len(tripwire_a) % 2 == 0:
            roi.set_tripwire_a(*tripwire_a)
        if tripwire_b and len(tripwire_b) >= 4 and len(tripwire_b) % 2 == 0:
            roi.set_tripwire_b(*tripwire_b)
        for zone in (exclusion_zones or []):
            roi.add_exclusion_zone(zone["poly"], zone.get("name", ""))

        dp = DataProcessor()
        vis = Visualizer(True, True, True, str(out_dir))

        prefecth = FramePrefetcher(video_path, rw, rh, si, self.batch_size, 16)

        writer = None
        if output_video:
            ow = int(rw * output_scale)
            oh = int(rh * output_scale)
            codec = _find_codec()
            out_path = str(out_dir / "processed.mp4")
            writer = cv2.VideoWriter(out_path, cv2.VideoWriter_fourcc(*codec),
                                     self.output_fps, (ow, oh))
            if not writer.isOpened():
                writer = None

        total_processed = int(total_f / si) if total_f > 0 else 0
        proc, t0 = 0, time.time()
        last_print = 0

        try:
            while True:
                batch, indices = prefecth.get_batch()
                if not batch:
                    break

                dets_all = detector.detect_batch(batch)

                for i, dets in enumerate(dets_all):
                    roi._frame_idx = indices[i]

                    tracks = tracker.update(dets)

                    valid_tracks = []
                    for t in tracks:
                        bc = t.get("bottom_center", t["center"])
                        tid = t["track_id"]
                        in_lane = roi.is_inside_lane(bc)
                        crossed_a = roi._track_crossed_a.get(tid, False)
                        if (in_lane or crossed_a) and not roi.is_in_exclusion(bc):
                            valid_tracks.append(t)

                    if valid_tracks:
                        passed, _ = roi.update(valid_tracks)
                        for p in passed:
                            p["pass_frame"] = indices[i]
                            dp.add_record("camera", p, indices[i])

                    if indices[i] % 100 == 0:
                        active_tids = set(tracker.active_tracks.keys())
                        roi.cleanup_stale(active_tids)

                    if writer and indices[i] % 9 == 0:
                        fps_now = proc / (time.time() - t0 + 1e-8)
                        disp = vis.draw_detections(batch[i], tracks, roi, fps_now)
                        if output_scale != 1.0:
                            disp = cv2.resize(disp, (ow, oh))
                        writer.write(disp)

                proc += len(batch)

                if self.progress_callback and total_processed > 0:
                    pct = min(int(proc / total_processed * 100), 100)
                    self.progress_callback(pct)

                now = time.time()
                if now - last_print > 3:
                    last_print = now

        except KeyboardInterrupt:
            pass
        finally:
            prefecth.close()
            if writer:
                writer.release()

        elapsed = time.time() - t0
        stats = dp.compute_statistics("camera", total_f / fps_in if fps_in > 0 else 25)
        print(f"\n  DONE {proc}frames/{elapsed:.0f}s | count={stats.total_vehicles}")

        # 生成图表
        charts = vis.generate_charts({"camera": stats}, None)
        csv_path = str(out_dir / "traffic_report.csv")
        dp.generate_report({"camera": stats}, csv_path)

        result = {
            "stats": stats,
            "output_video": str(out_dir / "processed.mp4") if writer else None,
            "charts": charts,
            "csv": csv_path,
            "total_vehicles": stats.total_vehicles,
            "vehicles_by_type": stats.vehicles_by_type,
            "peak_hourly": stats.peak_hourly_flow,
            "peak_minute": stats.peak_minute_flow,
            "elapsed": elapsed,
            "frames_processed": proc,
            "fps": proc / elapsed if elapsed > 0 else 0,
        }
        return result
