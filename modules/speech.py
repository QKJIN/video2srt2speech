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
    SUPPORTED_VOICES,
    SUBTITLE_DIR
)
from .websocket import send_message
import json
from .tts import tts as local_tts

async def generate_speech(file_id: str, subtitle_index: int, text: str, voice_name: str = "zh-CN-XiaoxiaoNeural", use_local_tts: bool = False):
    try:
        if use_local_tts:
            # 使用本地 TTS
            audio_data = await local_tts.generate_speech(text)
            
            # 准备音频文件路径
            audio_dir = AUDIO_DIR / file_id / "local"
            audio_dir.mkdir(parents=True, exist_ok=True)
            
            audio_file = audio_dir / f"{subtitle_index:04d}.mp3"
            
            # 保存音频
            import soundfile as sf
            sf.write(str(audio_file), audio_data, 22050)
            
            return {"success": True, "message": "本地TTS生成成功"}
        else:
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

async def recognize_speech(file_id: str, audio_path: Path, language: str = "zh-CN", max_retries: int = 3):
    """语音识别函数，添加重试机制"""
    for attempt in range(max_retries):
        try:
            if not audio_path.exists():
                raise HTTPException(500, f"音频文件不存在: {audio_path}")
                
            print(f"开始识别音频 (尝试 {attempt + 1}/{max_retries}): {audio_path}")
            
            # 如果不是第一次尝试，添加延迟
            if attempt > 0:
                delay = 5 * (attempt + 1)  # 递增延迟
                print(f"等待 {delay} 秒后重试...")
                await asyncio.sleep(delay)

            # 验证音频文件
            try:
                audio_info = await asyncio.create_subprocess_exec(
                    'ffprobe',
                    '-v', 'error',
                    '-show_entries', 'format=duration',
                    '-of', 'default=noprint_wrappers=1:nokey=1',
                    str(audio_path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await audio_info.communicate()
                if audio_info.returncode != 0 or not stdout:
                    raise Exception("无效的音频文件")
                duration = float(stdout.decode().strip())
                if duration < 0.1:  # 如果音频太短
                    return []  # 返回空结果
            except Exception as e:
                print(f"音频文件验证失败: {str(e)}")
                continue

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
                "SpeechServiceConnection_InitialSilenceTimeoutMs", "1000"
            )
            speech_config.set_property_by_name(
                "SpeechServiceConnection_EndSilenceTimeoutMs", "500"
            )
            speech_config.set_property_by_name(
                "SpeechServiceConnection_SegmentationMode", "SentenceBoundary"
            )
            
            audio_config = speechsdk.AudioConfig(filename=str(audio_path))
            speech_recognizer = speechsdk.SpeechRecognizer(
                speech_config=speech_config, 
                audio_config=audio_config
            )

            results = []
            recognition_complete = asyncio.Event()
            error_occurred = False
            error_message = None
            
            def handle_result(evt):
                if evt.result.text:
                    duration = evt.result.duration / 10000000
                    offset = evt.result.offset / 10000000
                    results.append({
                        "start": offset,
                        "duration": duration,
                        "text": evt.result.text
                    })

            def handle_canceled(evt):
                nonlocal error_occurred, error_message
                error_occurred = True
                error_message = f"语音识别被取消: {evt.result.cancellation_details.reason}\n" \
                              f"错误详情: {evt.result.cancellation_details.error_details}"
                recognition_complete.set()

            def handle_completed(evt):
                recognition_complete.set()

            speech_recognizer.recognized.connect(handle_result)
            speech_recognizer.session_stopped.connect(handle_completed)
            speech_recognizer.canceled.connect(handle_canceled)

            speech_recognizer.start_continuous_recognition()
            
            try:
                # 添加超时机制
                timeout = 30  # 30秒超时
                try:
                    await asyncio.wait_for(recognition_complete.wait(), timeout)
                except asyncio.TimeoutError:
                    print(f"识别超时，尝试 {attempt + 1}/{max_retries}")
                    continue
            finally:
                speech_recognizer.stop_continuous_recognition()

            if error_occurred:
                if "Quota exceeded" in error_message:
                    print(f"配额超限，尝试 {attempt + 1}/{max_retries}")
                    continue
                raise Exception(error_message)

            if results:
                return results
            
        except Exception as e:
            if attempt == max_retries - 1:
                print(f"所有重试都失败: {str(e)}")
                raise
            print(f"尝试 {attempt + 1} 失败: {str(e)}")
            continue

    raise HTTPException(500, "语音识别失败，超过最大重试次数")

async def generate_speech_for_file(
    file_id: str, 
    target_language: str = None,
    voice_name: str = None,
    use_local_tts: bool = False
):
    """为整个文件生成语音"""
    try:
        # 读取字幕文件
        file_id_without_ext = Path(file_id).stem
        subtitle_file = SUBTITLE_DIR / f"{file_id_without_ext}_{target_language}.json"
        if not subtitle_file.exists():
            subtitle_file = SUBTITLE_DIR / f"{file_id_without_ext}.json"
        
        if not subtitle_file.exists():
            raise HTTPException(404, f"未找到字幕文件")

        try:
            with open(subtitle_file, 'r', encoding='utf-8') as f:
                subtitles = json.load(f)
        except Exception as e:
            raise HTTPException(500, f"读取字幕文件失败: {str(e)}")

        # 准备音频目录
        audio_dir = AUDIO_DIR / file_id / (target_language if not use_local_tts else "local")
        audio_dir.mkdir(parents=True, exist_ok=True)

        audio_files = []
        total_count = len(subtitles)
        
        # 为每个字幕生成语音
        for i, subtitle in enumerate(subtitles):
            try:
                # 发送进度消息
                progress = (i + 1) / total_count * 100
                await send_message(file_id, {
                    "type": "progress",
                    "message": f"正在生成第 {i + 1}/{total_count} 个语音",
                    "progress": progress
                })

                if use_local_tts:
                    # 使用本地 TTS
                    await generate_speech(
                        file_id=file_id,
                        subtitle_index=i,
                        text=subtitle['text'],
                        use_local_tts=True
                    )
                else:
                    # 使用 Azure TTS
                    await generate_speech(
                        file_id=file_id,
                        subtitle_index=i,
                        text=subtitle['text'],
                        voice_name=voice_name
                    )

                audio_file = audio_dir / f"{i:04d}.mp3"
                if audio_file.exists():
                    audio_files.append({
                        "index": i,
                        "file": str(audio_file.relative_to(AUDIO_DIR)),
                        "text": subtitle['text'],
                        "start": subtitle['start'],
                        "duration": subtitle['duration']
                    })

            except Exception as e:
                print(f"警告：处理第 {i} 个字幕时出错: {str(e)}")
                continue

        if not audio_files:
            raise HTTPException(500, "未能生成任何语音文件")

        # 发送完成消息
        await send_message(file_id, {
            "type": "complete",
            "message": "语音生成完成",
            "progress": 100
        })

        return {
            "status": "success",
            "audio_files": audio_files,
            "total_count": len(audio_files),
            "language": target_language
        }

    except Exception as e:
        error_msg = f"生成语音失败: {str(e)}"
        print(error_msg)
        # 发送错误消息
        await send_message(file_id, {
            "type": "error",
            "message": error_msg
        })
        raise HTTPException(500, error_msg) 