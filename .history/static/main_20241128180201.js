document.getElementById('generateSubtitlesBtn').onclick = async function() {
    if (!currentFileId) {
        showMessage('错误', '请先上传视频文件');
        return;
    }

    try {
        showLoading();
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

// 更新字幕文本的函数
async function updateSubtitleText(index, newText) {
    if (!currentFileId) {
        throw new Error('没有当前文件ID');
    }

    try {
        const response = await fetch('/update-subtitle', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                file_id: currentFileId,
                index: index,
                text: newText
            })
        });

        if (!response.ok) {
            const error = await response.text();
            throw new Error(error);
        }

        return await response.json();
    } catch (error) {
        console.error('更新字幕失败:', error);
        throw error;
    }
}

// 修改字幕编辑相关函数
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

// 修改 updateSubtitleEditor 函数中的字幕编辑部分
function updateSubtitleEditor(subtitles) {
    // ... 其他代码保持不变 ...
    
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
                    <button class="btn btn-sm btn-outline-info" onclick="startEditing(document.querySelector('.subtitle-item[data-index=\\'${i}\\'] .original-text'))">
                        <i class="fas fa-edit"></i>
                    </button>
                </div>
            </div>
            <div class="subtitle-text">
                <div class="original-text" data-index="${i}">${originalText}</div>
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
    
    // ... 其他代码保持不变 ...
}
