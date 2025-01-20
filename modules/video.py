import os
from fastapi import HTTPException
import subprocess
import asyncio
import json  # 添加 json 导入
from pathlib import Path
from moviepy.editor import VideoFileClip
from .config import (
    UPLOAD_DIR,
    SUBTITLE_DIR,
    TEMP_DIR,
    SUBTITLED_VIDEO_DIR,
    MERGED_DIR
)
from .utils import convert_to_srt  # 改为从 utils 导入
import ass

# 颜色转换函数
def hex_to_ass_color(hex_color, alpha=0):
        # 去掉 "#" 并提取 RGB
        hex_color = hex_color.lstrip("#")
        r, g, b = int(hex_color[:2], 16), int(hex_color[2:4], 16), int(hex_color[4:], 16)
        # ASS 使用 AABBGGRR 格式，其中 AA 是 alpha 通道
        # 在 ASS 中，0 表示完全不透明，255 表示完全透明
        return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"

def convert_subtitle_style(frontend_data: dict) -> dict:
    """转换前端字幕样式为 ASS 格式
    Args:
        frontend_data (dict): 前端传入的字幕样式配置
    Returns:
        dict: ASS格式的字幕样式配置
    Raises:
        ValueError: 当样式参数无效时抛出
    """
    try:
        # 基础样式参数
        style_params = {
            'bgColor': ('#000000', str),
            'bgOpacity': ('0.5', float),
            'color': ('#FFFFFF', str),
            'fontSize': ('48', float),
            'strokeColor': ('#000000', str),
            'strokeWidth': ('3', float)
        }
        
        # 处理基础样式参数
        processed_params = process_style_params(frontend_data, style_params)
        
        # 处理边距参数
        margin_params = process_margin_params(frontend_data)
        
        # 构建最终样式
        return {
            'fontSize': str(int(processed_params['fontSize'])),
            'color': hex_to_ass_color(processed_params['color'], 0),
            'strokeColor': hex_to_ass_color(processed_params['strokeColor'], 0),
            'strokeWidth': str(processed_params['strokeWidth']),
            'bgColor': hex_to_ass_color(
                processed_params['bgColor'],
                int((1 - processed_params['bgOpacity']) * 255)
            ),
            'bgOpacity': str(processed_params['bgOpacity']),
            **margin_params
        }
    except Exception as e:
        raise ValueError(f"样式转换失败: {str(e)}")

def process_style_params(data: dict, params_config: dict) -> dict:
    """处理样式参数
    Args:
        data (dict): 输入数据
        params_config (dict): 参数配置
    Returns:
        dict: 处理后的参数
    """
    result = {}
    for key, (default, type_func) in params_config.items():
        try:
            value = data.get(key, default)
            result[key] = type_func(value)
        except (ValueError, TypeError) as e:
            raise ValueError(f"参数 {key} 无效: {str(e)}")
    return result

def process_margin_params(data: dict) -> dict:
    """处理边距参数
    Args:
        data (dict): 输入数据
    Returns:
        dict: 处理后的边距参数
    """
    return {
        'marginV': "20",  # 垂直边距
        'marginL': "10",  # 左边距
        'marginR': "10"   # 右边距
    }

