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

async def burn_subtitles(file_id: str, language: str, style: dict):
    """将字幕烧录到视频中"""
    try:
        # 确保目录存在
        SUBTITLED_VIDEO_DIR.mkdir(parents=True, exist_ok=True)
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        
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
        print(f"收到的样式参数: {style}")

        # 从 JSON 转换为 ASS 格式
        await json_to_ass(subtitle_path, ass_path, style)

        try:
            # 确保 ASS 文件存在并且有内容
            if not ass_path.exists():
                raise HTTPException(500, f"ASS字幕文件未生成: {ass_path}")
            
            # 读取并打印 ASS 文件内容
            with open(ass_path, 'r', encoding='utf-8') as f:
                ass_content = f.read()
                print(f"ASS文件内容:\n{ass_content}")

            # 使用 FFmpeg 烧录字幕
            cmd = [
                'ffmpeg', '-y',
                '-i', str(video_path),
                '-vf', f'ass={str(ass_path)}:fontsdir=/System/Library/Fonts',  # 指定字体目录
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
            # 暂时不删除 ASS 文件，用于调试
            print(f"保留 ASS 文件用于调试: {ass_path}")
            # if ass_path.exists():
            #     ass_path.unlink()

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
            # 使用测试样式的格式处理前端传来的样式
            font_size = int(float(style.get('fontSize', '68')))  # 默认使用68，跟测试样式一致
            
            # 颜色处理（确保格式跟测试样式一致）
            def process_color(color_str):
                color = color_str.lstrip('#').lower()  # 转小写以保持一致
                if len(color) == 6:
                    color = 'FF' + color  # 不透明
                return f"&H{color[6:8]}{color[4:6]}{color[2:4]}{color[0:2]}"

            # 处理颜色（使用跟测试样式一样的默认值）
            font_color = process_color(style.get('color', '#ff0000'))  # 默认红色
            stroke_color = process_color(style.get('strokeColor', '#000000'))  # 默认黑色
            
            # 背景颜色和透明度（使用跟测试样式一样的默认值）
            bg_color = style.get('bgColor', '#ffff00').lstrip('#').lower()  # 默认黄色
            bg_opacity = float(style.get('bgOpacity', '0.8'))  # 默认0.8
            bg_alpha = int((1 - bg_opacity) * 255)
            bg_color = f"&H{bg_alpha:02X}{bg_color}"
            
            # 描边宽度（使用跟测试样式一样的默认值）
            stroke_width = float(style.get('strokeWidth', '3'))  # 默认3

            # 添加样式定义（完全按照测试样式的格式）
            style_line = (
                f"Style: Default,Arial,{font_size},"  # 名称、字体、大小
                f"{font_color},"  # 主要颜色
                f"{font_color},"  # 次要颜色
                f"{stroke_color},"  # 边框颜色
                f"{bg_color},"  # 背景颜色
                f"1,0,0,0,"  # 粗体,斜体,下划线,删除线
                f"100,100,0,0,"  # 缩放X,缩放Y,间距,角度
                f"1,{stroke_width:.1f},0,"  # 边框样式,边框宽度,阴影
                f"2,10,10,10,1"  # 对齐,边距,右边距,垂直边距,编码
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

        # 验证 ASS 文件是否正确生成
        if not ass_path.exists():
            raise HTTPException(500, f"ASS 文件未生成: {ass_path}")

        # 检查 ASS 文件大小
        file_size = ass_path.stat().st_size
        if file_size == 0:
            raise HTTPException(500, "ASS 文件为空")

        print(f"ASS 文件大小: {file_size} 字节")

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