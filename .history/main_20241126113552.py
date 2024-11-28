import os
import json
import time
import subprocess
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, HTTPException, WebSocket, Body, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from moviepy.editor import VideoFileClip
import azure.cognitiveservices.speech as speechsdk
from azure.ai.translation.text import TextTranslationClient, TranslatorCredential
import uuid
import aiofiles
import asyncio
from typing import Dict
from pydub import AudioSegment
import math
import re

load_dotenv()

app = FastAPI()

# 创建必要的目录
UPLOAD_DIR = Path("uploads")
AUDIO_DIR = Path("audio")
SUBTITLE_DIR = Path("subtitles")
STATIC_DIR = Path("static")
MERGED_DIR = Path("merged")
SUBTITLED_VIDEO_DIR = Path("subtitled_videos")
TEMP_DIR = Path("temp")

for dir_path in [UPLOAD_DIR, AUDIO_DIR, SUBTITLE_DIR, STATIC_DIR, MERGED_DIR, SUBTITLED_VIDEO_DIR, TEMP_DIR]:
    dir_path.mkdir(exist_ok=True)

# 挂载静态文件目录
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/subtitled", StaticFiles(directory="subtitled_videos"), name="subtitled")
app.mount("/merged", StaticFiles(directory="merged"), name="merged")
app.mount("/audio", StaticFiles(directory="audio"), name="audio")

# 视频文件服务路由
@app.get("/video/{file_id}")
async def serve_video(file_id: str):
    file_path = UPLOAD_DIR / file_id
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="视频文件不存在")
    
    return FileResponse(
        path=file_path,
        media_type="video/mp4",
        headers={
            "Accept-Ranges": "bytes",
            "Content-Disposition": f"inline; filename={file_id}"
        }
    )

# Azure服务配置
speech_key = os.getenv("AZURE_SPEECH_KEY")
service_region = os.getenv("AZURE_SPEECH_REGION")
translator_key = os.getenv("AZURE_TRANSLATOR_KEY")
translator_region = os.getenv("AZURE_TRANSLATOR_REGION")

# 存储WebSocket连接
active_connections: Dict[str, WebSocket] = {}

# 定义语言代码映射
LANGUAGE_CODE_MAP = {
    "en": "en-US",
    "zh": "zh-CN",
    "zh-TW": "zh-CN",  # 暂时使用简体中文声音
    "ja": "ja-JP"
}

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

@app.get("/")
async def read_root():
    return FileResponse("static/index.html")

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    try:
        # 生成唯一文件ID，保留原始扩展名
        file_extension = os.path.splitext(file.filename)[1]
        file_id = str(uuid.uuid4()) + file_extension
        
        # 确保上传目录存在
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        
        # 保存上传的文件
        file_path = UPLOAD_DIR / file_id
        async with aiofiles.open(file_path, "wb") as f:
            content = await file.read()
            await f.write(content)
        
        print(f"文件已保存: {file_path}")
        return {"file_id": file_id}
        
    except Exception as e:
        print(f"上传文件时发生错误: {str(e)}")
        raise HTTPException(500, f"上传失败: {str(e)}")

@app.post("/extract-audio/{file_id}")
async def extract_audio(file_id: str):
    try:
        # 构建文件路径
        video_path = UPLOAD_DIR / file_id
        if not video_path.exists():
            raise HTTPException(404, "视频文件未找到")
            
        # 生成音频文件名（使用相同的UUID，但改为.mp3扩展名）
        audio_file_id = os.path.splitext(file_id)[0] + '.mp3'
        temp_audio_path = TEMP_DIR / f"temp_{audio_file_id}"
        final_audio_path = AUDIO_DIR / audio_file_id
        
        # 确保目录存在
        os.makedirs(AUDIO_DIR, exist_ok=True)
        os.makedirs(TEMP_DIR, exist_ok=True)
        
        try:
            # 提取音频并直接转换为MP3格式
            subprocess.run([
                'ffmpeg', '-y',
                '-i', str(video_path),
                '-vn',  # 不要视频流
                '-acodec', 'libmp3lame',  # 使用MP3编码器
                '-ac', '1',  # 单声道
                '-ar', '16000',  # 采样率16kHz
                '-q:a', '4',  # MP3质量设置（0-9，2-4为最佳质量范围）
                str(final_audio_path)
            ], check=True)
            
            print(f"音频提取完成: {final_audio_path}")
            return {"message": "音频提取成功", "audio_file": audio_file_id}
            
        except Exception as e:
            # 清理临时文件
            final_audio_path.unlink(missing_ok=True)
            raise e
            
    except Exception as e:
        raise HTTPException(500, f"音频提取失败: {str(e)}")

