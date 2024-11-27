// 全局变量
let currentFileId = null;
let subtitles = null;  // 原始字幕
let translations = null;  // 翻译后的字幕

// 显示加载动画
function showLoading() {
    document.querySelector('.loading-overlay').style.display = 'flex';
}

// 隐藏加载动画
function hideLoading() {
    document.querySelector('.loading-overlay').style.display = 'none';
}

// 显示错误信息
function showError(message) {
    alert(message);
}

// 显示视频
function displayVideo(fileId) {
    const videoContainer = document.getElementById('videoContainer');
    const videoPlayer = document.getElementById('videoPlayer');
    const subtitleStylePanel = document.getElementById('subtitleStylePanel');

    if (!videoContainer || !videoPlayer) {
        console.error('找不到视频容器或播放器元素');
        return;
    }

    console.log('显示视频，文件ID:', fileId);
    videoContainer.style.display = 'block';
    videoPlayer.style.display = 'block';  
    videoPlayer.src = `/video/${fileId}`;
    currentFileId = fileId;

    // 设置视频播放器属性
    videoPlayer.controls = true;
    videoPlayer.controlsList = 'nodownload';
    videoPlayer.preload = 'metadata';
    videoPlayer.playsInline = true;

    videoPlayer.load();
    videoPlayer.play().catch(e => console.log('自动播放失败:', e));

    // 添加 seeking 和 seeked 事件监听器
    videoPlayer.addEventListener('seeking', () => {
        const subtitleOverlay = document.getElementById('subtitleOverlay');
        if (subtitleOverlay) {
            subtitleOverlay.style.display = 'none';
        }
    });

    videoPlayer.addEventListener('seeked', () => {
        const currentTime = videoPlayer.currentTime;
        const subtitleOverlay = document.getElementById('subtitleOverlay');
        
        if (!subtitles || !Array.isArray(subtitles) || !subtitleOverlay) {
            return;
        }
        
        const currentSubtitle = subtitles.find(
            subtitle => currentTime >= subtitle.start && 
                       currentTime <= (subtitle.start + subtitle.duration)
        );

        if (currentSubtitle) {
            let displayText = currentSubtitle.text;
            
            if (translations && translations[subtitles.indexOf(currentSubtitle)]) {
                const translation = translations[subtitles.indexOf(currentSubtitle)];
                displayText = `${currentSubtitle.text}\n${translation.text}`;
            }
            
            subtitleOverlay.textContent = displayText;
            subtitleOverlay.style.display = 'block';
        }
    });

    if (subtitleStylePanel) {
        subtitleStylePanel.style.display = 'block';
        updateSubtitleStyle();
    }
}

// 预览视频文件
function previewVideo(file) {
    const url = URL.createObjectURL(file);
    videoPlayer.src = url;
    videoContainer.style.display = 'block';
}

// 上传视频文件
async function uploadVideo(file) {
    try {
        showLoading();
        const formData = new FormData();
        formData.append('file', file);

        const response = await fetch('/upload', {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            throw new Error('上传失败');
        }

        const data = await response.json();
        displayVideo(data.file_id);
    } catch (error) {
        showError('上传视频失败: ' + error.message);
    } finally {
        hideLoading();
    }
}

// 事件监听器
videoFile.addEventListener('change', (e) => {
    if (e.target.files.length > 0) {
        const file = e.target.files[0];
        if (file.type.startsWith('video/')) {
            previewVideo(file);
        } else {
            showError('请选择视频文件');
            e.target.value = '';
        }
    }
});

uploadBtn.addEventListener('click', async () => {
    const file = videoFile.files[0];
    if (!file) {
        showError('请选择视频文件');
        return;
    }
    
    if (!file.type.startsWith('video/')) {
        showError('请选择视频文件');
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
            throw new Error('上传失败');
        }

        const data = await response.json();
        console.log('上传成功，文件ID:', data.file_id);
        
        displayVideo(data.file_id);

        await extractAudio(data.file_id);

    } catch (error) {
        console.error('上传错误:', error);
        showError('上传视频失败: ' + error.message);
    } finally {
        hideLoading();
    }
});

// 提取音频
async function extractAudio(fileId) {
    try {
        showLoading();
        const response = await fetch(`/extract-audio/${fileId}`, {
            method: 'POST'
        });

        if (!response.ok) {
            throw new Error('音频提取失败');
        }

        const data = await response.json();
        return data.audio_file;
    } catch (error) {
        showError('音频提取失败: ' + error.message);
        throw error;
    } finally {
        hideLoading();
    }
}

