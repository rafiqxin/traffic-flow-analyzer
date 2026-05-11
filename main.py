"""
主流程 — 硬ROI掩膜 + 双绊线(Tripwire)车辆计数
用法: python main.py --camera all --batch 16
"""
import argparse, cv2, yaml, os, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from src.detector import VehicleDetector, FramePrefetcher
from src.tracker import ByteTracker
from src.roi_filter import ROIFilter
from src.data_processor import DataProcessor
from src.visualizer import Visualizer

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"


def load_config():
    with open(BASE_DIR / "config/model_config.yaml", "r", encoding="utf-8") as f:
        mc = yaml.safe_load(f)
    with open(BASE_DIR / "config/camera_roi.yaml", "r", encoding="utf-8") as f:
        cc = yaml.safe_load(f)
    return mc, cc


def get_video(cam_name):
    cm = {"south": "南进口", "north": "北进口", "east": "东进口"}
    for f in (BASE_DIR / ".." / "resources").glob(f"{cm[cam_name]}*.mp4"):
        return str(f)
    raise FileNotFoundError(f"找不到{cm[cam_name]}视频")


def process(cam, mc, cc, args):
    print(f"\n{'='*55}\n  {cam}\n{'='*55}")

    cap = cv2.VideoCapture(get_video(cam))
    total_f = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps_in = cap.get(cv2.CAP_PROP_FPS)
    rw = mc["video"]["resize_width"]
    rh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) * rw / cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    si = mc["video"]["sample_interval"]

    detector = VehicleDetector("yolo11l.pt", mc["model"]["confidence"],
                                mc["model"]["iou"], args.device, args.batch)
    tracker = ByteTracker(mc["tracker"]["track_lost_buffer"],
                          high_thresh=0.35, match_thresh=0.2,
                          low_match_thresh=0.45, min_hits=2)

    cfg = cc["cameras"][cam]
    # ROI filter: lane_mask + tripwire (不再需要direction_range和origin配置)
    roi = ROIFilter(cfg.get("lane_mask") or cfg.get("approach_lane") or [],
                    (0, 360),  # direction range unused in tripwire mode
                    cfg.get("ignore_region"), rw, rh)

    # 设置车道掩膜
    if cfg.get("lane_mask"):
        roi.set_lane_mask(cfg["lane_mask"])

    # 设置双绊线
    tw_a = cfg.get("tripwire_a")
    tw_b = cfg.get("tripwire_b")
    if tw_a and len(tw_a) >= 4 and len(tw_a) % 2 == 0:
        roi.set_tripwire_a(*tw_a)
    if tw_b and len(tw_b) >= 4 and len(tw_b) % 2 == 0:
        roi.set_tripwire_b(*tw_b)

    # 排除区
    for zone in cfg.get("exclusion_zones", []):
        roi.add_exclusion_zone(zone["poly"], zone.get("name", ""))

    dp = DataProcessor()
    vis = Visualizer(True, True, True, str(OUTPUT_DIR / cam))

    # 帧预取器: 后台线程读帧+缩放, CPU/GPU并行
    prefecth = FramePrefetcher(get_video(cam), rw, rh, si, args.batch,
                               mc.get("prefetch", {}).get("max_queue", 24))

    # 输出视频 (编解码器回退链)
    writer = None
    if args.output:
        out_d = OUTPUT_DIR / cam
        out_d.mkdir(parents=True, exist_ok=True)
        ow = int(rw * args.output_scale)
        oh = int(rh * args.output_scale)
        out_path = str(out_d / f"processed_{cam}.mp4")
        for codec_name in ("avc1", "mp4v", "XVID", "H264"):
            fourcc = cv2.VideoWriter_fourcc(*codec_name)
            writer = cv2.VideoWriter(out_path, fourcc,
                                     mc["video"]["output_fps"], (ow, oh))
            if writer.isOpened():
                print(f"  codec: {codec_name}")
                break
            writer.release()
            writer = None
        if writer is None:
            print(f"  WARNING: 无可用编解码器, 跳过视频输出")

    total_f = prefecth.total_frames
    print(f"  {rw}x{rh} | batch={args.batch} | tripwire={tw_b is not None} | "
          f"prefetch | sample=1/{si}")

    proc, t0 = 0, time.time()
    last_print = 0

    try:
        while True:
            batch, indices = prefecth.get_batch()
            if not batch:
                break

            # GPU批量推理 (CPU预取下一批期间GPU满载)
            dets_all = detector.detect_batch(batch)

            # 逐帧: 追踪全量 → 硬ROI过滤 → 绊线计数
            for i, dets in enumerate(dets_all):
                roi._frame_idx = indices[i]

                # 第一步: 追踪所有检测 (保持轨迹连续性, 防止ID碎片化)
                tracks = tracker.update(dets)

                # 第二步: 硬ROI掩膜过滤 (已穿A线的转弯车给免死金牌)
                valid_tracks = []
                for t in tracks:
                    bc = t.get("bottom_center", t["center"])
                    tid = t["track_id"]
                    # 车道内 OR 已穿过A线的转弯车 → 允许存活至撞B线
                    in_lane = roi.is_inside_lane(bc)
                    crossed_a = roi._track_crossed_a.get(tid, False)
                    if (in_lane or crossed_a) and not roi.is_in_exclusion(bc):
                        valid_tracks.append(t)

                # 第三步: 绊线穿越检测 (只对车道内轨迹)
                if valid_tracks:
                    passed, _ = roi.update(valid_tracks)
                    for p in passed:
                        p["pass_frame"] = indices[i]
                        dp.add_record(cam, p, indices[i])

                # 定期清理过期记录
                if indices[i] % 100 == 0:
                    active_tids = set(tracker.active_tracks.keys())
                    roi.cleanup_stale(active_tids)

                # 输出视频
                if writer and indices[i] % 9 == 0:
                    fps_now = proc / (time.time() - t0 + 1e-8)
                    disp = vis.draw_detections(batch[i], tracks, roi, fps_now)
                    if args.output_scale != 1.0:
                        disp = cv2.resize(disp, (ow, oh))
                    writer.write(disp)

            proc += len(batch)
            now = time.time()
            if now - last_print > 3:
                last_print = now
                elapsed = now - t0
                fps = proc / elapsed if elapsed > 0 else 0
                pct = min(proc / (total_f / si) * 100, 100) if total_f > 0 else 0
                eta = (total_f / si - proc) / fps if fps > 0 else 0
                print(f"  {pct:.0f}% | {fps:.1f}fps | count={roi.total_count} | "
                      f"ETA:{eta:.0f}s", flush=True)

    except KeyboardInterrupt:
        print("\n  interrupted")
    finally:
        prefecth.close()
        if writer:
            writer.release()

    elapsed = time.time() - t0
    stats = dp.compute_statistics(cam, total_f / fps_in)
    print(f"\n  DONE {proc}frames/{elapsed:.0f}s={proc/elapsed:.1f}fps | "
          f"count={stats.total_vehicles} "
          f"(car:{stats.vehicles_by_type.get('car',0)} "
          f"bus:{stats.vehicles_by_type.get('bus',0)} "
          f"truck:{stats.vehicles_by_type.get('truck',0)} "
          f"moto:{stats.vehicles_by_type.get('motorcycle',0)})")
    return {"camera_name": cam, "data_processor": dp, "roi_filter": roi, "stats": stats}