@app.websocket("/ws/{file_id}")
async def websocket_endpoint(websocket: WebSocket, file_id: str):
    try:
        await websocket.accept()
        active_connections[file_id] = websocket
        print(f"WebSocket连接已建立: {file_id}")
        
        try:
            while True:
                data = await websocket.receive_text()
                if data == "ping":
                    await websocket.send_text("pong")
                else:
                    print(f"收到WebSocket消息: {data}")
        except WebSocketDisconnect:
            print(f"WebSocket连接断开: {file_id}")
        except Exception as e:
            print(f"WebSocket错误: {str(e)}")
    except Exception as e:
        print(f"WebSocket连接建立失败: {str(e)}")
    finally:
        if file_id in active_connections:
            del active_connections[file_id]

async def send_ws_message(file_id: str, message: dict):
    if file_id in active_connections:
        ws = active_connections[file_id]
        try:
            await ws.send_json(message)
            # 如果是完成消息，发送后等待一小段时间再关闭连接
            if message.get("type") in ["complete", "error"]:
                await asyncio.sleep(1)  # 等待1秒确保消息发送完成
                if file_id in active_connections:
                    await ws.close()
                    del active_connections[file_id]
        except WebSocketDisconnect:
            print(f"发送消息时WebSocket已断开: {file_id}")
            if file_id in active_connections:
                del active_connections[file_id]
        except Exception as e:
            print(f"发送WebSocket消息时出错: {str(e)}")
            if file_id in active_connections:
                del active_connections[file_id]

