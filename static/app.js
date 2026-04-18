let latestData = null;
let currentUrl = null;
let isIngesting = false;
let currentQueryController = null;
let currentOverviewController = null;
let latestHistoryArchive = [];

const SUMMARY_LOADING_TEXT = 'AI 编辑正在努力生成今日简报，这可能需要几十秒...';

const ICONS = {
    external: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14L21 3"/></svg>',
    ask: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>',
    like: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/></svg>',
    dislike: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm7-13h3a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-3"/></svg>'
};

document.addEventListener('DOMContentLoaded', () => {
    fetchSummary();
    setupRagPanel();
    setupHistoryPanel();
});

function clearElement(element) {
    if (!element) return;
    while (element.firstChild) {
        element.removeChild(element.firstChild);
    }
}

function showLoadingState(message = SUMMARY_LOADING_TEXT) {
    const loadingState = document.getElementById('loading-state');
    clearElement(loadingState);
    loadingState.style.display = 'flex';

    const spinner = document.createElement('div');
    spinner.className = 'spinner';

    const text = document.createElement('p');
    text.textContent = message;

    loadingState.appendChild(spinner);
    loadingState.appendChild(text);
}

function showErrorState(message, retryHandler) {
    const loadingState = document.getElementById('loading-state');
    clearElement(loadingState);
    loadingState.style.display = 'flex';

    const box = document.createElement('div');
    box.className = 'error-message';

    const text = document.createElement('p');
    text.textContent = `获取简报失败: ${message}`;

    const retryButton = document.createElement('button');
    retryButton.className = 'retry-btn';
    retryButton.type = 'button';
    retryButton.textContent = '重试';
    retryButton.addEventListener('click', retryHandler);

    box.appendChild(text);
    box.appendChild(retryButton);
    loadingState.appendChild(box);
}

function computeSourceStats(items) {
    const stats = {};
    for (const item of items || []) {
        const source = item.source || '未知来源';
        stats[source] = (stats[source] || 0) + 1;
    }
    return stats;
}

async function fetchSummary(force = false, date = null) {
    let url = '/api/v1/summary';
    const params = [];
    if (force) params.push('force=true');
    if (date) params.push(`date=${encodeURIComponent(date)}`);
    
    if (params.length > 0) {
        url += '?' + params.join('&');
    }
    
    await fetchSummaryWithUrl(url);
}