// 生成字幕
generateSubtitlesBtn.addEventListener('click', async () => {
    if (!currentFileId) {
        showError('请先上传视频');
        return;
    }

    try {
        showLoading();
        console.log('开始生成字幕...');

        // 先发送 HTTP 请求
        const response = await fetch(`/generate-subtitles/${currentFileId}?language=${sourceLanguage.value}`, {
            method: 'POST'
        });

        if (!response.ok) {
            const data = await response.json();
            throw new Error(data.detail || '生成字幕失败');
        }

        // 连接 WebSocket 接收进度更新
        connectWebSocket(currentFileId);

        const data = await response.json();
        console.log('生成字幕响应:', data);

        // 检查响应数据格式
        if (!data || !Array.isArray(data)) {
            console.error('无效的响应数据:', data);
            throw new Error('服务器返回的数据格式不正确');
        }

        // 更新字幕数据
        subtitles = data;
        translations = null;  // 清除之前的翻译
        console.log('更新字幕数据:', subtitles);
        
        // 显示字幕
        displaySubtitles(currentFileId, subtitles);
        
        // 启用翻译和生成语音按钮
        if (translateBtn) translateBtn.disabled = false;
        if (generateSpeechBtn) generateSpeechBtn.disabled = false;

        showMessage('字幕生成成功！', 'success');

    } catch (error) {
        console.error('生成字幕错误:', error);
        showError(error.message || '生成字幕失败，请重试');
    } finally {
        hideLoading();
        // 关闭 WebSocket 连接
        if (ws) {
            ws.close();
        }
    }
});

