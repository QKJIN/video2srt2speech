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

async def generate_speech_for_file(file_id: str, target_language: str, voice_name: str = "zh-CN-XiaoxiaoNeural"):
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
        audio_dir = AUDIO_DIR / file_id / target_language
        audio_dir.mkdir(parents=True, exist_ok=True)

        # 配置语音合成
        speech_config = speechsdk.SpeechConfig(
            subscription=AZURE_SPEECH_KEY, 
            region=AZURE_SPEECH_REGION
        )
        speech_config.speech_synthesis_voice_name = voice_name

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

                # 生成临时WAV文件和最终MP3文件的路径
                temp_wav_file = audio_dir / f"{i:04d}_temp.wav"
                temp_silence_file = audio_dir / f"{i:04d}_silence.wav"
                audio_file = audio_dir / f"{i:04d}.mp3"
                
                # 获取要转换的文本
                text = subtitle.get("text", "")
                if not text:
                    print(f"警告：第 {i} 个字幕没有文本内容")
                    continue

                # 生成语音
                audio_config = speechsdk.audio.AudioOutputConfig(filename=str(temp_wav_file))
                synthesizer = speechsdk.SpeechSynthesizer(
                    speech_config=speech_config, 
                    audio_config=audio_config
                )
                
                result = synthesizer.speak_text_async(text).get()
                
                if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                    # 获取当前字幕的时间信息
                    current_start = float(subtitle.get("start", 0))
                    current_duration = float(subtitle.get("duration", 0))
                    
                    # 计算下一个字幕的开始时间
                    if i < len(subtitles) - 1:
                        next_start = float(subtitles[i + 1].get("start", 0))
                    else:
                        # 对于最后一个字幕，使用其结束时间
                        next_start = current_start + current_duration

                    # 计算需要的静音时长（从当前字幕开始到下一个字幕开始的时间）
                    total_segment_duration = next_start - current_start
                    
                    # 获取生成的语音文件时长
                    voice_duration = float(subprocess.check_output([
                        'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                        '-of', 'default=noprint_wrappers=1:nokey=1',
                        str(temp_wav_file)
                    ]).decode().strip())

                    # 计算需要添加的静音时长
                    silence_duration = max(0, total_segment_duration - voice_duration)
                    
                    print(f"字幕 {i}: 开始={current_start:.2f}, 总时长={total_segment_duration:.2f}, "
                          f"语音时长={voice_duration:.2f}, 需要静音={silence_duration:.2f}")

                    if silence_duration > 0:
                        # 生成静音音频
                        subprocess.run([
                            'ffmpeg', '-y',
                            '-f', 'lavfi',
                            '-i', f'anullsrc=r=16000:cl=mono',
                            '-t', str(silence_duration),
                            '-acodec', 'pcm_s16le',
                            str(temp_silence_file)
                        ], check=True)

                        # 合并语音和静音
                        subprocess.run([
                            'ffmpeg', '-y',
                            '-i', str(temp_wav_file),
                            '-i', str(temp_silence_file),
                            '-filter_complex', '[0:a][1:a]concat=n=2:v=0:a=1[out]',
                            '-map', '[out]',
                            '-codec:a', 'libmp3lame',
                            '-qscale:a', '4',
                            str(audio_file)
                        ], check=True)

                        # 删除临时文件
                        temp_silence_file.unlink(missing_ok=True)
                    else:
                        # 直接转换为MP3
                        subprocess.run([
                            'ffmpeg', '-y',
                            '-i', str(temp_wav_file),
                            '-codec:a', 'libmp3lame',
                            '-qscale:a', '4',
                            str(audio_file)
                        ], check=True)
                    
                    # 删除临时WAV文件
                    temp_wav_file.unlink(missing_ok=True)
                    
                    # 添加到音频文件列表，使用原始字幕的时间信息
                    audio_files.append({
                        "index": i,
                        "file": str(audio_file.relative_to(AUDIO_DIR)),
                        "text": text,
                        "start": current_start,
                        "duration": total_segment_duration  # 使用完整的段落时长
                    })
                else:
                    error_details = result.properties.get(
                        speechsdk.PropertyId.SpeechServiceResponse_JsonErrorDetails
                    )
                    print(f"警告：生成第 {i} 个语音失败: {error_details}")

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