def main():
    p = argparse.ArgumentParser(description="交通流检测")
    p.add_argument("--camera", default="south", choices=["south","north","east","all"])
    p.add_argument("--device", default="cuda:0")
    p.add_argument("--batch", type=int, default=16)
    p.add_argument("--output", action="store_true", default=True)
    p.add_argument("--no-output", action="store_true")
    p.add_argument("--output-scale", type=float, default=1.0)
    p.add_argument("--report", action="store_true", default=True)
    args = p.parse_args()
    if args.no_output:
        args.output = False

    print(f"{'='*55}\n  交通流检测 | batch={args.batch} | {args.device}\n{'='*55}")

    mc, cc = load_config()
    cams = ["south","north","east"] if args.camera == "all" else [args.camera]

    results = {}
    for cam in cams:
        r = process(cam, mc, cc, args)
        if r:
            results[cam] = r

    if len(results) > 1:
        print(f"\n{'='*55}\n  SUMMARY\n{'='*55}")
        total = sum(r["stats"].total_vehicles for r in results.values())
        print(f"  TOTAL: {total}")
        for cam, r in results.items():
            s = r["stats"]
            print(f"  {cam}: {s.total_vehicles} (car:{s.vehicles_by_type.get('car',0)} "
                  f"bus:{s.vehicles_by_type.get('bus',0)} "
                  f"truck:{s.vehicles_by_type.get('truck',0)} "
                  f"moto:{s.vehicles_by_type.get('motorcycle',0)})")

    if args.report and results:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        DataProcessor().generate_report(
            {r["camera_name"]: r["stats"] for r in results.values()},
            str(OUTPUT_DIR / "traffic_report.csv"))

    if args.output and results:
        Visualizer(output_dir=str(OUTPUT_DIR)).generate_charts(
            {r["camera_name"]: r["stats"] for r in results.values()}, None)
        print(f"\n  Output -> {OUTPUT_DIR}")

    print(f"\n{'='*55}\n  ALL DONE\n{'='*55}")


if __name__ == "__main__":
    main()