@app.post("/generate-subtitles/{file_id}")
async def generate_subtitles(file_id: str, language: str = "zh-CN"):
    try:
        print(f"开始生成字幕，文件ID: {file_id}")
        
        # 构建音频文件路径（使用.mp3扩展名）
        audio_file_id = os.path.splitext(file_id)[0] + '.mp3'
        audio_path = AUDIO_DIR / audio_file_id
        video_path = UPLOAD_DIR / file_id
        
        if not audio_path.exists():
            print(f"音频文件不存在: {audio_path}")
            raise HTTPException(404, "音频文件未找到，请先提取音频")

        print(f"开始处理音频文件: {audio_path}")
        print(f"源语言: {language}")

        # 获取视频时长
        video = VideoFileClip(str(video_path))
        video_duration = video.duration
        video.close()

        # 将音频分段处理
        segment_duration = 300  # 5分钟一段
        total_segments = math.ceil(video_duration / segment_duration)
        print(f"音频总时长: {video_duration}秒，分为 {total_segments} 段处理")

        # 存储所有字幕和错误
        all_subtitles = []
        recognition_errors = []
        
        async def process_segment(segment_index: int):
            start_time = segment_index * segment_duration
            end_time = min((segment_index + 1) * segment_duration, video_duration)
            
            # 创建临时音频段文件（使用WAV格式作为临时文件）
            segment_path = TEMP_DIR / f"{audio_file_id}_segment_{segment_index}.wav"
            
            try:
                # 使用ffmpeg从MP3提取音频段并转换为WAV格式（语音识别需要WAV格式）
                subprocess.run([
                    'ffmpeg', '-y',
                    '-i', str(audio_path),
                    '-ss', str(start_time),
                    '-t', str(end_time - start_time),
                    '-acodec', 'pcm_s16le',
                    '-ar', '16000',
                    '-ac', '1',
                    str(segment_path)
                ], check=True)
                
                # 配置语音识别
                speech_config = speechsdk.SpeechConfig(
                    subscription=speech_key, 
                    region=service_region
                )
                
                # 设置识别语言，确保使用正确的语言代码
                if language.lower() == "en":
                    speech_config.speech_recognition_language = "en-US"
                else:
                    speech_config.speech_recognition_language = language

                # 设置详细日志
                speech_config.set_property(
                    speechsdk.PropertyId.Speech_LogFilename, 
                    str(TEMP_DIR / f"azure_speech_{file_id}_segment_{segment_index}.log")
                )
                
                # 优化语音识别参数，启用按句子分割
                speech_config.set_property_by_name(
                    "SpeechServiceConnection_InitialSilenceTimeoutMs", 
                    "2000"  # 增加初始静音超时，以便更好地检测句子开始
                )
                speech_config.set_property_by_name(
                    "SpeechServiceConnection_EndSilenceTimeoutMs", 
                    "1000"  # 增加结束静音超时，以便更好地检测句子结束
                )
                
                # 启用语音分段模式，使用句子级别的分段
                speech_config.set_property_by_name(
                    "SpeechServiceConnection_SegmentationMode", 
                    "SentenceBoundary"  # 使用句子边界进行分段
                )
                
                # 启用详细日志
                speech_config.enable_audio_logging = True

                # 存储当前段的识别结果
                segment_results = []
                done = False
                current_segment_duration = end_time - start_time

                def calculate_progress(current_time):
                    """计算总体进度"""
                    previous_segments_progress = (segment_index * segment_duration) / video_duration
                    current_segment_progress = (current_time - start_time) / video_duration
                    total_progress = (previous_segments_progress + current_segment_progress) * 100
                    return min(100, int(total_progress))

                # 创建Future对象用于异步处理
                recognition_complete = asyncio.Event()
                
                def handle_result(evt):
                    try:
                        if evt.result.text:
                            print(f"识别到文本: {evt.result.text}")
                            # 从纳秒转换为秒
                            duration = evt.result.duration / 10000000 if isinstance(evt.result.duration, int) else evt.result.duration
                            
                            # 计算实际的开始时间（相对于整个视频）
                            start_time_in_video = start_time + (evt.result.offset / 10000000 if isinstance(evt.result.offset, int) else evt.result.offset)
                            
                            # 根据标点符号分割句子（如果需要的话）
                            sentences = re.split('[。！？.!?]', evt.result.text)
                            sentences = [s.strip() for s in sentences if s.strip()]
                            
                            if len(sentences) > 1:
                                # 如果有多个句子，按句子分配时长
                                total_chars = sum(len(s) for s in sentences)
                                for sentence in sentences:
                                    if not sentence:
                                        continue
                                        
                                    # 根据句子长度按比例分配时长
                                    sentence_ratio = len(sentence) / total_chars
                                    sentence_duration = duration * sentence_ratio
                                    
                                    # 确保每个句子的时长在合理范围内（2-10秒）
                                    optimal_duration = max(2.0, min(sentence_duration, 10.0))
                                    
                                    subtitle = {
                                        "start": start_time_in_video,
                                        "duration": optimal_duration,
                                        "text": sentence
                                    }
                                    segment_results.append(subtitle)
                                    print(f"添加字幕: {sentence} (时长: {optimal_duration:.2f}秒)")
                                    
                                    # 更新下一句的开始时间
                                    start_time_in_video += optimal_duration
                            else:
                                # 单个句子，确保时长在合理范围内
                                optimal_duration = max(2.0, min(duration, 10.0))
                                
                                subtitle = {
                                    "start": start_time_in_video,
                                    "duration": optimal_duration,
                                    "text": evt.result.text
                                }
                                segment_results.append(subtitle)
                                print(f"添加字幕: {evt.result.text} (时长: {optimal_duration:.2f}秒)")
                            
                            # 发送进度更新
                            progress = calculate_progress(start_time_in_video)
                            loop = asyncio.get_running_loop()
                            loop.create_task(send_ws_message(file_id, {
                                "type": "progress",
                                "text": evt.result.text,
                                "progress": progress
                            }))
                    except Exception as e:
                        print(f"处理识别结果时出错: {str(e)}")
                        recognition_errors.append(str(e))

                def handle_completed(evt):
                    try:
                        print(f"语音识别完成: {evt}")
                        recognition_complete.set()
                    except Exception as e:
                        print(f"处理完成事件时出错: {str(e)}")
                        recognition_errors.append(str(e))

                # 配置音频输入
                audio_config = speechsdk.AudioConfig(filename=str(segment_path))
                speech_recognizer = speechsdk.SpeechRecognizer(
                    speech_config=speech_config, 
                    audio_config=audio_config
                )

                # 注册事件处理函数
                speech_recognizer.recognized.connect(handle_result)
                speech_recognizer.session_stopped.connect(handle_completed)
                speech_recognizer.canceled.connect(handle_completed)

                # 开始识别
                speech_recognizer.start_continuous_recognition()
                
                try:
                    # 等待识别完成，但设置超时时间
                    timeout = (end_time - start_time) * 2  # 使用音频长度的2倍作为超时时间
                    await asyncio.wait_for(recognition_complete.wait(), timeout=timeout)
                except asyncio.TimeoutError:
                    print(f"语音识别超时，段落 {segment_index}")
                    recognition_errors.append(f"段落 {segment_index} 识别超时")
                finally:
                    # 停止识别
                    speech_recognizer.stop_continuous_recognition()
                
                return segment_results

            except Exception as e:
                error_msg = f"处理音频段 {segment_index} 时出错: {str(e)}"
                print(error_msg)
                recognition_errors.append(error_msg)
                return []
            finally:
                # 清理临时文件
                try:
                    if segment_path.exists():
                        segment_path.unlink()
                except Exception as e:
                    print(f"清理临时文件时出错: {str(e)}")

        # 并行处理所有音频段
        tasks = [process_segment(i) for i in range(total_segments)]
        segment_results = await asyncio.gather(*tasks)

        # 合并所有段落的结果
        for results in segment_results:
            all_subtitles.extend(results)

        # 按开始时间排序
        all_subtitles.sort(key=lambda x: x["start"])

        # 如果有错误但仍然有一些字幕，返回部分结果
        if recognition_errors and all_subtitles:
            print("生成字幕时发生一些错误，但仍然返回部分结果")
            print("错误信息:", "\n".join(recognition_errors))

        # 如果完全没有字幕，抛出错误
        if not all_subtitles:
            error_msg = "未能生成任何字幕\n" + "\n".join(recognition_errors)
            raise HTTPException(500, error_msg)

        # 保存字幕文件
        file_id_without_ext = os.path.splitext(file_id)[0]
        subtitles_file = SUBTITLE_DIR / f"{file_id_without_ext}.json"
        with open(subtitles_file, "w", encoding="utf-8") as f:
            json.dump(all_subtitles, f, ensure_ascii=False, indent=2)
        
        # 发送完成消息
        await send_ws_message(file_id, {"type": "complete", "message": "字幕生成完成"})
        
        return all_subtitles
    except Exception as e:
        error_msg = f"生成字幕时出错: {str(e)}"
        print(error_msg)
        # 发送错误消息
        await send_ws_message(file_id, {"type": "error", "message": error_msg})
        raise HTTPException(status_code=500, detail=error_msg)

