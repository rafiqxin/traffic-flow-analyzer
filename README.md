# TrafficFlow Analyzer v1.0.0

**基于 YOLO11 + ByteTrack + 双绊线计数** 的交通路口车辆检测 / 跟踪 / 计数系统。

支持 T 型 / 十字路口多路视频同时分析，自动识别汽车、公交车、卡车、摩托车四种车型，输出带标注的检测视频、流量时序图表、车型分布饼图和 CSV 统计报告。

---

## 效果数据

在 T 型路口 3 路 4K 视频（各 15 分钟）上测试，YOLO11x 模型：

| 摄像头 | 合计 | car | bus | truck | motorcycle |
|--------|------|-----|-----|-------|------------|
| 南进口 | 533 | 253 | 9 | 52 | 219 |
| 北进口 | 583 | 264 | 7 | 46 | 266 |
| 东进口（支路） | 263 | 115 | 2 | 35 | 111 |
| **合计** | **1,379** | 632 | 18 | 133 | 596 |

处理速度：**16~18 fps** @ RTX 4060 Laptop 8GB

---

## 功能特性

### 检测与跟踪
- **YOLO11 五档模型**：n（最快）/ s / m / l / x（最准），支持 4K 输入分辨率
- **ByteTrack 多目标跟踪**：匈牙利算法全局最优匹配 + Kalman 滤波位置预测，抗遮挡、抗漏检
- **两阶段匹配策略**：高置信度检测优先匹配 → 低置信度恢复遮挡目标

### 核心创新：双绊线计数
- **A 线（进入确认线，黄色）**：车辆必须先穿越 A 线建立"进入意图"
- **B 线（触发计数线，红色）**：仅已穿过 A 线的车辆穿越 B 线时才计数
- 支持多段折线绊线（非单一直线），适配弯曲道路
- 方向校验：只统计下行方向（朝相机方向），忽略逆行车辆
- 转弯车免疫：已穿 A 线车辆离开车道后仍保留计数资格

### 车道掩膜
- 多边形硬 ROI：仅轮胎接地点在车道多边形内的车辆参与统计
- 支持排除区域，屏蔽不需要的局部区域

### 性能优化
- **CPU / GPU 并行**：`FramePrefetcher` 后台线程预读 + 缩放帧，GPU 持续满负荷
- 批量推理：可配置 batch size（2~16），充分利用 GPU 显存

### 输出产物
| 产物 | 说明 |
|------|------|
| 带标注视频（.mp4） | 检测框 + 轨迹 ID + 绊线 + 车道掩膜 + 实时计数 |
| 流量时序图（PNG） | 每分钟流量曲线 |
| 车型饼图（PNG） | 四种车型占比分布 |
| 汇总柱状图（PNG） | 各车型总量对比 |
| CSV 报告 | 各摄像头 / 各车型数量汇总 |

---

## 下载与使用（免安装）

### 方式一：绿色免安装版（推荐）

