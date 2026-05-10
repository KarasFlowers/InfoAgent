let latestData = null;
let currentUrl = null;
let isIngesting = false;
let currentQueryController = null;
let currentOverviewController = null;
let latestHistoryArchive = [];
let currentBoardSlug = null;
let availableBoards = [];

const SUMMARY_LOADING_TEXT = 'AI 编辑正在努力生成今日简报，这可能需要几十秒...';

const ICONS = {
    external: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14L21 3"/></svg>',
    ask: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>',
    like: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/></svg>',
    dislike: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm7-13h3a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-3"/></svg>'
};

document.addEventListener('DOMContentLoaded', async () => {
    await initBoards();
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

async function initBoards() {
    try {
        const res = await fetch('/api/v1/boards');
        availableBoards = await res.json();
        
        const container = document.getElementById('board-tabs');
        if (availableBoards.length === 0) return;

        // Determine initial active board from localStorage or first default
        const saved = localStorage.getItem('argos_board');
        if (saved && availableBoards.find(b => b.slug === saved)) {
            currentBoardSlug = saved;
        } else {
            const def = availableBoards.find(b => b.is_default);
            currentBoardSlug = def ? def.slug : availableBoards[0].slug;
        }

        container.style.display = 'flex';
        renderBoardTabs();
    } catch (e) {
        console.error("Failed to initialize boards", e);
    }
}

function renderBoardTabs() {
    const container = document.getElementById('board-tabs');
    let html = '';
    for (const b of availableBoards) {
        const isActive = b.slug === currentBoardSlug ? 'active' : '';
        html += `<div class="board-tab-wrapper ${isActive}">
            <button class="board-tab" onclick="switchBoard('${b.slug}')">
                ${b.icon} ${b.name}
            </button>
            <button class="board-edit-btn" onclick="openBoardModal('${b.slug}')" title="设置此板块">⚙️</button>
        </div>`;
    }
    html += `<button class="board-add-btn" onclick="openBoardModal()" title="新建板块">➕ 添加板块</button>`;
    container.innerHTML = html;
}

function switchBoard(slug) {
    if (slug === currentBoardSlug) return;
    currentBoardSlug = slug;
    localStorage.setItem('argos_board', slug);
    renderBoardTabs();
    
    // Close panels if open
    document.getElementById('persona-panel').classList.remove('active');
    document.getElementById('insights-modal').style.display = 'none';
    
    fetchSummary();
}

// ==========================================
// Board Management Logic
// ==========================================

let wizardMessages = [];           // conversation history
let wizardLastConfig = null;       // most recent suggested config
let wizardIsLoading = false;

function switchBoardMode(mode) {
    // Toggle active tab
    document.querySelectorAll('#board-mode-tabs .board-mode-tab').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.mode === mode);
    });
    const wizardPanel = document.getElementById('board-wizard-panel');
    const form = document.getElementById('board-form');
    const wizardFooter = document.getElementById('board-wizard-footer');
    if (mode === 'wizard') {
        wizardPanel.style.display = 'block';
        form.style.display = 'none';
        wizardFooter.style.display = 'flex';
    } else {
        wizardPanel.style.display = 'none';
        form.style.display = 'block';
        wizardFooter.style.display = 'none';
    }
}

function resetWizard() {
    wizardMessages = [];
    wizardLastConfig = null;
    wizardIsLoading = false;
    const messagesDiv = document.getElementById('wizard-messages');
    if (messagesDiv) {
        messagesDiv.innerHTML = `<div class="wizard-msg wizard-msg--ai">👋 告诉我你想要一个什么样的板块，比如：<br>"我想每天学 5 个英语商务单词"，<br>"汇总国内外顶级 AI 实验室的最新论文"，<br>"每天给我一条冷门心理学知识"...</div>`;
    }
    const applyRow = document.getElementById('wizard-apply-row');
    if (applyRow) applyRow.style.display = 'none';
    const input = document.getElementById('wizard-input');
    if (input) { input.value = ''; input.disabled = false; }
    const btn = document.getElementById('wizard-submit-btn');
    if (btn) { btn.disabled = false; btn.textContent = '发送'; }
}

function appendWizardMsg(role, content) {
    const container = document.getElementById('wizard-messages');
    const div = document.createElement('div');
    div.className = `wizard-msg wizard-msg--${role}`;
    if (role === 'ai' && typeof marked !== 'undefined') {
        div.innerHTML = marked.parse(content);
    } else {
        div.textContent = content;
    }
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
    return div;
}

