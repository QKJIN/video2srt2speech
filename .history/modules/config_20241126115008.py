import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# 目录配置
UPLOAD_DIR = Path("uploads")
AUDIO_DIR = Path("audio")
SUBTITLE_DIR = Path("subtitles")
STATIC_DIR = Path("static")
MERGED_DIR = Path("merged")
SUBTITLED_VIDEO_DIR = Path("subtitled_videos")
TEMP_DIR = Path("temp")

# 创建必要的目录
DIRS = [UPLOAD_DIR, AUDIO_DIR, SUBTITLE_DIR, STATIC_DIR, MERGED_DIR, SUBTITLED_VIDEO_DIR, TEMP_DIR]

# Azure配置
AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY")
AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION")
AZURE_TRANSLATOR_KEY = os.getenv("AZURE_TRANSLATOR_KEY")
AZURE_TRANSLATOR_REGION = os.getenv("AZURE_TRANSLATOR_REGION")

# 语言配置
LANGUAGE_CODE_MAP = {
    "en": "en-US",
    "zh": "zh-CN",
    "zh-TW": "zh-CN",  # 暂时使用简体中文声音
    "ja": "ja-JP"
}

# 支持的语音列表
SUPPORTED_VOICES = {
    "zh-CN": [
        {"name": "zh-CN-XiaoxiaoNeural", "gender": "Female", "description": "晓晓 - 温暖自然"},
        # ... 其他中文语音
    ],
    "en-US": [
        {"name": "en-US-JennyNeural", "gender": "Female", "description": "Jenny - Casual and friendly"},
        # ... 其他英文语音
    ],
    "ja-JP": [
        {"name": "ja-JP-NanamiNeural", "gender": "Female", "description": "Nanami - Natural and warm"},
        # ... 其他日文语音
    ]
} 