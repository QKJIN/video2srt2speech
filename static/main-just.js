// 基础功能函数
function showLoading() {
    document.querySelector('.loading-overlay').style.display = 'flex';
}

function hideLoading() {
    document.querySelector('.loading-overlay').style.display = 'none';
}

function showMessage(type, message) {
    const messageBox = document.getElementById('messageBox');
    messageBox.className = 'alert ' + (type === '错误' ? 'alert-error' : 'alert-success');
    messageBox.textContent = message;
    messageBox.style.display = 'block';
    
    // 3秒后自动隐藏
    setTimeout(() => {
        messageBox.style.display = 'none';
    }, 3000);
}

// 文件上传相关的代码
document.getElementById('uploadBtn').onclick = async function() {
    const fileInput = document.getElementById('videoFile');
    const file = fileInput.files[0];
    
    if (!file) {
        showMessage('错误', '请先选择视频文件');
        return;
    }

    try {
        showLoading();
        
        const formData = new FormData();
        formData.append('file', file);

        const response = await fetch('/upload', {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            throw new Error(await response.text());
        }

        const result = await response.json();
        window.currentFileId = result.file_id;

        // 显示视频预览
        const videoContainer = document.getElementById('videoContainer');
        const videoPlayer = document.getElementById('videoPlayer');
        videoPlayer.src = `/video/${result.file_id}`;
        videoContainer.style.display = 'block';

        // 显示字幕样式面板
        document.getElementById('subtitleStylePanel').style.display = 'block';

        showMessage('成功', '视频上传成功');
        
    } catch (error) {
        console.error('上传失败:', error);
        showMessage('错误', '上传失败: ' + error.message);
    } finally {
        hideLoading();
    }
};

// 文件选择监听
document.getElementById('videoFile').onchange = function() {
    const file = this.files[0];
    if (file) {
        // 可以在这里添加文件类型检查
        if (!file.type.startsWith('video/')) {
            showMessage('错误', '请选择视频文件');
            this.value = '';
            return;
        }
        
        // 显示选中的文件名
        const fileName = file.name;
        showMessage('提示', `已选择文件: ${fileName}`);
    }
};

// 生成字幕按钮的处理函数
document.getElementById('generateSubtitlesBtn').onclick = async function() {
    if (!currentFileId) {
        showMessage('错误', '请先上传视频文件');
        return;
    }

    try {
        showLoading();
        
        // 先提取音频
        const extractResponse = await fetch(`/extract-audio/${currentFileId}`, {
            method: 'POST'
        });

        if (!extractResponse.ok) {
            throw new Error(await extractResponse.text());
        }

        await extractResponse.json();  // 等待音频提取完成
        
        // 然后生成字幕
        const sourceLanguage = document.getElementById('sourceLanguage').value;
        const modelSelect = document.getElementById('subtitleModel');
        const model = modelSelect.value;
        
        console.log('使用模型:', model);
        
        // 构建 URL 参数
        const params = new URLSearchParams();
        params.append('language', sourceLanguage);
        params.append('model', model);
        
        const url = `/generate-subtitles/${currentFileId}?${params.toString()}`;
        console.log('请求 URL:', url);
        
        const response = await fetch(url, {
            method: 'POST',
            headers: {
                'Accept': 'application/json'
            }
        });

        if (!response.ok) {
            const errorText = await response.text();
            console.error('服务器错误:', errorText);
            throw new Error(errorText);
        }

        const subtitles = await response.json();
        console.log('收到字幕数据:', subtitles);

        if (Array.isArray(subtitles) && subtitles.length > 0) {
            updateSubtitleEditor(subtitles);
            showMessage('成功', `成功生成 ${subtitles.length} 条字幕`);
        } else {
            throw new Error('未收到有效的字幕数据');
        }

    } catch (error) {
        console.error('生成字幕失败:', error);
        showMessage('错误', '生成字幕失败: ' + error.message);
    } finally {
        hideLoading();
    }
};

// 添加 updateSubtitleEditor 函数
function updateSubtitleEditor(subtitles) {
    const editor = document.getElementById('subtitleEditor');
    editor.innerHTML = '';  // 清空现有内容

    let html = '<div class="subtitle-list">';
    
    for (let i = 0; i < subtitles.length; i++) {
        const subtitle = subtitles[i];
        if (!subtitle || typeof subtitle.start === 'undefined' || typeof subtitle.duration === 'undefined') {
            console.error('无效的字幕条目:', subtitle);
            continue;
        }

        const startTime = formatTime(parseFloat(subtitle.start));
        const endTime = formatTime(parseFloat(subtitle.start) + parseFloat(subtitle.duration));
        const originalText = subtitle.text || '';
        const sequenceNumber = (i + 1).toString().padStart(3, '0');
        
        html += `
            <div class="subtitle-item" data-index="${i}" data-start="${subtitle.start}">
                <div class="subtitle-header">
                    <div class="subtitle-info">
                        <span class="sequence-number" data-time="${subtitle.start}">${sequenceNumber}</span>
                        <span class="subtitle-time">${startTime} - ${endTime}</span>
                    </div>
                    <div class="subtitle-controls">
                        <button class="btn btn-sm btn-outline-primary me-1" onclick="playSubtitle(${i})">
                            <i class="fas fa-play"></i>
                        </button>
                        <button class="btn btn-sm btn-outline-success me-1" onclick="generateSingleSpeech(${i})">
                            <i class="fas fa-volume-up"></i>
                        </button>
                        <button class="btn btn-sm btn-outline-info edit-btn" data-index="${i}">
                            <i class="fas fa-edit"></i>
                        </button>
                    </div>
                </div>
                <div class="subtitle-text">
                    <div class="original-text" data-index="${i}" contenteditable="false">${originalText}</div>
                    <div class="translated-text"></div>
                </div>
                <div class="audio-player" style="display: none;">
                    <audio controls class="subtitle-audio">
                        <source src="" type="audio/mpeg">
                        您的浏览器不支持音频播放。
                    </audio>
                </div>
            </div>
        `;
    }
    html += '</div>';
    
    editor.innerHTML = html;
    
    // 保存字幕数据到全局变量
    window.currentSubtitles = subtitles;
    
    // 添加编辑按钮事件监听器
    document.querySelectorAll('.edit-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            const index = parseInt(btn.dataset.index);
            const textElement = document.querySelector(`.original-text[data-index="${index}"]`);
            if (textElement) {
                startEditing(textElement);
            }
        });
    });
    
    // 更新视频播放器的字幕显示
    updateVideoSubtitles(subtitles);
}

