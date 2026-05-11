"""数据处理与统计分析模块"""
import pandas as pd
import numpy as np
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class TrafficStats:
    """交通统计数据容器"""
    # 流量统计
    total_vehicles: int = 0
    vehicles_by_type: Dict[str, int] = field(default_factory=dict)
    vehicles_by_direction: Dict[str, int] = field(default_factory=dict)

    # 时间分布
    flow_per_minute: List[int] = field(default_factory=list)
    peak_flow: int = 0
    peak_minute: int = 0

    # 异常统计
    wrong_way_count: int = 0
    turning_from_other: int = 0

    # 速度统计 (像素/秒, 可由实际距离换算)
    avg_speed: float = 0.0
    speed_samples: List[float] = field(default_factory=list)


class DataProcessor:
    """数据处理器: 清洗、聚合、统计分析"""

    def __init__(self, fps=30.0, pixels_per_meter=None):
        self.fps = fps
        self.pixels_per_meter = pixels_per_meter
        self.records = defaultdict(list)  # {camera_name: [records]}
        self.anomalies = defaultdict(list)

    def add_record(self, camera_name, pass_data, frame_idx):
        """
        添加一条通过记录
        Args:
            camera_name: 相机名 (south/north/east)
            pass_data: roi_filter返回的通过数据
            frame_idx: 当前帧号
        """
        record = {
            "camera": camera_name,
            "track_id": pass_data["track_id"],
            "vehicle_type": pass_data["cls_name"],
            "vehicle_cls": pass_data["cls"],
            "angle": pass_data["angle"],
            "is_turning": pass_data.get("is_turning", False),
            "pass_frame": frame_idx,
            "pass_timestamp": frame_idx / self.fps,  # 秒
        }
        self.records[camera_name].append(record)

    def add_anomaly(self, camera_name, anomaly_type, data):
        self.anomalies[camera_name].append({
            "type": anomaly_type,
            "track_id": data.get("track_id", -1),
            "vehicle_type": data.get("cls_name", "unknown"),
            "angle": data.get("angle", 0),
            "frame": data.get("pass_frame", 0),
        })

    def get_dataframe(self, camera_name=None):
        """获取DataFrame用于分析"""
        if camera_name:
            return pd.DataFrame(self.records.get(camera_name, []))
        all_records = []
        for cam, recs in self.records.items():
            all_records.extend(recs)
        return pd.DataFrame(all_records)

    def compute_statistics(self, camera_name=None, video_duration_sec=900):
        """
        计算交通统计数据
        Args:
            camera_name: None=汇总所有进口, 或指定进口
            video_duration_sec: 视频时长(秒)
        Returns:
            TrafficStats对象
        """
        df = self.get_dataframe(camera_name)

        if df.empty:
            return TrafficStats()

        stats = TrafficStats()

        # 1. 总流量
        stats.total_vehicles = len(df)

        # 2. 按车型统计
        stats.vehicles_by_type = df["vehicle_type"].value_counts().to_dict()

        # 3. 按进口方向统计
        if "camera" in df.columns:
            stats.vehicles_by_direction = df["camera"].value_counts().to_dict()

        # 4. 每分钟流量分布
        if "pass_timestamp" in df.columns:
            minutes = (df["pass_timestamp"] // 60).astype(int)
            stats.flow_per_minute = [
                int((minutes == m).sum())
                for m in range(int(video_duration_sec / 60) + 1)
            ]
            if stats.flow_per_minute:
                stats.peak_flow = max(stats.flow_per_minute)
                stats.peak_minute = stats.flow_per_minute.index(stats.peak_flow)

        # 5. 转弯汇入车辆
        if "is_turning" in df.columns:
            stats.turning_from_other = int(df["is_turning"].sum())

        # 6. 逆行车辆
        for cam, anoms in self.anomalies.items():
            stats.wrong_way_count += sum(1 for a in anoms if a["type"] == "wrong_way")

        # 7. 速度估算
        if self.pixels_per_meter and self.pixels_per_meter > 0:
            stats.speed_samples = self._estimate_speeds(df)
            if stats.speed_samples:
                stats.avg_speed = np.mean(stats.speed_samples)

        return stats

    def _estimate_speeds(self, df):
        """从轨迹估算速度 (需要pixels_per_meter标定)"""
        # 实际速度估算需要轨迹的像素位移,这里保留接口
        # 具体实现需要在trajectory中记录位移距离
        return []

    def generate_report(self, stats_dict, output_path=None):
        """
        生成统计分析报告
        Args:
            stats_dict: {camera_name: TrafficStats} 或 {"total": TrafficStats}
            output_path: 报告输出路径(.csv或None=打印)
        """
        lines = []
        lines.append("=" * 60)
        lines.append("          交通流量统计分析报告")
        lines.append("=" * 60)

        for cam_name, stats in stats_dict.items():
            lines.append(f"\n{'─' * 40}")
            lines.append(f"  [{cam_name}]")
            lines.append(f"{'─' * 40}")
            lines.append(f"  总通过车辆数: {stats.total_vehicles}")
            lines.append(f"  车型分布:")
            for vtype, count in sorted(stats.vehicles_by_type.items(),
                                        key=lambda x: -x[1]):
                lines.append(f"    {vtype}: {count}")
            lines.append(f"  逆向行驶: {stats.wrong_way_count}")
            lines.append(f"  转弯汇入: {stats.turning_from_other}")

            if stats.flow_per_minute:
                lines.append(f"  高峰小时流量: {stats.peak_flow * 60 // len(stats.flow_per_minute):.0f} 辆/小时(估算)")
                lines.append(f"  高峰分钟: 第{stats.peak_minute}分钟 ({stats.peak_flow}辆)")

            if stats.avg_speed > 0:
                lines.append(f"  平均车速: {stats.avg_speed:.1f} km/h")

        lines.append(f"\n{'=' * 60}")

        report = "\n".join(lines)
        print(report)

        if output_path:
            # 同时保存CSV数据
            all_data = []
            for cam_name, stats in stats_dict.items():
                all_data.append({
                    "进口": cam_name,
                    "总流量": stats.total_vehicles,
                    "小汽车": stats.vehicles_by_type.get("car", 0),
                    "摩托车": stats.vehicles_by_type.get("motorcycle", 0),
                    "公交车": stats.vehicles_by_type.get("bus", 0),
                    "卡车": stats.vehicles_by_type.get("truck", 0),
                    "逆行": stats.wrong_way_count,
                    "转弯汇入": stats.turning_from_other,
                    "高峰分钟流量": stats.peak_flow,
                    "高峰分钟": stats.peak_minute,
                })
            pd.DataFrame(all_data).to_csv(output_path, index=False, encoding="utf-8-sig")
            print(f"\n  数据已保存至: {output_path}")

        return report
