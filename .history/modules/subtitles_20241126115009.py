import json
import os
from fastapi import HTTPException
import aiofiles
from pathlib import Path
from .config import SUBTITLE_DIR

async def update_subtitle(file_id: str, index: int, new_text: str):
    try:
        file_id = file_id.rsplit('.', 1)[0] if '.' in file_id else file_id
        subtitle_file = SUBTITLE_DIR / f"{file_id}.json"
        
        if not subtitle_file.exists():
            raise HTTPException(404, "字幕文件不存在")

        async with aiofiles.open(subtitle_file, "r", encoding="utf-8") as f:
            content = await f.read()
            subtitles = json.loads(content)

        if not isinstance(subtitles, list) or index >= len(subtitles):
            raise HTTPException(400, "无效的字幕索引")

        subtitles[index]["text"] = new_text

        async with aiofiles.open(subtitle_file, "w", encoding="utf-8") as f:
            await f.write(json.dumps(subtitles, ensure_ascii=False, indent=2))

        return {"status": "success"}
    except Exception as e:
        raise HTTPException(500, f"更新字幕失败: {str(e)}")

def convert_to_srt(subtitles):
    srt_content = ""
    for i, subtitle in enumerate(subtitles, 1):
        start_time = float(subtitle['start'])
        duration = float(subtitle.get('duration', 5))
        end_time = start_time + duration
        
        start_str = f"{int(start_time//3600):02d}:{int((start_time%3600)//60):02d}:{int(start_time%60):02d},{int((start_time*1000)%1000):03d}"
        end_str = f"{int(end_time//3600):02d}:{int((end_time%3600)//60):02d}:{int(end_time%60):02d},{int((end_time*1000)%1000):03d}"
        
        srt_content += f"{i}\n{start_str} --> {end_str}\n{subtitle.get('text', '')}\n\n"
    
    return srt_content 