import subprocess
from fastapi import HTTPException
from pathlib import Path
from .config import (
    AUDIO_DIR, 
    UPLOAD_DIR, 
    TEMP_DIR, 
    MERGED_DIR,
    SUBTITLE_DIR
)
import asyncio
import json

# 常量定义
BATCH_SIZE = 20  # 每批字幕数量
SILENT_SAMPLE_RATE = 16000  # 静音采样率
SILENT_CHANNELS = 1  # 单声道


async def extract_audio(file_id: str):
    try:
        video_path = UPLOAD_DIR / file_id
        if not video_path.exists():
            raise HTTPException(404, "视频文件未找到")
            
        audio_file_id = Path(file_id).stem + '.mp3'
        final_audio_path = AUDIO_DIR / audio_file_id
        
        try:
            subprocess.run([
                'ffmpeg', '-y',
                '-i', str(video_path),
                '-vn',
                '-acodec', 'libmp3lame',
                '-ac', '1',
                '-ar', '16000',
                '-q:a', '4',
                str(final_audio_path)
            ], check=True)
            
            return {"message": "音频提取成功", "audio_file": audio_file_id}
            
        except Exception as e:
            final_audio_path.unlink(missing_ok=True)
            raise e
            
    except Exception as e:
        raise HTTPException(500, f"音频提取失败: {str(e)}")