从 [Releases](https://github.com/rafiqxin/traffic-flow-analyzer/releases) 下载两个 7z 分卷文件：

```
TrafficFlowAnalyzer_v1.0.0.7z.001
TrafficFlowAnalyzer_v1.0.0.7z.002
```

使用 [7-Zip](https://7-zip.org/) 解压：

```bash
7z x TrafficFlowAnalyzer_v1.0.0.7z.001
```

解压后得到 `TrafficFlowAnalyzer/` 文件夹，双击 `TrafficFlowAnalyzer.exe` 即可启动。

> **无需安装 Python、CUDA、PyTorch 或任何依赖**——全部环境已打包在 `_internal/` 中。

### 方式二：从源码运行

```bash
git clone https://github.com/rafiqxin/traffic-flow-analyzer.git
cd traffic-flow-analyzer
pip install -r requirements.txt
python desktop_app.py
```

要求：Python 3.10+、NVIDIA GPU、CUDA 12.1+

---

## 使用说明

### 桌面版 GUI

```bash
python desktop_app.py
```

操作流程：

1. **选择视频** — 点击「选择视频文件」，支持 mp4 / avi / mov / mkv
2. **提取标定帧** — 从视频中间提取一帧作为标定画布
3. **标定绊线与车道**（左键加点，右键完成）：
   - **A 线（黄）**：车辆进入确认线，至少 2 点
   - **B 线（红）**：车辆计数触发线，至少 2 点
   - **车道掩膜（绿）**：合法行驶区域多边形，至少 3 点，右键闭合
   - 支持撤销 / 清除
4. **选择模型** — 下拉选择 n / s / m / l / x，调整置信度 / IoU / Batch
5. **开始检测** — 查看进度条，完成后自动打开输出目录

首次运行时会自动下载所选 YOLO 模型文件。

### 命令行

```bash
# 单摄像头
python main.py --camera south --batch 16

# 全部摄像头
python main.py --camera all --batch 8 --device cuda:0
```

### 独立标定工具

```bash
python calibrate_roi.py --camera south
```

OpenCV 交互式窗口，鼠标 / 键盘标定。

---

## 自行编译

```bash
# 在已配置好 PyTorch + ultralytics + PyQt6 的 conda 环境中
pip install pyinstaller

pyinstaller --noconfirm --onedir --windowed \
    --name "TrafficFlowAnalyzer" \
    --hidden-import ultralytics \
    --hidden-import scipy \
    --collect-data ultralytics \
    desktop_app.py

# 拷贝运行时文件
cp -r config/ dist/TrafficFlowAnalyzer/
cp yolo11l.pt yolo11n.pt dist/TrafficFlowAnalyzer/
```

---

## 技术架构

```
视频文件 ──→ FramePrefetcher (CPU 预读 + 缩放)
                │
                ▼
         YOLO11 批量推理 (GPU)
                │
                ▼
         ByteTrack 多目标跟踪
      (匈牙利匹配 + Kalman 滤波)
                │
                ▼
         ROI 车道过滤 + 双绊线计数
                │
                ▼
         统计输出 ──→ 标注视频 + 图表 + CSV
```

### 关键参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| 模型 | yolo11x | n/s/m/l/x 可选 |
| 输入分辨率 | 2560px | 等比缩放宽度 |
| 采样间隔 | 3 帧 | 每 3 帧检测一次 |
| 输出帧率 | 20 fps | 输出视频帧率 |
| 置信度 | 0.10 | 检测阈值 |
| IoU | 0.65 | NMS 阈值 |
| Batch | 8 | GPU 批量大小 |

---

## 项目结构

```
├── desktop_app.py         # 桌面版主程序（PyQt6 GUI）
├── main.py                # 命令行入口
├── pipeline.py            # 可编程管线（PipelineRunner）
├── calibrate_roi.py       # 独立 ROI 标定工具
├── TrafficFlowAnalyzer.spec  # PyInstaller 编译配置
├── config/
│   ├── camera_roi.yaml    # 摄像头 ROI / 绊线预设
│   └── model_config.yaml  # 模型参数配置
├── src/
│   ├── detector.py        # YOLO 检测器 + 帧预取线程
│   ├── tracker.py         # ByteTrack 跟踪器
│   ├── roi_filter.py      # ROI 掩膜 + 双绊线计数逻辑
│   ├── visualizer.py      # 检测结果可视化
│   └── data_processor.py  # 统计汇总 + CSV 导出
├── dist/                  # 编译产物（绿色免安装）
├── output/                # 检测输出目录
└── resources/             # 输入视频（不入仓库）
```

---

## 系统要求

| 项目 | 最低配置 | 推荐配置 |
|------|----------|----------|
| 操作系统 | Windows 10/11 64-bit | Windows 11 |
| 显卡 | NVIDIA GTX 1060 6GB | RTX 4060 8GB+ |
| 内存 | 16 GB | 32 GB |
| 磁盘 | 15 GB 可用 | SSD 30 GB |

---

## License

MIT License