async function submitWizard(event) {
    event.preventDefault();
    if (wizardIsLoading) return;
    const input = document.getElementById('wizard-input');
    const text = input.value.trim();
    if (!text) return;

    // Append user message
    appendWizardMsg('user', text);
    wizardMessages.push({ role: 'user', content: text });
    input.value = '';

    // Loading state
    wizardIsLoading = true;
    const btn = document.getElementById('wizard-submit-btn');
    btn.disabled = true;
    btn.textContent = '思考中...';
    const loadingMsg = appendWizardMsg('ai', '🧠 正在为你设计板块...');

    try {
        const res = await fetch('/api/v1/boards/wizard', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ messages: wizardMessages }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        // Remove loading placeholder
        loadingMsg.remove();

        // Show AI reply
        appendWizardMsg('ai', data.reply || '（无回复）');
        wizardMessages.push({ role: 'assistant', content: data.reply || '' });

        if (data.ready && data.config) {
            wizardLastConfig = data.config;
            // Summary preview
            const cfg = data.config;
            const preview = `**推荐配置：**
- 名称：${cfg.icon} ${cfg.name}
- 标识：\`${cfg.slug}\`
- 类型：${cfg.source_type === 'rss' ? 'RSS 订阅源' : '纯 LLM 生成'}
${cfg.source_type === 'rss' && cfg.rss_urls.length > 0 ? `- 源：\n${cfg.rss_urls.map(u => '  - ' + u).join('\n')}` : ''}`;
            appendWizardMsg('ai', preview);
            document.getElementById('wizard-apply-row').style.display = 'flex';
        } else {
            wizardLastConfig = null;
            document.getElementById('wizard-apply-row').style.display = 'none';
        }
    } catch (e) {
        loadingMsg.remove();
        appendWizardMsg('ai', `❌ 出错了：${e.message}`);
    } finally {
        wizardIsLoading = false;
        btn.disabled = false;
        btn.textContent = '发送';
        input.focus();
    }
}

function applyWizardConfig() {
    if (!wizardLastConfig) return;
    const cfg = wizardLastConfig;
    document.getElementById('board-slug').value = cfg.slug || '';
    document.getElementById('board-slug').disabled = false;
    document.getElementById('board-name').value = cfg.name || '';
    document.getElementById('board-icon').value = cfg.icon || '📌';
    document.getElementById('board-source-type').value = cfg.source_type || 'rss';
    document.getElementById('board-prompt').value = cfg.system_prompt || '';
    if (cfg.source_type === 'rss' && cfg.rss_urls) {
        document.getElementById('board-rss-urls').value = cfg.rss_urls.join('\n');
    } else {
        document.getElementById('board-rss-urls').value = '';
    }
    toggleBoardSourceConfig();
    switchBoardMode('manual');
}

function openBoardModal(slug = null) {
    const modal = document.getElementById('board-modal');
    if (!modal) return;
    const title = document.getElementById('board-modal-title');
    const isEditInput = document.getElementById('board-is-edit');
    const deleteBtn = document.getElementById('board-delete-btn');
    const originalSlugInput = document.getElementById('board-original-slug');
    const modeTabs = document.getElementById('board-mode-tabs');
    
    // reset form and wizard state
    document.getElementById('board-form').reset();
    document.getElementById('board-rss-group').style.display = 'block';
    resetWizard();

    if (slug) {
        // Edit mode - jump straight to manual, hide wizard tabs
        title.textContent = '设置板块';
        isEditInput.value = 'true';
        originalSlugInput.value = slug;
        deleteBtn.style.display = 'inline-block';
        modeTabs.style.display = 'none';
        switchBoardMode('manual');
        
        const b = availableBoards.find(x => x.slug === slug);
        if (b) {
            document.getElementById('board-slug').value = b.slug;
            document.getElementById('board-slug').disabled = true;
            document.getElementById('board-name').value = b.name;
            document.getElementById('board-icon').value = b.icon;
            document.getElementById('board-source-type').value = b.source_type || 'rss';
            document.getElementById('board-prompt').value = b.system_prompt || '';
            
            if (b.source_type === 'rss') {
                const urls = b.source_config?.rss_urls || [];
                document.getElementById('board-rss-urls').value = urls.join('\n');
            }
            toggleBoardSourceConfig();
            
            if (b.is_default) {
                deleteBtn.style.display = 'none';
            }
        }
    } else {
        // Add mode - start with wizard
        title.textContent = '新建板块';
        isEditInput.value = 'false';
        originalSlugInput.value = '';
        deleteBtn.style.display = 'none';
        modeTabs.style.display = 'flex';
        document.getElementById('board-slug').disabled = false;
        document.getElementById('board-source-type').value = 'rss';
        toggleBoardSourceConfig();
        switchBoardMode('wizard');
    }
    
    modal.classList.add('active');
}

function closeBoardModal() {
    const modal = document.getElementById('board-modal');
    if (modal) modal.classList.remove('active');
}

function toggleBoardSourceConfig() {
    const type = document.getElementById('board-source-type').value;
    const rssGroup = document.getElementById('board-rss-group');
    if (type === 'rss') {
        rssGroup.style.display = 'block';
    } else {
        rssGroup.style.display = 'none';
    }
}

