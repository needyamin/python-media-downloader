const $ = (s) => document.querySelector(s);
let currentUrl = '';
let pollTimer = null;
let playlistEntries = [];
let selectedUrl = '';

const PHASE = {
  starting: 'Preparing',
  downloading: 'Downloading',
  processing: 'Processing',
  converting: 'Converting',
  done: 'Done',
  error: 'Failed',
};

function showError(msg) {
  $('#error').textContent = msg;
  $('#error').classList.remove('hidden');
}

function hideError() {
  $('#error').classList.add('hidden');
}

function getCsrf() {
  return document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
}

async function post(url, body) {
  const r = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': getCsrf(),
    },
    body: JSON.stringify(body),
  });
  const text = await r.text();
  let data = null;
  try {
    data = JSON.parse(text);
  } catch {
    const snippet = text.slice(0, 120).replace(/<[^>]+>/g, ' ');
    throw new Error(snippet || `Server error (${r.status})`);
  }
  if (!r.ok) throw new Error(data.error || 'Request failed');
  return data;
}

function fmtTime(sec) {
  if (!sec) return '';
  return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}`;
}

function setBadges(info) {
  const el = $('#badges');
  const tags = [];
  if (info.duration) tags.push(`<span class="badge">${fmtTime(info.duration)}</span>`);
  if (info.is_live) tags.push('<span class="badge live">LIVE</span>');
  if (info.is_playlist) tags.push(`<span class="badge">Playlist · ${info.entry_count || '?'}</span>`);
  if (info.is_stream) tags.push('<span class="badge">Stream</span>');
  el.innerHTML = tags.join('');
}

function fillFormats(selectId, formats) {
  const sel = $(selectId);
  sel.innerHTML = formats.map(f => `<option value="${f.format_id}">${f.label}</option>`).join('');
  if (formats.length) sel.selectedIndex = 0;
}

function showVideoPanel(info) {
  currentUrl = info.selected_url || currentUrl;
  selectedUrl = currentUrl;
  $('#title').textContent = info.title;
  const thumb = $('#thumb');
  if (info.thumbnail) {
    thumb.src = info.thumbnail;
    thumb.classList.remove('hidden');
  } else {
    thumb.classList.add('hidden');
  }
  setBadges(info);
  $('#note').textContent = info.note || '';
  $('#note').classList.toggle('hidden', !info.note);
  $('#live-opt').classList.toggle('hidden', !info.is_live);
  document.querySelector('.stream-only')?.classList.toggle('hidden', !info.is_stream);

  const videos = (info.formats || []).filter(f => f.kind === 'video');
  const audios = (info.formats || []).filter(f => f.kind === 'audio');
  fillFormats('#video-formats', videos);
  fillFormats('#audio-formats', audios);
  $('#video-fmt-box').classList.toggle('hidden', !videos.length);
  $('#audio-fmt-box').classList.toggle('hidden', !audios.length);
  $('#quality-box').classList.toggle('hidden', !videos.length && !audios.length);

  document.querySelectorAll('.playlist-item').forEach(el => {
    el.classList.toggle('active', el.dataset.url === selectedUrl);
  });
}

function renderPlaylist(info) {
  const box = $('#playlist-box');
  if (!info.is_playlist || !info.entries?.length) {
    box.classList.add('hidden');
    playlistEntries = [];
    return;
  }
  playlistEntries = info.entries;
  $('#playlist-heading').textContent = info.playlist_title || 'Playlist';
  const list = $('#playlist-list');
  list.innerHTML = info.entries.map(e => `
    <li class="playlist-item${e.url === info.selected_url ? ' active' : ''}" data-url="${e.url}">
      ${e.thumbnail ? `<img src="${e.thumbnail}" alt="" class="pl-thumb">` : ''}
      <span class="pl-num">${e.index}</span>
      <span class="pl-title">${e.title}${e.duration ? ` · ${fmtTime(e.duration)}` : ''}</span>
    </li>
  `).join('');
  box.classList.remove('hidden');
  list.querySelectorAll('.playlist-item').forEach(el => {
    el.addEventListener('click', () => selectPlaylistVideo(el.dataset.url));
  });
}

async function selectPlaylistVideo(url) {
  if (!url || url === selectedUrl) return;
  hideError();
  document.querySelectorAll('.playlist-item').forEach(b => b.classList.add('loading'));
  try {
    const info = await post('/info/', { url, video_url: url });
    showVideoPanel(info);
  } catch (err) {
    showError(err.message);
  } finally {
    document.querySelectorAll('.playlist-item').forEach(b => b.classList.remove('loading'));
  }
}

function setProgress(job) {
  $('#progress-panel').classList.remove('hidden');
  $('#phase-label').textContent = PHASE[job.phase] || job.phase;
  const pct = job.percent || 0;
  $('#percent-label').textContent = job.status === 'done' ? '100%' : `${pct}%`;
  $('#bar-fill').style.width = `${job.status === 'done' ? 100 : pct}%`;
  $('#progress-msg').textContent = job.message || '';
  $('#progress-meta').textContent = [job.speed, job.eta && `ETA ${job.eta}`].filter(Boolean).join(' · ');

  if (job.status === 'done') {
    $('#done-box').classList.remove('hidden');
    $('#dl-link').href = job.url;
    $('#dl-link').textContent = job.filename ? `Save: ${job.filename}` : 'Save to device';
    startExpireCountdown(job.delete_at);
    $('#progress-panel').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  } else {
    $('#done-box').classList.add('hidden');
  }
}

function startExpireCountdown(deleteAt) {
  if (!deleteAt) return;
  const el = $('#expire-note');
  const tick = () => {
    const left = Math.max(0, Math.ceil(deleteAt - Date.now() / 1000));
    if (left <= 0) { el.textContent = 'Removed from server'; return; }
    el.textContent = `Auto-delete in ${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}`;
    setTimeout(tick, 1000);
  };
  tick();
}

async function pollStatus(taskId) {
  const r = await fetch(`/status/${taskId}/`);
  const job = await r.json();
  if (!r.ok) throw new Error(job.error || 'Status failed');
  setProgress(job);
  if (job.status === 'done' || job.status === 'error') {
    clearInterval(pollTimer);
    pollTimer = null;
    document.querySelectorAll('.btn.dl, .btn.primary').forEach(b => { if (b.id !== 'btn-info') b.disabled = false; });
    if (job.status === 'error') showError(job.error || job.message);
  }
}

$('#form').addEventListener('submit', async (e) => {
  e.preventDefault();
  hideError();
  $('#result').classList.add('hidden');
  $('#progress-panel').classList.add('hidden');
  playlistEntries = [];
  currentUrl = normalizeUrl($('#url').value);
  if (!currentUrl) { showError('Enter a valid URL'); return; }
  $('#url').value = currentUrl;
  const btn = $('#btn-info');
  btn.disabled = true;
  btn.textContent = 'Loading...';
  try {
    const info = await post('/info/', { url: currentUrl });
    renderPlaylist(info);
    showVideoPanel(info);
    $('#result').classList.remove('hidden');
    $('#result').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (err) {
    showError(err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Get Info';
  }
});

async function doDownload(fmt) {
  if (!currentUrl) { showError('Select a video first'); return; }
  hideError();
  $('#done-box').classList.add('hidden');
  $('#progress-panel').classList.remove('hidden');
  setProgress({ phase: 'starting', percent: 0, message: 'Starting...', status: 'running' });
  document.querySelectorAll('.btn.dl').forEach(b => b.disabled = true);
  $('#progress-panel').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  try {
    const { task_id } = await post('/download/', {
      url: currentUrl,
      format: fmt,
      live_from_start: $('#live-start').checked,
    });
    pollTimer = setInterval(() => pollStatus(task_id), 800);
    await pollStatus(task_id);
  } catch (err) {
    showError(err.message);
    document.querySelectorAll('.btn.dl').forEach(b => b.disabled = false);
  }
}

document.querySelectorAll('.btn.dl[data-fmt]').forEach(btn => {
  btn.addEventListener('click', () => doDownload(btn.dataset.fmt));
});

$('#btn-video-fmt').addEventListener('click', () => {
  const id = $('#video-formats').value;
  doDownload(id.includes('+') ? id : `${id}+bestaudio/best`);
});

$('#btn-audio-fmt').addEventListener('click', () => doDownload($('#audio-formats').value));

function normalizeUrl(raw) {
  let s = (raw || '').trim();
  if (!s) return '';
  if (!/^https?:\/\//i.test(s)) s = 'https://' + s;
  return s;
}

function setUrlInput(raw) {
  const s = normalizeUrl(raw);
  if (!s) return false;
  $('#url').value = s;
  hideError();
  return true;
}

async function pasteLink() {
  const input = $('#url');
  try {
    if (navigator.clipboard?.readText) {
      const text = await navigator.clipboard.readText();
      if (setUrlInput(text)) {
        input.focus();
        return;
      }
    }
  } catch { /* fallback below */ }

  input.focus();
  input.select();
  const onPaste = (e) => {
    const text = e.clipboardData?.getData('text');
    if (text && setUrlInput(text)) e.preventDefault();
  };
  input.addEventListener('paste', onPaste, { once: true });
  showError('Press Ctrl+V to paste your link');
}

$('#btn-paste').addEventListener('click', pasteLink);