@app.post("/translate-subtitles/{file_id}")
async def translate_subtitles(file_id: str, source_language: str, target_language: str):
    try:
        print(f"开始翻译字幕，文件ID: {file_id}, 源语言: {source_language}, 目标语言: {target_language}")
        
        # 检查必要的配置
        if not translator_key or not translator_region:
            raise HTTPException(500, "翻译服务配置缺失，请检查环境变量")
        
        # 构建源字幕文件路径
        file_id_without_ext = os.path.splitext(file_id)[0]
        source_subtitle_file = SUBTITLE_DIR / f"{file_id_without_ext}.json"
        print(f"源字幕文件路径: {source_subtitle_file}")
        
        if not source_subtitle_file.exists():
            raise HTTPException(404, f"源字幕文件未找到: {source_subtitle_file}")

        print(f"开始读取源字幕文件...")
        try:
            with open(source_subtitle_file, 'r', encoding='utf-8') as f:
                subtitles = json.load(f)
            print(f"成功读取源字幕，共 {len(subtitles)} 条")
        except json.JSONDecodeError as e:
            raise HTTPException(500, f"源字幕文件格式错误: {str(e)}")
        except Exception as e:
            raise HTTPException(500, f"读取源字幕文件失败: {str(e)}")

        # 检查字幕数据
        if not subtitles or not isinstance(subtitles, list):
            raise HTTPException(400, "无效的字幕数据格式")

        # 初始化翻译客户端
        try:
            credential = TranslatorCredential(
                translator_key,
                translator_region
            )
            text_translator = TextTranslationClient(
                endpoint="https://api.cognitive.microsofttranslator.com",
                credential=credential
            )
            print("翻译客户端初始化成功")
        except Exception as e:
            raise HTTPException(500, f"初始化翻译客户端失败: {str(e)}")

        # 准备翻译文本
        texts = []
        for subtitle in subtitles:
            if not isinstance(subtitle, dict) or "text" not in subtitle:
                raise HTTPException(400, "字幕数据格式错误，缺少必要字段")
            texts.append(subtitle["text"])
        
        print(f"准备翻译 {len(texts)} 条字幕")

        # 批量翻译（每次最多100条）
        batch_size = 100
        translated_texts = []
        
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            try:
                # 将文本列表转换为正确的格式
                input_texts = [{"text": text} for text in batch]
                print(f"开始翻译第 {i//batch_size + 1} 批，共 {len(batch)} 条")
                print(f"源语言: {source_language}, 目标语言: {target_language}")
                
                response = text_translator.translate(
                    content=input_texts,
                    to=[target_language],
                    from_parameter=source_language
                )
                
                batch_translations = []
                for translation in response:
                    if translation.translations:
                        batch_translations.append(translation.translations[0].text)
                    else:
                        print(f"警告：第 {len(translated_texts)} 条字幕翻译结果为空")
                        batch_translations.append("")
                
                translated_texts.extend(batch_translations)
                print(f"已翻译 {len(translated_texts)}/{len(texts)} 条字幕")
                
            except Exception as e:
                error_msg = f"翻译批次 {i//batch_size + 1} 时出错: {str(e)}"
                print(error_msg)
                print(f"错误类型: {type(e)}")
                print(f"错误详情: {e.__dict__ if hasattr(e, '__dict__') else '无详细信息'}")
                raise HTTPException(500, error_msg)

        # 更新字幕
        if len(translated_texts) != len(subtitles):
            raise HTTPException(500, f"翻译结果数量不匹配：预期 {len(subtitles)}，实际 {len(translated_texts)}")

        # 创建翻译后的字幕列表，保持原始字幕的所有属性
        translated_subtitles = []
        for i, subtitle in enumerate(subtitles):
            translated_subtitle = subtitle.copy()  # 复制原始字幕的所有属性
            translated_subtitle["text"] = translated_texts[i]  # 只更新文本内容
            translated_subtitles.append(translated_subtitle)

        # 保存翻译后的字幕
        target_subtitle_file = SUBTITLE_DIR / f"{file_id_without_ext}_{target_language}.json"
        try:
            with open(target_subtitle_file, 'w', encoding='utf-8') as f:
                json.dump(translated_subtitles, f, ensure_ascii=False, indent=2)
            print(f"字幕翻译完成，已保存到 {target_subtitle_file}")
        except Exception as e:
            raise HTTPException(500, f"保存翻译后的字幕失败: {str(e)}")

        # 确保返回的数据是一个包含字幕列表的字典
        response_data = {
            "subtitles": translated_subtitles,
            "source_language": source_language,
            "target_language": target_language,
            "total_count": len(translated_subtitles)
        }
        print("返回数据示例：", json.dumps(response_data, ensure_ascii=False)[:200])
        return response_data

    except Exception as e:
        error_msg = f"翻译字幕时发生错误: {str(e)}"
        print(error_msg)
        print(f"错误类型: {type(e)}")
        print(f"错误详情: {e.__dict__ if hasattr(e, '__dict__') else '无详细信息'}")
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(500, error_msg)

