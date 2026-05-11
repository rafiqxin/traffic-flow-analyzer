"""
交通流检测 GUI — Gradio Web 前端
用法: python gui_app.py
"""
import gradio as gr
import cv2
import numpy as np
import os
import sys
import tempfile
import threading
import queue
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pipeline import PipelineRunner

MODEL_CHOICES = ["yolo11n.pt", "yolo11s.pt", "yolo11m.pt", "yolo11l.pt", "yolo11x.pt"]


def extract_frame(video_path):
    """从视频提取中间帧用于标定"""
    if video_path is None:
        return None, "请先上传视频"
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None, "无法打开视频"
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    mid = total // 2
    cap.set(cv2.CAP_PROP_POS_FRAMES, mid)
    ret, frame = cap.read()
    cap.release()
    if not ret:
        return None, "读取帧失败"

    h, w = frame.shape[:2]
    # 缩放到适合显示的尺寸 (最大1200px宽)
    max_disp_w = 1200
    if w > max_disp_w:
        scale = max_disp_w / w
        frame = cv2.resize(frame, (max_disp_w, int(h * scale)))
    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    note = f"显示: {frame.shape[1]}x{frame.shape[0]} | 原始: {orig_w}x{orig_h} | 帧号: {mid}/{total}"
    return frame, note


def draw_overlay(img, lane_pts, wire_a_pts, wire_b_pts, lane_closed):
    """在截帧上绘制标定叠加"""
    if img is None:
        return img
    display = img.copy()
    for i, p in enumerate(lane_pts):
        cv2.circle(display, tuple(p), 6, (0, 255, 0), -1)
        if i > 0:
            cv2.line(display, tuple(lane_pts[i-1]), tuple(p), (0, 255, 255), 2)
    if lane_closed and len(lane_pts) >= 3:
        pts_arr = np.array(lane_pts, np.int32).reshape((-1, 1, 2))
        overlay = display.copy()
        cv2.fillPoly(overlay, [pts_arr], (0, 255, 0))
        display = cv2.addWeighted(display, 0.7, overlay, 0.3, 0)
        cv2.polylines(display, [pts_arr], True, (0, 255, 0), 2)
        cv2.line(display, tuple(lane_pts[-1]), tuple(lane_pts[0]), (0, 255, 0), 2)

    for i, p in enumerate(wire_a_pts):
        cv2.circle(display, tuple(p), 6, (0, 255, 255), -1)
        if i > 0:
            cv2.line(display, tuple(wire_a_pts[i-1]), tuple(p), (0, 255, 255), 2)

    for i, p in enumerate(wire_b_pts):
        cv2.circle(display, tuple(p), 6, (255, 0, 0), -1)
        if i > 0:
            cv2.line(display, tuple(wire_b_pts[i-1]), tuple(p), (255, 0, 0), 2)

    return display


def get_norm_coords(pts, img_w, img_h):
    flat = []
    for x, y in pts:
        flat.append(round(x / img_w, 4))
        flat.append(round(y / img_h, 4))
    return flat


# ── 标定事件处理 ──

def on_image_click(evt: gr.SelectData, img, mode, lane_pts, wire_a_pts, wire_b_pts, lane_closed):
    if img is None or evt is None:
        return img, lane_pts, wire_a_pts, wire_b_pts, lane_closed, ""
    x, y = int(evt.index[0]), int(evt.index[1])
    msg = ""
    if mode == "A线 (进入线)":
        wire_a_pts = wire_a_pts + [(x, y)]
        msg = f"A线 +{len(wire_a_pts)}点"
    elif mode == "B线 (计数线)":
        wire_b_pts = wire_b_pts + [(x, y)]
        msg = f"B线 +{len(wire_b_pts)}点"
    elif mode == "车道掩膜" and not lane_closed:
        lane_pts = lane_pts + [(x, y)]
        msg = f"车道 +{len(lane_pts)}点"
    result = draw_overlay(img, lane_pts, wire_a_pts, wire_b_pts, lane_closed)
    return result, lane_pts, wire_a_pts, wire_b_pts, lane_closed, msg


