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

async def recognize_speech(file_id: str, audio_path: Path, language: str = "zh-CN"):
    try:
        # 首先验证音频文件是否存在和可访问
        if not audio_path.exists():
            raise HTTPException(500, f"音频文件不存在: {audio_path}")
            
        print(f"开始识别音频: {audio_path}, 语言: {language}")
        
        # 检查文件权限
        try:
            with open(audio_path, 'rb') as f:
                pass
        except Exception as e:
            raise HTTPException(500, f"无法访问音频文件: {str(e)}")

        # 配置语音识别
        speech_config = speechsdk.SpeechConfig(
            subscription=AZURE_SPEECH_KEY, 
            region=AZURE_SPEECH_REGION
        )
        
        # 设置识别语言
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
        speech_config.set_property_by_name(
            "Speech_SegmentationSilenceTimeoutMs", "500"
        )
        speech_config.set_property_by_name(
            "SpeechServiceResponse_PostProcessingOption", "TrueText"
        )
        speech_config.set_property_by_name(
            "Speech_ConfidenceThreshold", "0.7"
        )
        speech_config.set_property_by_name(
            "SpeechServiceConnection_NoiseSuppression", "true"
        )
        speech_config.set_property_by_name(
            "SpeechServiceConnection_AutomaticGainControl", "true"
        )
        
        # 启用详细日志
        speech_config.set_property(
            speechsdk.PropertyId.Speech_LogFilename, 
            str(TEMP_DIR / f"azure_speech_{file_id}.log")
        )
        speech_config.enable_audio_logging = True

        print(f"创建音频配置: {audio_path}")
        # 配置音频输入
        audio_config = speechsdk.AudioConfig(filename=str(audio_path))
        
        print("创建语音识别器")
        speech_recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config, 
            audio_config=audio_config
        )

        # 存储识别结果
        results = []
        recognition_complete = asyncio.Event()
        
        def handle_result(evt):
            try:
                if evt.result.text:
                    # 修改置信度检查的方式
                    try:
                        # 尝试解析 JSON 结果
                        json_result = json.loads(evt.result.properties.get(
                            speechsdk.PropertyId.SpeechServiceResponse_JsonResult,
                            "{}"
                        ))
                        confidence = float(json_result.get("Confidence", 0))
                    except (json.JSONDecodeError, ValueError, TypeError):
                        confidence = 0
                        
                    # 过滤掉可能的系统提示或统计信息
                    text = evt.result.text
                    if any(keyword in text.lower() for keyword in [
                        "total number", "source displays", "recognized", "transcript",
                        "system message", "processing", "analyzing"
                    ]):
                        print(f"跳过系统消息: {text}")
                        return

                    # 过滤掉过短的文本
                    if len(text.strip()) < 3:
                        print(f"跳过过短文本: {text}")
                        return

                    print(f"识别到文本 (置信度: {confidence}): {text}")
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
            except Exception as e:
                print(f"处理识别结果时出错: {str(e)}")
                print(f"错误类型: {type(e)}")
                print(f"错误详情: {e.__dict__ if hasattr(e, '__dict__') else '无详细信息'}")

        def handle_completed(evt):
            print("语音识别完成")
            recognition_complete.set()

        def handle_canceled(evt):
            print(f"语音识别被取消: {evt.result.cancellation_details.reason}")
            print(f"错误详情: {evt.result.cancellation_details.error_details}")
            recognition_complete.set()

        # 注册事件处理函数
        speech_recognizer.recognized.connect(handle_result)
        speech_recognizer.session_stopped.connect(handle_completed)
        speech_recognizer.canceled.connect(handle_canceled)

        print("开始语音识别")
        speech_recognizer.start_continuous_recognition()
        
        try:
            # 等待识别完成
            await recognition_complete.wait()
        finally:
            print("停止语音识别")
            speech_recognizer.stop_continuous_recognition()
        
        if not results:
            raise HTTPException(500, "未能识别出任何文本")
            
        return results

    except Exception as e:
        print(f"语音识别失败: {str(e)}")
        raise HTTPException(500, f"语音识别失败: {str(e)}")

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
                    # 将WAV转换为MP3
                    subprocess.run([
                        'ffmpeg', '-y',
                        '-i', str(temp_wav_file),
                        '-codec:a', 'libmp3lame',
                        '-qscale:a', '4',  # MP3质量设置
                        str(audio_file)
                    ], check=True)
                    
                    # 删除临时WAV文件
                    temp_wav_file.unlink(missing_ok=True)
                    
                    # 添加到音频文件列表
                    audio_files.append({
                        "index": i,
                        "file": str(audio_file.relative_to(AUDIO_DIR)),
                        "text": text,
                        "start": subtitle.get("start", 0),
                        "duration": subtitle.get("duration", 0)
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