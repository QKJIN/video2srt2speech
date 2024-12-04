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
    AZURE_SPEECH_REGION,
    MODELS_DIR
)
from .utils import convert_to_srt
import re
import azure.cognitiveservices.speech as speechsdk
import whisper
import torch

async def update_subtitle(file_id: str, data: dict):
    """更新字幕内容"""
    try:
        file_id = file_id.rsplit('.', 1)[0] if '.' in file_id else file_id
        subtitle_file = SUBTITLE_DIR / f"{file_id}.json"
        
        if not subtitle_file.exists():
            raise HTTPException(404, "字幕文件不存在")

        try:
            # 读取字幕文件
            async with aiofiles.open(subtitle_file, "r", encoding="utf-8") as f:
                content = await f.read()
                subtitles = json.loads(content)

            # 检查索引是否有效
            index = data.get("index")
            new_text = data.get("text")
            
            if index is None or new_text is None:
                raise HTTPException(400, "缺少必要的参数")
            
            if not isinstance(subtitles, list):
                raise HTTPException(400, "无效的字幕文件格式")
            
            if index < 0 or index >= len(subtitles):
                raise HTTPException(400, "无效的字幕索引")

            # 更新字幕文本
            subtitles[index]["text"] = new_text

            # 写入更新后的字幕
            async with aiofiles.open(subtitle_file, "w", encoding="utf-8") as f:
                await f.write(json.dumps(subtitles, ensure_ascii=False, indent=2))

            return {
                "status": "success",
                "message": "字幕更新成功",
                "index": index,
                "text": new_text
            }

        except json.JSONDecodeError:
            raise HTTPException(500, "字幕文件格式错误")
        except IOError as e:
            raise HTTPException(500, f"文件读写错误: {str(e)}")
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"更新字幕失败: {str(e)}")
        raise HTTPException(500, f"更新字幕失败: {str(e)}")

async def update_single_subtitle(file_id: str, index: int, new_text: str):
    """更新单个字幕"""
    if not isinstance(index, int):
        raise HTTPException(400, "字幕索引必须是整数")
    if not isinstance(new_text, str):
        raise HTTPException(400, "字幕文本必须是字符串")
        
    return await update_subtitle(file_id, {
        "index": index,
        "text": new_text
    })

async def generate_subtitles(file_id: str, audio_path: Path, model_type: str = "whisper_tiny", language: str = "zh"):
    """生成字幕的包装函数
    Args:
        file_id: 文件ID
        audio_path: 音频文件路径
        model_type: 模型类型 (whisper_tiny, whisper_base, whisper_small, whisper_medium, whisper_large, azure)
        language: 语言代码
    """
    return await subtitle_generator.generate_subtitles(file_id, audio_path, model_type, language)