async function fetchSummaryWithUrl(url) {
    const loadingState = document.getElementById('loading-state');
    const contentState = document.getElementById('content-state');
    const dateHeader = document.getElementById('summary-date');
    const overviewText = document.getElementById('summary-overview');
    const refreshBtn = document.getElementById('refresh-btn');

    try {
        showLoadingState();
        contentState.style.display = 'none';
        if (refreshBtn) refreshBtn.style.display = 'none';

        const response = await fetch(url);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();
        data.source_stats = data.source_stats || computeSourceStats(data.top_news || []);
        latestData = data;

        const dateObj = new Date(data.date);
        const options = { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' };
        dateHeader.textContent = dateObj.toLocaleDateString('zh-CN', options);
        overviewText.textContent = data.overview || '';

        renderHome();
        renderRecReport();

        loadingState.style.display = 'none';
        contentState.style.display = 'block';
        if (refreshBtn) refreshBtn.style.display = 'inline-flex';
    } catch (error) {
        console.error('Failed to fetch summary:', error);
        showErrorState(error.message, () => fetchSummary());
    }
}

function renderHome() {
    const container = document.getElementById('news-container');
    const overviewSection = document.querySelector('.overview-section');
    const viewControls = document.getElementById('view-controls');
    const statsContainer = document.getElementById('stats-container');
    const categoryNav = document.getElementById('category-nav');

    if (!latestData) return;

    clearElement(container);
    container.className = 'news-grid dashboard';
    overviewSection.style.display = 'block';
    statsContainer.style.display = 'flex';
    categoryNav.style.display = 'flex';
    viewControls.style.display = 'none';

    renderSourceStats(latestData.source_stats || computeSourceStats(latestData.top_news));
    renderCategoryNav();

    (latestData.top_news || []).forEach((newsItem, index) => {
        container.appendChild(createNewsCard(newsItem, index));
    });

    window.scrollTo({ top: 0, behavior: 'smooth' });
}

function applyFeedbackState(likeButton, dislikeButton, sentiment) {
    if (!likeButton || !dislikeButton) return;
    likeButton.classList.toggle('active', sentiment === 1);
    dislikeButton.classList.toggle('active', sentiment === -1);
}

function updateFeedbackStateInData(url, sentiment) {
    if (!latestData || !Array.isArray(latestData.top_news)) return;
    const storedSentiment = sentiment === 1 || sentiment === -1 ? sentiment : null;

    for (const item of latestData.top_news) {
        if (item.original_link === url) {
            item.feedback_sentiment = storedSentiment;
        }
    }
}

function renderCategoryNav() {
    const nav = document.getElementById('category-nav');
    clearElement(nav);

    if (!latestData || !latestData.top_news) return;

    const counts = latestData.top_news.reduce((acc, item) => {
        const category = item.category || '未分类';
        acc[category] = (acc[category] || 0) + 1;
        return acc;
    }, {});

    Object.keys(counts).sort().forEach((category) => {
        const entry = document.createElement('button');
        entry.type = 'button';
        entry.className = 'category-entry';
        entry.addEventListener('click', () => renderCategoryDetail(category));

        const label = document.createElement('span');
        label.textContent = category;

        const count = document.createElement('span');
        count.className = 'category-entry__count';
        count.textContent = String(counts[category]);

        entry.appendChild(label);
        entry.appendChild(count);
        nav.appendChild(entry);
    });
}

function createNewsCard(newsItem, index) {
    const safeLink = isSafeHttpUrlString(newsItem.original_link);
    const card = document.createElement('article');
    card.className = 'news-card fade-in';
    card.style.animationDelay = `${index * 0.05}s`;

    const header = document.createElement('div');
    header.className = 'card-header';

    const meta = document.createElement('div');
    meta.className = 'card-meta card-meta--split';

    const sourceLabel = document.createElement('span');
    sourceLabel.className = 'source-label';
    sourceLabel.textContent = newsItem.source || '未知来源';

    const categoryLabel = document.createElement('span');
    categoryLabel.className = 'category-badge';
    categoryLabel.textContent = newsItem.category || '未分类';

    meta.appendChild(sourceLabel);
    meta.appendChild(categoryLabel);

    // Personalized recommendation badge
    if (typeof newsItem.persona_score === 'number' && newsItem.persona_score > 0.5) {
        const recBadge = document.createElement('span');
        recBadge.className = 'persona-rec-badge';
        recBadge.textContent = '🎯 为你推荐';
        meta.appendChild(recBadge);
    }

    const headline = document.createElement('h2');
    headline.textContent = newsItem.headline || '未命名资讯';

    header.appendChild(meta);
    header.appendChild(headline);

    const body = document.createElement('div');
    body.className = 'card-body';

    const pointsList = document.createElement('ul');
    for (const point of newsItem.key_points || []) {
        const item = document.createElement('li');
        item.textContent = point;
        pointsList.appendChild(item);
    }
    body.appendChild(pointsList);

    if (Array.isArray(newsItem.tags) && newsItem.tags.length > 0) {
        const tagsContainer = document.createElement('div');
        tagsContainer.className = 'tags-container';
        for (const tag of newsItem.tags) {
            const badge = document.createElement('span');
            badge.className = 'tag-badge';
            badge.textContent = tag;
            tagsContainer.appendChild(badge);
        }
        body.appendChild(tagsContainer);
    }

    const footer = document.createElement('div');
    footer.className = 'card-footer';

    const readMore = document.createElement('a');
    readMore.className = 'read-more';
    readMore.textContent = '阅读原文';
    if (safeLink) {
        readMore.href = newsItem.original_link;
        readMore.target = '_blank';
        readMore.rel = 'noopener noreferrer';
    } else {
        readMore.href = '#';
        readMore.classList.add('is-disabled');
        readMore.addEventListener('click', (event) => event.preventDefault());
    }
    appendStaticIcon(readMore, ICONS.external);

    const actions = document.createElement('div');
    actions.className = 'card-actions';

    const feedbackContainer = document.createElement('div');
    feedbackContainer.className = 'feedback-container';

    const likeButton = document.createElement('button');
    likeButton.type = 'button';
    likeButton.className = 'feedback-btn like';
    likeButton.title = '感兴趣';
    likeButton.disabled = !safeLink;
    likeButton.innerHTML = ICONS.like;
    likeButton.addEventListener('click', () => sendFeedback(likeButton, newsItem.original_link, 1));

    const dislikeButton = document.createElement('button');
    dislikeButton.type = 'button';
    dislikeButton.className = 'feedback-btn dislike';
    dislikeButton.title = '不感兴趣';
    dislikeButton.disabled = !safeLink;
    dislikeButton.innerHTML = ICONS.dislike;
    dislikeButton.addEventListener('click', () => sendFeedback(dislikeButton, newsItem.original_link, -1));

    applyFeedbackState(likeButton, dislikeButton, newsItem.feedback_sentiment || 0);

    feedbackContainer.appendChild(likeButton);
    feedbackContainer.appendChild(dislikeButton);

    const askButton = document.createElement('button');
    askButton.type = 'button';
    askButton.className = 'ask-btn';
    askButton.disabled = !safeLink;
    askButton.addEventListener('click', () => openRagPanel(newsItem.original_link, newsItem.headline || '未命名资讯'));
    appendStaticIcon(askButton, ICONS.ask);
    askButton.appendChild(document.createTextNode('深度追问'));

    actions.appendChild(feedbackContainer);
    actions.appendChild(askButton);

    footer.appendChild(readMore);
    footer.appendChild(actions);

    card.appendChild(header);
    card.appendChild(body);
    card.appendChild(footer);

    return card;
}

function renderCategoryDetail(categoryName) {
    const container = document.getElementById('news-container');
    const overviewSection = document.querySelector('.overview-section');
    const viewControls = document.getElementById('view-controls');
    const statsContainer = document.getElementById('stats-container');
    const categoryNav = document.getElementById('category-nav');

    clearElement(container);
    container.className = 'news-grid';
    overviewSection.style.display = 'none';
    statsContainer.style.display = 'none';
    categoryNav.style.display = 'none';
    viewControls.style.display = 'flex';

    const detailHeader = document.createElement('div');
    detailHeader.className = 'category-header';

    const title = document.createElement('span');
    title.className = 'category-title';
    title.textContent = categoryName;

    const line = document.createElement('div');
    line.className = 'category-line';

    detailHeader.appendChild(title);
    detailHeader.appendChild(line);
    container.appendChild(detailHeader);

    (latestData.top_news || [])
        .filter((item) => (item.category || '未分类') === categoryName)
        .forEach((newsItem, index) => {
            container.appendChild(createNewsCard(newsItem, index));
        });

    window.scrollTo({ top: 0, behavior: 'smooth' });
}

function showDashboard() {
    renderHome();
}

function renderSourceStats(stats) {
    const statsContainer = document.getElementById('stats-container');
    clearElement(statsContainer);

    if (!stats || Object.keys(stats).length === 0) {
        statsContainer.style.display = 'none';
        return;
    }

    const label = document.createElement('div');
    label.className = 'stats-label';
    label.textContent = '来源分布 (今日生成)';
    statsContainer.appendChild(label);

    Object.keys(stats).sort().forEach((source) => {
        const pill = document.createElement('div');
        pill.className = 'source-pill';

        const name = document.createElement('span');
        name.className = 'source-pill__name';
        name.textContent = source;

        const count = document.createElement('span');
        count.className = 'source-pill__count';
        count.textContent = String(stats[source]);

        pill.appendChild(name);
        pill.appendChild(count);
        statsContainer.appendChild(pill);
    });
}

function openRefreshModal() {
    document.getElementById('refresh-modal').classList.add('active');
    document.getElementById('refresh-preference').value = '';
    document.getElementById('save-preference-chk').checked = false;
}

function closeRefreshModal() {
    document.getElementById('refresh-modal').classList.remove('active');
}

function confirmForceRefresh() {
    const preference = document.getElementById('refresh-preference').value.trim();
    const saveIt = document.getElementById('save-preference-chk').checked;
    closeRefreshModal();

    let url = '/api/v1/summary?force=true';
    if (preference) {
        url += `&preference=${encodeURIComponent(preference)}`;
        if (saveIt) {
            url += '&save_preference=true';
        }
    }

    fetchSummaryWithUrl(url);
}

function togglePersonaPanel() {
    const panel = document.getElementById('persona-panel');
    panel.classList.toggle('active');
    if (panel.classList.contains('active')) {
        loadPersonaData();
    }
}

async function loadPersonaData() {
    try {
        const response = await fetch('/api/v1/persona');
        if (response.ok) {
            renderPersonaInstructions(await response.json());
        }
    } catch (error) {
        console.error('Failed to load persona data:', error);
    }
}

function renderPersonaInstructions(personas) {
    const container = document.getElementById('persona-instructions');
    clearElement(container);

    if (!personas || personas.length === 0) {
        const empty = document.createElement('p');
        empty.className = 'empty-state-text';
        empty.textContent = '暂无长期偏好。重新生成时勾选“设为长期兴趣”即可添加。';
        container.appendChild(empty);
        return;
    }

    for (const persona of personas) {
        const item = document.createElement('div');
        item.className = 'persona-item';

        const text = document.createElement('span');
        text.textContent = persona.content;

        const removeButton = document.createElement('button');
        removeButton.type = 'button';
        removeButton.className = 'remove-btn';
        removeButton.title = '删除此偏好';
        removeButton.setAttribute('aria-label', '删除此偏好');
        removeButton.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
        removeButton.addEventListener('click', () => removePersona(persona.id));

        item.appendChild(text);
        item.appendChild(removeButton);
        container.appendChild(item);
    }
}

function renderRecReport() {
    const reportContainer = document.getElementById('rec-report-container');
    if (!latestData || !latestData.recommendation_report || Object.keys(latestData.recommendation_report).length === 0) {
        if (reportContainer) reportContainer.style.display = 'none';
        return;
    }

    const report = latestData.recommendation_report;
    const totalEl = document.getElementById('stat-total');
    const passedEl = document.getElementById('stat-passed');
    const samplesList = document.getElementById('excluded-samples');

    if (reportContainer) reportContainer.style.display = 'block';
    if (totalEl) totalEl.textContent = report.total_fetched || 0;
    if (passedEl) passedEl.textContent = report.passed_count || (latestData.top_news ? latestData.top_news.length : 0);

    clearElement(samplesList);
    if (Array.isArray(report.excluded_samples)) {
        report.excluded_samples.forEach(title => {
            const li = document.createElement('li');
            li.textContent = title;
            samplesList.appendChild(li);
        });
    }
}

async function removePersona(id) {
    try {
        const response = await fetch(`/api/v1/persona/${id}`, { method: 'DELETE' });
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        await loadPersonaData();
    } catch (error) {
        console.error('Failed to delete persona:', error);
    }
}

async function sendFeedback(buttonElement, url, sentiment) {
    const container = buttonElement.closest('.feedback-container');
    const likeButton = container ? container.querySelector('.feedback-btn.like') : null;
    const dislikeButton = container ? container.querySelector('.feedback-btn.dislike') : null;

    if (!likeButton || !dislikeButton) {
        return;
    }

    const currentSentiment = likeButton.classList.contains('active')
        ? 1
        : dislikeButton.classList.contains('active')
            ? -1
            : 0;
    const nextSentiment = currentSentiment === sentiment ? 0 : sentiment;

    applyFeedbackState(likeButton, dislikeButton, nextSentiment);
    likeButton.disabled = true;
    dislikeButton.disabled = true;

    try {
        const response = await fetch('/api/v1/rag/feedback', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url, sentiment: nextSentiment })
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        updateFeedbackStateInData(url, nextSentiment);
    } catch (error) {
        console.error('Failed to submit feedback:', error);
        applyFeedbackState(likeButton, dislikeButton, currentSentiment);
    } finally {
        const disabled = !isSafeHttpUrlString(url);
        likeButton.disabled = disabled;
        dislikeButton.disabled = disabled;
    }
}

