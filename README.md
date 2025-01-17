# Video Subtitle Generator and Translator

一个强大的视频字幕生成、翻译和语音合成工具。

## 功能特点

- 🎥 支持视频上传和预览
- 🎯 自动语音识别生成字幕
- 🌍 多语言字幕翻译
- 🎨 字幕样式自定义
- 🔊 文字转语音合成
- 📝 字幕实时编辑
- 🎬 字幕烧录到视频

## 支持的语言

- 中文（简体/繁体）
- 英语
- 日语
- 韩语
- 法语
- 德语

## 技术栈

### 后端
- Python 3.8+
- FastAPI
- Azure Cognitive Services
- FFmpeg

### 前端
- HTML5
- JavaScript
- Bootstrap 5
- WebSocket

## 安装要求

1. Python 3.8 或更高版本
2. FFmpeg
3. Azure 服务账号（默认使用EDGE TTS，如果要使用需要在环境变量里设置key）
4. 必要的Python包（见 requirements.txt）

## 环境变量配置（这一步可以不用了）

创建 `.env` 文件并配置以下变量：
AZURE_SPEECH_KEY=your_speech_key
AZURE_SPEECH_REGION=your_speech_region
AZURE_TRANSLATOR_KEY=your_translator_key
AZURE_TRANSLATOR_REGION=your_translator_region


## 安装步骤

1. 克隆仓库
bash
git clone https://github.com/QKJIN/video2srt2speech.git
cd video2srt2speech

2. 安装依赖
bash
pip install -r requirements.txt

3. 启动服务器
bash
uvicorn main:app --reload


4. 访问 http://localhost:8000 开始使用

## 使用说明

1. **上传视频**
   - 点击"选择视频文件"按钮
   - 选择要处理的视频文件
   - 点击"上传视频"开始上传

2. **生成字幕**
   - 选择源语言
   - 点击"生成字幕"按钮
   - 等待语音识别完成

3. **翻译字幕**
   - 选择目标语言
   - 点击"翻译字幕"按钮
   - 等待翻译完成

4. **生成语音**
   - 选择目标语言和语音
   - 点击"生成语音"按钮
   - 等待语音合成完成

5. **合并音频**
   - 点击"合并语音"按钮
   - 等待音频合并完成

6. **生成带字幕视频**
   - 自定义字幕样式
   - 点击"生成带字幕视频"按钮
   - 等待视频处理完成

## 目录结构

```plaintext
new-srt2speech/
├── main.py # 后端主程序
├── static/ # 静态文件目录
│ ├── index.html # 前端页面
│ └── main.js # 前端脚本
├── uploads/ # 上传的视频文件
├── audio/ # 生成的音频文件
├── subtitles/ # 字幕文件
├── merged/ # 合并后的音频
├── subtitled_videos/ # 带字幕的视频
└── modules/ # 各种功能文件



## 注意事项

1. 确保有足够的磁盘空间存储上传的视频和生成的文件
2. 视频处理可能需要较长时间，请耐心等待
3. 建议使用现代浏览器（Chrome、Firefox、Edge等）
4. 上传视频大小可能受到服务器配置限制

## License

MIT License