class SubtitleGenerator:
    def __init__(self):
        self.model = None
        self.model_name = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        
        # 添加语言代码映射
        self.language_codes = {
            "zh": "zh",
            "zh-CN": "zh",
            "zh-cn": "zh",
            "en": "en",
            "en-US": "en",
            "ja": "ja",
            "ja-JP": "ja",
            "ko": "ko",
            "ko-KR": "ko",
            "fr": "fr",
            "fr-FR": "fr",
            "de": "de",
            "de-DE": "de",
            "es": "es",
            "es-ES": "es",
            "ru": "ru",
            "ru-RU": "ru"
        }
        
    async def generate_subtitles(self, file_id: str, audio_path: Path, model_type: str = "whisper_tiny", language: str = "zh"):
        """生成字幕"""
        try:
            print(f"使用模型: {model_type}, 语言: {language}")
            
            # 转换语言代码
            whisper_language = self.language_codes.get(language, "zh")
            print(f"转换后的语言代码: {whisper_language}")
            
            if model_type == "azure":
                # 使用 Azure 语音识别
                results = await speech.recognize_speech(file_id, audio_path, language)
                
                # 转换为统一格式
                subtitles = []
                for result in results:
                    subtitles.append({
                        "start": result["start"],
                        "duration": result["duration"],
                        "text": result["text"]
                    })
                
            else:
                # 使用 Whisper 模型
                whisper_model = model_type.replace("whisper_", "")
                
                # 如果模型变化了，重新加载
                if self.model_name != whisper_model:
                    print(f"加载 Whisper 模型: {whisper_model}")
                    self.model = whisper.load_model(whisper_model, device=self.device)
                    self.model_name = whisper_model
                
                # 转录音频
                print(f"使用 {whisper_model} 模型转录音频...")
                result = self.model.transcribe(
                    str(audio_path),
                    language=whisper_language,  # 使用转换后的语言代码
                    task="transcribe",
                    verbose=False
                )
                
                # 提取字幕
                subtitles = []
                for segment in result["segments"]:
                    subtitles.append({
                        "start": segment["start"],
                        "duration": segment["end"] - segment["start"],
                        "text": segment["text"].strip()
                    })
                
                print(f"转录完成，生成了 {len(subtitles)} 条字幕")
            
            # 保存字幕文件
            file_id_without_ext = file_id.rsplit('.', 1)[0]
            subtitle_file = SUBTITLE_DIR / f"{file_id_without_ext}.json"
            with open(subtitle_file, 'w', encoding='utf-8') as f:
                json.dump(subtitles, f, ensure_ascii=False, indent=2)
            
            return subtitles
            
        except Exception as e:
            print(f"生成字幕失败: {str(e)}")
            raise HTTPException(500, f"生成字幕失败: {str(e)}")
    
    def __del__(self):
        # 清理模型
        if self.model is not None:
            del self.model
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

# 创建全局实例
subtitle_generator = SubtitleGenerator()

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
    temp_files = []  # 用于跟踪创建的临时文件
    
    try:
        file_id_without_ext = os.path.splitext(file_id)[0]
        
        # 确保临时目录存在
        TEMP_DIR.mkdir(exist_ok=True)
        
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
        
        srt_files = []
        # 转换并返回所有字幕文件
        for lang, subtitle_file in subtitle_files:
            try:
                # 读取JSON字幕
                with open(subtitle_file, 'r', encoding='utf-8') as f:
                    subtitles = json.load(f)
                
                # 转换为SRT格式
                srt_content = convert_to_srt(subtitles)
                
                # 创建临时SRT文件
                temp_srt = TEMP_DIR / f"{file_id_without_ext}_{lang}.srt"
                temp_files.append(temp_srt)  # 添加到跟踪列表
                
                # 写入内容
                with open(temp_srt, 'w', encoding='utf-8') as f:
                    f.write(srt_content)
                
                # 验证文件是否成功创建
                if not temp_srt.exists():
                    raise HTTPException(500, f"创建SRT文件失败: {temp_srt}")
                
                srt_files.append({
                    "language": lang,
                    "file_path": str(temp_srt),
                    "filename": f"{file_id_without_ext}_{lang}.srt"
                })
                
            except Exception as e:
                print(f"处理字幕文件失败: {str(e)}")
                raise
        
        if not srt_files:
            raise HTTPException(500, "未能创建任何SRT文件")
        
        # 确保所有文件都存在
        for srt_file in srt_files:
            if not Path(srt_file["file_path"]).exists():
                raise HTTPException(500, f"SRT文件不存在: {srt_file['file_path']}")
        
        return {
            "status": "success",
            "files": srt_files
        }
        
    except Exception as e:
        # 清理所有临时文件
        for temp_file in temp_files:
            try:
                if temp_file.exists():
                    temp_file.unlink()
            except Exception as cleanup_error:
                print(f"清理临时文件失败: {cleanup_error}")
        
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(500, f"导出SRT字幕失败: {str(e)}")

# 在文件末尾添加导出
__all__ = [
    'generate_subtitles',
    'update_subtitle',
    'update_single_subtitle',
    'merge_bilingual_subtitles'
]