// 添加时间格式化函数
function formatTime(seconds) {
    const pad = num => num.toString().padStart(2, '0');
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);
    const ms = Math.floor((seconds % 1) * 1000);
    return `${pad(hours)}:${pad(minutes)}:${pad(secs)},${ms.toString().padStart(3, '0')}`;
}

// 添加字幕播放功能
function playSubtitle(index) {
    const subtitle = window.currentSubtitles[index];
    if (!subtitle) return;
    
    const video = document.getElementById('videoPlayer');
    if (video) {
        video.currentTime = subtitle.start;
        video.play();
    }
}

// 更新视频播放器的字幕显示
function updateVideoSubtitles(subtitles) {
    const overlay = document.getElementById('subtitleOverlay');
    if (!overlay) return;
    
    const video = document.getElementById('videoPlayer');
    if (!video) return;
    
    // 清除现有的时间更新监听器
    if (window.subtitleUpdateInterval) {
        clearInterval(window.subtitleUpdateInterval);
    }
    
    // 设置新的时间更新监听器
    window.subtitleUpdateInterval = setInterval(() => {
        const currentTime = video.currentTime;
        const currentSubtitle = subtitles.find(s => 
            currentTime >= s.start && currentTime <= (s.start + s.duration)
        );
        
        overlay.textContent = currentSubtitle ? currentSubtitle.text : '';
    }, 100);
}