async def burn_subtitles(file_id: str, language: str, style: dict):
    """将字幕烧录到视频中
    Args:
        file_id (str): 视频文件ID
        language (str): 目标语言
        style (dict): 字幕样式配置
    Returns:
        dict: 包含处理结果的字典
    """
    # 准备文件路径
    file_id_without_ext = Path(file_id).stem
    paths = {
        'video': UPLOAD_DIR / f"{file_id_without_ext}.mp4",
        'subtitle': SUBTITLE_DIR / f"{file_id_without_ext}_{language}.json",
        'audio': MERGED_DIR / file_id_without_ext / f"{language}.mp3",
        'output': SUBTITLED_VIDEO_DIR / f"{file_id_without_ext}_subtitled.mp4",
        'ass': TEMP_DIR / f"{file_id_without_ext}.ass",
        'font': Path("static/fonts/SimSun.ttf")
    }

    try:
        # 创建必要的目录
        for directory in [SUBTITLED_VIDEO_DIR, TEMP_DIR]:
            directory.mkdir(exist_ok=True)

        # 验证输入文件
        required_files = ['video', 'subtitle', 'audio']  # 只检查必需的输入文件
        for key in required_files:
            if not paths[key].exists():
                raise HTTPException(500, f"找不到{key}文件: {paths[key]}")

        # 计算字幕框参数
        subtitle_params = calculate_subtitle_params(style)
        
        # 转换字幕格式
        await json_to_ass(paths['subtitle'], paths['ass'], {
            **convert_subtitle_style(style),
            'marginV': str(subtitle_params['margin_v'])
        })

        # 构建 FFmpeg 命令
        cmd = build_ffmpeg_command(paths, subtitle_params)
        
        # 执行 FFmpeg 命令
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            raise HTTPException(500, f"FFmpeg 执行失败: {stderr.decode()}")

        # 验证输出文件
        if not paths['output'].exists() or paths['output'].stat().st_size == 0:
            raise HTTPException(500, "输出文件无效")

        return {
            "status": "success",
            "message": "字幕烧录完成",
            "output_file": str(paths['output'].name)
        }

    except Exception as e:
        print(f"烧录字幕失败: {str(e)}")
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(500, f"烧录字幕失败: {str(e)}")
    finally:
        # 清理临时文件
        if paths['ass'].exists():
            paths['ass'].unlink(missing_ok=True)

def calculate_subtitle_params(style: dict, text: str = "") -> dict:
    """计算字幕框参数"""
    font_size = int(style['fontSize'])
    line_spacing = 1.2  # 行间距系数
    padding_vertical = 20
    padding_horizontal = 40  # 水平内边距
    
    # 计算行数
    lines = text.count('\\N') + 1 if text else 3
    
    # 计算框高
    subtitle_box_height = int(font_size * lines * line_spacing + padding_vertical * 2)
    bottom_margin = 10
    margin_v = int(subtitle_box_height / 2 - font_size)
    
    return {
        'box_height': subtitle_box_height,
        'bottom_margin': bottom_margin,
        'margin_v': margin_v,
        'padding_h': padding_horizontal,
        'line_count': lines
    }

def build_ffmpeg_command(paths: dict, subtitle_params: dict) -> list:
    """构建 FFmpeg 命令"""
    base_cmd = [
        'ffmpeg', '-y',
        '-i', str(paths['video']),
        '-i', str(paths['audio'])
    ]

    if paths['font'].exists():
        vf = f'ass={str(paths["ass"])}:fontsdir={paths["font"].parent}'
    else:
        vf = f'ass={str(paths["ass"])}'

    return [
        *base_cmd,
        '-vf', vf,
        '-c:v', 'libx264',
        '-preset', 'medium',
        '-crf', '23',
        '-c:a', 'aac',
        '-map', '0:v',
        '-map', '1:a',
        str(paths['output'])
    ]

def generate_ass_style(style: dict) -> str:
    """生成ASS样式定义"""
    try:
        font_name = "SimSun"
        font_size = style['fontSize']
        margin_v = style.get('marginV', '20')
        stroke_width = max(1.0, float(style.get('strokeWidth', 1)))

        return (
            f"Style: Default,{font_name},{font_size},"
            f"{style['color']},"  # PrimaryColour (文字颜色)
            f"{style['color']},"  # SecondaryColour (次要颜色)
            f"{style['strokeColor']},"  # OutlineColour (边框颜色)
            f"{style['bgColor']},"  #  BackColour(背景颜色)
            f"-1,0,0,0,"  # 加粗,斜体,下划线,删除线
            f"100,100,0,0,"  # 缩放X,缩放Y,间距,角度
            f"4,{stroke_width},0,"  # 边框样式(4=带阴影的不透明背景),边框宽度,阴影
            f"2,10,10,{margin_v},1"  # 对齐,边距,编码
        )
    except (KeyError, ValueError) as e:
        raise ValueError(f"样式参数无效: {str(e)}")

