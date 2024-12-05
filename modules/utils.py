import os
import uuid
from pathlib import Path
import aiofiles
from fastapi import UploadFile, HTTPException
from .config import UPLOAD_DIR, TEMP_DIR

async def save_upload_file(file: UploadFile, file_id: str = None) -> str:
    """保存上传的文件并返回文件ID"""
    try:
        # 获取文件扩展名
        ext = Path(file.filename).suffix
        
        # 如果没有提供 file_id，生成新的
        if not file_id:
            file_id = str(uuid.uuid4())
            
        # 确保 file_id 不包含扩展名
        file_id = file_id.rsplit('.', 1)[0]
        
        # 完整的文件名（带扩展名）
        filename = f"{file_id}{ext}"
        
        # 确保上传目录存在
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        
        # 保存文件
        file_path = UPLOAD_DIR / filename
        
        # 如果文件已存在，先删除
        if file_path.exists():
            file_path.unlink()
            
        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)
            
        return filename
        # return file_id
    except Exception as e:
        raise HTTPException(500, f"保存文件失败: {str(e)}")

def clean_temp_files(file_id: str):
    """清理临时文件"""
    try:
        temp_pattern = f"*{file_id}*"
        for temp_file in Path(TEMP_DIR).glob(temp_pattern):
            temp_file.unlink(missing_ok=True)
    except Exception as e:
        print(f"清理临时文件失败: {str(e)}")

def format_time(seconds: float) -> str:
    """将秒数转换为 HH:MM:SS,mmm 格式"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds = int(seconds % 60)
    milliseconds = int((seconds * 1000) % 1000)
    
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"

def convert_to_srt(subtitles):
    """将JSON字幕转换为SRT格式"""
    srt_content = []
    for i, subtitle in enumerate(subtitles, 1):
        start_time = float(subtitle['start'])
        duration = float(subtitle['duration'])
        end_time = start_time + duration
        
        # 转换时间格式 (秒 -> HH:MM:SS,mmm)
        start = format_time(start_time)
        end = format_time(end_time)
        
        srt_content.extend([
            str(i),
            f"{start} --> {end}",
            subtitle['text'],
            ""  # 空行分隔
        ])
    
    return "\n".join(srt_content)

def format_time(seconds):
    """将秒数转换为SRT时间格式"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds = seconds % 60
    milliseconds = int((seconds - int(seconds)) * 1000)
    return f"{hours:02d}:{minutes:02d}:{int(seconds):02d},{milliseconds:03d}"