function setupHistoryPanel() {
    const historyBtn = document.getElementById('history-btn');
    if (historyBtn) {
        // Just ensuring it's there
    }
}

function formatSummaryDate(date) {
    const dateObj = new Date(`${date}T00:00:00`);
    return dateObj.toLocaleDateString('zh-CN', {
        month: 'long',
        day: 'numeric',
        weekday: 'short'
    });
}

function createArchiveMeta(text, className) {
    const item = document.createElement('span');
    item.className = className;
    item.textContent = text;
    return item;
}

function renderHistoryInsights(weeklyRecap) {
    const statsContainer = document.getElementById('magazine-recap-stats');

    if (!statsContainer) return;

    clearElement(statsContainer);

    if (!weeklyRecap) {
        statsContainer.innerHTML = '<p class="magazine-placeholder">暂无近期的汇总数据。</p>';
        return;
    }

    const recapCard = document.createElement('div');
    recapCard.className = 'history-recap-card';
    recapCard.style.maxWidth = '100%'; 
    recapCard.style.margin = '0 auto';

    const badge = document.createElement('span');
    badge.className = 'history-recap-badge';
    badge.textContent = '本周概览';

    const title = document.createElement('h4');
    title.className = 'history-recap-title';
    title.textContent = `${formatSummaryDate(weeklyRecap.window_start)} - ${formatSummaryDate(weeklyRecap.window_end)}`;

    const summaryStats = document.createElement('div');
    summaryStats.className = 'history-insight-stats';
    summaryStats.appendChild(createArchiveMeta(`${weeklyRecap.days_covered || 0} 天`, 'history-chip history-chip--accent'));
    summaryStats.appendChild(createArchiveMeta(`${weeklyRecap.total_news || 0} 条资讯`, 'history-chip history-chip--accent'));

    (weeklyRecap.top_categories || []).slice(0, 3).forEach((item) => {
        summaryStats.appendChild(createArchiveMeta(`${item.name} × ${item.count}`, 'history-chip'));
    });

    (weeklyRecap.top_sources || []).slice(0, 2).forEach((item) => {
        summaryStats.appendChild(createArchiveMeta(`${item.name} × ${item.count}`, 'history-chip history-chip--source'));
    });

    const recapText = document.createElement('p');
    recapText.className = 'history-recap-text';
    recapText.textContent = weeklyRecap.recap_text || '本周已有多期简报，可快速查阅深度分析。';

    recapCard.appendChild(badge);
    recapCard.appendChild(title);
    recapCard.appendChild(summaryStats);
    recapCard.appendChild(recapText);
    
    statsContainer.appendChild(recapCard);
}