async def json_to_ass(json_path: Path, ass_path: Path, style: dict):
    """将 JSON 格式的字幕转换为 ASS 格式"""
    try:
        print(f"开始转换字幕，JSON文件路径: {json_path}")
        print(f"ASS文件将保存到: {ass_path}")
        print("收到的样式参数:", style)
        
        # 读取 JSON 字幕
        print("正在读取JSON字幕文件...")
        subtitles = read_json_subtitles(json_path)
        print(f"成功读取字幕，共 {len(subtitles)} 条")
        
        # 生成 ASS 内容
        print("正在生成ASS内容...")
        ass_content = generate_ass_content(subtitles, style)
        print("ASS内容生成完成")
        
        # 写入 ASS 文件
        print(f"正在写入ASS文件: {ass_path}")
        write_ass_file(ass_path, ass_content)
        print(f"ASS文件写入完成，文件大小: {ass_path.stat().st_size} 字节")

        # 详细输出 ASS 文件内容
        if ass_path.exists():
            with open(ass_path, 'r', encoding='utf-8') as f:
                content = f.read()
                print("\n=== ASS 文件完整内容 ===")
                print(content)
                print("=== ASS 文件内容结束 ===\n")
                
                # 分析样式部分
                style_section = [line for line in content.split('\n') if line.startswith('Style:')]
                print("\n=== 样式分析 ===")
                if style_section:
                    print("找到样式定义:", style_section[0])
                    parts = style_section[0].split(',')
                    print("样式参数解析:")
                    print(f"- 字体名称: {parts[1]}")
                    print(f"- 字体大小: {parts[2]}")
                    print(f"- 主要颜色: {parts[3]}")
                    print(f"- 次要颜色: {parts[4]}")
                    print(f"- 边框颜色: {parts[5]}")
                    print(f"- 背景颜色: {parts[6]}")
                    print(f"- 边框样式: {parts[15]}")
                else:
                    print("警告: 未找到样式定义")
                print("=== 样式分析结束 ===\n")
        else:
            raise HTTPException(500, "ASS文件未成功生成")

    except Exception as e:
        print(f"转换字幕格式失败: {str(e)}")
        raise HTTPException(500, f"转换字幕格式失败: {str(e)}")

def read_json_subtitles(json_path: Path) -> list:
    """读取JSON字幕文件"""
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON格式错误: {str(e)}")
    except Exception as e:
        raise ValueError(f"读取字幕文件失败: {str(e)}")

def generate_ass_content(subtitles: list, style: dict) -> str:
    """生成ASS文件内容"""
    # 基础配置
    ass_content = generate_ass_header()
    
    # 添加样式定义
    style_line = generate_ass_style(style)
    ass_content += style_line + "\n\n"
    
    # 添加事件格式定义和字幕内容
    ass_content += generate_ass_events(subtitles)
    
    return ass_content

def generate_ass_header() -> str:
    """生成ASS文件头部"""
    return """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
"""

def generate_ass_events(subtitles: list) -> str:
    """生成ASS事件部分"""
    events = "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    
    for subtitle in subtitles:
        try:
            start_time = format_time(subtitle['start'])
            end_time = format_time(subtitle['start'] + subtitle['duration'])
            text = subtitle['text'].replace('\n', '\\N')
            # 移除可能影响背景显示的样式覆盖
            events += f"Dialogue: 0,{start_time},{end_time},Default,,0,0,0,,{text}\n"
        except KeyError as e:
            print(f"警告: 字幕格式错误，跳过此条字幕: {str(e)}")
            continue
    
    return events

def write_ass_file(ass_path: Path, content: str):
    """写入ASS文件"""
    try:
        with open(ass_path, 'w', encoding='utf-8') as f:
            f.write(content)
    except Exception as e:
        raise ValueError(f"写入ASS文件失败: {str(e)}")

def format_time(seconds: float) -> str:
    """将秒数转换为 ASS 格式的时间字符串 (H:MM:SS.cc)"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centisecs = int((seconds * 100) % 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centisecs:02d}"

def get_video_duration(video_path: Path) -> float:
    """获取视频时长"""
    try:
        with VideoFileClip(str(video_path)) as video:
            return video.duration
    except Exception as e:
        raise HTTPException(500, f"获取视频时长失败: {str(e)}")