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
from pydub import AudioSegment
import io


import numpy as np
from scipy.io import wavfile
import soundfile as sf

def trim_silence_end(audio_data, sample_rate, threshold=0.01, min_silence_duration=0.1):
    """
    裁剪音频末尾的静音部分
    
    参数:
    - threshold: 音量阈值，低于此值视为静音
    - min_silence_duration: 最小静音持续时间(秒)
    """
    # 计算音频的RMS能量
    frame_length = int(sample_rate * 0.02)  # 20ms 帧
    energy = np.array([
        np.sqrt(np.mean(frame**2))
        for frame in np.array_split(audio_data, len(audio_data) // frame_length)
    ])
    
    # 从后向前查找第一个非静音帧
    min_silence_frames = int(min_silence_duration * sample_rate / frame_length)
    silence_count = 0
    end_frame = len(energy) - 1
    
    for i in range(len(energy) - 1, -1, -1):
        if energy[i] > threshold:
            end_frame = i + 1  # 保留一帧过渡
            break
        silence_count += 1
        if silence_count < min_silence_frames:
            end_frame = i
    
    # 计算实际采样点位置
    end_sample = min(len(audio_data), (end_frame + 1) * frame_length)
    return audio_data[:end_sample]

async def generate_speech(file_id: str, subtitle_index: int, text: str, voice_name: str = "zh-CN-XiaoxiaoNeural", use_local_tts: bool = False, target_language: str = "en-US", speed: float = 1.0):
    try:
        if use_local_tts:
            # 使用本地 TTS
            audio_data = await local_tts.generate_speech(text, target_language, voice_name, speed)
            
            # 裁剪末尾静音
            trimmed_audio = trim_silence_end(audio_data, 22050)  # 22050是采样率
            
            # 准备音频文件路径
            audio_dir = AUDIO_DIR / file_id / target_language
            audio_dir.mkdir(parents=True, exist_ok=True)
            
            audio_file = audio_dir / f"{subtitle_index:04d}.mp3"
            
            # 保存音频
            sf.write(str(audio_file), trimmed_audio, 22050)
            
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
            
            # 设置语速
            # Azure的语速范围是-100到200，0是正常速度
            # 将我们的speed参数(0.5-2.0)转换为Azure的范围
            rate_value = int((speed - 1) * 100)  # 1.0->0, 2.0->100, 0.5->-50
            speech_config.set_speech_synthesis_output_format(speechsdk.SpeechSynthesisOutputFormat.Audio16Khz32KBitRateMonoMp3)
            speech_config.speech_synthesis_rate = rate_value

            # 配置音频输出
            audio_config = speechsdk.audio.AudioOutputConfig(filename=str(temp_wav_file))

            # 创建语音合成器
            speech_synthesizer = speechsdk.SpeechSynthesizer(
                speech_config=speech_config, 
                audio_config=audio_config
            )
            
            # 生成语音
            result = speech_synthesizer.speak_text_async(text).get()
            
            if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                try:
                    # # 确保WAV文件已经生成
                    # if not temp_wav_file.exists():
                    #     raise Exception("WAV文件未生成")

                    # # 使用 pydub 转换为 MP3
                    # audio = AudioSegment.from_wav(str(temp_wav_file))
                    # audio.export(str(audio_file), format='mp3', parameters=["-q:a", "4"])
                    
                    # 确保WAV文件已经生成
                    if not temp_wav_file.exists():
                        raise Exception("WAV文件未生成")

                    # 使用 pydub 加载 WAV 文件
                    audio = AudioSegment.from_wav(str(temp_wav_file))
                    samples = np.array(audio.get_array_of_samples())
                    sample_rate = audio.frame_rate

                    # 裁剪静音
                    trimmed_samples = trim_silence_end(samples, sample_rate)

                    # 转换为 MP3
                    trimmed_audio = AudioSegment(
                        trimmed_samples.tobytes(), 
                        frame_rate=sample_rate,
                        sample_width=2,  # 16-bit
                        channels=1  # mono
                    )
                    trimmed_audio.export(str(audio_file), format='mp3', parameters=["-q:a", "4"])
                    # 删除临时文件
                    temp_wav_file.unlink(missing_ok=True)
                    
                    return {"success": True, "message": "语音生成成功"}
                except Exception as e:
                    raise HTTPException(500, f"音频转换失败: {str(e)}")
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
                print(f"音频文件验失败: {str(e)}")
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
    speed: float = 1.0,
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

        with open(subtitle_file, 'r', encoding='utf-8') as f:
            subtitles = json.load(f)

        audio_files = []
        total_count = len(subtitles)
        
        # 为每个字幕生成语音
        for i, subtitle in enumerate(subtitles):
           
            # 发送进度消息
            progress = (i + 1) / total_count * 100
            await send_message(file_id, {
                "type": "progress",
                "message": f"正在生成第 {i + 1}/{total_count} 个语音",
                "progress": progress
            })
            # 检查字幕文本是否为空
            if not subtitle.get('text', '').strip():
                print(f"警告：第 {i + 1} 个字幕文本为空，跳过")
                continue

            # 生成音频
            result = await generate_speech(
                file_id=file_id,
                subtitle_index=i,
                text=subtitle['text'],
                voice_name=voice_name,
                use_local_tts=use_local_tts,
                target_language=target_language,
                speed=speed
            )

            if result.get("success"):
                audio_filename = f"{i:04d}.mp3"
                audio_path = AUDIO_DIR / file_id / target_language / audio_filename
                
                # 检查音频时长
                audio = AudioSegment.from_file(str(audio_path))
                audio_duration = audio.duration_seconds
                
                # 计算与下一个字幕的间隔
                gap_duration = 0
                if i < len(subtitles) - 1:
                    next_subtitle = subtitles[i + 1]
                    gap_duration = next_subtitle["start"] - (subtitle["start"] + subtitle["duration"])
                
                # 可用的总时长 = 字幕时长 + 间隔时长
                available_duration = subtitle["duration"] + gap_duration
                
                # 检查是否会影响下一个字幕
                will_affect_next = audio_duration > available_duration

                audio_files.append({
                    "index": i,
                    "file": str(audio_path.relative_to(AUDIO_DIR)),
                    "text": subtitle['text'],
                    "start": subtitle['start'],
                    "duration": subtitle['duration'],
                    "audio_duration": audio_duration,
                    "gap_duration": gap_duration,
                    "available_duration": available_duration,
                    "will_affect_next": will_affect_next
                })
            else:
                print(f"生成语音失败: 第 {i + 1} 个字幕")
                continue

        if not audio_files:
            raise HTTPException(500, "未能生成任何语音文件")

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
        await send_message(file_id, {
            "type": "error",
            "message": error_msg
        })
        raise HTTPException(500, error_msg)

# 修改现有的 generate_speech 函数签名和实现
async def generate_speech_single(
    file_id: str,
    index: int,
    target_language: str,
    use_local_tts: bool = False,
    voice_name: str = None,
    speed: float = 1.0  # 添加语速参数
):
    """为单条字幕生成语音"""
    try:
        file_id = file_id.rsplit('.', 1)[0] if '.' in file_id else file_id
        subtitle_file = SUBTITLE_DIR / f"{file_id}.json"
        
        if not subtitle_file.exists():
            raise HTTPException(404, "字幕文件不存在")

        # 读取字幕数据
        with open(subtitle_file, 'r', encoding='utf-8') as f:
            subtitles = json.load(f)

        if index >= len(subtitles):
            raise HTTPException(400, "无效的字幕索引")

        # 获取当前字幕
        current_subtitle = subtitles[index]
        subtitle_duration = current_subtitle["duration"]
        
        # 计算与下一个字幕的间隔
        gap_duration = 0
        if index < len(subtitles) - 1:
            next_subtitle = subtitles[index + 1]
            gap_duration = next_subtitle["start"] - (current_subtitle["start"] + current_subtitle["duration"])
        
        # 可用的总时长 = 字幕时长 + 间隔时长
        available_duration = subtitle_duration + gap_duration

        # 获取要转换的文本
        text_to_convert = current_subtitle["text"]
        
        # 如果存在翻译文件，使用翻译后的文本
        translations_file = SUBTITLE_DIR / f"{file_id}_{target_language}.json"
        if translations_file.exists():
            with open(translations_file, 'r', encoding='utf-8') as f:
                translations = json.load(f)
                if translations[index]["text"]:
                    text_to_convert = translations[index]["text"]

        # 生成音频
        result = await generate_speech(
            file_id=file_id,
            subtitle_index=index,
            text=text_to_convert,
            voice_name=voice_name,
            use_local_tts=use_local_tts,
            target_language=target_language,
            speed=speed
        )

        if result.get("success"):
            audio_filename = f"{index:04d}.mp3"
            audio_path = AUDIO_DIR / file_id / target_language / audio_filename
            
            # 下面这段重复了，因为在生成语音的时候已经把语速参数设置进去了，也就是生成的语音是按照语速生成的
            # 如果需要调整语速
            # if speed != 1.0:
            #     audio = AudioSegment.from_file(str(audio_path))
            #     # 使用 pydub 的 speedup 功能调整语速
            #     # 注意：speedup 需要安装 ffmpeg
            #     adjusted_audio = audio._spawn(audio.raw_data, overrides={
            #         "frame_rate": int(audio.frame_rate * speed)
            #     })
            #     adjusted_audio.export(str(audio_path), format="mp3")
            #     audio_duration = adjusted_audio.duration_seconds
            # else:
                # audio = AudioSegment.from_file(str(audio_path))
                # audio_duration = audio.duration_seconds
            audio = AudioSegment.from_file(str(audio_path))
            audio_duration = audio.duration_seconds
            print('Audio duration is %s seconds' % audio_duration)
            # 计算时长差异（相对于字幕时长）
            duration_diff = audio_duration - subtitle_duration
            diff_percent = (duration_diff / subtitle_duration) * 100
            
            # 检查是否会影响下一个字幕
            will_affect_next = audio_duration > available_duration
            
            return {
                "status": "success",
                "audio_file": str(Path(file_id) / target_language / audio_filename),
                "index": index,
                "duration_check": {
                    "audio_duration": audio_duration,
                    "subtitle_duration": subtitle_duration,
                    "gap_duration": gap_duration,
                    "available_duration": available_duration,
                    "difference": duration_diff,
                    "difference_percent": diff_percent,
                    "exceeds_subtitle": audio_duration > subtitle_duration,
                    "will_affect_next": will_affect_next
                }
            }
        else:
            raise HTTPException(500, "生成语音失败")

    except Exception as e:
        raise HTTPException(500, f"生成语音失败: {str(e)}")
