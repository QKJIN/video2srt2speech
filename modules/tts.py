import torch
from pathlib import Path
from fastapi import HTTPException
import numpy as np
import edge_tts
import asyncio
import io
from pydub import AudioSegment
import langid

class EdgeTTS:
    def __init__(self):
        self.initialized = True
        
        # 语言到声音的映射
        self.voice_map = {
            "zh": "zh-CN-XiaoxiaoNeural",  # 中文
            "en": "en-US-AriaNeural",      # 英语
            "ja": "ja-JP-NanamiNeural",    # 日语
            "ko": "ko-KR-SunHiNeural",     # 韩语
            "fr": "fr-FR-DeniseNeural",    # 法语
            "de": "de-DE-KatjaNeural",     # 德语
            "es": "es-ES-ElviraNeural",    # 西班牙语
            "ru": "ru-RU-SvetlanaNeural",  # 俄语
            "it": "it-IT-DiegoNeural",     # 意大利语
            "pt": "pt-PT-DuarteNeural",   # 葡萄牙语
        }
        
        # 语言代码映射
        self.language_codes = {
            "zh": "zh-CN",
            "en": "en-US",
            "ja": "ja-JP",
            "ko": "ko-KR",
            "fr": "fr-FR",
            "de": "de-DE",
            "es": "es-ES",
            "ru": "ru-RU",
            "it": "it-IT",
            "pt": "pt-PT",
            # 添加语言代码转换
            "zh-CN": "zh-CN",
            "en-US": "en-US",
            "ja-JP": "ja-JP",
            "ko-KR": "ko-KR",
            "fr-FR": "fr-FR",
            "de-DE": "de-DE",
            "es-ES": "es-ES",
            "it-IT": "it-IT",
            "pt-PT": "pt-PT",
            "ru-RU": "ru-RU",
        }

    def detect_language(self, text: str) -> str:
        """检测文本语言"""
        lang, _ = langid.classify(text)
        return self.language_codes.get(lang, "en-US")  # 默认使用英语
    
    async def generate_speech(self, text: str, language: str = None, voice_name: str = None, speed: float = 1.0):
        """生成语音
        Args:
            text: 要转换的文本
            language: 语言代码 (zh-CN, en-US, etc.)
            voice_name: 指定的声音名称
            speed: 语速 (0.5-2.0)
        """
        try:
            # 如果没有指定语言，自动检测
            if language is None:
                language = self.detect_language(text)
            else:
                # 转换语言代码格式
                language = self.language_codes.get(language, "en-US")
            
            # 如果没有指定声音，使用默认映射
            if voice_name is None:
                base_lang = language.split('-')[0]
                voice_name = self.voice_map.get(base_lang, "en-US-AriaNeural")
            
            print(f"使用语言: {language}, 声音: {voice_name}")
            
            # 创建临时文件
            temp_file = io.BytesIO()
            
            # 生成音频
            print('speed is {0}'.format(speed))
            communicate = edge_tts.Communicate(
                text, 
                voice_name, 
                rate=f"+{int((speed-1)*100)}%"  # 格式应为 "+0%", "+50%", "-50%" 等
            )
            # edge-tts 使用百分比字符串来表示语速
            
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    temp_file.write(chunk["data"])
            
            # 重置缓冲区指针
            temp_file.seek(0)
            
            # 从 MP3 格式加载音频
            audio_segment = AudioSegment.from_mp3(temp_file)
            
            # 转换为单声道
            if audio_segment.channels > 1:
                audio_segment = audio_segment.set_channels(1)
            
            # 转换为 numpy array
            samples = np.array(audio_segment.get_array_of_samples(), dtype=np.float32)
            samples = samples / (2**15)  # 转换为 [-1, 1] 范围
            
            return samples
            
        except Exception as e:
            print(f"生成语音失败: {str(e)}")
            raise HTTPException(500, f"生成语音失败: {str(e)}")

# 创建全局 TTS 实例
tts = EdgeTTS()