async function triggerWeeklyInsight() {
    const content = document.getElementById('weekly-insight-content');
    const genBtn = document.getElementById('gen-weekly-btn');

    if (!content || !genBtn) return;

    genBtn.style.opacity = '0.5';
    genBtn.disabled = true;
    genBtn.textContent = '⚡ 深度复盘中...';
    
    clearElement(content);
    loadingMsg.className = 'generating-text';
    loadingMsg.id = 'insight-loading-status';
    loadingMsg.textContent = 'Wired 主编正在策划本周特稿';
    content.appendChild(loadingMsg);

    const statuses = [
        '正在分析本周技术趋势',
        '正在梳理行业权力版图',
        '正在撰写叙事导读',
        '主编正在进行最后润色'
    ];
    
    let statusIndex = 0;
    const interval = setInterval(() => {
        if (statusIndex < statuses.length) {
            loadingMsg.textContent = statuses[statusIndex];
            statusIndex++;
        }
    }, 2500);

    try {
        const response = await fetch('/api/v1/history/weekly_insight');
        clearInterval(interval);
        
        if (!response.ok) throw new Error('Generation failed');
        
        const data = await response.json();
        
        clearElement(content);
        wrapper.classList.remove('generating-insight');
        
        if (typeof marked !== 'undefined') {
            content.innerHTML = marked.parse(data.weekly_insight);
        } else {
            content.textContent = data.weekly_insight;
        }

    } catch (error) {
        clearInterval(interval);
        clearElement(content);
        genBtn.style.opacity = '1';
        genBtn.disabled = false;
        genBtn.textContent = '⚡ 生成本周深读 (Wired Style)';
        
        const err = document.createElement('p');
        err.className = 'error-message';
        err.textContent = '周刊生成出了点意外，请稍后再试。';
        content.appendChild(err);
    }
}

