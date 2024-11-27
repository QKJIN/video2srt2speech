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
    try:
        # 获取字幕文件
        file_id_without_ext = os.path.splitext(file_id)[0]
        subtitle_file = SUBTITLE_DIR / f"{file_id_without_ext}_{language}.json"
        if not subtitle_file.exists():
            raise HTTPException(404, "字幕文件不存在")

        with open(subtitle_file, 'r', encoding='utf-8') as f:
            subtitles = json.load(f)

        # 转换为SRT格式
        srt_content = convert_to_srt(subtitles)
        srt_file = TEMP_DIR / f"{file_id}_{language}.srt"
        with open(srt_file, 'w', encoding='utf-8') as f:
            f.write(srt_content)

        # 获取视频文件
        video_file = UPLOAD_DIR / file_id
        if not video_file.exists():
            raise HTTPException(404, "视频文件不存在")

        # 准备字幕样式
        font_size = style.get('fontSize', 24)
        font_color = style.get('fontColor', '#ffffff').lstrip('#')
        bg_color = style.get('backgroundColor', '#000000').lstrip('#')
        bg_opacity = style.get('backgroundOpacity', 0.5)
        stroke_color = style.get('strokeColor', '#000000').lstrip('#')
        stroke_width = style.get('strokeWidth', 2)

        subtitle_style = (
            f"FontSize={font_size},"
            f"FontName=Arial,"
            f"PrimaryColour=&H{font_color},"
            f"BackColour=&H{hex(int(bg_opacity * 255))[2:].zfill(2)}{bg_color},"
            f"OutlineColour=&H{stroke_color},"
            f"Outline={stroke_width},"
            f"BorderStyle=1"
        )

        # 生成输出文件
        output_file = SUBTITLED_VIDEO_DIR / f"{file_id}_{language}_subtitled.mp4"

        # 使用FFmpeg添加字幕
        cmd = [
            'ffmpeg', '-y',
            '-i', str(video_file),
            '-vf', f"subtitles={srt_file}:force_style='{subtitle_style}'",
            '-c:a', 'copy',
            str(output_file)
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            raise HTTPException(500, "生成字幕视频失败")

        # 清理临时文件
        srt_file.unlink(missing_ok=True)

        return {
            "subtitled_video": f"{file_id}_{language}_subtitled.mp4"
        }

    except Exception as e:
        raise HTTPException(500, str(e))

def get_video_duration(video_path: Path) -> float:
    """获取视频时长"""
    try:
        with VideoFileClip(str(video_path)) as video:
            return video.duration
    except Exception as e:
        raise HTTPException(500, f"获取视频时长失败: {str(e)}") 