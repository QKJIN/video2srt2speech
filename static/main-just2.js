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
        console.log('开始提取音频...');
        const extractResponse = await fetch(`/extract-audio/${currentFileId}`, {
            method: 'POST'
        });

        if (!extractResponse.ok) {
            throw new Error(await extractResponse.text());
        }

        await extractResponse.json();
        console.log('音频提取完成');

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

// 更新字幕编辑器
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

// 添加字幕编辑相关函数
function startEditing(element) {
    if (element.classList.contains('editing')) return;
    
    const index = parseInt(element.dataset.index);
    if (isNaN(index)) {
        console.error('无效的字幕索引');
        return;
    }
    
    element.classList.add('editing');
    element.contentEditable = true;
    element.focus();
    
    // 保存原始文本以备取消
    element.dataset.originalText = element.textContent;
    
    // 添加事件监听器
    element.addEventListener('keydown', handleEditKeydown);
    element.addEventListener('blur', finishEditing);
}

function handleEditKeydown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        event.target.blur();
    } else if (event.key === 'Escape') {
        event.preventDefault();
        event.target.textContent = event.target.dataset.originalText;
        event.target.blur();
    }
}

async function finishEditing(event) {
    const element = event.target;
    const index = parseInt(element.dataset.index);
    const newText = element.textContent.trim();
    
    element.classList.remove('editing');
    element.contentEditable = false;
    element.removeEventListener('keydown', handleEditKeydown);
    element.removeEventListener('blur', finishEditing);
    
    if (newText !== element.dataset.originalText) {
        try {
            await updateSubtitleText(index, newText);
            window.currentSubtitles[index].text = newText;
            showMessage('成功', '字幕更新成功');
        } catch (error) {
            console.error('更新字幕失败:', error);
            element.textContent = element.dataset.originalText;
            showMessage('错误', '更新字幕失败: ' + error.message);
        }
    }
}

// 更新视频播放器的字幕显示
function updateVideoSubtitles(subtitles) {
    // ... 其他代码保持不变
}

// 添加时间格式化函数
function formatTime(seconds) {
    // ... 其他代码保持不变
}

// 翻译字幕按钮处理
document.getElementById('translateBtn').onclick = async function() {
    if (!currentFileId) {
        showMessage('错误', '请先生成原始字幕');
        return;
    }

    try {
        showLoading();
        const sourceLanguage = document.getElementById('sourceLanguage').value;
        const targetLanguage = document.getElementById('targetLanguage').value;

        // 使用 URL 参数而不是 JSON body
        const url = `/translate-subtitles/${currentFileId}?source_language=${sourceLanguage}&target_language=${targetLanguage}`;
        
        const response = await fetch(url, {
            method: 'POST',
            headers: {
                'Accept': 'application/json'
            }
        });

        if (!response.ok) {
            throw new Error(await response.text());
        }

        const result = await response.json();
        
        // 更新翻译后的字幕显示
        if (result.subtitles && result.subtitles.length > 0) {
            result.subtitles.forEach((subtitle, index) => {
                const translatedDiv = document.querySelector(`.subtitle-item[data-index="${index}"] .translated-text`);
                if (translatedDiv) {
                    translatedDiv.textContent = subtitle.text;
                }
            });
        }
        
        showMessage('成功', `成功翻译 ${result.subtitles.length} 条字幕`);

    } catch (error) {
        console.error('翻译失败:', error);
        showMessage('错误', '翻译失败: ' + error.message);
    } finally {
        hideLoading();
    }
};

// 生成语音按钮处理
document.getElementById('generateSpeechBtn').onclick = async function() {
    if (!currentFileId) {
        showMessage('错误', '请先生成字幕');
        return;
    }

    try {
        showLoading();
        const targetLanguage = document.getElementById('targetLanguage').value;
        const voiceName = document.getElementById('voiceSelect').value;

        const response = await fetch(`/generate-speech/${currentFileId}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                target_language: targetLanguage,
                voice_name: voiceName
            })
        });

        if (!response.ok) {
            throw new Error(await response.text());
        }

        const result = await response.json();
        showMessage('成功', '语音生成完成');

    } catch (error) {
        console.error('生成语音失败:', error);
        showMessage('错误', '生成语音失败: ' + error.message);
    } finally {
        hideLoading();
    }
};

// 合并语音按钮处理
document.getElementById('mergeAudioBtn').onclick = async function() {
    if (!currentFileId) {
        showMessage('错误', '请先生成语音');
        return;
    }

    try {
        showLoading();
        const targetLanguage = document.getElementById('targetLanguage').value;

        const response = await fetch(`/merge-audio/${currentFileId}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                target_language: targetLanguage
            })
        });

        if (!response.ok) {
            throw new Error(await response.text());
        }

        const result = await response.json();
        
        // 显示合并后的音频
        const mergedAudio = document.getElementById('mergedAudio');
        const mergedAudioContainer = document.getElementById('mergedAudioContainer');
        mergedAudio.src = `/merged/${result.merged_file}`;
        mergedAudioContainer.style.display = 'block';

        showMessage('成功', '音频合并完成');

    } catch (error) {
        console.error('合并音频失败:', error);
        showMessage('错误', '合并音频失败: ' + error.message);
    } finally {
        hideLoading();
    }
};

// 生成带字幕视频按钮处理
document.getElementById('burnSubtitlesBtn').onclick = async function() {
    if (!currentFileId) {
        showMessage('错误', '请先生成字幕');
        return;
    }

    try {
        showLoading();
        
        // 获取字幕样式
        const style = {
            fontSize: document.getElementById('subtitleFontSize').value,
            color: document.getElementById('subtitleColor').value,
            strokeColor: document.getElementById('subtitleStrokeColor').value,
            strokeWidth: document.getElementById('subtitleStrokeWidth').value,
            bgColor: document.getElementById('subtitleBgColor').value,
            bgOpacity: document.getElementById('subtitleBgOpacity').value
        };

        const language = document.getElementById('sourceLanguage').value;
        
        const response = await fetch(`/burn-subtitles/${currentFileId}?language=${language}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(style)
        });

        if (!response.ok) {
            throw new Error(await response.text());
        }

        const result = await response.json();
        
        // 显示带字幕的视频
        const subtitledVideo = document.getElementById('subtitledVideo');
        const subtitledVideoContainer = document.getElementById('subtitledVideoContainer');
        
        subtitledVideo.src = `/subtitled/${result.output_file}`;
        subtitledVideoContainer.style.display = 'block';
        
        showMessage('成功', '字幕烧录完成');
        
    } catch (error) {
        console.error('生成带字幕视频失败:', error);
        showMessage('错误', '生成带字幕视频失败: ' + error.message);
    } finally {
        hideLoading();
    }
};

// 下载字幕按钮处理
document.getElementById('saveSubtitlesBtn').onclick = async function() {
    if (!currentFileId) {
        showMessage('错误', '没有可用的字幕文件');
        return;
    }

    try {
        showLoading();
        
        // 构建下载URL
        let downloadUrl = `/export-subtitles/${currentFileId}`;
        const targetLang = document.getElementById('targetLanguage').value;
        if (targetLang) {
            downloadUrl += `?target_language=${targetLang}`;
        }

        const response = await fetch(downloadUrl);
        if (!response.ok) {
            throw new Error(await response.text());
        }

        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${currentFileId}_subtitles.srt`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);

        showMessage('成功', '字幕下载开始');
    } catch (error) {
        console.error('下载字幕失败:', error);
        showMessage('错误', '下载字幕失败: ' + error.message);
    } finally {
        hideLoading();
    }
};