function toggleHistoryPanel() {
    const panel = document.getElementById('history-modal');
    panel.classList.toggle('active');
    if (panel.classList.contains('active')) {
        loadHistoryData('history');
    }
}

function toggleMagazinePanel() {
    const panel = document.getElementById('magazine-modal');
    panel.classList.toggle('active');
    if (panel.classList.contains('active')) {
        loadHistoryData('magazine');
    }
}

async function loadHistoryData(target = 'history') {
    const listContainer = document.getElementById('history-list');
    
    // Preliminary cleanup
    if (target === 'history' && listContainer) {
        clearElement(listContainer);
        const skeleton = document.createElement('p');
        skeleton.className = 'history-hint';
        skeleton.textContent = '正在加载历史记录...';
        listContainer.appendChild(skeleton);
    }

    try {
        const response = await fetch('/api/v1/history');
        if (!response.ok) throw new Error('Failed to fetch history');

        const historyData = await response.json();
        latestHistoryArchive = Array.isArray(historyData.archive_items) ? historyData.archive_items : [];
        
        // Dispatch to both
        renderHistoryInsights(historyData.weekly_recap || null);

        if (!listContainer) return;
        clearElement(listContainer);

        if (!latestHistoryArchive || latestHistoryArchive.length === 0) {
            const empty = document.createElement('p');
            empty.className = 'history-hint';
            empty.textContent = '暂无历史记录。';
            listContainer.appendChild(empty);
            return;
        }

        latestHistoryArchive.forEach((item) => {
            listContainer.appendChild(createArchiveCard(item));
        });

        latestHistoryArchive.forEach((entry) => {
            const item = document.createElement('button');
            item.type = 'button';
            item.className = 'history-item';
            if (latestData && latestData.date === entry.date) {
                item.classList.add('active');
            }

            const main = document.createElement('div');
            main.className = 'history-main';

            const topRow = document.createElement('div');
            topRow.className = 'history-top-row';

            const dateSpan = document.createElement('span');
            dateSpan.className = 'history-date';
            dateSpan.textContent = formatSummaryDate(entry.date);

            const countSpan = createArchiveMeta(`${entry.news_count || 0} 条资讯`, 'history-count');
            topRow.appendChild(dateSpan);
            topRow.appendChild(countSpan);

            const preview = document.createElement('p');
            preview.className = 'history-preview';
            preview.textContent = entry.overview_preview || '暂无概要。';

            const meta = document.createElement('div');
            meta.className = 'history-meta';

            if (Array.isArray(entry.top_categories) && entry.top_categories.length > 0) {
                entry.top_categories.slice(0, 3).forEach((category) => {
                    meta.appendChild(createArchiveMeta(category, 'history-chip'));
                });
            }

            if (entry.source_stats && Object.keys(entry.source_stats).length > 0) {
                const topSource = Object.entries(entry.source_stats)
                    .sort((a, b) => b[1] - a[1])[0];
                if (topSource) {
                    meta.appendChild(createArchiveMeta(`${topSource[0]} × ${topSource[1]}`, 'history-chip history-chip--source'));
                }
            }

            main.appendChild(topRow);
            main.appendChild(preview);
            if (meta.childNodes.length > 0) {
                main.appendChild(meta);
            }

            const icon = document.createElement('span');
            icon.className = 'history-go';
            icon.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="19" y2="12"></line><polyline points="12 5 19 12 12 19"></polyline></svg>';

            item.appendChild(main);
            item.appendChild(icon);

            item.addEventListener('click', () => {
                toggleHistoryPanel();
                fetchSummary(false, entry.date);
            });

            listContainer.appendChild(item);
        });
    } catch (error) {
        console.error('History load error:', error);
        latestHistoryArchive = [];
        renderHistoryInsights(null);
        clearElement(listContainer);
        const err = document.createElement('p');
        err.className = 'history-hint';
        err.textContent = '加载失败，请重试。';
        listContainer.appendChild(err);
    }
}