async function saveBoard(event) {
    event.preventDefault();
    const isEdit = document.getElementById('board-is-edit').value === 'true';
    const originalSlug = document.getElementById('board-original-slug').value;
    
    const slug = document.getElementById('board-slug').value.trim();
    const name = document.getElementById('board-name').value.trim();
    const icon = document.getElementById('board-icon').value.trim();
    const sourceType = document.getElementById('board-source-type').value;
    const prompt = document.getElementById('board-prompt').value.trim();
    
    const payload = {
        slug: slug,
        name: name,
        icon: icon,
        source_type: sourceType,
        system_prompt: prompt || null,
        source_config: {}
    };
    
    if (sourceType === 'rss') {
        const rawUrls = document.getElementById('board-rss-urls').value;
        const urls = rawUrls.split('\n').map(u => u.trim()).filter(u => u.length > 0);
        payload.source_config = { rss_urls: urls };
    }
    
    try {
        const url = isEdit ? `/api/v1/boards/${originalSlug}` : '/api/v1/boards';
        const method = isEdit ? 'PUT' : 'POST';
        
        const res = await fetch(url, {
            method: method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || '保存失败');
        }
        
        closeBoardModal();
        if (!isEdit) {
            currentBoardSlug = slug; // Switch to new board
            localStorage.setItem('argos_board', slug);
        }
        await initBoards();
        if (!isEdit) fetchSummary();
    } catch (e) {
        alert("保存板块出错: " + e.message);
    }
}

async function deleteBoard() {
    const slug = document.getElementById('board-original-slug').value;
    if (!confirm('确定要删除此板块吗？归档记录也会一起清理。')) return;
    
    try {
        const res = await fetch(`/api/v1/boards/${slug}`, {
            method: 'DELETE'
        });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || '删除失败');
        }
        
        closeBoardModal();
        currentBoardSlug = null;
        localStorage.removeItem('argos_board');
        await initBoards();
        fetchSummary();
    } catch (e) {
        alert("删除板块出错: " + e.message);
    }
}

async function fetchSummary(force = false, date = null) {
    let url = '/api/v1/summary';
    const params = [];
    if (force) params.push('force=true');
    if (date) params.push(`date=${encodeURIComponent(date)}`);
    if (currentBoardSlug) params.push(`board=${encodeURIComponent(currentBoardSlug)}`);
    
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
        fetchSystemMetrics();

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
    likeButton.addEventListener('click', () => sendFeedback(likeButton, newsItem.original_link, 1, newsItem));

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
    statsContainer.style.display = 'flex';

    const label = document.createElement('h4');
    label.className = 'metrics-card-title';
    label.textContent = '来源分布 (今日)';
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
        loadExplicitPreferences();
    }
}

async function fetchSystemMetrics() {
    try {
        const response = await fetch('/api/v1/metrics');
        const data = await response.json();
        
        if (data.tokens) {
            document.getElementById('metric-tokens').textContent = data.tokens.total.toLocaleString();
        }
        if (data.latency) {
            document.getElementById('metric-p50').textContent = data.latency.p50_sec > 0 ? `${data.latency.p50_sec} s` : '--';
            document.getElementById('metric-p99').textContent = data.latency.p99_sec > 0 ? `${data.latency.p99_sec} s` : '--';
        }
    } catch (e) {
        console.error("Failed to load metrics", e);
    }
}

