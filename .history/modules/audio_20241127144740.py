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
            
            print(f"处理批次 {batch_index//BATCH_SIZE + 1}: {batch_start:.2f}s - {batch_end:.2f}s (duration: {batch_duration:.2f}s)")
            
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
                for i, subtitle in enumerate(batch_subtitles):
                    audio_file = audio_dir / f"{batch_index + i:04d}.mp3"
                    if audio_file.exists():
                        inputs.extend(['-i', str(audio_file)])
                        relative_start = float(subtitle['start']) - batch_start
                        duration = float(subtitle['duration'])
                        
                        filter_parts.append(
                            f'[{valid_audio_count + 1}:a]volume=1.5,afade=t=in:st=0:d=0.5,afade=t=out:st={duration-0.5}:d=0.5,adelay={int(relative_start*1000)}|{int(relative_start*1000)}[delayed{valid_audio_count}];'
                        )
                        valid_audio_count += 1

                if valid_audio_count > 0:
                    # 构建混音命令
                    filter_complex = ''.join(filter_parts)
                    filter_complex += '[0:a]volume=0.1[base];[base]'
                    for i in range(valid_audio_count):
                        filter_complex += f'[delayed{i}]'
                    filter_complex += f'amerge=inputs={valid_audio_count + 1}[aout]'

                    # 生成这个批次的音频
                    cmd = [
                        'ffmpeg', '-y'
                    ] + inputs + [
                        '-filter_complex', filter_complex,
                        '-map', '[aout]',
                        '-codec:a', 'libmp3lame',
                        '-q:a', '2',
                        str(temp_output)
                    ]
                    
                    process = subprocess.run(cmd, capture_output=True, text=True)
                    if process.returncode != 0:
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
                print("暂时不清理临时文件！")
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
        
        # 确保输入文件存在
        if not audio_path.exists():
            raise HTTPException(500, f"源音频文件不存在: {audio_path}")
        
        # 运行ffmpeg命令，添加音频预处理
        process = await asyncio.create_subprocess_exec(
            'ffmpeg', '-y',
            '-i', str(audio_path),
            '-ss', str(start_time),
            '-t', str(end_time - start_time),
            # 添加降噪
            '-af', 'anlmdn=s=7:p=0.002:r=0.01,highpass=f=200,lowpass=f=3000',
            '-acodec', 'pcm_s16le',  # WAV格式
            '-ar', '16000',          # 16kHz采样率
            '-ac', '1',              # 单声道
            str(output_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            print(f"FFmpeg错误输出: {stderr.decode()}")
            raise HTTPException(500, f"音频段提取失败: {stderr.decode()}")
        
        if not output_path.exists():
            raise HTTPException(500, "音频段提取失败：输出文件未生成")
            
        # 验证输出文件大小
        if output_path.stat().st_size == 0:
            raise HTTPException(500, "音频段提取失败：输出文件为空")
            
        print(f"音频段提取成功: {output_path}")
            
    except Exception as e:
        print(f"提取音频段失败: {str(e)}")
        raise HTTPException(500, f"提取音频段失败: {str(e)}") 