# 交通流检测系统 — TrafficFlow Analyzer

基于 **YOLO11 + ByteTrack + 双绊线** 的交通路口车辆检测/跟踪/计数系统。支持 **Web 版** 和 **桌面版** 两种交互方式。

## 功能特性

- **高精度检测**: YOLO11 (n/s/m/l/x) 4K 推理，car/bus/truck/motorcycle 四类
- **ByteTrack 跟踪**: 匈牙利全局最优匹配 + Kalman 预测，抗遮挡
- **双绊线计数**: A 线(进入确认) → B 线(触发计数)，支持多段折线
- **硬 ROI 掩膜**: 车道级过滤，仅统计合法车道内车辆
- **转弯车免疫**: 已穿 A 线的转弯车辆保留至计数完成
- **批量 GPU 推理**: CPU 预取 + GPU 批量，最大化吞吐
- **可视化输出**: 检测叠加视频 + 流量图表 + CSV 报告

## 环境要求

- Python 3.10+
- NVIDIA GPU (推荐 8GB+ VRAM)
- CUDA 12.1+

## 快速开始

### 安装

```bash
git clone https://github.com/yourname/traffic-flow-analyzer.git
cd traffic-flow-analyzer
pip install -r requirements.txt
```

### 方式一：Web 版 (Gradio)

```bash
python gui_app.py
```
浏览器打开 `http://127.0.0.1:7860`，三步操作：
1. 上传视频 → 选择模型 → 调参数
2. 截取标定帧 → 点击画面绘制 A/B 线
3. 开始检测 → 查看输出视频和图表

### 方式二：桌面版 (PyQt6)

```bash
python desktop_app.py
```
原生窗口应用，同样点击式标定交互，无需浏览器。
- 左键点击画面添加标定点
- 右键完成当前折线
- 支持 A 线/B 线/车道掩膜三种模式

### 命令行模式

```bash
python main.py --camera south --batch 16
python main.py --camera all --batch 8 --device cuda:0
```

### 独立标定工具

```bash
python calibrate_roi.py --camera south
```

## 项目结构

```
py_project/
├── gui_app.py           # Web 版 (Gradio)
├── desktop_app.py       # 桌面版 (PyQt6)
├── main.py              # CLI 入口
├── pipeline.py          # 可编程管线
├── calibrate_roi.py     # 独立标定工具
├── run.bat              # 一键启动
├── config/
│   ├── model_config.yaml
│   └── camera_roi.yaml
├── src/
│   ├── detector.py      # YOLO检测 + 帧预取
│   ├── tracker.py       # ByteTrack 跟踪
│   ├── roi_filter.py    # ROI掩膜 + 双绊线
│   ├── visualizer.py    # 可视化渲染
│   └── data_processor.py# 统计 + CSV
└── output/              # 输出目录
```

## 技术架构

```
视频 → FramePrefetcher(CPU预取) → YOLO批量推理(GPU)
     → ByteTrack(匈牙利+Kalman) → ROI过滤(硬掩膜+双绊线)
     → 统计输出(图表+CSV+视频)
```

## License

MIT License
