from azure.ai.translation.text import TextTranslationClient, TranslatorCredential
from fastapi import HTTPException
from .config import (
    AZURE_TRANSLATOR_KEY,
    AZURE_TRANSLATOR_REGION,
    SUBTITLE_DIR
)
import json

async def translate_subtitles(file_id: str, source_language: str, target_language: str):
    try:
        if not AZURE_TRANSLATOR_KEY or not AZURE_TRANSLATOR_REGION:
            raise HTTPException(500, "翻译服务配置缺失")
        
        # 读取源字幕
        print(f"读取源字幕: {file_id}")
        file_id_without_ext = file_id.rsplit('.', 1)[0]
        source_subtitle_file = SUBTITLE_DIR / f"{file_id_without_ext}.json"
        
        if not source_subtitle_file.exists():
            raise HTTPException(404, "源字幕文件未找到")

        with open(source_subtitle_file, 'r', encoding='utf-8') as f:
            subtitles = json.load(f)

        if not subtitles or not isinstance(subtitles, list):
            raise HTTPException(400, "无效的字幕数据格式")

        # 初始化翻译客户端
        credential = TranslatorCredential(
            AZURE_TRANSLATOR_KEY,
            AZURE_TRANSLATOR_REGION
        )
        translator = TextTranslationClient(
            endpoint="https://api.cognitive.microsofttranslator.com",
            credential=credential
        )

        # 准备翻译文本
        texts = [subtitle["text"] for subtitle in subtitles]
        
        # 批量翻译
        batch_size = 100
        translated_texts = []
        
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            input_texts = [{"text": text} for text in batch]
            
            response = translator.translate(
                content=input_texts,
                to=[target_language],
                from_parameter=source_language
            )
            
            batch_translations = [
                translation.translations[0].text if translation.translations 
                else "" for translation in response
            ]
            translated_texts.extend(batch_translations)

        # 创建翻译后的字幕
        translated_subtitles = []
        for i, subtitle in enumerate(subtitles):
            translated_subtitle = subtitle.copy()
            translated_subtitle["text"] = translated_texts[i]
            translated_subtitles.append(translated_subtitle)

        # 保存翻译后的字幕
        target_subtitle_file = SUBTITLE_DIR / f"{file_id_without_ext}_{target_language}.json"
        with open(target_subtitle_file, 'w', encoding='utf-8') as f:
            json.dump(translated_subtitles, f, ensure_ascii=False, indent=2)

        return {
            "subtitles": translated_subtitles,
            "source_language": source_language,
            "target_language": target_language,
            "total_count": len(translated_subtitles)
        }

    except Exception as e:
        raise HTTPException(500, f"翻译失败: {str(e)}") 