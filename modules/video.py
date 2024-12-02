import os
from fastapi import HTTPException
import subprocess
import asyncio
from pathlib import Path
from moviepy.editor import VideoFileClip
from .config import (
    UPLOAD_DIR,
    SUBTITLE_DIR,
    TEMP_DIR,
    SUBTITLED_VIDEO_DIR
)
from .utils import convert_to_srt  # 改为从 utils 导入


# 颜色转换函数
def hex_to_ass_color(hex_color, alpha=0):
        # 去掉 "#" 并提取 RGB
        hex_color = hex_color.lstrip("#")
        r, g, b = int(hex_color[:2], 16), int(hex_color[2:4], 16), int(hex_color[4:], 16)
        # ASS 使用 AABBGGRR 格式，其中 AA 是 alpha 通道
        # 在 ASS 中，0 表示完全不透明，255 表示完全透明
        return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"

def convert_subtitle_style(frontend_data):
    """转换前端字幕样式为 ASS 格式"""
    # 获取前端数据
    bg_color = frontend_data["bgColor"]  # 背景颜色 (e.g., "#000000")
    bg_opacity = float(frontend_data["bgOpacity"])  # 背景透明度 (e.g., "0.5")
    font_color = frontend_data["color"]  # 字体颜色 (e.g., "#ffffff")
    font_size = int(float(frontend_data["fontSize"]))  # 字体大小
    stroke_color = frontend_data["strokeColor"]  # 描边颜色
    stroke_width = float(frontend_data["strokeWidth"])  # 描边宽度



    # 计算 ASS 格式的 alpha 值（反转透明度）
    # 前端的 opacity: 0.0 (完全透明) -> ASS alpha: 255 (完全透明)
    # 前端的 opacity: 1.0 (完全不透明) -> ASS alpha: 0 (完全不透明)
    ass_alpha = int((1 - bg_opacity) * 255)

    # 获取背景框设置
    box_margin_v = int(frontend_data.get("boxMarginV", 10))
    box_margin_h = int(frontend_data.get("boxMarginH", 10))
    box_padding_v = int(frontend_data.get("boxPaddingV", 5))
    box_padding_h = int(frontend_data.get("boxPaddingH", 10))

    # 构建 ASS 样式字典
    return {
        'fontSize': str(font_size),
        'color': hex_to_ass_color(font_color, 0),  # 字体颜色（完全不透明）
        'strokeColor': hex_to_ass_color(stroke_color, 0),  # 描边颜色（完全不透明）
        'strokeWidth': str(stroke_width),
        'bgColor': hex_to_ass_color(bg_color, ass_alpha),  # 背景颜色（使用计算的透明度）
        'bgOpacity': str(bg_opacity),  # 保存原始透明度值
        # 添加背景框设置
        'marginV': str(box_margin_v),
        'marginH': str(box_margin_h),
        'marginL': str(box_margin_h),
        'marginR': str(box_margin_h)
    }

async def burn_subtitles(file_id: str, language: str, style: dict):
    """将字幕烧录到视频中"""
    try:
        
        # 确保目录存在
        SUBTITLED_VIDEO_DIR.mkdir(exist_ok=True)
        TEMP_DIR.mkdir(exist_ok=True)
        
        # 准备文件路径
        file_id_without_ext = Path(file_id).stem
        video_path = UPLOAD_DIR / f"{file_id}.mp4"
        subtitle_path = SUBTITLE_DIR / f"{file_id_without_ext}.json"
        output_path = SUBTITLED_VIDEO_DIR / f"{file_id_without_ext}_subtitled.mp4"
        ass_path = TEMP_DIR / f"{file_id_without_ext}.ass"

        print(f"视频文件路径: {video_path}")
        print(f"字幕文件路径: {subtitle_path}")
        print(f"ASS字幕路径: {ass_path}")
        print(f"输出文件路径: {output_path}")
        
        # 使用测试样式
        test_style = {
            'fontSize': '68',  # 更大的字体
            'color': '#FF0000',  # 红色
            'strokeColor': '#000000',  # 黑色描边
            'strokeWidth': '3',  # 更粗的描边
            'bgColor': '#FFFF00',  # 黄色背景
            'bgOpacity': '0.8'  # 较高的不透明度
        }

        # 从 JSON 转换为 ASS 格式
        await json_to_ass(subtitle_path, ass_path, convert_subtitle_style(style))  # 使用测试样式

        try:
            # 确保 ASS 文件存在
            if not ass_path.exists():
                raise HTTPException(500, f"ASS字幕文件未生成: {ass_path}")

            # 使用 FFmpeg 烧录字幕
            cmd = [
                'ffmpeg', '-y',
                '-i', str(video_path),
                '-vf', f'ass={str(ass_path)}',  # 移除单引号
                '-c:v', 'libx264',
                '-preset', 'medium',
                '-crf', '23',
                '-c:a', 'copy',
                str(output_path)
            ]
            
            print(f"执行命令: {' '.join(cmd)}")
            
            # 执行命令并捕获输出
            process = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True
            )
            
            print(f"FFmpeg 标准输出: {process.stdout}")
            print(f"FFmpeg 错误输出: {process.stderr}")

            # 检查输出文件
            if not output_path.exists() or output_path.stat().st_size == 0:
                raise HTTPException(500, "输出文件无效")

            print(f"字幕烧录完成，输出文件: {output_path}")
            return {
                "status": "success",
                "message": "字幕烧录完成",
                "output_file": str(output_path.name)
            }

        finally:
            # 清理临时文件
            if ass_path.exists():
                print(f"清理临时ASS文件: {ass_path}")
                ass_path.unlink()

    except subprocess.CalledProcessError as e:
        print(f"FFmpeg 执行失败: {e.stderr}")
        raise HTTPException(500, f"FFmpeg 执行失败: {e.stderr}")
    except Exception as e:
        print(f"烧录字幕失败: {str(e)}")
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(500, f"烧录字幕失败: {str(e)}")