def on_finish(mode, lane_pts, wire_a_pts, wire_b_pts, lane_closed, img):
    msg = "请先添加至少2个点"
    if mode == "车道掩膜" and len(lane_pts) >= 3:
        lane_closed = True
        msg = f"车道掩膜已闭合 ({len(lane_pts)}点)"
    elif mode == "车道掩膜":
        msg = f"车道至少需要3个点 (当前{len(lane_pts)})"
    elif mode == "A线 (进入线)" and len(wire_a_pts) >= 2:
        msg = f"A线完成 ({len(wire_a_pts)}点折线)"
    elif mode == "A线 (进入线)":
        msg = f"A线至少需要2个点 (当前{len(wire_a_pts)})"
    elif mode == "B线 (计数线)" and len(wire_b_pts) >= 2:
        msg = f"B线完成 ({len(wire_b_pts)}点折线)"
    elif mode == "B线 (计数线)":
        msg = f"B线至少需要2个点 (当前{len(wire_b_pts)})"
    result = draw_overlay(img, lane_pts, wire_a_pts, wire_b_pts, lane_closed)
    return result, lane_pts, wire_a_pts, wire_b_pts, lane_closed, msg


def on_undo(mode, lane_pts, wire_a_pts, wire_b_pts, lane_closed, img):
    if mode == "车道掩膜" and lane_pts:
        lane_pts = lane_pts[:-1]
        lane_closed = False
    elif mode == "A线 (进入线)" and wire_a_pts:
        wire_a_pts = wire_a_pts[:-1]
    elif mode == "B线 (计数线)" and wire_b_pts:
        wire_b_pts = wire_b_pts[:-1]
    result = draw_overlay(img, lane_pts, wire_a_pts, wire_b_pts, lane_closed)
    return result, lane_pts, wire_a_pts, wire_b_pts, lane_closed


def on_clear(mode, lane_pts, wire_a_pts, wire_b_pts, lane_closed, img):
    if mode == "车道掩膜":
        lane_pts = []
        lane_closed = False
    elif mode == "A线 (进入线)":
        wire_a_pts = []
    elif mode == "B线 (计数线)":
        wire_b_pts = []
    result = draw_overlay(img, lane_pts, wire_a_pts, wire_b_pts, lane_closed)
    return result, lane_pts, wire_a_pts, wire_b_pts, lane_closed


def sync_coord_texts(lane_pts, wire_a_pts, wire_b_pts):
    """生成坐标文本显示"""
    twa = ",".join(f"{x},{y}" for x, y in wire_a_pts) if wire_a_pts else ""
    twb = ",".join(f"{x},{y}" for x, y in wire_b_pts) if wire_b_pts else ""
    lane_s = ",".join(f"{x},{y}" for x, y in lane_pts) if lane_pts else ""
    return twa, twb, lane_s


# ── 运行管线 ──