@app.get("/available-voices/{language}")
async def get_available_voices(language: str):
    try:
        # 将简单语言代码映射到完整的语言代码
        full_language_code = LANGUAGE_CODE_MAP.get(language, language)
        print(f"获取语音列表，语言: {language} -> {full_language_code}")
        
        if full_language_code in SUPPORTED_VOICES:
            voices = SUPPORTED_VOICES[full_language_code]
            print(f"找到 {len(voices)} 个可用语音")
            return {
                "voices": voices,
                "language": full_language_code,
                "total": len(voices)
            }
        else:
            print(f"未找到语言 {full_language_code} 的语音")
            return {
                "voices": [],
                "language": full_language_code,
                "total": 0,
                "error": f"不支持的语言: {full_language_code}"
            }
    except Exception as e:
        print(f"获取语音列表失败: {str(e)}")
        raise HTTPException(500, f"获取语音列表失败: {str(e)}")

@app.post("/generate-speech/{file_id}/{subtitle_index}")
async def generate_speech(file_id: str, subtitle_index: int, text: str, voice_name: str = "zh-CN-XiaoxiaoNeural"):
    try:
        # 验证语音名称
        language = voice_name.split("-")[0]  # 从语音名称中提取语言代码
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
            subscription=speech_key, 
            region=service_region
        )
        speech_config.speech_synthesis_voice_name = voice_name
        
        # 准备音频文件路径
        audio_dir = AUDIO_DIR / file_id / language
        audio_dir.mkdir(parents=True, exist_ok=True)
        
        # 生成临时WAV文件和最终MP3文件的路径
        temp_wav_file = audio_dir / f"{subtitle_index:04d}_temp.wav"
        audio_file = audio_dir / f"{subtitle_index:04d}.mp3"
        
        # 配置音频输出
        audio_config = speechsdk.AudioOutputConfig(
            filename=str(temp_wav_file)
        )
        
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
                '-qscale:a', '4',  # MP3质量设置
                str(audio_file)
            ], check=True)
            
            # 删除临时WAV文件
            temp_wav_file.unlink(missing_ok=True)
            
            return {"success": True, "message": "语音生成成功"}
        else:
            error_details = result.properties.get(
                speechsdk.PropertyId.SpeechServiceResponse_JsonErrorDetails
            )
            raise HTTPException(500, f"生成语音失败: {error_details}")
            
    except Exception as e:
        raise HTTPException(500, f"生成语音失败: {str(e)}")