// 显示字幕
async function displaySubtitles(fileId, subtitleData, translationData = null) {
    try {
        const subtitleEditor = document.getElementById('subtitleEditor');
        if (!subtitleEditor) return;

        // 保存当前文件ID，移除扩展名
        currentFileId = fileId.includes('.') ? fileId.split('.')[0] : fileId;

        let html = '<div class="subtitle-list">';
        
        for (let i = 0; i < subtitleData.length; i++) {
            const subtitle = subtitleData[i];
            const translation = translationData && translationData[i] ? translationData[i] : null;

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
                        <span class="sequence-number" data-time="${subtitle.start}">${sequenceNumber}</span>
                        <span class="subtitle-time">${startTime} - ${endTime}</span>
                        <div class="subtitle-controls">
                            <button class="btn btn-sm btn-outline-primary edit-btn">编辑</button>
                            <button class="btn btn-sm btn-outline-success save-btn" style="display: none;">保存</button>
                            <button class="btn btn-sm btn-outline-secondary cancel-btn" style="display: none;">取消</button>
                        </div>
                    </div>
                    <div class="subtitle-text">
                        <div class="original-text" contenteditable="false">${originalText}</div>
                        ${translation ? `<div class="translated-text">${translation.text}</div>` : ''}
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
        
        console.log('生成的HTML长度:', html.length);
        subtitleEditor.innerHTML = html;
        
        // 添加样式
        const styleId = 'subtitle-styles';
        let style = document.getElementById(styleId);
        if (!style) {
            style = document.createElement('style');
            style.id = styleId;
            style.textContent = `
                .subtitle-list {
                    max-width: 800px;
                    margin: 0 auto;
                    padding: 20px;
                }
                .subtitle-item {
                    margin-bottom: 15px;
                    padding: 15px;
                    border: 1px solid #ddd;
                    border-radius: 8px;
                    background-color: #fff;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.05);
                }
                .subtitle-header {
                    display: flex;
                    align-items: center;
                    margin-bottom: 8px;
                }
                .sequence-number {
                    font-family: monospace;
                    font-size: 1.1em;
                    font-weight: bold;
                    color: #2196F3;
                    margin-right: 10px;
                    cursor: pointer;
                    padding: 2px 6px;
                    border-radius: 4px;
                    transition: background-color 0.2s;
                }
                .sequence-number:hover {
                    background-color: #e3f2fd;
                }
                .subtitle-time {
                    color: #666;
                    font-size: 0.9em;
                    font-family: monospace;
                }
                .subtitle-text {
                    line-height: 1.6;
                }
                .original-text {
                    margin-bottom: 8px;
                    font-size: 1.1em;
                }
                .translated-text {
                    color: #2196F3;
                    padding: 8px 15px;
                    background-color: #f8f9fa;
                    border-radius: 4px;
                    margin-top: 8px;
                }
                .audio-player {
                    margin-top: 10px;
                }
                .audio-player audio {
                    width: 100%;
                    margin-top: 5px;
                }
            `;
            document.head.appendChild(style);
        }
        
        // 存储字幕数据
        subtitles = subtitleData;
        translations = translationData;
        
        // 添加序号点击事件监听器
        document.querySelectorAll('.sequence-number').forEach(number => {
            number.addEventListener('click', function() {
                const time = parseFloat(this.dataset.time);
                const videoPlayer = document.getElementById('videoPlayer');
                if (videoPlayer) {
                    videoPlayer.currentTime = time;
                    videoPlayer.play().catch(e => console.log('播放失败:', e));
                }
            });
        });

        // 添加字幕编辑事件监听器
        document.querySelectorAll('.subtitle-item').forEach(item => {
            const editBtn = item.querySelector('.edit-btn');
            const saveBtn = item.querySelector('.save-btn');
            const cancelBtn = item.querySelector('.cancel-btn');
            const textDiv = item.querySelector('.original-text');
            let originalContent = textDiv.textContent;

            editBtn.addEventListener('click', () => {
                textDiv.contentEditable = true;
                textDiv.focus();
                editBtn.style.display = 'none';
                saveBtn.style.display = 'inline-block';
                cancelBtn.style.display = 'inline-block';
                textDiv.classList.add('editing');
            });

            saveBtn.addEventListener('click', async () => {
                const index = parseInt(item.dataset.index);
                const newText = textDiv.textContent.trim();
                
                try {
                    console.log('发送字幕更新请求:', {
                        file_id: currentFileId,
                        index: index,
                        text: newText
                    });

                    const response = await fetch('/update-subtitle', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({
                            file_id: currentFileId,
                            index: index,
                            text: newText
                        })
                    });

                    const result = await response.json();

                    if (!response.ok) {
                        throw new Error(result.detail || '保存失败');
                    }

                    // 更新成功
                    subtitles[index].text = newText;
                    textDiv.contentEditable = false;
                    editBtn.style.display = 'inline-block';
                    saveBtn.style.display = 'none';
                    cancelBtn.style.display = 'none';
                    textDiv.classList.remove('editing');
                    originalContent = newText;

                    // 显示成功消息
                    showMessage('字幕已更新', 'success');
                } catch (error) {
                    console.error('保存字幕失败:', error);
                    showMessage('保存字幕失败: ' + error.message, 'error');
                    
                    // 恢复原始内容
                    textDiv.textContent = originalContent;
                    textDiv.contentEditable = false;
                    editBtn.style.display = 'inline-block';
                    saveBtn.style.display = 'none';
                    cancelBtn.style.display = 'none';
                    textDiv.classList.remove('editing');
                }
            });

            cancelBtn.addEventListener('click', () => {
                textDiv.textContent = originalContent;
                textDiv.contentEditable = false;
                editBtn.style.display = 'inline-block';
                saveBtn.style.display = 'none';
                cancelBtn.style.display = 'none';
                textDiv.classList.remove('editing');
            });
        });
        
    } catch (error) {
        console.error('显示字幕时出错:', error);
        subtitleEditor.innerHTML = '<p>显示字幕时出错</p>';
    }
}

// 跳转到指定时间
function jumpToTime(time) {
    const videoPlayer = document.getElementById('videoPlayer');
    if (videoPlayer) {
        videoPlayer.currentTime = parseFloat(time);
        videoPlayer.play().catch(e => console.log('播放失败:', e));
    }
}