async def merge_audio(file_id: str, target_language: str):
    try:
        audio_dir = AUDIO_DIR / file_id / target_language
        if not audio_dir.exists():
            raise HTTPException(404, "音频文件目录未找到")
            
        # 读取字幕文件以获取时间信息
        file_id_without_ext = Path(file_id).stem
        subtitle_file = SUBTITLE_DIR / f"{file_id_without_ext}_{target_language}.json"
        if not subtitle_file.exists():
            subtitle_file = SUBTITLE_DIR / f"{file_id_without_ext}.json"
        
        if not subtitle_file.exists():
            raise HTTPException(404, "字幕文件未找到")
            
        with open(subtitle_file, 'r', encoding='utf-8') as f:
            subtitles = json.load(f)
            
        # 获取最后一个字幕的结束时间作为总时长
        last_subtitle = subtitles[-1]
        total_duration = last_subtitle['start'] + last_subtitle['duration']
            
        # 创建输出目录
        output_dir = MERGED_DIR / file_id
        output_dir.mkdir(parents=True, exist_ok=True)
        final_output = output_dir / f"{target_language}.mp3"

        # 分批处理，每批20个音频
        BATCH_SIZE = 20
        temp_files = []
        
        # 按时间顺序排序字幕
        subtitles.sort(key=lambda x: float(x['start']))
        
        # 分批处理
        for batch_index in range(0, len(subtitles), BATCH_SIZE):
            batch_subtitles = subtitles[batch_index:batch_index + BATCH_SIZE]
            
            # 计算这个批次的时间范围
            batch_start = float(batch_subtitles[0]['start'])
            if batch_index + BATCH_SIZE >= len(subtitles):
                # 最后一个批次，使用总时长作为结束时间
                batch_end = total_duration
            else:
                # 使用下一个批次的开始时间作为结束时间
                next_batch_start = float(subtitles[batch_index + BATCH_SIZE]['start'])
                batch_end = next_batch_start
            
            batch_duration = batch_end - batch_start
            
            print(f"\n===== 处理批次 {batch_index//BATCH_SIZE + 1}/{(len(subtitles)-1)//BATCH_SIZE + 1} =====")
            print(f"批次范围: {batch_start:.2f}s - {batch_end:.2f}s (duration: {batch_duration:.2f}s)")
            print(f"包含字幕索引: {batch_index} - {batch_index + len(batch_subtitles) - 1}")
            
            # 创建这个批次的基础静音文件
            temp_base = TEMP_DIR / f"{file_id}_base_{batch_index}.wav"
            temp_output = TEMP_DIR / f"{file_id}_batch_{batch_index}.mp3"
            
            try:
                # 创建基础静音
                subprocess.run([
                    'ffmpeg', '-y',
                    '-f', 'lavfi',
                    '-i', f'anullsrc=r=16000:cl=mono',
                    '-t', str(batch_duration),
                    '-acodec', 'pcm_s16le',
                    str(temp_base)
                ], check=True)

                # 准备这个批次的过滤器
                inputs = ['-i', str(temp_base)]
                filter_parts = []
                valid_audio_count = 0
                
                # 处理这个批次的字幕
                print(f"\n开始处理批次内的字幕，批次大小: {len(batch_subtitles)}")
                for i, subtitle in enumerate(batch_subtitles):
                    global_index = batch_index + i  # 计算全局索引
                    audio_file = audio_dir / f"{global_index:04d}.mp3"
                    print(f"检查音频文件: {audio_file}")
                    print(f"\n处理字幕 {global_index:04d}")
                    print(f"字幕内容: {subtitle.get('text', '')}")
                    print(f"字幕时间: {subtitle['start']:.3f} -> {subtitle['start'] + subtitle['duration']:.3f}")

                    
                    if audio_file.exists():
                        print(f"找到音频文件 {global_index:04d}.mp3")
                                # 检查文件大小
                        file_size = audio_file.stat().st_size
                        if file_size < 1024:
                            print(f"❌ 音频文件过小 ({file_size} bytes): {audio_file}")
                            continue
                        # 检查音频文件大小和时长
                        try:
                            audio_duration = float(subprocess.check_output([
                                'ffprobe', '-v', 'error',
                                '-show_entries', 'format=duration',
                                '-of', 'default=noprint_wrappers=1:nokey=1',
                                str(audio_file)
                            ]).decode().strip())

                            if audio_duration < 0.1:
                                print(f"❌ 音频时长过短 ({audio_duration:.3f}s): {audio_file}")
                                continue
                                
                            if abs(audio_duration - subtitle['duration']) > 0.5:
                                print(f"⚠️ 音频时长与字幕不匹配: 音频={audio_duration:.3f}s, 字幕={subtitle['duration']:.3f}s")
                            
                            
                            inputs.extend(['-i', str(audio_file)])
                            relative_start = float(subtitle['start']) - batch_start
                            duration = float(subtitle['duration'])
                            target_duration = float(subtitle['duration'])
                            
                            # print(f"✅ 添加音频:")
                            # print(f"  - 文件大小: {file_size/1024:.1f}KB")
                            # print(f"  - 音频时长: {audio_duration:.3f}s")
                            # print(f"  - 相对起始时间: {relative_start:.3f}s")
                            # print(f"  - 计划使用时长: {duration:.3f}s")
                            print(f"✅ 添加音频:")
                            print(f"  - 文件大小: {file_size/1024:.1f}KB")
                            print(f"  - 原始时长: {audio_duration:.3f}s")
                            print(f"  - 目标时长: {target_duration:.3f}s")
                            print(f"  - 相对起始时间: {relative_start:.3f}s")
                            

                            # 计算需要的语速倍率
                            tempo = 1.0
                            tempo_filters = []
                            if audio_duration > target_duration:
                                tempo = audio_duration / target_duration
                                print(f"  - 需要的语速倍率: {tempo:.2f}x")
                                # ffmpeg的atempo限制在0.5-2.0之间，如果超过需要串联多个atempo
                                # 分解语速调整为多个步骤
                                remaining_tempo = tempo
                                while remaining_tempo > 1.01:  # 添加一点容差
                                    if remaining_tempo > 2.0:
                                        tempo_filters.append('atempo=2.0')
                                        remaining_tempo /= 2.0
                                    else:
                                        tempo_filters.append(f'atempo={remaining_tempo:.3f}')
                                        remaining_tempo = 1.0
                                        
                                print(f"  - 语速调整步骤: {' -> '.join(tempo_filters)}")
                            
                            if not tempo_filters:
                                tempo_filters = ['atempo=1.0']
                            
                            # filter_parts.append(
                            #     f'[{valid_audio_count + 1}:a]' +
                            #     f'volume=2,' +  # 音量调整
                            #     f'{",".join(tempo_filters)},' +  # 串联的语速调整
                            #     f'asetpts=PTS-STARTPTS,' +  # 重置时间戳
                            #     f'adelay={int(relative_start*1000)}|{int(relative_start*1000)},' +  # 延迟到正确位置
                            #     f'apad=whole_dur={batch_duration}' +  # 补充静音到批次长度
                            #     f'[delayed{valid_audio_count}];'
                            # )
    
                            # 简化过滤器，只保留基本的音量、延迟和补齐
                            filter_parts.append(
                                f'[{valid_audio_count + 1}:a]' +
                                f'volume=2,' +  # 音量调整
                                f'asetpts=PTS-STARTPTS,' +  # 重置时间戳
                                f'adelay={int(relative_start*1000)}|{int(relative_start*1000)},' +  # 延迟到正确位置
                                f'apad=whole_dur={batch_duration}' +  # 补充静音到批次长度
                                f'[delayed{valid_audio_count}];'
                            )

                            # 改进过滤器命令
                            # filter_parts.append(
                            #     f'[{valid_audio_count + 1}:a]' +
                            #     f'volume=2,' +  # 调整音量
                            #     f'atrim=0:{duration},' +  # 裁剪到字幕时长
                            #     f'asetpts=PTS-STARTPTS,' +  # 重置时间戳
                            #     f'adelay={int(relative_start*1000)}|{int(relative_start*1000)},' +  # 延迟到正确位置
                            #     # f'apad=whole_len={int(batch_duration*16000)}:packet_size=1024' +  # 使用采样点数来填充
                            #     # f'apad=whole_len={int((batch_duration + 1)*16000)}' +  # 增加1秒缓冲
                            #     f'apad=whole_dur={batch_duration}' +  # 确保音频长度足够
                            #     f'[delayed{valid_audio_count}];'
                            # )

                            valid_audio_count += 1
                            print(f"  - 过滤器添加成功 ✓")
                        except Exception as e:
                            print(f"❌ 处理音频文件失败: {str(e)}")
                            print(f"  - 错误详情: {e.__class__.__name__}: {str(e)}")
                            continue
                    else:
                        print(f"警告：未找到音频文件 {global_index:04d}.mp3")

                # print(f"批次处理完成，有效音频数量: {valid_audio_count}")
                print(f"\n批次统计:")
                print(f"- 总字幕数: {len(batch_subtitles)}")
                print(f"- 有效音频数: {valid_audio_count}")
                print(f"- 丢失音频数: {len(batch_subtitles) - valid_audio_count}")

                if valid_audio_count > 0:
                    print(f"\n开始合并音频:")
                    print(f"- 有效音频数量: {valid_audio_count}")
                    print(f"- 批次时长: {batch_duration:.3f}s")
                    # 构建混音命令
                    filter_complex = ''.join(filter_parts)
                    # 添加基础静音轨道
                    filter_complex += f'[0:a]apad=whole_dur={batch_duration}[base];'
                    
                    # 构建混音命令
                    if valid_audio_count > 1:
                        # 先合并所有延迟的音频
                        merge_cmd = ''
                        for i in range(valid_audio_count):
                            merge_cmd += f'[delayed{i}]'
                        # merge_cmd += f'amerge=inputs={valid_audio_count},volume={1.0/valid_audio_count}[merged];'  # 添加音量补偿
                        merge_cmd += f'amerge=inputs={valid_audio_count}[merged];'
                        filter_complex += merge_cmd
                        # 然后与基础静音混合
                        # filter_complex += '[base][merged]amix=inputs=2:duration=first[aout]'
                        # 使用 amix 时设置 normalize=0 来保持原始音量
                        filter_complex += '[base][merged]amix=inputs=2:normalize=0:weights=0 1[aout]'
                    else:
                        # 只有一个音频时直接与基础静音混合
                        # filter_complex += '[base][delayed0]amix=inputs=2:duration=first[aout]'
                        # 使用 amix 时设置 normalize=0 来保持原始音量
                        filter_complex += '[base][delayed0]amix=inputs=2:normalize=0:weights=0 1[aout]'
                    
                    print("- 过滤器复杂度:", filter_complex.count(';'))
                    
                    # 生成这个批次的音频
                    cmd = [
                        'ffmpeg', '-y'
                    ] + inputs + [
                        '-filter_complex', filter_complex,
                        '-map', '[aout]',
                        '-t', str(batch_duration),  # 限制输出时长
                        '-codec:a', 'libmp3lame',
                        '-q:a', '2',
                        str(temp_output)
                    ]
                    
                    print(f"执行批次 {batch_index//BATCH_SIZE + 1} 合并命令:")
                    print(' '.join(cmd))
                    
                    process = subprocess.run(cmd, capture_output=True, text=True)
                    if process.returncode != 0:
                        print(f"FFmpeg错误输出: {process.stderr}")
                        raise Exception(f"批次处理失败: {process.stderr}")
                    
                    # 验证批次文件的时长
                    batch_duration_actual = float(subprocess.check_output([
                        'ffprobe', '-v', 'error',
                        '-show_entries', 'format=duration',
                        '-of', 'default=noprint_wrappers=1:nokey=1',
                        str(temp_output)
                    ]).decode().strip())
                    
                    print(f"批次 {batch_index//BATCH_SIZE + 1} 音频时长: {batch_duration_actual:.2f}秒，预期时长: {batch_duration:.2f}秒")
                    
                    temp_files.append((temp_output, batch_start))

            finally:
                # 清理临时文件
                if temp_base.exists():
                    temp_base.unlink()

        # 最终合并所有批次
        if temp_files:
            print(f"开始合并 {len(temp_files)} 个批次的音频文件")
            
            # 使用 concat demuxer 而不是 filter_complex
            concat_list = TEMP_DIR / f"{file_id}_concat_list.txt"
            with open(concat_list, 'w', encoding='utf-8') as f:
                # 按时间顺序排序临时文件
                temp_files.sort(key=lambda x: x[1])  # 按开始时间排序
                for temp_file, _ in temp_files:
                    f.write(f"file '{temp_file.absolute()}'\n")

            try:
                # 使用 concat demuxer 合并所有文件
                final_cmd = [
                    'ffmpeg', '-y',
                    '-f', 'concat',
                    '-safe', '0',
                    '-i', str(concat_list),
                    '-c:a', 'libmp3lame',
                    '-q:a', '2',
                    str(final_output)
                ]
                
                print(f"执行最终合并命令: {' '.join(final_cmd)}")
                process = subprocess.run(final_cmd, capture_output=True, text=True)
                
                if process.returncode != 0:
                    print(f"FFmpeg错误输出: {process.stderr}")
                    raise Exception(f"最终合并失败: {process.stderr}")

            finally:
                # 清理临时文件
                # print("暂时不清理临时文件！")
                concat_list.unlink(missing_ok=True)
                for temp_file, _ in temp_files:
                    temp_file.unlink(missing_ok=True)

            # 验证最终文件的时长
            final_duration = float(subprocess.check_output([
                'ffprobe', '-v', 'error',
                '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                str(final_output)
            ]).decode().strip())
            
            print(f"合并后的音频时长: {final_duration:.2f}秒，预期时长: {total_duration:.2f}秒")
            
            return {"merged_file": f"{file_id}/{target_language}.mp3"}
        else:
            raise HTTPException(500, "没有找到任何音频文件可以合并")
            
    except Exception as e:
        print(f"合并音频失败: {str(e)}")
        raise HTTPException(500, str(e))