async function loadPersonaData() {
    try {
        let url = '/api/v1/persona';
        if (currentBoardSlug) url += `?board=${encodeURIComponent(currentBoardSlug)}`;
        const response = await fetch(url);
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

async function sendFeedback(buttonElement, url, sentiment, newsItem) {
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

        // On a fresh positive like, offer the user a chance to declare WHY
        // (capturing abstract intent rather than literal subject).
        if (nextSentiment === 1 && currentSentiment !== 1 && newsItem) {
            showInterestReasonPopup(buttonElement, newsItem);
        }
    } catch (error) {
        console.error('Failed to submit feedback:', error);
        applyFeedbackState(likeButton, dislikeButton, currentSentiment);
    } finally {
        const disabled = !isSafeHttpUrlString(url);
        likeButton.disabled = disabled;
        dislikeButton.disabled = disabled;
    }
}

async function showInterestReasonPopup(anchorButton, newsItem) {
    // Remove any existing popup
    document.querySelectorAll('.interest-popup').forEach((el) => el.remove());

    const card = anchorButton.closest('.news-card');
    if (!card) return;

    const popup = document.createElement('div');
    popup.className = 'interest-popup';
    popup.innerHTML = `
        <div class="interest-popup__header">
            <span class="interest-popup__title">🎯 你为什么感兴趣？</span>
            <button type="button" class="interest-popup__close" aria-label="关闭">×</button>
        </div>
        <p class="interest-popup__hint">选一项，添加为长期偏好。会影响后续生成的简报。</p>
        <div class="interest-popup__options">
            <div class="interest-popup__loading">AI 正在为你提炼选项...</div>
        </div>
    `;
    card.appendChild(popup);

    const closeBtn = popup.querySelector('.interest-popup__close');
    closeBtn.addEventListener('click', () => popup.remove());

    // Auto-dismiss after 25s if untouched
    const dismissTimer = setTimeout(() => popup.remove(), 25000);

    let options = [];
    try {
        const res = await fetch('/api/v1/feedback/interest-options', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                headline: newsItem.headline || '',
                key_points: newsItem.key_points || [],
                tags: newsItem.tags || [],
            }),
        });
        if (res.ok) {
            const data = await res.json();
            options = Array.isArray(data.options) ? data.options : [];
        }
    } catch (error) {
        console.error('Failed to fetch interest options:', error);
    }

    const optionsContainer = popup.querySelector('.interest-popup__options');
    optionsContainer.innerHTML = '';
    if (options.length === 0) {
        optionsContainer.innerHTML = '<div class="interest-popup__empty">未能生成选项，可稍后在偏好面板手动添加。</div>';
        return;
    }

    options.forEach((opt) => {
        const chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'interest-chip';
        chip.textContent = opt;
        chip.addEventListener('click', async () => {
            chip.disabled = true;
            chip.classList.add('saving');
            try {
                let url = '/api/v1/feedback/save-reason';
                if (currentBoardSlug) url += `?board=${encodeURIComponent(currentBoardSlug)}`;
                const r = await fetch(url, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ content: opt }),
                });
                if (!r.ok) throw new Error(`HTTP ${r.status}`);
                clearTimeout(dismissTimer);
                popup.classList.add('saved');
                popup.querySelector('.interest-popup__options').innerHTML =
                    `<div class="interest-popup__success">✅ 已添加：<strong>${opt}</strong></div>`;
                setTimeout(() => popup.remove(), 1500);
            } catch (error) {
                console.error('Failed to save interest reason:', error);
                chip.disabled = false;
                chip.classList.remove('saving');
            }
        });
        optionsContainer.appendChild(chip);
    });
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
        let url = '/api/v1/history/weekly_insight';
        if (currentBoardSlug) url += `?board=${encodeURIComponent(currentBoardSlug)}`;
        const response = await fetch(url);
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
        let url = '/api/v1/history';
        if (currentBoardSlug) url += `?board=${encodeURIComponent(currentBoardSlug)}`;
        const response = await fetch(url);
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

    // --- Background-aware ingestion: check status first, skip loading if already done ---
    let alreadyIngested = false;
    try {
        const statusRes = await fetch(`/api/v1/rag/ingest_status?url=${encodeURIComponent(panelUrl)}`);
        if (statusRes.ok) {
            const statusData = await statusRes.json();
            if (statusData.status === 'done') {
                alreadyIngested = true;
            }
        }
    } catch (_) { /* ignore – will fall through to ingest */ }

    if (alreadyIngested) {
        const ingestMessage = appendMessage('system', '知识索引已就绪，你可以直接提问。');
        input.disabled = false;
        input.focus();
        isIngesting = false;
    } else {
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

    let citations = [];

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
                        if (metadata.citations) {
                            citations = metadata.citations;
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

        if (citations.length > 0) {
            renderCitations(aiMessage, citations);
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

function renderCitations(message, citations) {
    const existing = message.querySelector('.citation-sources');
    if (existing) existing.remove();
    if (!citations || citations.length === 0) return;

    const wrapper = document.createElement('div');
    wrapper.className = 'citation-sources';

    const heading = document.createElement('div');
    heading.className = 'citation-heading';
    heading.textContent = '📚 参考来源';
    wrapper.appendChild(heading);

    citations.forEach((cite) => {
        const card = document.createElement('div');
        card.className = 'citation-card';

        const badge = document.createElement('span');
        badge.className = 'citation-index';
        badge.textContent = `[${cite.index}]`;

        const text = document.createElement('span');
        text.className = 'citation-preview';
        text.textContent = cite.preview || '无预览';

        const src = document.createElement('span');
        src.className = `score-tag ${sourceLabel(cite.source || 'semantic').cls}`;
        src.textContent = sourceLabel(cite.source || 'semantic').text;

        card.appendChild(badge);
        card.appendChild(text);
        card.appendChild(src);
        wrapper.appendChild(card);
    });

    const content = ensureAiContent(message);
    content.appendChild(wrapper);
    scrollRagMessagesToBottom();
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

// ---------------------------------------------------------------
// Insights Panel
// ---------------------------------------------------------------

function toggleInsightsPanel() {
    const modal = document.getElementById('insights-modal');
    const isOpen = modal.style.display === 'flex';
    modal.style.display = isOpen ? 'none' : 'flex';
    if (!isOpen) fetchHeatmap();
}

async function fetchHeatmap() {
    const days = document.getElementById('heatmap-days').value;
    const container = document.getElementById('heatmap-container');
    container.innerHTML = '<p class="heatmap-placeholder">加载中...</p>';
    try {
        let url = `/api/v1/insights/heatmap?days=${days}`;
        if (currentBoardSlug) url += `&board=${encodeURIComponent(currentBoardSlug)}`;
        const res = await fetch(url);
        const data = await res.json();
        renderHeatmap(data, container);
    } catch (e) {
        container.innerHTML = '<p class="heatmap-placeholder">加载失败</p>';
    }
}

function renderHeatmap(data, container) {
    if (!data.topics || data.topics.length === 0) {
        container.innerHTML = '<p class="heatmap-placeholder">暂无足够历史数据</p>';
        return;
    }
    const dates = data.dates || [];
    const maxCount = Math.max(...data.topics.flatMap(t => t.counts), 1);

    // Build header row
    let html = `<div class="heatmap-grid" style="--cols:${dates.length}">`;
    html += '<div class="heatmap-label"></div>';
    for (const d of dates) {
        const short = d.slice(5); // "04-21"
        html += `<div class="heatmap-date">${short}</div>`;
    }

    for (const topic of data.topics) {
        html += `<div class="heatmap-label" title="${topic.name} (${topic.total})">${topic.name}</div>`;
        for (const c of topic.counts) {
            const opacity = c === 0 ? 0 : Math.max(0.15, c / maxCount);
            html += `<div class="heatmap-cell" style="opacity:${opacity}" title="${c}"></div>`;
        }
    }
    html += '</div>';
    container.innerHTML = html;
}

async function fetchEntityTimeline() {
    const entity = document.getElementById('entity-input').value.trim();
    if (!entity) return;
    const container = document.getElementById('timeline-container');
    container.innerHTML = '<p class="timeline-placeholder">搜索中...</p>';
    try {
        let url = `/api/v1/insights/timeline?entity=${encodeURIComponent(entity)}&days=30`;
        if (currentBoardSlug) url += `&board=${encodeURIComponent(currentBoardSlug)}`;
        const res = await fetch(url);
        const data = await res.json();
        renderTimeline(data, container);
    } catch (e) {
        container.innerHTML = '<p class="timeline-placeholder">搜索失败</p>';
    }
}

function renderTimeline(data, container) {
    if (!data.items || data.items.length === 0) {
        container.innerHTML = `<p class="timeline-placeholder">近 ${data.days} 天内未找到与"${data.entity}"相关的报道</p>`;
        return;
    }
    let html = `<p class="timeline-summary">近 ${data.days} 天共 <strong>${data.total}</strong> 条与"${data.entity}"相关的报道</p>`;
    html += '<div class="timeline-list">';
    for (const item of data.items) {
        html += `<div class="timeline-item">
            <span class="timeline-date">${item.date}</span>
            <span class="timeline-cat">${item.category}</span>
            <a href="${item.link}" target="_blank" class="timeline-headline">${item.headline}</a>
            <span class="timeline-source">${item.source}</span>
        </div>`;
    }
    html += '</div>';
    container.innerHTML = html;
}

// ---------------------------------------------------------------
// Explicit Preference Tags
// ---------------------------------------------------------------

async function loadExplicitPreferences() {
    try {
        let url = '/api/v1/preferences';
        if (currentBoardSlug) url += `?board=${encodeURIComponent(currentBoardSlug)}`;
        const res = await fetch(url);
        const data = await res.json();
        for (const cat of ['focus_topic', 'block_topic', 'prefer_source', 'avoid_source']) {
            renderPrefTags(cat, data[cat] || []);
        }
    } catch (e) {
        console.error('Failed to load preferences', e);
    }
}

function renderPrefTags(category, items) {
    const container = document.getElementById(`pref-tags-${category}`);
    if (!container) return;
    if (items.length === 0) {
        container.innerHTML = '<span class="pref-empty">暂无</span>';
        return;
    }
    container.innerHTML = items.map(item =>
        `<span class="pref-tag pref-tag-${category}">${item.content}<button class="pref-del" onclick="deletePrefTag(${item.id})">&times;</button></span>`
    ).join('');
}

async function addPrefTag(category) {
    const input = document.getElementById(`pref-input-${category}`);
    const content = input.value.trim();
    if (!content) return;
    try {
        let url = '/api/v1/persona';
        if (currentBoardSlug) url += `?board=${encodeURIComponent(currentBoardSlug)}`;
        await fetch(url, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({content, category}),
        });
        input.value = '';
        loadExplicitPreferences();
    } catch (e) {
        console.error('Failed to add preference', e);
    }
}

async function deletePrefTag(id) {
    try {
        await fetch(`/api/v1/persona/${id}`, {method: 'DELETE'});
        loadExplicitPreferences();
    } catch (e) {
        console.error('Failed to delete preference', e);
    }
}

// ==========================================
// Insights Panel (Heatmap + Entity Timeline)
// ==========================================

function toggleInsightsPanel() {
    const modal = document.getElementById('insights-modal');
    if (!modal) return;
    modal.classList.toggle('active');
    if (modal.classList.contains('active')) {
        fetchHeatmap();
    }
}

async function fetchHeatmap() {
    const container = document.getElementById('heatmap-container');
    if (!container) return;
    const daysSelect = document.getElementById('heatmap-days');
    const days = daysSelect ? daysSelect.value : 7;

    container.innerHTML = '<p class="heatmap-placeholder">正在加载话题热度...</p>';

    try {
        const res = await fetch(`/api/v1/insights/heatmap?days=${days}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        renderHeatmap(data, container);
    } catch (e) {
        console.error('Failed to fetch heatmap', e);
        container.innerHTML = `<p class="heatmap-placeholder">加载失败: ${e.message}</p>`;
    }
}

function renderHeatmap(data, container) {
    container.innerHTML = '';

    const dates = data.dates || [];
    const topics = data.topics || [];

    if (dates.length === 0 || topics.length === 0) {
        container.innerHTML = '<p class="heatmap-placeholder">暂无足够数据生成热度图</p>';
        return;
    }

    // Topics are already sorted by total from backend; take top 20
    const sortedTopics = topics.slice(0, 20);

    // Find global max for color scaling
    let maxCount = 0;
    for (const t of sortedTopics) {
        for (const c of t.counts) {
            if (c > maxCount) maxCount = c;
        }
    }
    if (maxCount === 0) maxCount = 1;

    // Format short dates for header
    const shortDates = dates.map(d => {
        const parts = d.split('-');
        return `${parts[1]}/${parts[2]}`;
    });

    // Build grid
    const table = document.createElement('div');
    table.className = 'heatmap-grid';
    table.style.cssText = `display: grid; grid-template-columns: 160px repeat(${dates.length}, 1fr); gap: 3px; font-size: 0.78rem;`;

    // Header row
    const cornerCell = document.createElement('div');
    cornerCell.className = 'heatmap-corner';
    cornerCell.style.cssText = 'font-weight: 600; color: var(--text-secondary); padding: 6px 8px;';
    cornerCell.textContent = '话题 / 日期';
    table.appendChild(cornerCell);

    for (const sd of shortDates) {
        const headerCell = document.createElement('div');
        headerCell.className = 'heatmap-date-header';
        headerCell.style.cssText = 'text-align: center; font-weight: 600; color: var(--text-secondary); padding: 6px 4px;';
        headerCell.textContent = sd;
        table.appendChild(headerCell);
    }

    // Data rows
    for (const topic of sortedTopics) {
        const labelCell = document.createElement('div');
        labelCell.className = 'heatmap-label';
        labelCell.style.cssText = 'color: var(--text-primary); padding: 6px 8px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; display: flex; align-items: center;';
        labelCell.textContent = topic.name;
        labelCell.title = `${topic.name} (总计: ${topic.total})`;
        table.appendChild(labelCell);

        for (let i = 0; i < dates.length; i++) {
            const count = topic.counts[i] || 0;
            const intensity = count / maxCount;
            const cell = document.createElement('div');
            cell.className = 'heatmap-cell';

            let bg, color;
            if (count === 0) {
                bg = 'rgba(255,255,255,0.03)';
                color = 'transparent';
            } else if (intensity < 0.33) {
                bg = 'rgba(99, 102, 241, 0.15)';
                color = 'rgba(165, 180, 252, 0.9)';
            } else if (intensity < 0.66) {
                bg = 'rgba(99, 102, 241, 0.35)';
                color = '#fff';
            } else {
                bg = 'rgba(99, 102, 241, 0.7)';
                color = '#fff';
            }

            cell.style.cssText = `background: ${bg}; color: ${color}; text-align: center; padding: 6px 4px; border-radius: 6px; font-weight: 600; font-size: 0.75rem; transition: all 0.2s; cursor: default;`;
            cell.textContent = count > 0 ? count : '';
            cell.title = `${topic.name} · ${dates[i]}: ${count} 条`;
            table.appendChild(cell);
        }
    }

    container.appendChild(table);
}

async function fetchEntityTimeline() {
    const input = document.getElementById('entity-input');
    const container = document.getElementById('timeline-container');
    if (!input || !container) return;

    const entity = input.value.trim();
    if (!entity) return;

    container.innerHTML = '<p class="timeline-placeholder">正在搜索...</p>';

    try {
        const res = await fetch(`/api/v1/insights/timeline?entity=${encodeURIComponent(entity)}&days=30`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        renderEntityTimeline(data, container);
    } catch (e) {
        console.error('Failed to fetch entity timeline', e);
        container.innerHTML = `<p class="timeline-placeholder">搜索失败: ${e.message}</p>`;
    }
}

function renderEntityTimeline(data, container) {
    container.innerHTML = '';

    if (!data.items || data.items.length === 0) {
        container.innerHTML = `<p class="timeline-placeholder">在最近 ${data.days || 30} 天内未找到与 "${data.entity}" 相关的资讯</p>`;
        return;
    }

    const header = document.createElement('div');
    header.style.cssText = 'margin-bottom: 1.25rem; color: var(--text-secondary); font-size: 0.85rem;';
    header.textContent = `找到 ${data.total} 条与 "${data.entity}" 相关的资讯（近 ${data.days} 天）`;
    container.appendChild(header);

    const timeline = document.createElement('div');
    timeline.className = 'entity-timeline';
    timeline.style.cssText = 'display: flex; flex-direction: column; gap: 0.75rem; position: relative; padding-left: 1.5rem; border-left: 2px solid rgba(99, 102, 241, 0.3);';

    for (const item of data.items) {
        const entry = document.createElement('div');
        entry.className = 'timeline-entry';
        entry.style.cssText = 'position: relative; padding: 1rem 1.25rem; background: var(--surface-color); border: 1px solid var(--border-color); border-radius: 12px; transition: all 0.3s ease; cursor: default;';

        // Dot on the timeline line
        const dot = document.createElement('div');
        dot.style.cssText = 'position: absolute; left: -2rem; top: 1.25rem; width: 10px; height: 10px; background: var(--accent-color); border-radius: 50%; box-shadow: 0 0 8px rgba(99,102,241,0.5);';
        entry.appendChild(dot);

        const dateLine = document.createElement('div');
        dateLine.style.cssText = 'font-size: 0.78rem; color: var(--accent-color); font-weight: 600; margin-bottom: 0.35rem;';
        dateLine.textContent = item.date || '';
        entry.appendChild(dateLine);

        const headline = document.createElement('div');
        headline.style.cssText = 'font-size: 0.95rem; color: var(--text-primary); font-weight: 600; margin-bottom: 0.3rem; line-height: 1.4;';
        headline.textContent = item.headline || '未命名';
        entry.appendChild(headline);

        if (item.source) {
            const source = document.createElement('div');
            source.style.cssText = 'font-size: 0.78rem; color: var(--text-secondary);';
            source.textContent = `来源: ${item.source}`;
            entry.appendChild(source);
        }

        timeline.appendChild(entry);
    }

    container.appendChild(timeline);
}

// ==========================================
// Sources Management Panel
// ==========================================

function toggleSourcesPanel() {
    const modal = document.getElementById('sources-modal');
    if (!modal) return;
    modal.classList.toggle('active');
    if (modal.classList.contains('active')) {
        loadSourcesForCurrentBoard();
    }
}

function _getCurrentBoardObj() {
    if (!currentBoardSlug || !availableBoards.length) return null;
    return availableBoards.find(b => b.slug === currentBoardSlug) || null;
}

async function loadSourcesForCurrentBoard() {
    const listEl = document.getElementById('sources-feed-list');
    const labelEl = document.getElementById('sources-board-label');
    const board = _getCurrentBoardObj();

    if (!board) {
        labelEl.textContent = '当前板块: --';
        listEl.innerHTML = '<p class="sources-placeholder">未选择板块</p>';
        return;
    }

    labelEl.textContent = `${board.icon || ''} ${board.name} (${board.source_type})`.trim();

    // For RSS and multi-source boards, extract feeds from source_config
    const config = board.source_config || {};
    let feeds = [];

    if (board.source_type === 'rss') {
        feeds = config.feeds || [];
    } else if (board.source_type === 'multi') {
        // Multi-source: extract RSS feeds if any
        const sources = config.sources || {};
        if (sources.rss && sources.rss.feeds) {
            feeds = sources.rss.feeds;
        }
    }

    if (feeds.length === 0) {
        listEl.innerHTML = '<p class="sources-placeholder">此板块暂无配置 RSS 信息源</p>';
        return;
    }

    renderFeedList(feeds, listEl);
}

function renderFeedList(feeds, container) {
    container.innerHTML = '';
    feeds.forEach((url, index) => {
        const item = document.createElement('div');
        item.className = 'source-feed-item';
        item.id = `source-item-${index}`;

        item.innerHTML = `
            <span class="source-feed-index">${index + 1}</span>
            <span class="source-feed-url">${url}</span>
            <span class="source-feed-status" id="source-status-${index}"></span>
            <div class="source-feed-actions">
                <button class="source-feed-test-btn" onclick="testExistingFeed(${index}, '${url.replace(/'/g, "\\'")}')">测试</button>
                <button class="source-feed-del-btn" onclick="deleteSourceFeed(${index})">删除</button>
            </div>
        `;
        container.appendChild(item);
    });
}

async function testSourceFeed() {
    const input = document.getElementById('new-source-url');
    const resultEl = document.getElementById('source-test-result');
    const url = input.value.trim();

    if (!url) return;

    resultEl.style.display = 'block';
    resultEl.className = 'source-test-result';
    resultEl.innerHTML = '<span style="animation: pulseText 1.5s infinite;">正在测试连接...</span>';

    try {
        const res = await fetch('/api/v1/sources/test', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({url}),
        });
        const data = await res.json();

        if (data.ok) {
            resultEl.className = 'source-test-result test-ok';
            const samples = data.sample_titles.map(t => `<li>${t}</li>`).join('');
            resultEl.innerHTML = `
                <strong>✓ 连接成功</strong> — ${data.feed_title}<br>
                <span style="opacity:0.8;">共 ${data.article_count} 篇文章</span>
                ${samples ? `<ul style="margin: 0.5rem 0 0 1rem; opacity: 0.8; font-size: 0.8rem;">${samples}</ul>` : ''}
            `;
        } else {
            resultEl.className = 'source-test-result test-fail';
            resultEl.innerHTML = `<strong>✗ 连接失败</strong> — ${data.error}`;
        }
    } catch (e) {
        resultEl.className = 'source-test-result test-fail';
        resultEl.innerHTML = `<strong>✗ 请求异常</strong> — ${e.message}`;
    }
}

async function testExistingFeed(index, url) {
    const statusEl = document.getElementById(`source-status-${index}`);
    if (!statusEl) return;

    statusEl.className = 'source-feed-status status-testing';
    statusEl.textContent = '测试中…';

    try {
        const res = await fetch('/api/v1/sources/test', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({url}),
        });
        const data = await res.json();

        if (data.ok) {
            statusEl.className = 'source-feed-status status-ok';
            statusEl.textContent = `✓ ${data.article_count}篇`;
            statusEl.title = data.feed_title;
        } else {
            statusEl.className = 'source-feed-status status-fail';
            statusEl.textContent = '✗ 失败';
            statusEl.title = data.error;
        }
    } catch (e) {
        statusEl.className = 'source-feed-status status-fail';
        statusEl.textContent = '✗ 异常';
        statusEl.title = e.message;
    }
}

async function _updateBoardFeeds(newFeeds) {
    const board = _getCurrentBoardObj();
    if (!board) return;

    let newConfig;
    if (board.source_type === 'rss') {
        newConfig = {...(board.source_config || {}), feeds: newFeeds};
    } else if (board.source_type === 'multi') {
        const oldConfig = board.source_config || {};
        const sources = oldConfig.sources || {};
        sources.rss = {...(sources.rss || {}), feeds: newFeeds};
        newConfig = {...oldConfig, sources};
    } else {
        return;
    }

    const res = await fetch(`/api/v1/boards/${encodeURIComponent(board.slug)}`, {
        method: 'PATCH',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({source_config: newConfig}),
    });

    if (!res.ok) {
        const detail = await res.text();
        throw new Error(detail);
    }

    // Update the local board object so UI stays in sync
    const updated = await res.json();
    board.source_config = updated.source_config;
    // Also update the availableBoards array
    const idx = availableBoards.findIndex(b => b.slug === board.slug);
    if (idx !== -1) availableBoards[idx] = {...availableBoards[idx], source_config: updated.source_config};
}

function _getCurrentFeeds() {
    const board = _getCurrentBoardObj();
    if (!board) return [];
    const config = board.source_config || {};
    if (board.source_type === 'rss') return [...(config.feeds || [])];
    if (board.source_type === 'multi') {
        const sources = config.sources || {};
        return [...(sources.rss?.feeds || [])];
    }
    return [];
}

async function addSourceFeed() {
    const input = document.getElementById('new-source-url');
    const url = input.value.trim();
    if (!url) return;

    const feeds = _getCurrentFeeds();
    if (feeds.includes(url)) {
        alert('此信息源已存在');
        return;
    }

    feeds.push(url);

    try {
        await _updateBoardFeeds(feeds);
        input.value = '';
        document.getElementById('source-test-result').style.display = 'none';
        loadSourcesForCurrentBoard();
    } catch (e) {
        alert('添加失败: ' + e.message);
    }
}

async function deleteSourceFeed(index) {
    const feeds = _getCurrentFeeds();
    if (index < 0 || index >= feeds.length) return;

    const removed = feeds[index];
    if (!confirm(`确认删除此信息源？\n${removed}`)) return;

    feeds.splice(index, 1);

    try {
        await _updateBoardFeeds(feeds);
        loadSourcesForCurrentBoard();
    } catch (e) {
        alert('删除失败: ' + e.message);
    }
}