// 翻译字幕
translateBtn.addEventListener('click', async () => {
    if (!currentFileId) {
        showError('请先上传视频');
        return;
    }

    if (!subtitles) {
        showError('请先生成字幕');
        return;
    }

    try {
        showLoading();
        console.log('开始翻译字幕...');
        
        const sourceLanguageValue = sourceLanguage.value;
        const targetLanguageValue = targetLanguage.value;
        
        console.log(`源语言: ${sourceLanguageValue}, 目标语言: ${targetLanguageValue}`);
        
        const response = await fetch(`/translate-subtitles/${currentFileId}?source_language=${sourceLanguageValue}&target_language=${targetLanguageValue}`, {
            method: 'POST'
        });

        const data = await response.json();
        console.log('翻译响应:', data);

        if (!response.ok) {
            throw new Error(data.detail || '翻译失败');
        }

        // 检查响应数据格式
        if (!data || !data.subtitles || !Array.isArray(data.subtitles)) {
            console.error('无效的响应数据:', data);
            throw new Error('服务器返回的数据格式不正确');
        }

        // 更新翻译后的字幕
        translations = data.subtitles;
        console.log(`成功获取 ${data.total_count} 条翻译字幕`);
        
        // 显示原文和译文
        displaySubtitles(currentFileId, subtitles, translations);
        
        // 启用生成语音按钮
        if (generateSpeechBtn) {
            generateSpeechBtn.disabled = false;
        }
        
    } catch (error) {
        console.error('翻译错误:', error);
        showError('翻译字幕失败: ' + error.message);
    } finally {
        hideLoading();
    }
});

// 生成语音
generateSpeechBtn.addEventListener('click', async () => {
    if (!currentFileId || !subtitles) {
        showError('请先生成字幕');
        return;
    }

    if (!targetLanguage.value) {
        showError('请选择目标语言');
        return;
    }

    if (!voiceSelect.value) {
        showError('请选择语音');
        return;
    }

    try {
        showLoading();
        console.log('开始生成语音...');
        
        // 连接WebSocket以接收实时进度
        connectWebSocket(currentFileId);
        
        const response = await fetch(`/generate-speech/${currentFileId}?target_language=${targetLanguage.value}&voice_name=${voiceSelect.value}`, {
            method: 'POST'
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.detail || '生成语音失败');
        }

        const data = await response.json();
        console.log('生成语音响应:', data);

        if (data && data.status === 'success' && Array.isArray(data.audio_files)) {
            // 更新字幕音频播放器
            updateSubtitleAudio(data.audio_files);
            // 启用合并音频按钮
            if (mergeAudioBtn) mergeAudioBtn.disabled = false;
            
            // 显示成功消息
            showMessage(`成功生成 ${data.total_count} 个音频文件`, 'success');
        } else {
            throw new Error('无效的音频文件数据');
        }

    } catch (error) {
        console.error('生成语音错误:', error);
        showError('生成语音失败: ' + error.message);
    } finally {
        hideLoading();
    }
});

// 合并音频
mergeAudioBtn.addEventListener('click', async () => {
    if (!currentFileId) {
        showError('请先生成语音');
        return;
    }

    try {
        showLoading();
        const response = await fetch(`/merge-audio/${currentFileId}?target_language=${targetLanguage.value}`, {
            method: 'POST'
        });

        if (!response.ok) {
            throw new Error('合并音频失败');
        }

        const data = await response.json();
        if (data.merged_file) {
            displayMergedAudio(data.merged_file);
        } else {
            throw new Error('未找到合并后的音频文件');
        }
    } catch (error) {
        showError('合并音频失败: ' + error.message);
    } finally {
        hideLoading();
    }
});

// 生成带字幕的视频
burnSubtitlesBtn.addEventListener('click', async () => {
    if (!currentFileId || !subtitles) {
        showError('请先生成字幕');
        return;
    }

    try {
        showLoading();
        const subtitleStyle = {
            fontSize: parseInt(subtitleFontSize.value),
            fontColor: subtitleColor.value,
            backgroundColor: `${subtitleBgColor.value}${Math.round(subtitleBgOpacity.value * 255).toString(16).padStart(2, '0')}`,
            webkitTextStroke: `${subtitleStrokeWidth.value}px ${subtitleStrokeColor.value}`,
            textStroke: `${subtitleStrokeWidth.value}px ${subtitleStrokeColor.value}`,
            padding: '0.2em 0.5em',
            borderRadius: '4px',
            maxWidth: '90%',
            margin: '0 auto',
            whiteSpace: 'pre-wrap',
            wordWrap: 'break-word'
        };

        const response = await fetch(`/burn-subtitles/${currentFileId}?language=${targetLanguage.value}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ style: subtitleStyle })
        });

        if (!response.ok) {
            throw new Error('生成带字幕视频失败');
        }

        const data = await response.json();
        displaySubtitledVideo(data.subtitled_video);
    } catch (error) {
        showError('生成带字幕视频失败: ' + error.message);
    } finally {
        hideLoading();
    }
});

// 保存字幕
saveSubtitlesBtn.addEventListener('click', async () => {
    if (!currentFileId || !subtitles) {
        showError('没有可保存的字幕');
        return;
    }

    try {
        showLoading();
        const response = await fetch(`/update-subtitles/${currentFileId}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                subtitles: subtitles
            })
        });

        if (!response.ok) {
            throw new Error('保存字幕失败');
        }

        showError('字幕保存成功');
    } catch (error) {
        showError('保存字幕失败: ' + error.message);
    } finally {
        hideLoading();
    }
});