function parseSseEvents(buffer) {
    const normalizedBuffer = buffer.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
    const events = [];
    let remaining = normalizedBuffer;

    while (true) {
        const separatorIndex = remaining.indexOf('\n\n');
        if (separatorIndex === -1) {
            break;
        }

        const rawEvent = remaining.slice(0, separatorIndex);
        remaining = remaining.slice(separatorIndex + 2);

        const dataLines = rawEvent
            .split('\n')
            .filter((line) => line.startsWith('data:'))
            .map((line) => {
                const value = line.slice(5);
                return value.startsWith(' ') ? value.slice(1) : value;
            });

        if (dataLines.length > 0) {
            events.push(dataLines.join('\n'));
        }
    }

    return { events, buffer: remaining };
}

function setupRagPanel() {
    const overlay = document.getElementById('rag-overlay');
    const closeBtn = document.getElementById('rag-close-btn');
    const form = document.getElementById('rag-form');
    const input = document.getElementById('rag-input');

    overlay.addEventListener('click', closeRagPanel);
    closeBtn.addEventListener('click', closeRagPanel);

    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const question = input.value.trim();
        if (!question || !currentUrl || isIngesting) return;

        input.value = '';
        appendMessage('user', question);
        await runRagQuery(question);
    });
}

async function openRagPanel(url, headline) {
    const panelUrl = url;
    currentUrl = panelUrl;
    isIngesting = true;

    const messages = document.getElementById('rag-messages');
    const input = document.getElementById('rag-input');

    clearElement(messages);
    document.getElementById('rag-article-title').textContent = headline;
    document.getElementById('rag-overlay').classList.add('visible');
    document.getElementById('rag-panel').classList.add('open');
    input.disabled = true;

    try {
        const historyRes = await fetch(`/api/v1/rag/history?url=${encodeURIComponent(panelUrl)}`);
        if (historyRes.ok) {
            const historyData = await historyRes.json();
            if (currentUrl !== panelUrl) {
                return;
            }
            if (Array.isArray(historyData.history) && historyData.history.length > 0) {
                historyData.history.forEach((message) => {
                    const role = message.role === 'assistant' ? 'ai' : message.role;
                    appendMessage(role, message.content);
                });
                appendMessage('system', '以上为之前的对话记录');
            }
        }
    } catch (error) {
        console.error('Failed to load history:', error);
    }

    if (currentUrl !== panelUrl) {
        return;
    }

    const overviewMessage = appendMessage('ai', '');
    setAiMessageText(overviewMessage, '正在生成更详细的文章概要...');

    if (currentOverviewController) {
        currentOverviewController.abort();
    }
    currentOverviewController = new AbortController();

    const overviewPromise = (async () => {
        let hasContent = false;
        let markdownContent = '**快速导读**\n\n';

        try {
            const response = await fetch('/api/v1/rag/overview', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url: panelUrl }),
                signal: currentOverviewController.signal
            });

            if (!response.ok || !response.body) {
                throw new Error('详细概要生成失败，但你仍可继续提问。');
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const parsed = parseSseEvents(buffer);
                buffer = parsed.buffer;

                for (const token of parsed.events) {
                    if (token === '[DONE]') continue;
                    if (currentUrl !== panelUrl) {
                        return;
                    }

                    hasContent = true;
                    markdownContent += token;
                    renderAiMarkdown(overviewMessage, markdownContent);
                }
            }

            if (!hasContent && currentUrl === panelUrl) {
                throw new Error('详细概要生成失败，但你仍可继续提问。');
            }
        } catch (error) {
            if (error.name === 'AbortError' || currentUrl !== panelUrl) {
                return;
            }
            setAiMessageText(overviewMessage, error.message);
        } finally {
            if (currentOverviewController && currentOverviewController.signal.aborted) {
                currentOverviewController = null;
            } else if (currentOverviewController) {
                currentOverviewController = null;
            }
        }
    })();

    const ingestMessage = appendMessage('system', '正在阅读原文并建立知识索引，请稍候...');

    try {
        const response = await fetch('/api/v1/rag/ingest', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: panelUrl })
        });

        if (!response.ok) {
            throw new Error('文章索引失败，请检查该链接是否可访问。');
        }

        const data = await response.json();
        if (currentUrl !== panelUrl) {
            return;
        }
        ingestMessage.textContent = `原文已加载（共 ${data.chunks} 个段落块）。现在你可以继续追问了。`;

        // Show quality warning if extraction was problematic
        if (data.quality && data.quality.verdict !== 'good') {
            const qualityMsg = appendMessage('system', '');
            const detail = data.quality.details ? `（${data.quality.details}）` : '';
            if (data.quality.verdict === 'partial') {
                qualityMsg.className = 'rag-msg rag-msg--system quality-warning';
                qualityMsg.textContent = `⚠️ 内容解析不完整，回答可能有遗漏${detail}`;
            } else {
                qualityMsg.className = 'rag-msg rag-msg--system quality-error';
                qualityMsg.textContent = `❌ 内容提取质量很差，建议直接阅读原文${detail}`;
            }
        }

        input.disabled = false;
        input.focus();
    } catch (error) {
        if (currentUrl === panelUrl) {
            ingestMessage.textContent = error.message;
        }
    } finally {
        if (!currentUrl || currentUrl === panelUrl) {
            isIngesting = false;
        }
    }

    await overviewPromise;
}

