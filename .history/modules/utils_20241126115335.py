import os
import uuid
from pathlib import Path
import aiofiles
from fastapi import UploadFile, HTTPException
from .config import UPLOAD_DIR

async def save_upload_file(file: UploadFile) -> str:
    """保存上传的文件并返回文件ID"""
    try:
        file_extension = os.path.splitext(file.filename)[1]
        file_id = str(uuid.uuid4()) + file_extension
        
        file_path = UPLOAD_DIR / file_id
        async with aiofiles.open(file_path, "wb") as f:
            content = await file.read()
            await f.write(content)
        
        return file_id
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