async def json_to_ass(json_path: Path, ass_path: Path, style: dict):
    """将 JSON 格式的字幕转换为 ASS 格式"""
    try:
        import json
        
        print("收到的样式参数:", style)
        
        # 读取 JSON 字幕
        with open(json_path, 'r', encoding='utf-8') as f:
            subtitles = json.load(f)

        # 生成 ASS 文件内容
        ass_content = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
"""
        try:
            # 直接使用转换后的样式参数
            font_size = style['fontSize']
            font_color = style['color']
            stroke_color = style['strokeColor']
            bg_opacity = float(style['bgOpacity'])
            ass_alpha = int((1 - bg_opacity) * 255)  # 转换透明度
            # bg_color = hex_to_ass_color(style['bgColor'], ass_alpha)  # 确保正确透明度
            bg_color = style['bgColor']  # 这里的 bg_color 已经包含了透明度信息
            # stroke_width = style['strokeWidth']
            stroke_width = max(1.0, float(style['strokeWidth']))  # 边框宽度，避免 0 导致问题

            # 添加样式定义
            style_line = (
                f"Style: Default,Arial,{font_size},"  # 名称、字体、大小
                f"{font_color},"  # 主要颜色
                f"{font_color},"  # 次要颜色
                f"{stroke_color},"  # 边框颜色
                f"{bg_color},"  # 背景颜色（已包含透明度）
                f"1,0,0,0,"  # 粗体,斜体,下划线,删除线
                f"100,100,0,0,"  # 缩放X,缩放Y,间距,角度
                f"3,{stroke_width},0,"  # 边框样式(3=显示背景),边框宽度,阴影
                f"2,{style['marginL']},{style['marginR']},{style['marginV']},1"  # 对齐,左边距,右边距,垂直边距,编码
            )
            
            ass_content += style_line + "\n\n"
            print(f"ASS样式行: {style_line}")

        except ValueError as e:
            print(f"样式参数处理错误: {e}")
            print(f"原始样式参数: {style}")
            raise HTTPException(500, f"样式参数处理错误: {str(e)}")

        # 添加事件格式定义
        ass_content += "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"

        # 添加字幕事件
        for subtitle in subtitles:
            start_time = format_time(subtitle['start'])
            end_time = format_time(subtitle['start'] + subtitle['duration'])
            text = subtitle['text'].replace('\n', '\\N')
            
            # 添加字幕事件
            ass_content += f"Dialogue: 0,{start_time},{end_time},Default,,0,0,0,,{text}\n"

        # 写入 ASS 文件
        with open(ass_path, 'w', encoding='utf-8') as f:
            f.write(ass_content)

        print(f"生成的ASS文件内容:\n{ass_content}")

    except Exception as e:
        print(f"转换字幕格式失败: {str(e)}")
        raise HTTPException(500, f"转换字幕格式失败: {str(e)}")

def format_time(seconds: float) -> str:
    """将秒数转换为 ASS 格式的时间字符串 (H:MM:SS.cc)"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centisecs = int((seconds * 100) % 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centisecs:02d}"

def get_video_duration(video_path: Path) -> float:
    """获取视频时长"""
    try:
        with VideoFileClip(str(video_path)) as video:
            return video.duration
    except Exception as e:
        raise HTTPException(500, f"获取视频时长失败: {str(e)}") 