function closeRagPanel() {
    document.getElementById('rag-panel').classList.remove('open');
    document.getElementById('rag-overlay').classList.remove('visible');
    if (currentQueryController) {
        currentQueryController.abort();
        currentQueryController = null;
    }
    if (currentOverviewController) {
        currentOverviewController.abort();
        currentOverviewController = null;
    }
    isIngesting = false;
    currentUrl = null;
}

async function runRagQuery(question) {
    const aiMessage = appendMessage('ai', '');
    const input = document.getElementById('rag-input');
    input.disabled = true;

    if (currentQueryController) {
        currentQueryController.abort();
    }
    currentQueryController = new AbortController();

    try {
        const response = await fetch('/api/v1/rag/query', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: currentUrl, question }),
            signal: currentQueryController.signal
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            const message = errorData.detail || `HTTP ${response.status}`;
            setAiMessageText(aiMessage, `错误: ${message}`);
            return;
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let markdownContent = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const parsed = parseSseEvents(buffer);
            buffer = parsed.buffer;

            for (const token of parsed.events) {
                if (token === '[DONE]') continue;

                const metadataMatch = token.match(/\[METADATA\]([\s\S]*?)\[\/METADATA\]/);
                if (metadataMatch) {
                    try {
                        const metadata = JSON.parse(metadataMatch[1]);
                        if (metadata.type === 'scoring_explain') {
                            renderScoringExplain(aiMessage, metadata.scores || []);
                        }
                    } catch (error) {
                        console.error('Failed to parse metadata:', error);
                    }
                    continue;
                }

                markdownContent += token;
                renderAiMarkdown(aiMessage, markdownContent);
            }
        }
    } catch (error) {
        if (error.name !== 'AbortError') {
            setAiMessageText(aiMessage, `连接错误: ${error.message}`);
        }
    } finally {
        if (currentQueryController && currentQueryController.signal.aborted) {
            currentQueryController = null;
        } else if (currentQueryController) {
            currentQueryController = null;
        }
        input.disabled = false;
        input.focus();
    }
}

function appendMessage(role, text) {
    const messages = document.getElementById('rag-messages');
    const message = document.createElement('div');
    message.className = `rag-msg rag-msg--${role}`;

    if (role === 'ai') {
        const content = document.createElement('div');
        content.className = 'rag-msg__content';
        message.appendChild(content);
        if (text) {
            setAiMessageText(message, text);
        }
    } else {
        message.textContent = text;
    }

    messages.appendChild(message);
    messages.scrollTop = messages.scrollHeight;
    return message;
}

function setAiMessageText(message, text) {
    const content = ensureAiContent(message);
    content.textContent = text;
}

