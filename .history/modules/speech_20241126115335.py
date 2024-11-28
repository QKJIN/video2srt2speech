import azure.cognitiveservices.speech as speechsdk
from fastapi import HTTPException
import asyncio
import subprocess
from pathlib import Path
import re
from .config import (
    AZURE_SPEECH_KEY, 
    AZURE_SPEECH_REGION,
    TEMP_DIR,
    AUDIO_DIR,
    SUPPORTED_VOICES
)
from .websocket import send_message

async def generate_speech(file_id: str, subtitle_index: int, text: str, voice_name: str = "zh-CN-XiaoxiaoNeural"):
    try:
        # 验证语音名称
        language = voice_name.split("-")[0] + "-" + voice_name.split("-")[1]
        if language not in SUPPORTED_VOICES:
            raise HTTPException(400, f"不支持的语言: {language}")
            
        voice_exists = False
        for voice in SUPPORTED_VOICES[language]:
            if voice["name"] == voice_name:
                voice_exists = True
                break
        if not voice_exists:
            raise HTTPException(400, f"指定的语音 {voice_name} 不存在")
            
        # 配置语音合成
        speech_config = speechsdk.SpeechConfig(
            subscription=AZURE_SPEECH_KEY, 
            region=AZURE_SPEECH_REGION
        )
        speech_config.speech_synthesis_voice_name = voice_name
        
        # 准备音频文件路径
        audio_dir = AUDIO_DIR / file_id / language
        audio_dir.mkdir(parents=True, exist_ok=True)
        
        temp_wav_file = audio_dir / f"{subtitle_index:04d}_temp.wav"
        audio_file = audio_dir / f"{subtitle_index:04d}.mp3"
        
        # 配置音频输出
        audio_config = speechsdk.AudioOutputConfig(filename=str(temp_wav_file))
        
        # 创建语音合成器
        speech_synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=speech_config, 
            audio_config=audio_config
        )
        
        # 生成语音
        result = speech_synthesizer.speak_text_async(text).get()
        
        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            # 将WAV转换为MP3
            subprocess.run([
                'ffmpeg', '-y',
                '-i', str(temp_wav_file),
                '-codec:a', 'libmp3lame',
                '-qscale:a', '4',
                str(audio_file)
            ], check=True)
            
            temp_wav_file.unlink(missing_ok=True)
            return {"success": True, "message": "语音生成成功"}
        else:
            error_details = result.properties.get(
                speechsdk.PropertyId.SpeechServiceResponse_JsonErrorDetails
            )
            raise HTTPException(500, f"生成语音失败: {error_details}")
            
    except Exception as e:
        raise HTTPException(500, f"生成语音失败: {str(e)}")

async def recognize_speech(file_id: str, audio_path: Path, language: str = "zh-CN"):
    try:
        speech_config = speechsdk.SpeechConfig(
            subscription=AZURE_SPEECH_KEY, 
            region=AZURE_SPEECH_REGION
        )
        
        if language.lower() == "en":
            speech_config.speech_recognition_language = "en-US"
        else:
            speech_config.speech_recognition_language = language

        # 优化语音识别参数
        speech_config.set_property_by_name(
            "SpeechServiceConnection_InitialSilenceTimeoutMs", "2000"
        )
        speech_config.set_property_by_name(
            "SpeechServiceConnection_EndSilenceTimeoutMs", "1000"
        )
        speech_config.set_property_by_name(
            "SpeechServiceConnection_SegmentationMode", "SentenceBoundary"
        )
        
        # 配置音频输入
        audio_config = speechsdk.AudioConfig(filename=str(audio_path))
        speech_recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config, 
            audio_config=audio_config
        )

        # 存储识别结果
        results = []
        recognition_complete = asyncio.Event()
        
        def handle_result(evt):
            if evt.result.text:
                duration = evt.result.duration / 10000000
                offset = evt.result.offset / 10000000
                
                # 分割句子
                sentences = re.split('[。！？.!?]', evt.result.text)
                sentences = [s.strip() for s in sentences if s.strip()]
                
                if len(sentences) > 1:
                    total_chars = sum(len(s) for s in sentences)
                    current_offset = offset
                    for sentence in sentences:
                        if not sentence:
                            continue
                        sentence_ratio = len(sentence) / total_chars
                        sentence_duration = duration * sentence_ratio
                        optimal_duration = max(2.0, min(sentence_duration, 10.0))
                        
                        results.append({
                            "start": current_offset,
                            "duration": optimal_duration,
                            "text": sentence
                        })
                        current_offset += optimal_duration
                else:
                    optimal_duration = max(2.0, min(duration, 10.0))
                    results.append({
                        "start": offset,
                        "duration": optimal_duration,
                        "text": evt.result.text
                    })

        def handle_completed(evt):
            recognition_complete.set()

        # 注册事件处理函数
        speech_recognizer.recognized.connect(handle_result)
        speech_recognizer.session_stopped.connect(handle_completed)
        speech_recognizer.canceled.connect(handle_completed)

        # 开始识别
        speech_recognizer.start_continuous_recognition()
        
        try:
            await recognition_complete.wait()
        finally:
            speech_recognizer.stop_continuous_recognition()
        
        return results

    except Exception as e:
        raise HTTPException(500, f"语音识别失败: {str(e)}") 