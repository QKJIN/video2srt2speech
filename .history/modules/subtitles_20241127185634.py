import json
import os
from fastapi import HTTPException
import aiofiles
from pathlib import Path
import math
import asyncio
from . import speech, audio, video, websocket
from .config import (
    TEMP_DIR, 
    SUBTITLE_DIR, 
    AUDIO_DIR, 
    UPLOAD_DIR,
    AZURE_SPEECH_KEY,
    AZURE_SPEECH_REGION
)
from .utils import convert_to_srt
import re
import azure.cognitiveservices.speech as speechsdk

async def update_subtitle(file_id: str, data: dict):
    """更新字幕内容"""
    try:
        file_id = file_id.rsplit('.', 1)[0] if '.' in file_id else file_id
        subtitle_file = SUBTITLE_DIR / f"{file_id}.json"
        
        if not subtitle_file.exists():
            raise HTTPException(404, "字幕文件不存在")

        async with aiofiles.open(subtitle_file, "r", encoding="utf-8") as f:
            content = await f.read()
            subtitles = json.loads(content)

        # 检查索引是否有效
        index = data.get("index")
        new_text = data.get("text")
        
        if not isinstance(subtitles, list) or index >= len(subtitles):
            raise HTTPException(400, "无效的字幕索引")

        # 更新字幕文本
        subtitles[index]["text"] = new_text

        async with aiofiles.open(subtitle_file, "w", encoding="utf-8") as f:
            await f.write(json.dumps(subtitles, ensure_ascii=False, indent=2))

        return {"status": "success"}
    except Exception as e:
        raise HTTPException(500, f"更新字幕失败: {str(e)}")

async def update_single_subtitle(file_id: str, index: int, new_text: str):
    """更新单个字幕"""
    return await update_subtitle(file_id, {"index": index, "text": new_text})

async def generate_subtitles(file_id: str, language: str = "zh-CN", use_whisper: bool = False):
    """生成字幕的主要逻辑"""
    try:
        print(f"开始生成字幕，文件ID: {file_id}, 使用Whisper: {use_whisper}")
        
        # 获取音频文件路径
        audio_file_id = os.path.splitext(file_id)[0] + '.mp3'
        audio_path = AUDIO_DIR / audio_file_id
        video_path = UPLOAD_DIR / file_id
        
        if not audio_path.exists():
            print(f"音频文件不存在: {audio_path}")
            raise HTTPException(404, "音频文件未找到，请先提取音频")

        # 如果使用 Whisper
        if use_whisper:
            from . import whisper_utils
            
            # 发送开始消息
            await websocket.send_message(file_id, {
                "type": "progress",
                "message": "正在使用Whisper生成字幕",
                "progress": 0
            })
            
            try:
                # 使用 Whisper 生成字幕
                all_subtitles = await whisper_utils.transcribe_audio(audio_path, language)
                
                # 发送完成消息
                await websocket.send_message(file_id, {
                    "type": "progress",
                    "message": "Whisper字幕生成完成",
                    "progress": 100
                })
                
            except Exception as e:
                error_msg = f"Whisper字幕生成失败: {str(e)}"
                print(error_msg)
                await websocket.send_message(file_id, {
                    "type": "error",
                    "message": error_msg
                })
                raise HTTPException(500, error_msg)
                
        else:
            # 使用原有的 Azure 方式生成字幕
            # ... 原有的代码保持不变 ...

        # 保存字幕文件
        file_id_without_ext = os.path.splitext(file_id)[0]
        subtitle_path = SUBTITLE_DIR / f"{file_id_without_ext}.json"
        with open(subtitle_path, "w", encoding="utf-8") as f:
            json.dump(all_subtitles, f, ensure_ascii=False, indent=2)
        
        return all_subtitles

    except Exception as e:
        error_msg = f"生成字幕时出错: {str(e)}"
        print(error_msg)
        await websocket.send_message(file_id, {
            "type": "error",
            "message": error_msg
        })
        raise HTTPException(500, error_msg)

async def merge_bilingual_subtitles(file_id: str, source_language: str, target_language: str):
    """合并双语字幕"""
    try:
        file_id_without_ext = Path(file_id).stem
        source_file = SUBTITLE_DIR / f"{file_id_without_ext}.json"
        target_file = SUBTITLE_DIR / f"{file_id_without_ext}_{target_language}.json"

        if not source_file.exists() or not target_file.exists():
            raise HTTPException(404, "源语言或目标语言字幕文件不存在")

        # 读取源语言字幕
        with open(source_file, 'r', encoding='utf-8') as f:
            source_subtitles = json.load(f)

        # 读取目标语言字幕
        with open(target_file, 'r', encoding='utf-8') as f:
            target_subtitles = json.load(f)

        if len(source_subtitles) != len(target_subtitles):
            raise HTTPException(500, "源语言和目标语言字幕数量不匹配")

        # 合并字幕
        bilingual_subtitles = []
        for src, tgt in zip(source_subtitles, target_subtitles):
            bilingual_subtitle = src.copy()
            bilingual_subtitle["text"] = f"{src['text']}\n{tgt['text']}"
            bilingual_subtitles.append(bilingual_subtitle)

        # 保存双语字幕
        output_file = SUBTITLE_DIR / f"{file_id_without_ext}_bilingual.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(bilingual_subtitles, f, ensure_ascii=False, indent=2)

        return {
            "message": "双语字幕合并成功",
            "subtitles": bilingual_subtitles
        }

    except Exception as e:
        raise HTTPException(500, f"合并双语字幕失败: {str(e)}")

async def save_subtitles_as_srt(file_id: str, language: str = None):
    """导出字幕为SRT格式"""
    try:
        file_id_without_ext = os.path.splitext(file_id)[0]
        
        # 确定要导出的字幕文件
        subtitle_files = []
        
        # 原始字幕
        original_subtitle = SUBTITLE_DIR / f"{file_id_without_ext}.json"
        if original_subtitle.exists():
            subtitle_files.append(("original", original_subtitle))
        
        # 翻译字幕（如果存在）
        if language:
            translated_subtitle = SUBTITLE_DIR / f"{file_id_without_ext}_{language}.json"
            if translated_subtitle.exists():
                subtitle_files.append((language, translated_subtitle))
        
        if not subtitle_files:
            raise HTTPException(404, "未找到字幕文件")
        
        # 转换并返回所有字幕文件
        srt_files = []
        for lang, subtitle_file in subtitle_files:
            # 读取JSON字幕
            with open(subtitle_file, 'r', encoding='utf-8') as f:
                subtitles = json.load(f)
            
            # 转换为SRT格式
            srt_content = convert_to_srt(subtitles)
            
            # 创建临时SRT文件
            temp_srt = TEMP_DIR / f"{file_id_without_ext}_{lang}.srt"
            with open(temp_srt, 'w', encoding='utf-8') as f:
                f.write(srt_content)
            
            srt_files.append({
                "language": lang,
                "file_path": str(temp_srt),
                "filename": f"{file_id_without_ext}_{lang}.srt"
            })
        
        return {
            "status": "success",
            "files": srt_files
        }
        
    except Exception as e:
        raise HTTPException(500, f"导出SRT字幕失败: {str(e)}")