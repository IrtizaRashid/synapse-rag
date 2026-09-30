(() => {
  'use strict';

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const state = {
    user: null, bots: [], files: [], conversations: [], conversation: null,
    activeBots: [], attachments: [], view: 'chat', sending: false,
    uploadTarget: 'files', fileView: localStorage.getItem('synapse-file-view') || 'list',
    botFilter: 'all', theme: localStorage.getItem('synapse-theme') || 'dark',
    textModalAction: null, confirmAction: null, currentPreview: null,
  };
  const avatars = ['✦', '⌘', '◈', '∆', '◎', '◇', '⚡', 'Σ'];
  const colors = ['#7967ff', '#4189e8', '#20a987', '#dc6e9c', '#d68145', '#7c70bd', '#3d9da4', '#b36ee0'];
  const codeExtensions = new Set(['js','jsx','ts','tsx','py','java','c','cpp','h','hpp','html','css','sql','php','go','rs','rb','sh','yaml','yml','json','xml','ini','env','config','log']);

  function escapeHtml(value = '') {
    return String(value).replace(/[&<>'"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
  }
  function attr(value = '') { return escapeHtml(value).replace(/`/g, '&#96;'); }
  function initials(value = '') { return value.trim().split(/\s+/).slice(0, 2).map(x => x[0]).join('').toUpperCase() || 'AI'; }
  function botColor(bot) { return bot.color || colors[Math.abs(hash(String(bot.id || bot.name))) % colors.length]; }
  function botAvatar(bot) { return avatars.includes(bot.avatar) ? bot.avatar : (bot.avatar && bot.avatar.length <= 3 ? bot.avatar : initials(bot.name)); }
  function hash(value) { let n = 0; for (let i = 0; i < value.length; i++) n = ((n << 5) - n + value.charCodeAt(i)) | 0; return n; }
  function formatBytes(bytes = 0) { if (!bytes) return '—'; const units = ['B','KB','MB','GB']; const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), 3); return `${(bytes / 1024 ** i).toFixed(i ? 1 : 0)} ${units[i]}`; }
  function formatDate(epoch, includeTime = false) { if (!epoch) return '—'; const date = new Date(epoch * 1000); return new Intl.DateTimeFormat(undefined, includeTime ? {month:'short',day:'numeric',hour:'numeric',minute:'2-digit'} : {month:'short',day:'numeric',year: date.getFullYear() !== new Date().getFullYear() ? 'numeric' : undefined}).format(date); }
  function extensionOf(file) { return (file.extension || file.name?.split('.').pop() || 'file').replace('.', '').toUpperCase().slice(0, 5); }
  function debounce(fn, wait = 220) { let timer; return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), wait); }; }

  async function readApiJson(response) {
    const text = await response.text();
    if (!text) return {};
    try { return JSON.parse(text); }
    catch (_) {
      const html = /^\s*</.test(text) || /<!doctype|<html/i.test(text);
      throw new Error(html
        ? `The server returned a web page instead of API data (HTTP ${response.status}). Refresh and try again.`
        : `The server returned invalid data (HTTP ${response.status}). Please try again.`);
    }
  }
  async function api(path, options = {}) {
    const settings = {...options, headers: {...(options.headers || {})}};
    if (settings.body && !(settings.body instanceof FormData) && typeof settings.body !== 'string') {
      settings.headers['Content-Type'] = 'application/json';
      settings.body = JSON.stringify(settings.body);
    }
    let response;
    try { response = await fetch(path, settings); }
    catch (_) { throw new Error('Cannot reach the workspace. Check your connection and try again.'); }
    const data = await readApiJson(response);
    if (response.status === 401) { location.href = '/login'; throw new Error('Your session expired.'); }
    if (!response.ok) {
      const detail = data.detail;
      const message = Array.isArray(detail) ? detail.map(x => x.msg).join(', ') : (detail || data.message || `Request failed (HTTP ${response.status})`);
      throw new Error(message);
    }
    return data;
  }
  function toast(message, type = 'success') {
    const node = document.createElement('div');
    node.className = `toast ${type}`; node.textContent = message;
    $('#toastStack').append(node);
    setTimeout(() => { node.style.opacity = '0'; node.style.transform = 'translateY(5px)'; setTimeout(() => node.remove(), 180); }, 3600);
  }
  function announceSending(sending) {
    window.dispatchEvent(new CustomEvent('synapse:sending', {detail:{sending}}));
  }

  function setTheme(theme) {
    state.theme = theme;
    localStorage.setItem('synapse-theme', theme);
    const actual = theme === 'system' ? (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark') : theme;
    document.documentElement.dataset.theme = actual;
    $$('[data-theme-choice]').forEach(button => button.classList.toggle('active', button.dataset.themeChoice === theme));
  }

  function showView(view) {
    state.view = view;
    $$('[data-view-panel]').forEach(panel => panel.classList.toggle('active', panel.dataset.viewPanel === view));
    $$('[data-view]').forEach(button => button.classList.toggle('active', button.classList.contains('nav-item') && button.dataset.view === view));
    $('.topbar').style.display = view === 'chat' ? '' : 'none';
    $('#appShell').classList.remove('sidebar-open');
    closePopovers();
    if (view === 'bots') renderBots();
    if (view === 'files') renderFiles();
  }

  function dateGroup(epoch) {
    const date = new Date(epoch * 1000), now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const day = new Date(date.getFullYear(), date.getMonth(), date.getDate());
    const delta = Math.round((today - day) / 86400000);
    if (delta === 0) return 'Today'; if (delta === 1) return 'Yesterday'; if (delta < 7) return 'Previous 7 days'; return 'Older';
  }
  function renderConversations() {
    const root = $('#conversationList');
    $('#conversationCount').textContent = state.conversations.length;
    if (!state.conversations.length) { root.innerHTML = '<div class="context-empty">No conversations yet.<br>Start a new chat to begin.</div>'; return; }
    const groups = {};
    state.conversations.forEach(conversation => (groups[dateGroup(conversation.updated_at)] ||= []).push(conversation));
    root.innerHTML = Object.entries(groups).map(([group, conversations]) => `
      <div class="conversation-group-label">${group}</div>
      ${conversations.map(conversation => `<div class="conversation-item ${state.conversation?.id === conversation.id ? 'active' : ''}" data-conversation-id="${attr(conversation.id)}">
        <span class="conversation-copy"><strong>${escapeHtml(conversation.title)}</strong><small>${escapeHtml((conversation.preview || 'No messages yet').slice(0, 65))}</small></span>
        <button class="conversation-more" data-action="conversation-item-menu" data-id="${attr(conversation.id)}" aria-label="Options">•••</button>
      </div>`).join('')}`).join('');
  }
  async function loadConversations(query = '') {
    const data = await api(`/api/conversations${query ? `?q=${encodeURIComponent(query)}` : ''}`);
    state.conversations = data.conversations || []; renderConversations();
  }
  async function newConversation(botIds = null) {
    const ids = botIds || state.activeBots;
    const data = await api('/api/conversations', {method:'POST', body:{title:'New conversation', bot_ids:ids}});
    state.conversations.unshift(data.conversation);
    await openConversation(data.conversation.id);
    showView('chat'); $('#messageInput').focus();
  }
  async function openConversation(id) {
    const data = await api(`/api/conversations/${encodeURIComponent(id)}`);
    state.conversation = data.conversation;
    state.activeBots = [...(state.conversation.bot_ids || [])];
    state.attachments = [];
    $('#conversationTitle').textContent = state.conversation.title;
    renderConversations(); renderActiveBots(); renderMessages(); renderAttachments(); renderContext();
    showView('chat');
    requestAnimationFrame(() => { const scroller = $('#chatScroll'); scroller.scrollTop = scroller.scrollHeight; });
  }

  function inlineMarkdown(text) {
    return text
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/__([^_]+)__/g, '<strong>$1</strong>')
      .replace(/(^|\s)\*([^*\n]+)\*/g, '$1<em>$2</em>');
  }
  function renderMarkdown(markdown = '') {
    const blocks = [];
    let source = String(markdown).replace(/```([\w+-]*)\n?([\s\S]*?)```/g, (_, lang, code) => {
      const index = blocks.length;
      blocks.push(`<div class="code-block"><div class="code-head"><span>${escapeHtml(lang || 'code')}</span><button data-action="copy-code">Copy</button></div><pre><code>${escapeHtml(code.replace(/\n$/, ''))}</code></pre></div>`);
      return `@@CODEBLOCK${index}@@`;
    });
    source = escapeHtml(source);
    const lines = source.split('\n');
    const out = []; let list = null;
    const closeList = () => { if (list) { out.push(`</${list}>`); list = null; } };
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (/^@@CODEBLOCK\d+@@$/.test(line.trim())) { closeList(); out.push(line.trim()); continue; }
      if (/^\|.+\|$/.test(line.trim()) && i + 1 < lines.length && /^\|?\s*:?-+/.test(lines[i + 1])) {
        closeList(); const headers = line.split('|').filter(Boolean); i += 2; const rows = [];
        while (i < lines.length && /^\|.+\|$/.test(lines[i].trim())) { rows.push(lines[i].split('|').filter(Boolean)); i++; } i--;
        out.push(`<table><thead><tr>${headers.map(x => `<th>${inlineMarkdown(x.trim())}</th>`).join('')}</tr></thead><tbody>${rows.map(row => `<tr>${row.map(x => `<td>${inlineMarkdown(x.trim())}</td>`).join('')}</tr>`).join('')}</tbody></table>`); continue;
      }
      const heading = line.match(/^(#{1,3})\s+(.+)/); if (heading) { closeList(); const level = heading[1].length; out.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`); continue; }
      const quote = line.match(/^&gt;\s?(.*)/); if (quote) { closeList(); out.push(`<blockquote>${inlineMarkdown(quote[1])}</blockquote>`); continue; }
      const unordered = line.match(/^\s*[-*+]\s+(.+)/); const ordered = line.match(/^\s*\d+\.\s+(.+)/);
      if (unordered || ordered) { const wanted = ordered ? 'ol' : 'ul'; if (list !== wanted) { closeList(); out.push(`<${wanted}>`); list = wanted; } out.push(`<li>${inlineMarkdown((unordered || ordered)[1])}</li>`); continue; }
      closeList(); if (!line.trim()) out.push(''); else out.push(`<p>${inlineMarkdown(line)}</p>`);
    }
    closeList();
    let html = out.join('\n');
    blocks.forEach((block, index) => { html = html.replace(`@@CODEBLOCK${index}@@`, block); });
    return html;
  }

  function attachmentMarkup(sources = []) {
    return sources.map(source => `<button class="inline-attachment" data-source="${attr(source)}"><span>▱</span>${escapeHtml(source)}</button>`).join('');
  }
  function messageMarkup(message) {
    if (message.role === 'user') return `<article class="message-row user" data-message-id="${attr(message.id)}"><div>${message.attachments?.length ? `<div class="message-attachments">${attachmentMarkup(message.attachments)}</div>` : ''}<div class="user-bubble">${escapeHtml(message.content)}</div></div></article>`;
    const bot = state.bots.find(item => String(item.id) === String(message.bot_id)) || {name:message.bot_name || 'Assistant', color:'#7967ff', avatar:'✦'};
    const sources = message.sources || [];
    return `<article class="message-row assistant" data-message-id="${attr(message.id)}">
      <div class="message-avatar" style="background:${attr(botColor(bot))}">${escapeHtml(botAvatar(bot))}</div>
      <div class="message-content"><div class="message-author"><strong>${escapeHtml(message.bot_name || bot.name)}</strong><span>Grounded response</span></div>
      <div class="markdown">${renderMarkdown(message.content)}</div>
      ${sources.length ? `<div class="source-list">${sources.map(source => `<button class="source-chip" data-source="${attr(source.source)}"><span>${source.number || '•'}</span>${escapeHtml(source.source)}${source.location ? ` · ${escapeHtml(source.location)}` : ''}</button>`).join('')}</div>` : ''}
      <div class="message-actions"><button data-action="copy-message">▣ Copy</button><button data-action="regenerate" data-id="${attr(message.id)}">↻ Regenerate</button><button data-action="feedback">♡ Helpful</button></div></div></article>`;
  }
  function renderMessages() {
    const messages = state.conversation?.messages || [];
    $('#welcomeState').classList.toggle('hidden', messages.length > 0);
    $('#messageStream').innerHTML = messages.map(messageMarkup).join('');
    $('#conversationTitle').textContent = state.conversation?.title || 'New conversation';
  }
  function renderThinking() {
    const active = state.activeBots.map(id => state.bots.find(bot => String(bot.id) === String(id))).filter(Boolean);
    $('#thinkingStack').innerHTML = state.sending ? active.map(bot => `<div class="thinking-card"><div class="message-avatar" style="background:${attr(botColor(bot))}">${escapeHtml(botAvatar(bot))}</div><span>${escapeHtml(bot.name)} is searching and reading sources</span><span class="thinking-dots"><i></i><i></i><i></i></span></div>`).join('') : '';
  }
  async function streamConversationMessage(conversationId, payload, onEvent) {
    let response;
    try {
      response = await fetch(`/api/conversations/${conversationId}/messages/stream`, {
        method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload),
      });
    } catch (_) { throw new Error('Cannot reach the workspace. Check your connection and try again.'); }
    if (!response.ok) {
      const data = await readApiJson(response);
      if (response.status === 401) { location.href = '/login'; throw new Error('Your session expired.'); }
      throw new Error(data.detail || data.message || `Request failed (HTTP ${response.status})`);
    }
    if (!response.body) throw new Error('Streaming is unavailable in this browser.');
    const reader = response.body.getReader(), decoder = new TextDecoder(); let buffer = '';
    while (true) {
      const {value, done} = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), {stream: !done});
      const lines = buffer.split('\n'); buffer = lines.pop() || '';
      for (const line of lines) {
        if (!line.trim()) continue;
        try { onEvent(JSON.parse(line)); }
        catch (_) { throw new Error('The response stream contained invalid data. Please try again.'); }
      }
      if (done) break;
    }
    if (buffer.trim()) onEvent(JSON.parse(buffer));
  }
  async function sendMessage(prompt = null) {
    if (state.sending) return;
    const input = $('#messageInput'); const content = (prompt ?? input.value).trim();
    if (!content) return;
    if (!state.activeBots.length) { toast('Select at least one bot before sending.', 'error'); toggleBotPicker(); return; }
    if (!state.conversation) await newConversation();
    state.sending = true; announceSending(true); $('#sendButton').disabled = true; input.value = ''; autoGrow(input); renderThinking();
    const optimistic = {id:'temp', role:'user', content, attachments:[...state.attachments]};
    state.conversation.messages ||= []; state.conversation.messages.push(optimistic); renderMessages();
    const scroller = $('#chatScroll'); requestAnimationFrame(() => scroller.scrollTop = scroller.scrollHeight);
    try {
      await streamConversationMessage(state.conversation.id, {content, bot_ids:state.activeBots, attachments:state.attachments}, event => {
        if (event.type === 'assistant' && event.message) {
          state.conversation.messages = state.conversation.messages.filter(message => message.id !== event.message.id);
          state.conversation.messages.push(event.message); renderMessages();
          requestAnimationFrame(() => scroller.scrollTop = scroller.scrollHeight);
        } else if (event.type === 'done' && event.conversation) {
          state.conversation.title = event.conversation.title;
          $('#conversationTitle').textContent = event.conversation.title;
        }
      });
      state.attachments = []; renderAttachments();
      await Promise.all([openConversation(state.conversation.id), loadConversations()]);
    } catch (error) {
      state.conversation.messages = state.conversation.messages.filter(message => message.id !== 'temp'); renderMessages(); toast(error.message, 'error');
    } finally { state.sending = false; announceSending(false); $('#sendButton').disabled = false; renderThinking(); input.focus(); }
  }
  async function regenerate(messageId) {
    if (!state.conversation || state.sending) return;
    state.sending = true; announceSending(true); renderThinking();
    try { await api(`/api/conversations/${state.conversation.id}/messages/${messageId}/regenerate`, {method:'POST'}); await openConversation(state.conversation.id); toast('Response regenerated.'); }
    catch (error) { toast(error.message, 'error'); }
    finally { state.sending = false; announceSending(false); renderThinking(); }
  }

  function renderActiveBots() {
    state.activeBots = state.activeBots.filter(id => state.bots.some(bot => String(bot.id) === String(id) && bot.enabled !== false));
    const active = state.activeBots.map(id => state.bots.find(bot => String(bot.id) === String(id))).filter(Boolean);
    $('#activeBotAvatars').innerHTML = active.slice(0, 3).map(bot => `<span class="mini-avatar" style="background:${attr(botColor(bot))}">${escapeHtml(botAvatar(bot))}</span>`).join('');
    $('#activeBotSummary').textContent = active.length ? (active.length === 1 ? active[0].name : `${active.length} bots active`) : 'Select bots';
    $('#composerBotCount').textContent = `${active.length} bot${active.length === 1 ? '' : 's'}`;
    $('#botPickerList').innerHTML = state.bots.filter(bot => bot.enabled !== false).map(bot => `<button type="button" class="bot-picker-option ${state.activeBots.includes(String(bot.id)) ? 'selected' : ''}" data-bot-id="${attr(bot.id)}" aria-pressed="${state.activeBots.includes(String(bot.id))}"><div class="mini-avatar" style="background:${attr(botColor(bot))}">${escapeHtml(botAvatar(bot))}</div><div class="bot-picker-copy"><strong>${escapeHtml(bot.name)}</strong><small>${escapeHtml(bot.description || `${bot.sources?.length || 0} connected files`)}</small></div><span class="check">✓</span></button>`).join('') || '<div class="context-empty">Create an enabled bot to start chatting.</div>';
    $('#welcomeBots').innerHTML = active.length ? `<div class="welcome-bot-row">${active.map(bot => `<button class="welcome-bot active" data-bot-id="${attr(bot.id)}"><span class="mini-avatar" style="background:${attr(botColor(bot))}">${escapeHtml(botAvatar(bot))}</span>${escapeHtml(bot.name)}</button>`).join('')}</div>` : '';
    renderContext();
  }
  function readyFiles() { return state.files.filter(file => (file.status || 'ready') === 'ready' && (file.chunks || 0) > 0); }
  function maybeShowOnboarding() {
    if (!state.user || readyFiles().length || state.bots.length) return;
    showModal('onboardingModal');
  }
  function onboardingLocked() {
    return !$('#modalBackdrop').hidden && !$('#onboardingModal').hidden;
  }
  async function toggleBot(id) {
    id = String(id); const index = state.activeBots.indexOf(id);
    if (index >= 0) state.activeBots.splice(index, 1); else state.activeBots.push(id);
    renderActiveBots();
    if (state.conversation) {
      try { await api(`/api/conversations/${state.conversation.id}`, {method:'PATCH', body:{bot_ids:state.activeBots}}); state.conversation.bot_ids = [...state.activeBots]; }
      catch (error) { toast(error.message, 'error'); }
    }
  }
  function toggleBotPicker() {
    const picker = $('#botPicker'); picker.hidden = !picker.hidden;
    $('#conversationMenu').hidden = true;
  }

  function renderBots() {
    const search = $('#botSearch').value.toLowerCase();
    const filtered = state.bots.filter(bot => (!search || `${bot.name} ${bot.description}`.toLowerCase().includes(search)) && (state.botFilter === 'all' || (state.botFilter === 'enabled' ? bot.enabled !== false : bot.enabled === false)));
    $('#botCount').textContent = state.bots.length;
    $('#botGrid').innerHTML = filtered.length ? filtered.map(bot => `<article class="bot-card ${bot.enabled === false ? 'disabled' : ''}"><div class="bot-card-top"><div class="bot-avatar" style="background:${attr(botColor(bot))}">${escapeHtml(botAvatar(bot))}</div><div class="bot-card-copy"><strong>${escapeHtml(bot.name)}</strong><span>${bot.enabled === false ? 'Disabled' : 'Available'} · ${bot.sources?.length || 0} source${bot.sources?.length === 1 ? '' : 's'}</span></div><button class="bot-card-menu" data-action="edit-bot" data-id="${attr(bot.id)}">•••</button></div><p class="bot-card-description">${escapeHtml(bot.description || 'No description added yet.')}</p><div class="bot-card-sources">${(bot.sources || []).slice(0, 3).map(source => `<span class="tiny-chip">${escapeHtml(source)}</span>`).join('')}${bot.sources?.length > 3 ? `<span class="tiny-chip">+${bot.sources.length - 3}</span>` : ''}</div><div class="bot-card-actions"><button class="chat-with" data-action="chat-with-bot" data-id="${attr(bot.id)}">Ask this bot</button><button data-action="toggle-bot" data-id="${attr(bot.id)}">${bot.enabled === false ? 'Enable bot' : 'Disable bot'}</button><button data-action="delete-bot" data-id="${attr(bot.id)}">Delete</button></div></article>`).join('') : '<div class="empty-panel"><strong>No bots yet</strong>Upload at least one document, then create a bot and select which files it can answer from.<br><button class="primary-btn clear-primary empty-action" data-action="upload-files"><span class="btn-icon">↥</span><span>Upload files first</span></button></div>';
  }
  function renderBotSourceList(selected = null) {
    const chosen = selected || new Set($$('#botSourceList input:checked').map(input => input.value));
    const query = $('#botSourceSearch').value.toLowerCase();
    const files = readyFiles().filter(file => !query || file.name.toLowerCase().includes(query));
    $('#botSourceList').innerHTML = files.map(file => `<label class="source-option"><input type="checkbox" value="${attr(file.source)}" ${chosen.has(file.source) ? 'checked' : ''}><span class="file-icon">${escapeHtml(extensionOf(file))}</span><span>${escapeHtml(file.name)}</span></label>`).join('') || '<div class="source-empty"><strong>No uploaded documents available.</strong><span>Upload a document first, then come back to select it for this bot.</span><button type="button" class="primary-btn clear-primary" data-action="upload-files"><span class="btn-icon">↥</span><span>Upload files first</span></button></div>';
    updateBotSourceCount();
  }
  function updateBotSourceCount() { $('#botSourceCount').textContent = `${$$('#botSourceList input:checked').length} selected`; }
  function openBotModal(bot = null) {
    if (!bot && !readyFiles().length) { toast('Upload at least one document before creating a bot.', 'error'); showView('files'); setTimeout(() => $('#fileInput').click(), 120); return; }
    closePopovers(); $('#botModalTitle').textContent = bot ? 'Edit bot' : 'Create bot'; $('#botId').value = bot?.id || '';
    $('#saveBotButton').innerHTML = bot ? '<span class="btn-icon">✓</span><span>Save bot changes</span>' : '<span class="btn-icon">✓</span><span>Create bot with selected files</span>';
    $('#botName').value = bot?.name || ''; $('#botDescription').value = bot?.description || ''; $('#botInstructions').value = bot?.instructions || '';
    $('#botEnabled').checked = bot?.enabled !== false; $('#botAvatarButton').textContent = botAvatar(bot || {avatar:'✦'}); $('#botAvatarButton').dataset.avatar = botAvatar(bot || {avatar:'✦'}); $('#botAvatarButton').style.background = botColor(bot || {id:Date.now()});
    renderBotSourceList(new Set(bot?.sources || [])); showModal('botModal'); setTimeout(() => $('#botName').focus(), 50);
  }
  async function saveBot(event) {
    event.preventDefault(); const id = $('#botId').value; const button = $('#saveBotButton'); button.disabled = true;
    const body = {name:$('#botName').value.trim(), description:$('#botDescription').value.trim(), instructions:$('#botInstructions').value.trim(), enabled:$('#botEnabled').checked, avatar:$('#botAvatarButton').dataset.avatar || '✦', color:$('#botAvatarButton').style.backgroundColor || '#7967ff', sources:$$('#botSourceList input:checked').map(input => input.value)};
    if (!body.sources.length) { toast('Select at least one uploaded document for this bot.', 'error'); button.disabled = false; return; }
    try { const data = await api(id ? `/api/chatbots/${id}` : '/api/chatbots', {method:id ? 'PATCH' : 'POST', body}); if (id) state.bots = state.bots.map(bot => String(bot.id) === String(id) ? data.chatbot : bot); else state.bots.push(data.chatbot); closeModal(); renderBots(); renderActiveBots(); if (id) toast('Bot updated instantly.'); else { toast('Bot created.'); showModal('nextStepModal'); } }
    catch (error) { toast(error.message, 'error'); } finally { button.disabled = false; }
  }

  function renderFiles() {
    const query = $('#fileSearch').value.toLowerCase(), ext = $('#fileTypeFilter').value;
    let files = state.files.filter(file => (!query || `${file.name} ${file.source}`.toLowerCase().includes(query)) && (!ext || file.extension === ext));
    const sort = $('#fileSort').value; files.sort((a,b) => sort === 'name' ? a.name.localeCompare(b.name) : sort === 'oldest' ? a.created_at-b.created_at : sort === 'size' ? b.size_bytes-a.size_bytes : b.updated_at-a.updated_at);
    const root = $('#fileList'); root.classList.toggle('grid', state.fileView === 'grid'); $('#fileCount').textContent = state.files.length;
    root.innerHTML = files.length ? files.map(file => `<article class="file-row" data-file-id="${attr(file.id)}"><div class="file-primary"><span class="file-icon">${escapeHtml(extensionOf(file))}</span><div class="file-copy"><strong>${escapeHtml(file.name)}</strong><span>${escapeHtml(file.mime_type || file.extension || 'Document')}${file.bots?.length ? ` · Used by ${escapeHtml(file.bots.join(', '))}` : ''}</span></div></div><span class="file-cell">${formatBytes(file.size_bytes)}</span><span class="file-cell">${file.chunks || 0} chunks</span><span class="file-cell">${formatDate(file.created_at)}</span><span class="status-pill ${file.status}">${escapeHtml(file.status || 'ready')}</span><div class="file-actions"><button data-action="attach-file" data-id="${attr(file.id)}" title="Attach">＋</button><button data-action="preview-file" data-id="${attr(file.id)}" title="Preview">◉</button><button data-action="rename-file" data-id="${attr(file.id)}" title="Rename">✎</button><button data-action="delete-file" data-id="${attr(file.id)}" title="Delete">⌫</button></div><div class="file-grid-meta"><span>${formatBytes(file.size_bytes)}</span><span>${file.chunks || 0} chunks</span><span>${formatDate(file.created_at)}</span></div></article>`).join('') : '<div class="empty-panel"><strong>Upload documents first</strong>Your bot needs at least one document before it can be created. You can add more documents here later.<br><button class="primary-btn clear-primary empty-action" data-action="upload-files"><span class="btn-icon">↥</span><span>Upload files first</span></button></div>';
    const extensions = [...new Set(state.files.map(file => file.extension).filter(Boolean))].sort(); const current = $('#fileTypeFilter').value;
    $('#fileTypeFilter').innerHTML = '<option value="">All types</option>' + extensions.map(extension => `<option value="${attr(extension)}" ${current === extension ? 'selected' : ''}>${escapeHtml(extension.replace('.','').toUpperCase())}</option>`).join('');
  }
  async function loadFiles() { const data = await api('/api/files'); state.files = data.files || []; renderFiles(); renderAttachments(); renderContext(); }
  function renderAttachments() {
    const items = state.attachments.map(source => state.files.find(file => file.source === source) || {source,name:source,status:'ready'});
    $('#composerAttachments').innerHTML = items.map(file => `<div class="attachment-card"><span class="file-icon">${escapeHtml(extensionOf(file))}</span><div class="attachment-copy"><strong>${escapeHtml(file.name)}</strong><span>${formatBytes(file.size_bytes)} · ${escapeHtml(file.status || 'ready')}</span></div><button data-action="remove-attachment" data-source="${attr(file.source)}">×</button></div>`).join('');
    renderContext();
  }
  function attachFile(file) { if (!file || state.attachments.includes(file.source)) return; state.attachments.push(file.source); renderAttachments(); toast(`${file.name} attached to this conversation.`); showView('chat'); }
  async function uploadFiles(fileList, attachAfter = false) {
    const files = [...fileList]; if (!files.length) { maybeShowOnboarding(); return; }
    const oversized = files.filter(file => file.size > 25 * 1024 * 1024); if (oversized.length) toast(`${oversized[0].name} exceeds 25 MB.`, 'error');
    const allowed = files.filter(file => file.size <= 25 * 1024 * 1024); if (!allowed.length) return;
    const placeholders = allowed.map(file => ({id:`upload-${Math.random()}`,name:file.name,source:file.name,size_bytes:file.size,status:'processing',extension:'.'+file.name.split('.').pop().toLowerCase(),created_at:Date.now()/1000,updated_at:Date.now()/1000,chunks:0}));
    state.files.unshift(...placeholders); renderFiles();
    const form = new FormData(); allowed.forEach(file => form.append('files', file));
    try { const data = await api('/api/ingest/files', {method:'POST', body:form}); const errors = (data.results || []).filter(item => item.status === 'error'); await loadFiles(); if (attachAfter) (data.results || []).filter(item => item.status === 'indexed').forEach(item => { if (!state.attachments.includes(item.source)) state.attachments.push(item.source); }); renderAttachments(); if (errors.length) toast(`${errors.length} file${errors.length > 1 ? 's' : ''} could not be processed: ${errors[0].error}`, 'error'); else { toast(`${allowed.length} file${allowed.length > 1 ? 's' : ''} uploaded and ready.`); if (!attachAfter && !state.bots.length) setTimeout(() => openBotModal(), 350); } }
    catch (error) { state.files = state.files.filter(file => !String(file.id).startsWith('upload-')); renderFiles(); toast(error.message, 'error'); }
    finally { $('#fileInput').value = ''; if (!readyFiles().length && !state.bots.length) setTimeout(maybeShowOnboarding, 250); }
  }
  async function previewFile(file) {
    if (!file) return; showModal('previewModal'); state.currentPreview = file; $('#previewTitle').textContent = file.name; $('#previewIcon').textContent = extensionOf(file); $('#previewMeta').textContent = `${file.mime_type || file.extension || 'Document'} · ${formatBytes(file.size_bytes)} · Uploaded ${formatDate(file.created_at, true)}`; $('#downloadFileButton').href = `/api/files/${encodeURIComponent(file.id)}/download`; $('#previewStats').innerHTML = '<span class="stat-card"><strong>Loading…</strong><span>Preview</span></span>'; $('#previewBody').textContent = 'Preparing preview…';
    try { const data = await api(`/api/files/${encodeURIComponent(file.id)}/preview`); state.currentPreview = data.file; renderPreview(data.file, data.content || ''); }
    catch (error) { $('#previewBody').textContent = error.message; $('#previewStats').innerHTML = ''; }
  }
  function renderPreview(file, content) {
    const meta = file.metadata || {}; const stats = [];
    if (meta.rows != null) stats.push(['Rows', meta.rows]); if (meta.columns != null) stats.push(['Columns', meta.columns]); if (file.chunks != null) stats.push(['Chunks', file.chunks]); if (meta.characters) stats.push(['Characters', meta.characters.toLocaleString()]); if (meta.sections) stats.push(['Sections', meta.sections]);
    $('#previewStats').innerHTML = stats.map(([label,value]) => `<span class="stat-card"><strong>${escapeHtml(value)}</strong><span>${escapeHtml(label)}</span></span>`).join('');
    const root = $('#previewBody'); root.className = 'preview-body';
    if (meta.preview_rows?.length) { const rows = meta.preview_rows; const headers = rows[0] || []; root.innerHTML = `<div class="data-table-wrap"><table class="data-table"><thead><tr><th>#</th>${headers.map(cell => `<th>${escapeHtml(cell)}</th>`).join('')}</tr></thead><tbody>${rows.slice(1).map((row,index) => `<tr><td>${index+1}</td>${row.map(cell => `<td>${escapeHtml(cell)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`; return; }
    if (codeExtensions.has(extensionOf(file).toLowerCase())) { root.classList.add('code-view'); root.innerHTML = content.split('\n').map(line => `<span class="code-line">${escapeHtml(line) || ' '}</span>`).join(''); }
    else if (['MD','MARKD'].includes(extensionOf(file))) root.innerHTML = `<div class="markdown">${renderMarkdown(content)}</div>`;
    else root.textContent = content || 'No preview is available for this file.';
  }

  function renderContext() {
    const active = state.activeBots.map(id => state.bots.find(bot => String(bot.id) === String(id))).filter(Boolean);
    $('#contextBots').innerHTML = active.length ? active.map(bot => `<div class="context-bot"><div class="mini-avatar" style="background:${attr(botColor(bot))}">${escapeHtml(botAvatar(bot))}</div><div class="context-item-copy"><strong>${escapeHtml(bot.name)}</strong><span>${bot.sources?.length || 0} knowledge sources</span></div><button class="icon-btn" data-bot-id="${attr(bot.id)}">×</button></div>`).join('') : '<div class="context-empty">No bots selected.</div>';
    const files = state.attachments.map(source => state.files.find(file => file.source === source)).filter(Boolean);
    $('#contextFiles').innerHTML = files.length ? files.map(file => `<button class="context-file" data-action="preview-file" data-id="${attr(file.id)}"><span class="file-icon">${escapeHtml(extensionOf(file))}</span><span class="context-item-copy"><strong>${escapeHtml(file.name)}</strong><span>${formatBytes(file.size_bytes)} · ${file.chunks || 0} chunks</span></span></button>`).join('') : '<div class="context-empty">Attach files from the composer or Files workspace.</div>';
    const sources = [...new Set((state.conversation?.messages || []).flatMap(message => (message.sources || []).map(source => source.source)))].slice(-10).reverse();
    $('#contextSources').innerHTML = sources.length ? sources.map(source => `<button class="context-source" data-source="${attr(source)}"><span>▱</span><span class="context-item-copy"><strong>${escapeHtml(source)}</strong><span>Used in this conversation</span></span></button>`).join('') : '<div class="context-empty">Sources cited by responses will appear here.</div>';
  }

  function showModal(id) { $('#modalBackdrop').hidden = false; $$('.modal').forEach(modal => modal.hidden = modal.id !== id); }
  function closeModal() { if (onboardingLocked()) return; $('#modalBackdrop').hidden = true; $$('.modal').forEach(modal => modal.hidden = true); state.textModalAction = null; }
  function openTextModal(title, label, value, action) { $('#textModalTitle').textContent = title; $('#textModalLabel').textContent = label; $('#textModalInput').value = value || ''; state.textModalAction = action; showModal('textModal'); setTimeout(() => { $('#textModalInput').focus(); $('#textModalInput').select(); }, 40); }
  function confirmAction(title, text, action) { $('#confirmTitle').textContent = title; $('#confirmText').textContent = text; state.confirmAction = action; showModal('confirmModal'); }
  function closePopovers() { $('#botPicker').hidden = true; $('#conversationMenu').hidden = true; }
  function autoGrow(input) { input.style.height = 'auto'; input.style.height = `${Math.min(input.scrollHeight, 180)}px`; }
  function fileBySource(source) { return state.files.find(file => file.source === source); }

  async function initialize() {
    setTheme(state.theme);
    try {
      const [me, bots, files, conversations] = await Promise.all([api('/api/auth/me'), api('/api/chatbots'), api('/api/files'), api('/api/conversations')]);
      state.user = me.user; state.bots = bots.chatbots || []; state.files = files.files || []; state.conversations = conversations.conversations || [];
      state.activeBots = state.bots.filter(bot => bot.enabled !== false).slice(0, 1).map(bot => String(bot.id));
      $('#accountName').textContent = state.user.name || state.user.email?.split('@')[0] || 'Your workspace'; $('#accountEmail').textContent = state.user.email || 'Authenticated'; $('#settingsEmail').textContent = state.user.email || 'Authenticated user'; $('#accountAvatar').textContent = initials(state.user.name || state.user.email || 'U');
      renderConversations(); renderActiveBots(); renderBots(); renderFiles(); renderContext(); maybeShowOnboarding();
    } catch (error) { toast(error.message, 'error'); }
  }

  document.addEventListener('click', async event => {
    const viewButton = event.target.closest('[data-view]'); if (viewButton) showView(viewButton.dataset.view);
    const conversationItem = event.target.closest('.conversation-item'); if (conversationItem && !event.target.closest('button')) { try { await openConversation(conversationItem.dataset.conversationId); } catch (error) { toast(error.message,'error'); } return; }
    const botOption = event.target.closest('[data-bot-id]'); if (botOption) { await toggleBot(botOption.dataset.botId); return; }
    const sourceButton = event.target.closest('[data-source]'); if (sourceButton && !sourceButton.matches('[data-action="remove-attachment"]')) { const file = fileBySource(sourceButton.dataset.source); if (file) previewFile(file); return; }
    const actionElement = event.target.closest('[data-action]'); if (!actionElement) { if (!event.target.closest('.popover')) closePopovers(); return; }
    const action = actionElement.dataset.action, id = actionElement.dataset.id;
    try {
      if (action === 'new-chat') await newConversation();
      else if (action === 'open-sidebar') $('#appShell').classList.add('sidebar-open');
      else if (action === 'close-sidebar') $('#appShell').classList.remove('sidebar-open');
      else if (action === 'toggle-context') $('#appShell').classList.toggle('context-open'), $('#appShell').classList.toggle('context-closed');
      else if (action === 'toggle-theme') setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
      else if (action === 'toggle-bot-picker') toggleBotPicker();
      else if (action === 'conversation-menu') { $('#conversationMenu').hidden = !$('#conversationMenu').hidden; $('#botPicker').hidden = true; }
      else if (action === 'send') await sendMessage();
      else if (action === 'upload-onboarding') { $('#modalBackdrop').hidden = true; $$('.modal').forEach(modal => modal.hidden = true); state.uploadTarget = 'files'; showView('files'); $('#fileInput').click(); }
      else if (action === 'upload-chat') { state.uploadTarget = 'chat'; $('#fileInput').click(); }
      else if (action === 'upload-files') { state.uploadTarget = 'files'; $('#fileInput').click(); }
      else if (action === 'create-bot') openBotModal();
      else if (action === 'edit-bot') openBotModal(state.bots.find(bot => String(bot.id) === String(id)));
      else if (action === 'cycle-avatar') { const current = actionElement.dataset.avatar || '✦'; const index = (avatars.indexOf(current) + 1) % avatars.length; actionElement.dataset.avatar = avatars[index]; actionElement.textContent = avatars[index]; actionElement.style.background = colors[index % colors.length]; }
      else if (action === 'chat-with-bot') { state.activeBots = [String(id)]; renderActiveBots(); await newConversation([String(id)]); }
      else if (action === 'toggle-bot') { const bot = state.bots.find(item => String(item.id) === String(id)); const data = await api(`/api/chatbots/${id}`, {method:'PATCH', body:{enabled:bot.enabled === false}}); state.bots = state.bots.map(item => String(item.id) === String(id) ? data.chatbot : item); renderBots(); renderActiveBots(); toast(`${bot.name} ${bot.enabled === false ? 'enabled' : 'disabled'}.`); }
      else if (action === 'delete-bot') { const bot = state.bots.find(item => String(item.id) === String(id)); confirmAction('Delete bot?', `${bot.name} will be removed. Your files will remain available.`, async () => { await api(`/api/chatbots/${id}`, {method:'DELETE'}); state.bots = state.bots.filter(item => String(item.id) !== String(id)); state.activeBots = state.activeBots.filter(botId => botId !== String(id)); closeModal(); renderBots(); renderActiveBots(); toast('Bot deleted.'); }); }
      else if (action === 'preview-file') previewFile(state.files.find(file => String(file.id) === String(id)));
      else if (action === 'attach-file') attachFile(state.files.find(file => String(file.id) === String(id)));
      else if (action === 'remove-attachment') { state.attachments = state.attachments.filter(source => source !== actionElement.dataset.source); renderAttachments(); }
      else if (action === 'rename-file') { const file = state.files.find(item => String(item.id) === String(id)); openTextModal('Rename file', 'File name', file.name, async name => { const data = await api(`/api/files/${id}`, {method:'PATCH', body:{name}}); state.files = state.files.map(item => String(item.id) === String(id) ? data.file : item); closeModal(); renderFiles(); toast('File renamed.'); }); }
      else if (action === 'delete-file') { const file = state.files.find(item => String(item.id) === String(id)); confirmAction('Delete file?', `${file.name} and its indexed knowledge will be removed immediately.`, async () => { await api(`/api/files/${id}`, {method:'DELETE'}); state.files = state.files.filter(item => String(item.id) !== String(id)); state.attachments = state.attachments.filter(source => source !== file.source); closeModal(); renderFiles(); renderAttachments(); toast('File deleted.'); }); }
      else if (action === 'rename-conversation' && state.conversation) openTextModal('Rename conversation', 'Conversation title', state.conversation.title, async title => { const data = await api(`/api/conversations/${state.conversation.id}`, {method:'PATCH', body:{title}}); state.conversation.title = data.conversation.title; closeModal(); $('#conversationTitle').textContent = data.conversation.title; await loadConversations(); toast('Conversation renamed.'); });
      else if (action === 'delete-conversation' && state.conversation) confirmAction('Delete conversation?', 'The complete message history will be permanently removed.', async () => { const idToDelete = state.conversation.id; await api(`/api/conversations/${idToDelete}`, {method:'DELETE'}); state.conversation = null; state.conversations = state.conversations.filter(item => item.id !== idToDelete); closeModal(); renderConversations(); renderMessages(); $('#conversationTitle').textContent = 'New conversation'; toast('Conversation deleted.'); });
      else if (action === 'conversation-item-menu') { const conversation = state.conversations.find(item => item.id === id); openTextModal('Rename conversation', 'Conversation title', conversation.title, async title => { await api(`/api/conversations/${id}`, {method:'PATCH', body:{title}}); closeModal(); await loadConversations(); toast('Conversation renamed.'); }); }
      else if (action === 'regenerate') await regenerate(id);
      else if (action === 'copy-message') { const content = actionElement.closest('.message-content').querySelector('.markdown').innerText; await navigator.clipboard.writeText(content); actionElement.textContent = '✓ Copied'; setTimeout(() => actionElement.textContent = '▣ Copy', 1300); }
      else if (action === 'copy-code') { await navigator.clipboard.writeText(actionElement.closest('.code-block').querySelector('code').innerText); actionElement.textContent = 'Copied'; setTimeout(() => actionElement.textContent = 'Copy', 1200); }
      else if (action === 'feedback') { actionElement.textContent = '♥ Thanks'; }
      else if (action === 'fullscreen-preview') $('#previewModal').classList.toggle('fullscreen');
      else if (action === 'add-url') openTextModal('Add website', 'Website URL', 'https://', async url => { const data = await api('/api/ingest/url', {method:'POST', body:{url}}); closeModal(); await loadFiles(); toast(`${data.source} indexed and ready.`); });
      else if (action === 'next-start-chat') { closeModal(); if (state.bots.length) { state.activeBots = [String(state.bots[state.bots.length - 1].id)]; renderActiveBots(); await newConversation([...state.activeBots]); } }
      else if (action === 'add-more-docs') { closeModal(); showView('files'); state.uploadTarget = 'files'; setTimeout(() => $('#fileInput').click(), 80); }
      else if (action === 'close-modal') closeModal();
      else if (action === 'logout') { await api('/api/auth/logout', {method:'POST'}); location.href = '/login'; }
    } catch (error) { toast(error.message, 'error'); }
  });

  $('#messageInput').addEventListener('input', event => autoGrow(event.target));
  $('#messageInput').addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); sendMessage(); } });
  $('#fileInput').addEventListener('change', event => uploadFiles(event.target.files, state.uploadTarget === 'chat'));
  $('#conversationSearch').addEventListener('input', debounce(event => loadConversations(event.target.value).catch(error => toast(error.message,'error'))));
  $('#botSearch').addEventListener('input', renderBots); $('#botSourceSearch').addEventListener('input', () => renderBotSourceList()); $('#botSourceList').addEventListener('change', updateBotSourceCount);
  $('#fileSearch').addEventListener('input', renderFiles); $('#fileTypeFilter').addEventListener('change', renderFiles); $('#fileSort').addEventListener('change', renderFiles);
  $('#botForm').addEventListener('submit', saveBot);
  $('#textModalForm').addEventListener('submit', async event => { event.preventDefault(); if (!state.textModalAction) return; const action = state.textModalAction; const value = $('#textModalInput').value.trim(); if (!value) return; try { await action(value); } catch (error) { toast(error.message,'error'); } });
  $('#confirmButton').addEventListener('click', async () => { if (!state.confirmAction) return; const action = state.confirmAction; $('#confirmButton').disabled = true; try { await action(); } catch (error) { toast(error.message,'error'); } finally { $('#confirmButton').disabled = false; state.confirmAction = null; } });
  $('#previewSearch').addEventListener('input', event => { if (!state.currentPreview) return; const body = $('#previewBody'), query = event.target.value.trim().toLowerCase(); if (!query) { api(`/api/files/${state.currentPreview.id}/preview`).then(data => renderPreview(data.file,data.content)); $('#previewMatches').textContent=''; return; } const text = body.innerText; const count = text.toLowerCase().split(query).length - 1; $('#previewMatches').textContent = `${count} match${count===1?'':'es'}`; });
  $$('[data-bot-filter]').forEach(button => button.addEventListener('click', () => { state.botFilter = button.dataset.botFilter; $$('[data-bot-filter]').forEach(item => item.classList.toggle('active', item === button)); renderBots(); }));
  $$('[data-file-view]').forEach(button => button.addEventListener('click', () => { state.fileView = button.dataset.fileView; localStorage.setItem('synapse-file-view', state.fileView); $$('[data-file-view]').forEach(item => item.classList.toggle('active', item === button)); renderFiles(); }));
  $$('[data-theme-choice]').forEach(button => button.addEventListener('click', () => setTheme(button.dataset.themeChoice)));
  $$('.quick-action[data-prompt]').forEach(button => button.addEventListener('click', () => { $('#messageInput').value = button.dataset.prompt; autoGrow($('#messageInput')); $('#messageInput').focus(); }));
  window.addEventListener('magicui:prompt', event => {
    const prompt = event.detail?.prompt || '';
    if (!prompt) return;
    $('#messageInput').value = prompt;
    autoGrow($('#messageInput'));
    $('#messageInput').focus();
  });
  $('#mobileScrim').addEventListener('click', () => $('#appShell').classList.remove('sidebar-open'));
  $('#modalBackdrop').addEventListener('click', event => { if (event.target === $('#modalBackdrop') && !onboardingLocked()) closeModal(); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') { closePopovers(); if (!$('#modalBackdrop').hidden && !onboardingLocked()) closeModal(); } if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); newConversation().catch(error => toast(error.message,'error')); } });
  ['composerDropzone','fileDropzone'].forEach(id => { const node = $('#'+id); ['dragenter','dragover'].forEach(type => node.addEventListener(type, event => { event.preventDefault(); node.classList.add('drag-active'); })); ['dragleave','drop'].forEach(type => node.addEventListener(type, event => { event.preventDefault(); node.classList.remove('drag-active'); })); node.addEventListener('drop', event => uploadFiles(event.dataTransfer.files, id === 'composerDropzone')); });
  matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => { if (state.theme === 'system') setTheme('system'); });

  initialize();
})();