// 更新字幕音频
function updateSubtitleAudio(audioFiles) {
    console.log('更新字幕音频:', audioFiles);
    if (!Array.isArray(audioFiles) || audioFiles.length === 0) {
        console.error('无效的音频文件数组');
        return;
    }

    const subtitleItems = document.querySelectorAll('.subtitle-item');
    if (!subtitleItems || subtitleItems.length === 0) {
        console.error('未找到字幕元素');
        return;
    }

    console.log(`找到 ${subtitleItems.length} 个字幕元素`);

    audioFiles.forEach((audioFile, index) => {
        if (!audioFile || !audioFile.file) {
            console.error(`无效的音频文件数据 [${index}]:`, audioFile);
            return;
        }

        const subtitleItem = subtitleItems[index];
        if (!subtitleItem) {
            console.error(`未找到索引 ${index} 的字幕元素`);
            return;
        }

        const audioPlayer = subtitleItem.querySelector('.audio-player');
        const audio = subtitleItem.querySelector('.subtitle-audio');
        if (!audioPlayer || !audio) {
            console.error(`未找到索引 ${index} 的音频播放器元素`);
            return;
        }

        try {
            // 使用后端返回的音频文件路径，添加时间戳防止缓存
            const timestamp = new Date().getTime();
            const audioPath = `/audio/${audioFile.file}?t=${timestamp}`;
            console.log(`设置音频源 [${index}]: ${audioPath}`);
            
            const source = audio.querySelector('source');
            if (!source) {
                console.error(`未找到索引 ${index} 的音频源元素`);
                return;
            }

            source.src = audioPath;
            source.type = 'audio/wav';
            audio.load(); // 重新加载音频源
            audioPlayer.style.display = 'block';
            
            console.log(`成功更新音频 [${index}]: ${audioPath}`);
        } catch (error) {
            console.error(`更新音频 [${index}] 时出错:`, error);
        }
    });

    console.log('音频更新完成');
}

// 显示音频文件
function displayAudioFiles(audioFiles) {
    audioFiles.forEach((audio, index) => {
        const audioDiv = document.getElementById(`audio-${index}`);
        if (audioDiv) {
            const audioPlayer = document.createElement('audio');
            audioPlayer.controls = true;
            audioPlayer.src = `/audio/${audio.file}`;
            audioDiv.innerHTML = ''; 
            audioDiv.appendChild(audioPlayer);
        }
    });
}