def run_pipeline(video_path, model_name, confidence, iou, batch_size,
                 lane_pts, wire_a_pts, wire_b_pts, img_shape,
                 progress=gr.Progress()):
    if video_path is None:
        yield None, None, None, None, "请先上传视频"
        return

    if len(wire_a_pts) < 2 or len(wire_b_pts) < 2:
        yield None, None, None, None, "请先在Tab2完成A线和B线标定 (各至少2点)"
        return

    h, w = img_shape if img_shape else (2160, 3840)
    twa = get_norm_coords(wire_a_pts, w, h)
    twb = get_norm_coords(wire_b_pts, w, h)
    lane_norm = get_norm_coords(lane_pts, w, h) if lane_pts else []

    progress(0, desc="正在初始化...")

    q = queue.Queue()

    def progress_callback(pct):
        q.put(("progress", pct))

    pipeline = PipelineRunner(
        model_name=model_name,
        confidence=confidence,
        iou=iou,
        device="cuda:0",
        batch_size=int(batch_size),
        resize_width=2560,
        sample_interval=3,
        output_fps=20,
        progress_callback=progress_callback,
    )

    out_dir = tempfile.mkdtemp(prefix="traffic_")

    def _run():
        try:
            result = pipeline.run(
                video_path=video_path,
                tripwire_a=twa,
                tripwire_b=twb,
                lane_mask=lane_norm,
                output_dir=out_dir,
                output_video=True,
            )
            q.put(("result", result))
        except Exception as e:
            import traceback
            traceback.print_exc()
            q.put(("error", str(e)))

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    result = None
    while thread.is_alive() or not q.empty():
        try:
            kind, val = q.get(timeout=0.3)
            if kind == "progress":
                progress(val / 100, desc=f"检测中... {val}%")
            elif kind == "result":
                result = val
                break
            elif kind == "error":
                yield None, None, None, val, f"错误: {val}"
                return
        except queue.Empty:
            continue

    if result is None:
        yield None, None, None, None, "未返回结果"
        return

    progress(100, desc="完成")

    stats = result["stats"]
    summary = [{"车型": k, "数量": v} for k, v in stats.vehicles_by_type.items()]
    summary.append({"车型": "总计", "数量": stats.total_vehicles})

    status = (
        f"总计: {stats.total_vehicles} | "
        f"car: {stats.vehicles_by_type.get('car',0)} | "
        f"bus: {stats.vehicles_by_type.get('bus',0)} | "
        f"truck: {stats.vehicles_by_type.get('truck',0)} | "
        f"moto: {stats.vehicles_by_type.get('motorcycle',0)} | "
        f"耗时: {result['elapsed']:.0f}s @ {result['fps']:.1f}fps"
    )

    yield (
        result.get("output_video"),
        result.get("charts", {}).get("flow_timeline"),
        result.get("charts", {}).get("vehicle_types"),
        summary,
        status,
    )


# ── GUI ──