async def extract_audio_segment(audio_path: Path, output_path: Path, start_time: float, end_time: float):
    """从音频文件中提取指定时间段的音频"""
    try:
        print(f"提取音频段: {start_time}s - {end_time}s -> {output_path}")
        
        if not audio_path.exists():
            raise HTTPException(500, f"源音频文件不存在: {audio_path}")

        # 直接使用一步转换，简化处理过程
        process = await asyncio.create_subprocess_exec(
            'ffmpeg', '-y',
            '-i', str(audio_path),
            '-ss', str(start_time),
            '-t', str(end_time - start_time),
            '-acodec', 'pcm_s16le',
            '-ar', '16000',
            '-ac', '1',
            '-f', 'wav',
            '-sample_fmt', 's16',  # 确保16位采样
            '-flags', '+bitexact',  # 使用精确模式
            str(output_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            print(f"音频转换失败: {stderr.decode()}")
            raise Exception(stderr.decode())

        # 验证输出文件
        if not output_path.exists() or output_path.stat().st_size == 0:
            raise Exception("输出文件无效")

        print(f"音频段提取成功: {output_path}")
        return True
            
    except Exception as e:
        print(f"提取音频段失败: {str(e)}")
        if output_path.exists():
            output_path.unlink()
        raise HTTPException(500, f"提取音频段失败: {str(e)}") 
    


# # 日志打印工具
# def log(message, level="INFO"):
#     print(f"[{level}] {message}")

# # 异步合并音频主函数
# async def merge_audio(file_id: str, target_language: str):
#     try:
#         # 路径检查与准备
#         audio_dir, subtitle_file = check_and_prepare_paths(file_id, target_language)
#         subtitles = load_subtitles(subtitle_file)
#         total_duration = calculate_total_duration(subtitles)
#         output_dir, final_output = prepare_output_paths(file_id, target_language)

#         # 按批次生成临时音频文件
#         temp_files = await process_batches(subtitles, audio_dir, total_duration, file_id)

#         # 合并批次生成最终文件
#         merge_final_audio(file_id, temp_files, final_output)

#         # 验证生成结果
#         verify_audio_duration(final_output, total_duration)
#         log(f"音频合并成功！最终文件: {final_output}", "SUCCESS")
#         return {"merged_file": f"{file_id}/{target_language}.mp3"}

#     except Exception as e:
#         log(f"音频合并失败: {str(e)}", "ERROR")
#         raise HTTPException(500, str(e))

# # 检查和准备路径
# def check_and_prepare_paths(file_id, target_language):
#     audio_dir = AUDIO_DIR / file_id / target_language
#     if not audio_dir.exists():
#         raise HTTPException(404, "音频文件目录未找到")

#     file_id_without_ext = Path(file_id).stem
#     subtitle_file = SUBTITLE_DIR / f"{file_id_without_ext}_{target_language}.json"
#     if not subtitle_file.exists():
#         subtitle_file = SUBTITLE_DIR / f"{file_id_without_ext}.json"

#     if not subtitle_file.exists():
#         raise HTTPException(404, "字幕文件未找到")

#     log(f"音频目录: {audio_dir}")
#     log(f"字幕文件: {subtitle_file}")
#     return audio_dir, subtitle_file

# # 加载字幕
# def load_subtitles(subtitle_file):
#     with open(subtitle_file, 'r', encoding='utf-8') as f:
#         subtitles = json.load(f)
#     subtitles.sort(key=lambda x: float(x['start']))
#     return subtitles

# # 计算总时长
# def calculate_total_duration(subtitles):
#     last_subtitle = subtitles[-1]
#     total_duration = last_subtitle['start'] + last_subtitle['duration']
#     log(f"字幕总时长: {total_duration:.2f} 秒")
#     return total_duration

# # 准备输出目录
# def prepare_output_paths(file_id, target_language):
#     output_dir = MERGED_DIR / file_id
#     output_dir.mkdir(parents=True, exist_ok=True)
#     final_output = output_dir / f"{target_language}.mp3"
#     return output_dir, final_output

# # 批次处理逻辑
# async def process_batches(subtitles, audio_dir, total_duration, file_id):
#     temp_files = []
#     batch_tasks = []

#     for batch_index in range(0, len(subtitles), BATCH_SIZE):
#         batch_subtitles = subtitles[batch_index:batch_index + BATCH_SIZE]
#         batch_tasks.append(process_single_batch(batch_index, batch_subtitles, audio_dir, total_duration, file_id))

#     results = await asyncio.gather(*batch_tasks)
#     for result in results:
#         if result:
#             temp_files.append(result)
#     return temp_files

# # 处理单个批次
# async def process_single_batch(batch_index, batch_subtitles, audio_dir, total_duration, file_id):
#     batch_start = float(batch_subtitles[0]['start'])
#     batch_end = total_duration if batch_index + BATCH_SIZE >= len(batch_subtitles) else float(batch_subtitles[-1]['start'])
#     batch_duration = batch_end - batch_start

#     temp_base = TEMP_DIR / f"{file_id}_base_{batch_index}.wav"
#     temp_output = TEMP_DIR / f"{file_id}_batch_{batch_index}.mp3"
    
#     try:
#         # 创建静音基础轨道
#         create_silence_track(temp_base, batch_duration)
#         filter_complex, inputs, valid_audio_count = prepare_filter_complex(batch_subtitles, audio_dir, batch_start, batch_duration, batch_index)

#         if valid_audio_count > 0:
#             merge_batch_audio(filter_complex, inputs, valid_audio_count, batch_duration, temp_base, temp_output)
#             return temp_output, batch_start

#     except Exception as e:
#         log(f"处理批次 {batch_index // BATCH_SIZE + 1} 失败: {str(e)}", "ERROR")
#         return None

#     finally:
#         if temp_base.exists():
#             temp_base.unlink()
# # 创建静音轨道
# def create_silence_track(output_path, duration):
#     subprocess.run([
#         'ffmpeg', '-y',
#         '-f', 'lavfi',
#         '-i', f'anullsrc=r={SILENT_SAMPLE_RATE}:cl=mono',
#         '-t', str(duration),
#         str(output_path)
#     ], check=True)

# # 准备过滤器
# def prepare_filter_complex(batch_subtitles, audio_dir, batch_start, batch_duration, batch_index):
#     filter_parts = []
#     inputs = []
#     valid_audio_count = 0

#     for i, subtitle in enumerate(batch_subtitles):
#         global_index = batch_index + i  # 使用全局索引
#         audio_file = audio_dir / f"{global_index:04d}.mp3"
        
#         if audio_file.exists() and validate_audio_file(audio_file, subtitle):
#             inputs.extend(['-i', str(audio_file)])
#             relative_start = subtitle['start'] - batch_start
#             # 定义延迟和补齐的过滤器
#             filter_parts.append(
#                 f"[{valid_audio_count + 1}:a]adelay={int(relative_start * 1000)}|{int(relative_start * 1000)},apad=whole_dur={batch_duration}[audio{valid_audio_count}];"
#             )
#             valid_audio_count += 1

#     # 如果有多个输入音频，合并它们
#     if valid_audio_count > 1:
#         merge_cmd = ''.join(f"[audio{i}]" for i in range(valid_audio_count))
#         merge_cmd += f"amerge=inputs={valid_audio_count}[merged];"
#         filter_parts.append(merge_cmd)
#     elif valid_audio_count == 1:
#         # 只有一个输入时直接命名为 `merged`
#         filter_parts.append(f"[audio0][merged];")

#     return ''.join(filter_parts), inputs, valid_audio_count
# # 验证音频文件
# def validate_audio_file(audio_file, subtitle):
#     file_size = audio_file.stat().st_size
#     if file_size < 1024:
#         log(f"音频文件过小: {audio_file}", "WARNING")
#         return False
#     return True

# # 合并单个批次音频
# def merge_batch_audio(filter_complex, inputs, valid_audio_count, batch_duration, temp_base, temp_output):
#     # 如果没有有效输入音频，跳过合并
#     if valid_audio_count == 0:
#         log("没有有效音频，跳过合并", level="WARNING")
#         return

#     # 构建 FFmpeg 命令
#     cmd = [
#         'ffmpeg', '-y', '-i', str(temp_base),  # 基础静音文件
#         *inputs,                              # 批次音频文件
#         '-filter_complex', filter_complex,    # 过滤器复杂度
#         '-map', '[merged]',                   # 映射合并的音频
#         '-t', str(batch_duration),            # 限制时长
#         '-codec:a', 'libmp3lame', '-q:a', '2',  # 使用 MP3 编码
#         str(temp_output)
#     ]
#     log(f"执行批次合并命令: {' '.join(cmd)}")
#     subprocess.run(cmd, check=True)

# # 最终合并
# def merge_final_audio(file_id, temp_files, final_output):
#     concat_list = TEMP_DIR /  f"{file_id}_concat_list.txt"
#     with open(concat_list, 'w', encoding='utf-8') as f:
#         # 按时间顺序排序临时文件
#         temp_files.sort(key=lambda x: x[1])  # 按开始时间排序
#         for temp_file, _ in temp_files:
#             f.write(f"file '{temp_file.absolute()}'\n")


#     subprocess.run([
#         'ffmpeg', '-y',
#         '-f', 'concat', '-safe', '0', '-i', str(concat_list),
#         '-c:a', 'libmp3lame', '-q:a', '2', str(final_output)
#     ], check=True)

# # 验证生成文件时长
# def verify_audio_duration(final_output, total_duration):
#     actual_duration = float(subprocess.check_output([
#         'ffprobe', '-v', 'error',
#         '-show_entries', 'format=duration',
#         '-of', 'default=noprint_wrappers=1:nokey=1',
#         str(final_output)
#     ]).decode().strip())
#     # if abs(actual_duration - total_duration) > 1:
#     #     raise Exception(f"生成文件时长不匹配: {actual_duration:.2f}s (实际) vs {total_duration:.2f}s (预期)") 