// 显示合并后的音频
function displayMergedAudio(audioFile) {
    const container = document.getElementById('mergedAudioContainer');
    const audio = document.getElementById('mergedAudio');
    
    audio.src = `/merged/${audioFile}?t=${new Date().getTime()}`;
    
    audio.addEventListener('loadeddata', () => {
        console.log('音频加载成功，时长:', audio.duration);
    });
    
    audio.addEventListener('error', (e) => {
        console.error('音频加载失败:', e);
        showError('音频加载失败，请重试');
    });
    
    container.style.display = 'block';
    
    container.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// 显示带字幕的视频
function displaySubtitledVideo(videoFile) {
    const container = document.getElementById('subtitledVideoContainer');
    const video = document.getElementById('subtitledVideo');
    
    video.src = `/subtitled/${videoFile}?t=${new Date().getTime()}`;
    
    video.addEventListener('loadeddata', () => {
        console.log('视频加载成功，时长:', video.duration);
    });
    
    video.addEventListener('error', (e) => {
        console.error('视频加载失败:', e);
        showError('视频加载失败，请重试');
    });
    
    container.style.display = 'block';
    
    container.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// 格式化时间
function formatTime(seconds) {
    if (isNaN(seconds)) {
        console.error('无效的时间值:', seconds);
        return '00:00';
    }
    
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = Math.floor(seconds % 60);
    return `${minutes.toString().padStart(2, '0')}:${remainingSeconds.toString().padStart(2, '0')}`;
}

// 加载目标语言的可用语音
targetLanguage.addEventListener('change', async () => {
    try {
        const response = await fetch(`/available-voices/${targetLanguage.value}`);
        if (!response.ok) {
            throw new Error('获取语音列表失败');
        }
        const data = await response.json();
        
        const voiceSelect = document.getElementById('voiceSelect');
        voiceSelect.innerHTML = '<option value="">选择语音...</option>';
        
        data.voices.forEach(voice => {
            const option = document.createElement('option');
            option.value = voice.name;
            option.textContent = `${voice.description}`;
            voiceSelect.appendChild(option);
        });
        
        document.getElementById('generateSpeechBtn').disabled = false;
    } catch (error) {
        showError('加载语音列表失败: ' + error.message);
        const voiceSelect = document.getElementById('voiceSelect');
        voiceSelect.innerHTML = '<option value="">加载失败</option>';
        document.getElementById('generateSpeechBtn').disabled = true;
    }
});

// 显示字幕文本
function appendSubtitle(text) {
    const subtitleText = document.getElementById('subtitleText');
    if (subtitleText) {
        subtitleText.textContent = text;
    }
}

// 更新视频播放时的字幕显示
videoPlayer.addEventListener('timeupdate', () => {
    const currentTime = videoPlayer.currentTime;
    const subtitleOverlay = document.getElementById('subtitleOverlay');
    
    if (!subtitles || !Array.isArray(subtitles) || !subtitleOverlay) {
        return;
    }
    
    try {
        const currentSubtitle = subtitles.find(
            subtitle => currentTime >= subtitle.start && 
                       currentTime <= (subtitle.start + subtitle.duration)
        );

        if (currentSubtitle) {
            let displayText = currentSubtitle.text;
            
            // 如果有翻译，显示双语字幕
            if (translations && translations[subtitles.indexOf(currentSubtitle)]) {
                const translation = translations[subtitles.indexOf(currentSubtitle)];
                displayText = `${currentSubtitle.text}\n${translation.text}`;
            }
            
            subtitleOverlay.textContent = displayText;
            subtitleOverlay.style.display = 'block';
        } else {
            subtitleOverlay.style.display = 'none';
        }
    } catch (error) {
        console.error('显示字幕时出错:', error);
        subtitleOverlay.style.display = 'none';
    }
});

// 监听样式控制变化
[subtitleFontSize, subtitleColor, subtitleBgColor, subtitleBgOpacity, subtitleStrokeColor, subtitleStrokeWidth].forEach(
    control => {
        if (control) {
            control.addEventListener('input', updateSubtitleStyle);
        }
    }
);

// 更新字幕样式
function updateSubtitleStyle() {
    const style = {
        fontSize: `${subtitleFontSize.value}px`,
        color: subtitleColor.value,
        backgroundColor: `${subtitleBgColor.value}${Math.round(subtitleBgOpacity.value * 255).toString(16).padStart(2, '0')}`,
        webkitTextStroke: `${subtitleStrokeWidth.value}px ${subtitleStrokeColor.value}`,
        textStroke: `${subtitleStrokeWidth.value}px ${subtitleStrokeColor.value}`,
        padding: '0.2em 0.5em',
        borderRadius: '4px',
        maxWidth: '90%',
        margin: '0 auto',
        whiteSpace: 'pre-wrap',
        wordWrap: 'break-word'
    };

    Object.assign(subtitleOverlay.style, style);
}

// WebSocket连接
let ws;
let wsKeepAliveInterval;
let wsReconnectAttempts = 0;
let isTaskCompleted = false;  // 任务完成标志
let isClosing = false;  // 主动关闭标志

const MAX_RECONNECT_ATTEMPTS = 3;  // 最大重连次数
const RECONNECT_DELAY = 1000;  // 基础重连延迟（毫秒）

function connectWebSocket(fileId) {
    // 重置任务状态
    isTaskCompleted = false;
    isClosing = false;

    // 如果已经存在连接且连接是打开的，不需要重新连接
    if (ws && ws.readyState === WebSocket.OPEN) {
        console.log('WebSocket连接已存在且处于打开状态');
        return;
    }

    // 如果存在旧连接，先清理
    if (ws) {
        console.log('清理现有WebSocket连接');
        clearInterval(wsKeepAliveInterval);
        if (ws.readyState === WebSocket.OPEN) {
            isClosing = true;  // 标记正在关闭
            ws.close();
        }
        ws = null;
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/${fileId}`;
    
    try {
        console.log('正在建立新的WebSocket连接...');
        ws = new WebSocket(wsUrl);

        ws.onopen = () => {
            console.log('WebSocket连接已建立');
            wsReconnectAttempts = 0;  // 重置重连次数
            // 开始定时发送保活消息
            wsKeepAliveInterval = setInterval(() => {
                if (ws && ws.readyState === WebSocket.OPEN && !isTaskCompleted) {
                    ws.send('ping');
                }
            }, 30000);
        };

        ws.onmessage = (event) => {
            try {
                if (event.data === 'pong') {
                    console.log('收到保活消息');
                    return;
                }

                const data = JSON.parse(event.data);
                console.log('收到消息:', data);

                if (data.type === 'progress') {
                    updateProgress(data.progress);
                } else if (data.type === 'complete') {
                    console.log('收到完成消息');
                    updateProgress(100);
                    isTaskCompleted = true;  // 标记任务完成
                    closeWebSocketGracefully();  // 优雅关闭连接
                } else if (data.type === 'error') {
                    console.error('收到错误消息:', data.error);
                    showError(data.error);
                    isTaskCompleted = true;  // 错误也视为任务完成
                    closeWebSocketGracefully();
                }
            } catch (error) {
                console.error('处理WebSocket消息时出错:', error);
            }
        };

        ws.onclose = (event) => {
            console.log('WebSocket连接已关闭', event);
            clearInterval(wsKeepAliveInterval);

            // 只有在任务未完成且不是主动关闭的情况下才尝试重连
            if (!isTaskCompleted && !isClosing && wsReconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
                console.log(`尝试重新连接 (${wsReconnectAttempts + 1}/${MAX_RECONNECT_ATTEMPTS})`);
                wsReconnectAttempts++;
                setTimeout(() => connectWebSocket(fileId), 
                    RECONNECT_DELAY * Math.pow(2, wsReconnectAttempts - 1));
            }
        };

        ws.onerror = (error) => {
            console.error('WebSocket错误:', error);
            // 错误发生时不立即关闭，让 onclose 处理重连逻辑
        };

    } catch (error) {
        console.error('建立WebSocket连接时出错:', error);
    }
}

function closeWebSocketGracefully() {
    if (!ws) return;
    
    console.log('正在优雅关闭WebSocket连接...');
    isClosing = true;  // 标记正在主动关闭
    clearInterval(wsKeepAliveInterval);
    
    if (ws.readyState === WebSocket.OPEN) {
        ws.close();
    }
    ws = null;
}

// 更新进度条
function updateProgress(progress) {
    const progressBar = document.getElementById('progressBar');
    if (progressBar) {
        progressBar.style.width = `${progress}%`;
        progressBar.setAttribute('aria-valuenow', progress);
        progressBar.textContent = `${progress}%`;
    }
}

// 显示字幕文本
function appendSubtitle(text) {
    const subtitleText = document.getElementById('subtitleText');
    if (subtitleText) {
        subtitleText.textContent = text;
    }
}

// 显示消息
function showMessage(message, type = 'info') {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${type}`;
    messageDiv.textContent = message;
    document.body.appendChild(messageDiv);

    // 添加样式
    messageDiv.style.position = 'fixed';
    messageDiv.style.top = '20px';
    messageDiv.style.right = '20px';
    messageDiv.style.padding = '10px 20px';
    messageDiv.style.borderRadius = '4px';
    messageDiv.style.zIndex = '9999';
    messageDiv.style.opacity = '0';
    messageDiv.style.transition = 'opacity 0.3s ease-in-out';

    // 根据类型设置颜色
    if (type === 'success') {
        messageDiv.style.backgroundColor = '#4caf50';
        messageDiv.style.color = 'white';
    } else if (type === 'error') {
        messageDiv.style.backgroundColor = '#f44336';
        messageDiv.style.color = 'white';
    } else {
        messageDiv.style.backgroundColor = '#2196f3';
        messageDiv.style.color = 'white';
    }

    // 显示消息
    setTimeout(() => {
        messageDiv.style.opacity = '1';
    }, 100);

    // 3秒后淡出
    setTimeout(() => {
        messageDiv.style.opacity = '0';
        setTimeout(() => {
            document.body.removeChild(messageDiv);
        }, 300);
    }, 3000);
}