function renderAiMarkdown(message, markdownText) {
    const content = ensureAiContent(message);
    content.innerHTML = renderMarkdownSafe(markdownText);
    scrollRagMessagesToBottom();
}

function ensureAiContent(message) {
    let content = message.querySelector('.rag-msg__content');
    if (!content) {
        content = document.createElement('div');
        content.className = 'rag-msg__content';
        message.appendChild(content);
    }
    return content;
}

function renderScoringExplain(message, scores) {
    const existing = message.querySelector('.thinking-process');
    if (existing) {
        existing.remove();
    }

    if (!scores || scores.length === 0) {
        return;
    }

    const wrapper = document.createElement('div');
    wrapper.className = 'thinking-process';

    const details = document.createElement('details');
    const summary = document.createElement('summary');
    summary.textContent = '展开 AI 思考过程（基于两阶段检索 + 个性化重排）';

    const list = document.createElement('div');
    list.className = 'thinking-list';

    scores.forEach((score, index) => {
        const item = document.createElement('div');
        item.className = 'thinking-item';

        const rank = document.createElement('div');
        rank.className = 'thinking-rank';
        rank.textContent = `#${index + 1}`;

        const content = document.createElement('div');
        content.className = 'thinking-content';

        const preview = document.createElement('div');
        preview.className = 'thinking-preview';
        preview.textContent = score.preview || '无预览';

        const badges = document.createElement('div');
        badges.className = 'thinking-scores';

        badges.appendChild(createScoreTag(sourceLabel(score.source).cls, sourceLabel(score.source).text));
        badges.appendChild(createScoreTag('relevance', `相关性: ${score.cross_score}`));
        if (score.bonus > 0) {
            badges.appendChild(createScoreTag('bonus', `个性化: +${score.bonus}`));
        }
        if (score.penalty > 0) {
            badges.appendChild(createScoreTag('penalty', `负反馈: -${score.penalty}`));
        }
        badges.appendChild(createScoreTag('total', `总分: ${score.total}`));

        content.appendChild(preview);
        content.appendChild(badges);

        item.appendChild(rank);
        item.appendChild(content);
        list.appendChild(item);
    });

    details.appendChild(summary);
    details.appendChild(list);
    wrapper.appendChild(details);
    message.insertBefore(wrapper, ensureAiContent(message));
}

function createScoreTag(type, text) {
    const tag = document.createElement('span');
    tag.className = `score-tag ${type}`;
    tag.textContent = text;
    return tag;
}

function sourceLabel(source) {
    const mapping = {
        semantic: { text: '语义', cls: 'source-semantic' },
        keyword: { text: '关键词', cls: 'source-keyword' },
        hybrid: { text: '混合命中', cls: 'source-hybrid' }
    };
    return mapping[source] || mapping.semantic;
}

function renderMarkdownSafe(text) {
    const rawHtml = typeof marked !== 'undefined'
        ? marked.parse(text)
        : `<p>${escapeHtml(text).replace(/\n/g, '<br>')}</p>`;

    const template = document.createElement('template');
    template.innerHTML = rawHtml;

    template.content.querySelectorAll('script, style, iframe, object, embed, link, img, svg, math, form, input, textarea, button, meta, base').forEach((node) => node.remove());

    template.content.querySelectorAll('*').forEach((node) => {
        [...node.attributes].forEach((attr) => {
            const name = attr.name.toLowerCase();
            const value = attr.value || '';
            if (name.startsWith('on')) {
                node.removeAttribute(attr.name);
                return;
            }
            if ((name === 'href' || name === 'src') && value && !isSafeHttpUrlString(value)) {
                node.removeAttribute(attr.name);
                return;
            }
            if (name === 'style') {
                node.removeAttribute(attr.name);
            }
        });

        if (node.tagName === 'A') {
            const href = node.getAttribute('href') || '';
            if (!isSafeHttpUrlString(href)) {
                const textNode = document.createTextNode(node.textContent || href);
                node.replaceWith(textNode);
                return;
            }
            node.setAttribute('target', '_blank');
            node.setAttribute('rel', 'noopener noreferrer');
        }
    });

    return template.innerHTML;
}

function escapeHtml(text) {
    return String(text ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function isSafeHttpUrlString(value) {
    try {
        const url = new URL(value);
        return url.protocol === 'http:' || url.protocol === 'https:';
    } catch {
        return false;
    }
}

function appendStaticIcon(element, svgMarkup) {
    const wrapper = document.createElement('span');
    wrapper.className = 'icon-inline';
    wrapper.innerHTML = svgMarkup;
    wrapper.setAttribute('aria-hidden', 'true');
    element.appendChild(wrapper);
}

function scrollRagMessagesToBottom() {
    const messages = document.getElementById('rag-messages');
    messages.scrollTop = messages.scrollHeight;
}