def create_gui():
    css = """
    .calib-row img { max-height: 65vh !important; }
    footer { display: none !important; }
    """
    with gr.Blocks(title="交通流检测系统") as app:
        gr.Markdown("# 交通流检测系统\n> 上传视频 → 截帧标定绊线 → 选择模型 → 自动计数")

        with gr.Tabs():
            # ═══ Tab 1: 配置 ═══
            with gr.TabItem("1. 上传与配置"):
                with gr.Row():
                    with gr.Column(scale=3):
                        video_input = gr.Video(label="上传视频", sources=["upload"])
                        extract_btn = gr.Button("截取标定帧", variant="secondary")
                        extract_msg = gr.Textbox(label="状态", interactive=False, lines=2)
                    with gr.Column(scale=2):
                        model_dd = gr.Dropdown(
                            MODEL_CHOICES, value="yolo11x.pt",
                            label="YOLO 模型", info="n=最快 | x=最准"
                        )
                        conf_sl = gr.Slider(0.05, 0.5, value=0.10, step=0.05, label="置信度阈值")
                        iou_sl = gr.Slider(0.3, 0.9, value=0.65, step=0.05, label="IoU 阈值")
                        batch_rb = gr.Radio([4, 8, 16], value=8, label="Batch Size")

            # ═══ Tab 2: 标定 ═══
            with gr.TabItem("2. 标定绊线"):
                gr.Markdown(
                    "**步骤**: ①选择模式 → ②点击图片放顶点 → ③点\"完成折线\"\n"
                    "🟡黄=A线(进入确认) | 🔴红=B线(计数触发) | 🟢绿=车道掩膜"
                )
                with gr.Row(elem_classes=["calib-row"]):
                    with gr.Column(scale=3):
                        calib_img = gr.Image(
                            label="标定画面 — 点击添加顶点",
                            type="numpy", interactive=True,
                        )
                    with gr.Column(scale=1):
                        mode_rb = gr.Radio(
                            ["A线 (进入线)", "B线 (计数线)", "车道掩膜"],
                            value="A线 (进入线)", label="绘制模式"
                        )
                        finish_btn = gr.Button("完成折线", variant="primary")
                        undo_btn = gr.Button("撤销最后一点", size="sm")
                        clear_btn = gr.Button("清除当前模式", size="sm")
                        calib_msg = gr.Textbox(label="提示", interactive=False)

                with gr.Accordion("像素坐标 (可手动编辑)", open=False):
                    twa_text = gr.Textbox(label="A线坐标", placeholder="x1,y1,x2,y2,...")
                    twb_text = gr.Textbox(label="B线坐标", placeholder="x1,y1,x2,y2,...")
                    lane_text = gr.Textbox(label="车道掩膜", placeholder="x1,y1,x2,y2,...")

            # ═══ Tab 3: 运行 & 结果 ═══
            with gr.TabItem("3. 运行与结果"):
                run_btn = gr.Button("开始检测", variant="primary", size="lg")
                run_status = gr.Textbox(label="运行状态", interactive=False)

                with gr.Row():
                    out_video = gr.Video(label="输出视频", height=400)
                    stats_df = gr.DataFrame(headers=["车型", "数量"], label="统计汇总")

                with gr.Row():
                    flow_plot = gr.Plot(label="流量时序图")
                    type_plot = gr.Plot(label="车型分布")

        # ── State ──
        lane_st = gr.State([])
        wire_a_st = gr.State([])
        wire_b_st = gr.State([])
        lane_closed_st = gr.State(False)
        img_shape_st = gr.State(None)

        # ── Events ──

        extract_btn.click(
            fn=extract_frame,
            inputs=[video_input],
            outputs=[calib_img, extract_msg],
        ).then(
            fn=lambda img: (img.shape[:2] if img is not None else None),
            inputs=[calib_img],
            outputs=[img_shape_st],
        ).then(
            fn=lambda: ([], [], [], False),
            outputs=[lane_st, wire_a_st, wire_b_st, lane_closed_st],
        )

        calib_img.select(
            fn=on_image_click,
            inputs=[calib_img, mode_rb, lane_st, wire_a_st, wire_b_st, lane_closed_st],
            outputs=[calib_img, lane_st, wire_a_st, wire_b_st, lane_closed_st, calib_msg],
        ).then(
            fn=sync_coord_texts,
            inputs=[lane_st, wire_a_st, wire_b_st],
            outputs=[twa_text, twb_text, lane_text],
        )

        finish_btn.click(
            fn=on_finish,
            inputs=[mode_rb, lane_st, wire_a_st, wire_b_st, lane_closed_st, calib_img],
            outputs=[calib_img, lane_st, wire_a_st, wire_b_st, lane_closed_st, calib_msg],
        ).then(
            fn=sync_coord_texts,
            inputs=[lane_st, wire_a_st, wire_b_st],
            outputs=[twa_text, twb_text, lane_text],
        )

        undo_btn.click(
            fn=on_undo,
            inputs=[mode_rb, lane_st, wire_a_st, wire_b_st, lane_closed_st, calib_img],
            outputs=[calib_img, lane_st, wire_a_st, wire_b_st, lane_closed_st],
        ).then(
            fn=sync_coord_texts,
            inputs=[lane_st, wire_a_st, wire_b_st],
            outputs=[twa_text, twb_text, lane_text],
        )

        clear_btn.click(
            fn=on_clear,
            inputs=[mode_rb, lane_st, wire_a_st, wire_b_st, lane_closed_st, calib_img],
            outputs=[calib_img, lane_st, wire_a_st, wire_b_st, lane_closed_st],
        ).then(
            fn=sync_coord_texts,
            inputs=[lane_st, wire_a_st, wire_b_st],
            outputs=[twa_text, twb_text, lane_text],
        )

        run_btn.click(
            fn=run_pipeline,
            inputs=[video_input, model_dd, conf_sl, iou_sl, batch_rb,
                    lane_st, wire_a_st, wire_b_st, img_shape_st],
            outputs=[out_video, flow_plot, type_plot, stats_df, run_status],
        )

    return app


if __name__ == "__main__":
    app = create_gui()
    app.launch(
        server_name="127.0.0.1",
        server_port=7860,
        share=False,
        show_error=True,
        css=""".calib-row img { max-height: 65vh !important; } footer { display: none !important; }""",
    )