@app.post("/generate-speech/{file_id}")
async def generate_speech_for_file(file_id: str, target_language: str, voice_name: str):
    try:
        print(f"开始为整个文件生成语音，文件ID: {file_id}, 目标语言: {target_language}, 语音: {voice_name}")
        
        # 验证语音名称
        language = voice_name.split("-")[0] + "-" + voice_name.split("-")[1]  # 获取完整的语言代码，如 "zh-CN"
        
        # 检查语言代码是否在支持的语音列表中
        if language not in SUPPORTED_VOICES:
            # 尝试从目标语言获取语言代码
            language = target_language
            if language not in SUPPORTED_VOICES:
                # 尝试使用语言映射
                language = LANGUAGE_CODE_MAP.get(language, language)
                if language not in SUPPORTED_VOICES:
                    raise HTTPException(400, f"不支持的语言: {language}")
            
        voice_exists = False
        for voice in SUPPORTED_VOICES[language]:
            if voice["name"] == voice_name:
                voice_exists = True
                break
        if not voice_exists:
            raise HTTPException(400, f"指定的语音 {voice_name} 不存在")

        # 读取字幕文件
        file_id_without_ext = os.path.splitext(file_id)[0]
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
        audio_dir = AUDIO_DIR / file_id / language
        audio_dir.mkdir(parents=True, exist_ok=True)

        # 配置语音合成
        speech_config = speechsdk.SpeechConfig(
            subscription=speech_key, 
            region=service_region
        )
        speech_config.speech_synthesis_voice_name = voice_name

        audio_files = []
        total_count = len(subtitles)
        
        # 为每个字幕生成语音
        for i, subtitle in enumerate(subtitles):
            try:
                # 发送进度消息
                progress = (i + 1) / total_count * 100
                await send_ws_message(file_id, {
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
                synthesizer = speechsdk.SpeechSynthesizer(
                    speech_config=speech_config, 
                    audio_config=speechsdk.audio.AudioOutputConfig(filename=str(temp_wav_file))
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
        await send_ws_message(file_id, {
            "type": "complete",
            "message": "语音生成完成"
        })

        return {
            "status": "success",
            "audio_files": audio_files,
            "total_count": len(audio_files),
            "language": language
        }

    except Exception as e:
        error_msg = f"生成语音失败: {str(e)}"
        print(error_msg)
        # 发送错误消息
        await send_ws_message(file_id, {
            "type": "error",
            "message": error_msg
        })
        raise HTTPException(500, error_msg)

@app.post("/merge-audio/{file_id}")
async def merge_audio(file_id: str, target_language: str):
    try:
        print(f"开始合并音频，文件ID: {file_id}, 语言: {target_language}")
        
        # 将简单语言代码映射到完整的语言代码
        language = LANGUAGE_CODE_MAP.get(target_language, target_language)
        
        # 检查音频目录
        audio_dir = AUDIO_DIR / file_id / language
        if not audio_dir.exists():
            raise HTTPException(404, "音频文件目录未找到")
            
        # 获取所有音频文件
        audio_files = sorted(list(audio_dir.glob("*.mp3")), key=lambda x: int(x.stem))
        if not audio_files:
            raise HTTPException(404, "未找到任何音频文件")
            
        print(f"找到 {len(audio_files)} 个音频文件")
        
        try:
            # 创建输出目录
            output_dir = MERGED_DIR / file_id
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # 准备输出文件路径
            output_path = output_dir / f"{target_language}.mp3"
            
            # 构建ffmpeg命令
            inputs = []
            filter_complex = []
            
            # 为每个音频文件添加输入
            for i, audio_file in enumerate(audio_files):
                inputs.extend(['-i', str(audio_file)])
                filter_complex.append(f'[{i}:a]')
            
            # 构建完整的filter_complex字符串
            filter_complex = ''.join(filter_complex) + f'concat=n={len(audio_files)}:v=0:a=1[outa]'
            
            # 构建完整的ffmpeg命令
            command = [
                'ffmpeg', '-y',
                *inputs,
                '-filter_complex', filter_complex,
                '-map', '[outa]',
                '-codec:a', 'libmp3lame',  # 使用MP3编码器
                '-q:a', '4',  # MP3质量设置（0-9，2-4为最佳质量范围）
                str(output_path)
            ]
            
            print("执行ffmpeg命令:", ' '.join(command))
            
            # 执行命令
            process = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            if process.returncode != 0:
                print(f"合并音频失败: {process.stderr}")
                raise HTTPException(500, f"合并音频失败: {process.stderr}")
                
            print("音频合并成功")
            return {"merged_file": f"{file_id}/{target_language}.mp3"}
            
        except Exception as e:
            print(f"合并音频失败: {str(e)}")
            raise HTTPException(500, f"合并音频失败: {str(e)}")
            
    except Exception as e:
        print(f"合并音频失败: {str(e)}")
        raise HTTPException(500, str(e))

@app.get("/available-voices/{language}")
async def get_available_voices(language: str):
    try:
        # 将简单语言代码映射到完整的语言代码
        full_language_code = LANGUAGE_CODE_MAP.get(language, language)
        print(f"获取语音列表，语言: {language} -> {full_language_code}")
        
        if full_language_code in SUPPORTED_VOICES:
            voices = SUPPORTED_VOICES[full_language_code]
            print(f"找到 {len(voices)} 个可用语音")
            return {
                "voices": voices,
                "language": full_language_code,
                "total": len(voices)
            }
        else:
            print(f"未找到语言 {full_language_code} 的语音")
            return {
                "voices": [],
                "language": full_language_code,
                "total": 0,
                "error": f"不支持的语言: {full_language_code}"
            }
    except Exception as e:
        print(f"获取语音列表失败: {str(e)}")
        raise HTTPException(500, f"获取语音列表失败: {str(e)}")

@app.post("/burn-subtitles/{file_id}")
async def burn_subtitles(file_id: str, language: str, style: dict = Body(...)):
    try:
        # 获取字幕文件
        file_id_without_ext = os.path.splitext(file_id)[0]
        subtitle_file = os.path.join(SUBTITLE_DIR, f"{file_id_without_ext}_{language}.json")
        if not os.path.exists(subtitle_file):
            raise HTTPException(status_code=404, detail="字幕文件不存在")

        with open(subtitle_file, 'r', encoding='utf-8') as f:
            subtitles = json.load(f)

        # 将字幕转换为SRT格式
        srt_content = convert_to_srt(subtitles)
        srt_file = os.path.join(TEMP_DIR, f"{file_id}_{language}.srt")
        with open(srt_file, 'w', encoding='utf-8') as f:
            f.write(srt_content)

        # 获取原始视频文件
        video_file = os.path.join(UPLOAD_DIR, file_id)
        if not os.path.exists(video_file):
            raise HTTPException(status_code=404, detail="视频文件不存在")

        # 准备FFmpeg命令的字幕样式参数
        font_size = style.get('fontSize', 24)
        font_color = style.get('fontColor', '#ffffff')
        bg_color = style.get('backgroundColor', '#000000')
        bg_opacity = style.get('backgroundOpacity', 0.5)
        stroke_color = style.get('strokeColor', '#000000')
        stroke_width = style.get('strokeWidth', 2)

        # 转换颜色格式（去掉#号）
        font_color = font_color.lstrip('#')
        bg_color = bg_color.lstrip('#')
        stroke_color = stroke_color.lstrip('#')

        # 构建字幕样式
        subtitle_style = (
            f"FontSize={font_size},"
            f"FontName=Arial,"
            f"PrimaryColour=&H{font_color},"
            f"BackColour=&H{hex(int(bg_opacity * 255))[2:].zfill(2)}{bg_color},"
            f"OutlineColour=&H{stroke_color},"
            f"Outline={stroke_width},"
            f"BorderStyle=1"
        )

        # 生成带字幕的视频文件名
        output_file = os.path.join(SUBTITLED_VIDEO_DIR, f"{file_id}_{language}_subtitled.mp4")

        # 使用FFmpeg添加字幕
        cmd = [
            'ffmpeg', '-y',
            '-i', video_file,
            '-vf', f"subtitles={srt_file}:force_style='{subtitle_style}'",
            '-c:a', 'copy',
            output_file
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            print(f"FFmpeg error: {stderr.decode()}")
            raise HTTPException(status_code=500, detail="生成字幕视频失败")

        # 清理临时文件
        os.remove(srt_file)

        return {
            "subtitled_video": f"{file_id}_{language}_subtitled.mp4"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/update-subtitles/{file_id}")
async def update_subtitles(file_id: str, data: dict):
    try:
        subtitles = data.get("subtitles", [])
        translations = data.get("translations", {})
        
        # 保存原始字幕
        file_id_without_ext = os.path.splitext(file_id)[0]
        subtitle_path = SUBTITLE_DIR / f"{file_id_without_ext}.json"
        with open(subtitle_path, 'w', encoding='utf-8') as f:
            json.dump(subtitles, f, ensure_ascii=False, indent=2)
            
        # 保存翻译字幕
        if translations:
            translation_path = SUBTITLE_DIR / f"{file_id}_translations.json"
            with open(translation_path, 'w', encoding='utf-8') as f:
                json.dump(translations, f, ensure_ascii=False, indent=2)
        
        return {"message": "字幕更新成功"}
    except Exception as e:
        print(f"字幕更新错误: {str(e)}")
        raise HTTPException(500, f"字幕更新错误: {str(e)}")

@app.post("/update-subtitle")
async def update_subtitle(request: Request):
    try:
        data = await request.json()
        file_id = data.get("file_id")
        index = data.get("index")
        new_text = data.get("text")

        print(f"更新字幕请求: file_id={file_id}, index={index}, new_text={new_text}")  

        if not all([file_id, isinstance(index, int), new_text]):
            print(f"参数验证失败: file_id={file_id}, index={index}, new_text={new_text}")  
            raise HTTPException(400, "缺少必要参数")

        # 从文件ID中移除扩展名（如果有的话）
        file_id = file_id.rsplit('.', 1)[0] if '.' in file_id else file_id

        # 读取字幕文件
        subtitle_file = SUBTITLE_DIR / f"{file_id}.json"
        if not subtitle_file.exists():
            print(f"字幕文件不存在: {subtitle_file}")  
            raise HTTPException(404, "字幕文件不存在")

        async with aiofiles.open(subtitle_file, "r", encoding="utf-8") as f:
            content = await f.read()
            subtitles = json.loads(content)

        if not isinstance(subtitles, list) or index >= len(subtitles):
            print(f"无效的字幕索引: index={index}, subtitles长度={len(subtitles)}")  
            raise HTTPException(400, "无效的字幕索引")

        # 更新字幕文本
        subtitles[index]["text"] = new_text

        # 保存更新后的字幕
        async with aiofiles.open(subtitle_file, "w", encoding="utf-8") as f:
            await f.write(json.dumps(subtitles, ensure_ascii=False, indent=2))

        print(f"字幕更新成功: file_id={file_id}, index={index}")  
        return {"status": "success"}

    except json.JSONDecodeError as e:
        print(f"JSON解析错误: {str(e)}")  
        raise HTTPException(400, "无效的请求数据")
    except Exception as e:
        print(f"更新字幕时发生错误: {str(e)}")  
        raise HTTPException(500, f"更新字幕失败: {str(e)}")

def convert_to_srt(subtitles):
    srt_content = ""
    for i, subtitle in enumerate(subtitles, 1):
        start_time = float(subtitle['start'])
        duration = float(subtitle.get('duration', 5))  # 默认持续5秒
        end_time = start_time + duration
        
        # 转换时间格式为 HH:MM:SS,mmm
        start_str = f"{int(start_time//3600):02d}:{int((start_time%3600)//60):02d}:{int(start_time%60):02d},{int((start_time*1000)%1000):03d}"
        end_str = f"{int(end_time//3600):02d}:{int((end_time%3600)//60):02d}:{int(end_time%60):02d},{int((end_time*1000)%1000):03d}"
        
        # 写入SRT格式字幕
        srt_content += f"{i}\n"
        srt_content += f"{start_str} --> {end_str}\n"
        srt_content += f"{subtitle.get('text', '')}\n\n"
    
    return srt_content
