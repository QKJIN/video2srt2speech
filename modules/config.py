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
# LANGUAGE_CODE_MAP = {
#     "en": "en-US",
#     "zh": "zh-CN",
#     "zh-TW": "zh-CN",  # 暂时使用简体中文声音
#     "ja": "ja-JP"
# }
# 添加语言代码映射
LANGUAGE_CODE_MAP = {
    "zh-CN": "zh",
    "zh-TW": "zh",
    "en-US": "en",
    "en": "en",
    "ja-JP": "ja",
    "ja": "ja",
    "ko-KR": "ko",
    "ko": "ko",
    "fr-FR": "fr",
    "fr": "fr",
    "de-DE": "de",
    "de": "de",
    "es-ES": "es",
    "es": "es",
    "it-IT": "it",
    "it": "it",
    "pt-PT": "pt",
    "pt": "pt",
    "ru-RU": "ru",
    "ru": "ru"
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
    "zh-TW": [
        {"name": "zh-TW-HsiaoChenNeural", "gender": "Female", "description": "晓晨 - 活力女声"},
        {"name": "zh-TW-HsiaoYuNeural", "gender": "Female", "description": "晓语 - 温柔女声"},
        {"name": "zh-TW-HsiaoMeiNeural", "gender": "Female", "description": "晓美 - 甜美女声"},
        {"name": "zh-TW-HsiaoXuanNeural", "gender": "Female", "description": "晓萱 - 成熟女声"},
        {"name": "zh-TW-HsiaoQianNeural", "gender": "Female", "description": "晓倩 - 甜美女声"},
        {"name": "zh-TW-YunJheNeural", "gender": "Male", "description": "云哲 - 专业男声"},
        {"name": "zh-TW-WeiJyeNeural", "gender": "Male", "description": "伟杰 - 成熟男声"},
        {"name": "zh-TW-LiShiNeural", "gender": "Male", "description": "力士 - 青年男声"},
        {"name": "zh-TW-YuShiNeural", "gender": "Male", "description": "宇士 - 活力男声"}
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
    ],
    "ko-KR": [
        {"name": "ko-KR-SunHiNeural", "gender": "Female", "description": "Sun-Hi - 温暖自然"},
        {"name": "ko-KR-InJoonNeural", "gender": "Male", "description": "In-Joon - 专业男声"},
        {"name": "ko-KR-YuJinNeural", "gender": "Female", "description": "Yu-Jin - 活力女声"},
        {"name": "ko-KR-JiMinNeural", "gender": "Female", "description": "Ji-Min - 友好女声"},
        {"name": "ko-KR-SeoHyeonNeural", "gender": "Female", "description": "Seo-Hyeon - 成熟女声"},
        {"name": "ko-KR-GookMinNeural", "gender": "Male", "description": "Gook-Min - 年轻男声"},
        {"name": "ko-KR-BongJinNeural", "gender": "Male", "description": "Bong-Jin - 稳重男声"}
    ],
    "fr-FR": [
        {"name": "fr-FR-DeniseNeural", "gender": "Female", "description": "Denise - Professional"},
        {"name": "fr-FR-HenriNeural", "gender": "Male", "description": "Henri - Professional"}
    ],
    "de-DE": [
        {"name": "de-DE-KatjaNeural", "gender": "Female", "description": "Katja - Professional"},
        {"name": "de-DE-HannaNeural", "gender": "Female", "description": "Hanna - Professional"},
        {"name": "de-DE-BjarneNeural", "gender": "Male", "description": "Bjarne - Professional"},
        {"name": "de-DE-BerndNeural", "gender": "Male", "description": "Bernd - Professional"}
    ],
    "es-ES": [
        {"name": "es-ES-ElviraNeural", "gender": "Female", "description": "Elvira - Professional"},
        {"name": "es-ES-AlvaroNeural", "gender": "Male", "description": "Alvaro - Professional"}
    ],
    "it-IT": [
        {"name": "it-IT-IsabellaNeural", "gender": "Female", "description": "Isabella - Professional"},
        {"name": "it-IT-DiegoNeural", "gender": "Male", "description": "Diego - Professional"}
    ],
    "pt-PT": [
        {"name": "pt-PT-FernandaNeural", "gender": "Female", "description": "Fernanda - Professional"},
        {"name": "pt-PT-RaquelNeural", "gender": "Female", "description": "Raquel - Professional"},
        {"name": "pt-PT-DuarteNeural", "gender": "Male", "description": "Duarte - Professional"}
    ],
    "ru-RU": [
        {"name": "ru-RU-DariyaNeural", "gender": "Female", "description": "Dariya - Professional"},
        {"name": "ru-RU-SvetlanaNeural", "gender": "Female", "description": "Svetlana - Professional"},
        {"name": "ru-RU-DmitryNeural", "gender": "Male", "description": "Dmitry - Professional"}
    ]
}

# Whisper 模型配置
WHISPER_MODELS = {
    "tiny": {"size": "74 MB", "description": "最小模型，速度最快，精度最低"},
    "base": {"size": "142 MB", "description": "小型模型，速度较快，精度一般"},
    "small": {"size": "466 MB", "description": "中型模型，速度和精度均衡"},
    "medium": {"size": "1.5 GB", "description": "大型模型，精度较高，速度较慢"},
    "large": {"size": "2.9 GB", "description": "最大模型，精度最高，速度最慢"}
}

WHISPER_MODEL_SIZE = "base"  # 默认使用 base 模型
WHISPER_MODEL_PATH = MODELS_DIR / f"whisper-{WHISPER_MODEL_SIZE}.pt"
