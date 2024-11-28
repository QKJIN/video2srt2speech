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
MODELS_DIR = Path("models")

# 创建必要的目录
DIRS = [UPLOAD_DIR, AUDIO_DIR, SUBTITLE_DIR, STATIC_DIR, MERGED_DIR, SUBTITLED_VIDEO_DIR, TEMP_DIR, MODELS_DIR]

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
# 定义支持的语音列表
SUPPORTED_VOICES = {
    "zh-CN": [
        {"name": "zh-CN-XiaoxiaoNeural", "gender": "Female", "description": "晓晓 - 温暖自然"},
        {"name": "zh-CN-YunxiNeural", "gender": "Male", "description": "云希 - 青年男声"},
        {"name": "zh-CN-YunjianNeural", "gender": "Male", "description": "云健 - 成年男声"},
        {"name": "zh-CN-XiaochenNeural", "gender": "Female", "description": "晓辰 - 活力女声"},
        {"name": "zh-CN-YunyangNeural", "gender": "Male", "description": "云扬 - 新闻播音"},
        {"name": "zh-CN-XiaohanNeural", "gender": "Female", "description": "晓涵 - 温柔女声"},
        {"name": "zh-CN-XiaomoNeural", "gender": "Female", "description": "晓墨 - 活泼女声"},
        {"name": "zh-CN-XiaoxuanNeural", "gender": "Female", "description": "晓萱 - 成熟女声"}
    ],
    "en-US": [
        {"name": "en-US-JennyNeural", "gender": "Female", "description": "Jenny - Casual and friendly"},
        {"name": "en-US-GuyNeural", "gender": "Male", "description": "Guy - Professional"},
        {"name": "en-US-AriaNeural", "gender": "Female", "description": "Aria - Professional"},
        {"name": "en-US-DavisNeural", "gender": "Male", "description": "Davis - Casual"},
        {"name": "en-US-AmberNeural", "gender": "Female", "description": "Amber - Warm and engaging"},
        {"name": "en-US-JasonNeural", "gender": "Male", "description": "Jason - Natural and clear"},
        {"name": "en-US-SaraNeural", "gender": "Female", "description": "Sara - Clear and precise"},
        {"name": "en-US-TonyNeural", "gender": "Male", "description": "Tony - Friendly and natural"}
    ],
    "ja-JP": [
        {"name": "ja-JP-NanamiNeural", "gender": "Female", "description": "Nanami - Natural and warm"},
        {"name": "ja-JP-KeitaNeural", "gender": "Male", "description": "Keita - Professional"},
        {"name": "ja-JP-AoiNeural", "gender": "Female", "description": "Aoi - Cheerful and clear"},
        {"name": "ja-JP-DaichiNeural", "gender": "Male", "description": "Daichi - Friendly and natural"}
    ]
}

# 添加 Whisper 配置
WHISPER_MODEL_SIZE = "base"  # 可选: tiny, base, small, medium, large
WHISPER_MODEL_PATH = MODELS_DIR / f"whisper-{WHISPER_MODEL_SIZE}.pt"
