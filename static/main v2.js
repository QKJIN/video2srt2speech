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
