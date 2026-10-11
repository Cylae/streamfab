/**
 * StreamFab Modern Web Application Logic
 * Real-time SSE streaming, responsive UI orchestration, media player integration
 * 100% English Localization
 */

(function () {
  'use strict';

  class StreamFabApp {
    constructor() {
      this.state = {
        mediaType: 'audio',
        audioCodec: 'mp3',
        audioBitrate: '320k',
        videoFormat: 'mp4',
        videoQuality: 'best',
        currentMedia: null,
        activeTaskId: null,
        eventSource: null,
        useClientCompute: true,
        isProcessing: false,
        operationId: 0,
        blobUrl: null,
      };

      this.dom = {};
      this.init();
    }

    init() {
      this.cacheDom();
      this.bindEvents();
      this.initTheme();
      this.refreshCookieStatus();
    }

    cacheDom() {
      this.dom.html = document.documentElement;
      this.dom.themeToggleBtn = document.getElementById('themeToggleBtn');
      this.dom.urlForm = document.getElementById('urlForm');
      this.dom.urlInput = document.getElementById('urlInput');
      this.dom.pasteBtn = document.getElementById('pasteBtn');
      this.dom.clearBtn = document.getElementById('clearBtn');
      this.dom.analyzeBtn = document.getElementById('analyzeBtn');
      this.dom.btnText = this.dom.analyzeBtn.querySelector('.btn-text');
      this.dom.btnSpinner = this.dom.analyzeBtn.querySelector('.btn-spinner');

      this.dom.errorAlert = document.getElementById('errorAlert');
      this.dom.errorMessage = document.getElementById('errorMessage');

      this.dom.inspectorSection = document.getElementById('inspectorSection');
      this.dom.mediaThumbnail = document.getElementById('mediaThumbnail');
      this.dom.durationBadge = document.getElementById('durationBadge');
      this.dom.togglePreviewBtn = document.getElementById('togglePreviewBtn');
      this.dom.previewPlayerContainer = document.getElementById('previewPlayerContainer');
      this.dom.previewVideoPlayer = document.getElementById('previewVideoPlayer');

      this.dom.mediaTitle = document.getElementById('mediaTitle');
      this.dom.mediaUploader = document.getElementById('mediaUploader').querySelector('.uploader-name');
      this.dom.mediaViews = document.getElementById('mediaViews').querySelector('.views-count');

      this.dom.tabAudio = document.getElementById('tabAudio');
      this.dom.tabVideo = document.getElementById('tabVideo');
      this.dom.audioOptionsPanel = document.getElementById('audioOptionsPanel');
      this.dom.videoOptionsPanel = document.getElementById('videoOptionsPanel');
      this.dom.videoResolutionsGrid = document.getElementById('videoResolutionsGrid');

      this.dom.trimmerAccordionBtn = document.getElementById('trimmerAccordionBtn');
      this.dom.trimmerPanel = document.getElementById('trimmerPanel');
      this.dom.trimmerAccIcon = document.getElementById('trimmerAccIcon');
      this.dom.trimStartInput = document.getElementById('trimStartInput');
      this.dom.trimEndInput = document.getElementById('trimEndInput');

      this.dom.subtitleSelect = document.getElementById('subtitleSelect');
      this.dom.embedMetaCheck = document.getElementById('embedMetaCheck');

      this.dom.playlistContainer = document.getElementById('playlistContainer');
      this.dom.playlistCount = document.getElementById('playlistCount');
      this.dom.playlistList = document.getElementById('playlistList');

      this.dom.startConvertBtn = document.getElementById('startConvertBtn');
      this.dom.convertBtnLabel = document.getElementById('convertBtnLabel');

      this.dom.progressSection = document.getElementById('progressSection');
      this.dom.progressDetail = document.getElementById('progressDetail');
      this.dom.progressPercentBadge = document.getElementById('progressPercentBadge');
      this.dom.progressBarFill = document.getElementById('progressBarFill');
      this.dom.metricSpeed = document.getElementById('metricSpeed');
      this.dom.metricEta = document.getElementById('metricEta');
      this.dom.metricStatus = document.getElementById('metricStatus');
      this.dom.metricCpu = document.getElementById('metricCpu');

      this.dom.downloadReadyActions = document.getElementById('downloadReadyActions');
      this.dom.finalDownloadLink = document.getElementById('finalDownloadLink');
      this.dom.downloadBtnText = document.getElementById('downloadBtnText');
      this.dom.cancelActionRow = document.getElementById('cancelActionRow');

      // Cookie Assistant & Anti-Bot Challenge DOM elements
      this.dom.cookieNavBtn = document.getElementById('cookieNavBtn');
      this.dom.cookieNavDot = document.getElementById('cookieNavDot');
      this.dom.cookieNavLabel = document.getElementById('cookieNavLabel');
      this.dom.botChallengeGuidance = document.getElementById('botChallengeGuidance');
      this.dom.cookieModal = document.getElementById('cookieModal');
      this.dom.cookieModalDot = document.getElementById('cookieModalDot');
      this.dom.cookieModalStatusText = document.getElementById('cookieModalStatusText');
      this.dom.cookieDeleteBtn = document.getElementById('cookieDeleteBtn');
      this.dom.tabUploadFile = document.getElementById('tabUploadFile');
      this.dom.tabPasteText = document.getElementById('tabPasteText');
      this.dom.cookieUploadPane = document.getElementById('cookieUploadPane');
      this.dom.cookiePastePane = document.getElementById('cookiePastePane');
      this.dom.cookieDropzone = document.getElementById('cookieDropzone');
      this.dom.cookieFileInput = document.getElementById('cookieFileInput');
      this.dom.cookieTextarea = document.getElementById('cookieTextarea');
      this.dom.cookieModalAlert = document.getElementById('cookieModalAlert');
    }

    bindEvents() {
      const actions = new Set(['openCookieModal', 'closeCookieModal', 'hideError', 'hideBotGuidance', 'handleAnalyze', 'switchMediaType', 'setAudioCodec', 'setAudioBitrate', 'setVideoFormat', 'toggleTrimmer', 'resetTrimmer', 'toggleAllPlaylist', 'toggleComputeMode', 'startDownload', 'resetAll', 'cancelCurrentTask', 'deleteCookies', 'switchCookieTab', 'savePastedCookies']);
      document.querySelectorAll('[data-action]').forEach((element) => {
        element.addEventListener(element.dataset.event || 'click', (event) => {
          if (event.type === 'submit') event.preventDefault();
          const action = element.dataset.action;
          if (action === 'browseCookies') return this.dom.cookieFileInput.click();
          if (!actions.has(action)) return;
          let arg = element.dataset.arg;
          if (element.dataset.checked) arg = element.checked;
          else if (arg === 'true' || arg === 'false') arg = arg === 'true';
          this[action](arg);
        });
      });
      document.getElementById('cookieAdminToken')?.addEventListener('change', () => this.refreshCookieStatus());
      // Theme toggle
      this.dom.themeToggleBtn.addEventListener('click', () => this.toggleTheme());

      // Input changes & clear button
      this.dom.urlInput.addEventListener('input', () => {
        if (this.dom.urlInput.value.trim().length > 0) {
          this.dom.clearBtn.classList.remove('hidden');
        } else {
          this.dom.clearBtn.classList.add('hidden');
        }
      });

      this.dom.clearBtn.addEventListener('click', () => {
        this.dom.urlInput.value = '';
        this.dom.clearBtn.classList.add('hidden');
        this.dom.urlInput.focus();
      });

      // Paste button
      this.dom.pasteBtn.addEventListener('click', async () => {
        try {
          const text = await navigator.clipboard.readText();
          if (text) {
            this.dom.urlInput.value = text.trim();
            this.dom.clearBtn.classList.remove('hidden');
            this.handleAnalyze();
          }
        } catch (e) {
          this.dom.urlInput.focus();
        }
      });

      // Quick pills
      document.querySelectorAll('.quick-pill').forEach((pill) => {
        pill.addEventListener('click', (e) => {
          document.querySelectorAll('.quick-pill').forEach((p) => p.classList.remove('active'));
          pill.classList.add('active');

          const type = pill.dataset.type;
          const format = pill.dataset.format;
          const quality = pill.dataset.quality;

          this.switchMediaType(type);
          if (type === 'audio') {
            this.setAudioCodec(format);
            if (format === 'mp3') {
              this.setAudioBitrate(quality);
            }
          } else {
            this.setVideoFormat(format);
            this.state.videoQuality = quality;
            if (this.state.currentMedia) this.renderVideoResolutions(this.state.currentMedia.available_video_resolutions || []);
            this.updateConvertButtonLabel();
          }
        });
      });

      // In-app preview player toggle
      this.dom.togglePreviewBtn.addEventListener('click', () => {
        if (!this.state.currentMedia || !this.state.currentMedia.preview_url) {
          alert('Live preview is not available for this stream (media will be converted directly).');
          return;
        }
        const isHidden = this.dom.previewPlayerContainer.classList.contains('hidden');
        if (isHidden) {
          this.dom.previewPlayerContainer.classList.remove('hidden');
          this.dom.previewVideoPlayer.src = this.state.currentMedia.preview_url;
          this.dom.previewVideoPlayer.play().catch(() => {});
        } else {
          this.dom.previewPlayerContainer.classList.add('hidden');
          this.dom.previewVideoPlayer.pause();
        }
      });

      // Cookie Dropzone Drag and Drop
      if (this.dom.cookieDropzone) {
        ['dragenter', 'dragover'].forEach((evtName) => {
          this.dom.cookieDropzone.addEventListener(evtName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            this.dom.cookieDropzone.classList.add('dragover');
          });
        });

        ['dragleave', 'dragend', 'drop'].forEach((evtName) => {
          this.dom.cookieDropzone.addEventListener(evtName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            this.dom.cookieDropzone.classList.remove('dragover');
          });
        });

        this.dom.cookieDropzone.addEventListener('drop', (e) => {
          const files = e.dataTransfer?.files;
          if (files && files.length > 0) {
            const file = files[0];
            const reader = new FileReader();
            reader.onload = (evt) => {
              this.uploadCookieContent(evt.target.result);
            };
            reader.readAsText(file);
          }
        });
      }

      // Cookie File Input change
      if (this.dom.cookieFileInput) {
        this.dom.cookieFileInput.addEventListener('change', (e) => {
          const file = e.target.files?.[0];
          if (file) {
            const reader = new FileReader();
            reader.onload = (evt) => {
              this.uploadCookieContent(evt.target.result);
            };
            reader.readAsText(file);
          }
        });
      }

      // Close modal on background click
      if (this.dom.cookieModal) {
        this.dom.cookieModal.addEventListener('click', (e) => {
          if (e.target === this.dom.cookieModal) {
            this.closeCookieModal();
          }
        });
      }

      // Keyboard Esc to close modal
      document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && this.dom.cookieModal && !this.dom.cookieModal.classList.contains('hidden')) {
          this.closeCookieModal();
        }
      });
    }

    /* ---------------- Theme Management ---------------- */
    initTheme() {
      let saved;
      try { saved = localStorage.getItem('streamfab_theme'); } catch (e) {}
      if (saved) {
        this.setTheme(saved);
      } else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) {
        this.setTheme('light');
      } else {
        this.setTheme('dark');
      }
    }

    setTheme(theme) {
      this.dom.html.setAttribute('data-theme', theme);
      try { localStorage.setItem('streamfab_theme', theme); } catch (e) {}
    }

    toggleTheme() {
      const current = this.dom.html.getAttribute('data-theme') || 'dark';
      const next = current === 'dark' ? 'light' : 'dark';
      this.setTheme(next);
    }

    /* ---------------- Analysis & Metadata ---------------- */
    async handleAnalyze() {
      if (this.state.isProcessing || this.dom.analyzeBtn.disabled) return;
      const url = this.dom.urlInput.value.trim();
      if (!url) return;

      this.state.currentMedia = null;
      this.dom.inspectorSection.classList.add('hidden');
      this.hideError();
      this.hideBotGuidance();
      this.setAnalyzeLoading(true);

      try {
        const res = await fetch('/api/info', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...this.cookieHeaders() },
          body: JSON.stringify({ url }),
        });

        const data = await res.json();
        if (!res.ok || !data.success) {
          throw new Error(data.detail || 'Unable to extract media information.');
        }

        this.hideBotGuidance();
        this.renderMediaInfo(data.data);
      } catch (err) {
        const msg = String(err.message || '');
        const isBotCheck =
          msg.includes('YOUTUBE_BOT_CHECK') ||
          msg.toLowerCase().includes('not a bot') ||
          msg.toLowerCase().includes('verification challenge') ||
          (msg.toLowerCase().includes('bot') && (msg.toLowerCase().includes('sign in') || msg.toLowerCase().includes('cookies')));

        if (isBotCheck) {
          this.showBotGuidance();
        } else {
          this.showError(msg || 'An unexpected error occurred.');
        }
      } finally {
        this.setAnalyzeLoading(false);
      }
    }

    setAnalyzeLoading(loading) {
      if (loading) {
        this.dom.btnText.textContent = 'Analyzing link...';
        this.dom.btnSpinner.classList.remove('hidden');
        this.dom.analyzeBtn.disabled = true;
      } else {
        this.dom.btnText.textContent = 'Analyze & Configure';
        this.dom.btnSpinner.classList.add('hidden');
        this.dom.analyzeBtn.disabled = false;
      }
    }

    showError(msg) {
      this.dom.errorMessage.textContent = msg;
      this.dom.errorAlert.classList.remove('hidden');
    }

    hideError() {
      this.dom.errorAlert.classList.add('hidden');
    }

    showBotGuidance() {
      this.hideError();
      if (this.dom.botChallengeGuidance) {
        this.dom.botChallengeGuidance.classList.remove('hidden');
        this.dom.botChallengeGuidance.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
    }

    hideBotGuidance() {
      if (this.dom.botChallengeGuidance) {
        this.dom.botChallengeGuidance.classList.add('hidden');
      }
    }

    renderMediaInfo(info) {
      this.state.currentMedia = info;
      this.resetTrimmer();
      this.dom.previewVideoPlayer.pause();
      this.dom.previewVideoPlayer.removeAttribute('src');
      this.dom.previewPlayerContainer.classList.add('hidden');
      this.dom.mediaThumbnail.removeAttribute('src');

      // Meta info
      this.dom.mediaTitle.textContent = info.title;
      this.dom.mediaUploader.textContent = info.uploader;
      this.dom.mediaViews.textContent = info.view_count ? `${Number(info.view_count).toLocaleString()} views` : 'Web media';
      this.dom.durationBadge.textContent = info.duration_formatted || '00:00';
      if (info.thumbnail) {
        this.dom.mediaThumbnail.src = info.thumbnail;
      }

      // Trimmer defaults
      if (info.duration) {
        this.dom.trimEndInput.placeholder = info.duration_formatted;
      }

      // Populate Video resolutions
      this.renderVideoResolutions(info.available_video_resolutions || []);

      // Populate Subtitles
      this.renderSubtitles(info.subtitles || []);

      // Handle Playlist
      if (info.is_playlist && info.playlist_entries && info.playlist_entries.length > 0) {
        this.dom.playlistContainer.classList.remove('hidden');
        this.dom.playlistCount.textContent = info.playlist_count;
        this.renderPlaylistEntries(info.playlist_entries);
      } else {
        this.dom.playlistContainer.classList.add('hidden');
      }

      // Update button label
      this.updateConvertButtonLabel();

      // Show Inspector Section and smooth scroll
      this.dom.inspectorSection.classList.remove('hidden');
      this.dom.inspectorSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    renderVideoResolutions(resolutions) {
      this.dom.videoResolutionsGrid.innerHTML = '';
      if (!resolutions.length) {
        resolutions = [{ value: 'best', label: 'Best available resolution' }];
      }

      resolutions.forEach((res, idx) => {
        const selectedIndex = resolutions.findIndex(r => r.value === this.state.videoQuality);
        const isDefault = idx === (selectedIndex >= 0 ? selectedIndex : 0);
        const card = document.createElement('label');
        card.className = `radio-card ${isDefault ? 'active' : ''}`;
        const input = document.createElement('input');
        input.type = 'radio'; input.name = 'videoRes'; input.value = res.value; input.checked = isDefault;
        const content = document.createElement('span'); content.className = 'card-content';
        const title = document.createElement('span'); title.className = 'card-title'; title.textContent = res.label;
        const desc = document.createElement('span'); desc.className = 'card-desc'; desc.textContent = res.height ? `${res.height}p Original stream` : 'Optimal';
        content.append(title, desc); card.append(input, content);
        card.querySelector('input').addEventListener('change', () => {
          this.dom.videoResolutionsGrid.querySelectorAll('.radio-card').forEach((c) => c.classList.remove('active'));
          card.classList.add('active');
          this.state.videoQuality = res.value;
          this.updateConvertButtonLabel();
        });
        this.dom.videoResolutionsGrid.appendChild(card);
      });

      const selected = this.dom.videoResolutionsGrid.querySelector('input:checked');
      if (selected) this.state.videoQuality = selected.value;
    }

    renderSubtitles(subs) {
      this.dom.subtitleSelect.innerHTML = '<option value="">No subtitles</option>';
      subs.forEach((sub) => {
        const opt = document.createElement('option');
        opt.value = sub.code;
        opt.textContent = `${sub.name || sub.code.toUpperCase()} ${sub.is_auto ? '(Auto)' : ''}`;
        this.dom.subtitleSelect.appendChild(opt);
      });
    }

    renderPlaylistEntries(entries) {
      this.dom.playlistList.innerHTML = '';
      entries.forEach((item) => {
        const div = document.createElement('div');
        div.className = 'playlist-item';
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox'; checkbox.className = 'playlist-check'; checkbox.dataset.idx = item.index; checkbox.checked = true;
        const index = document.createElement('span'); index.className = 'playlist-idx'; index.textContent = `#${item.index}`;
        const title = document.createElement('span'); title.className = 'playlist-item-title'; title.textContent = item.title;
        const duration = document.createElement('span'); duration.className = 'playlist-item-dur'; duration.textContent = item.duration_formatted;
        div.append(checkbox, index, title, duration);
        this.dom.playlistList.appendChild(div);
      });
    }

    toggleAllPlaylist(check) {
      this.dom.playlistList.querySelectorAll('.playlist-check').forEach((cb) => {
        cb.checked = check;
      });
    }

    /* ---------------- Format Switching & Button Label ---------------- */
    updateConvertButtonLabel() {
      if (this.state.mediaType === 'audio') {
        const qualityStr = this.state.audioCodec === 'mp3' ? ` (${this.state.audioBitrate})` : ' (Optimal)';
        this.dom.convertBtnLabel.textContent = `Download in ${this.state.audioCodec.toUpperCase()}${qualityStr}`;
      } else {
        const qualityStr = this.state.videoQuality ? ` (${this.state.videoQuality})` : '';
        this.dom.convertBtnLabel.textContent = `Download in ${this.state.videoFormat.toUpperCase()}${qualityStr}`;
      }
    }

    switchMediaType(type) {
      this.state.mediaType = type;
      if (type === 'audio') {
        this.dom.tabAudio.classList.add('active');
        this.dom.tabAudio.setAttribute('aria-selected', 'true');
        this.dom.tabVideo.classList.remove('active');
        this.dom.tabVideo.setAttribute('aria-selected', 'false');
        this.dom.audioOptionsPanel.classList.remove('hidden');
        this.dom.videoOptionsPanel.classList.add('hidden');
      } else {
        this.dom.tabVideo.classList.add('active');
        this.dom.tabVideo.setAttribute('aria-selected', 'true');
        this.dom.tabAudio.classList.remove('active');
        this.dom.tabAudio.setAttribute('aria-selected', 'false');
        this.dom.videoOptionsPanel.classList.remove('hidden');
        this.dom.audioOptionsPanel.classList.add('hidden');
      }
      this.updateConvertButtonLabel();
    }

    setAudioCodec(codec) {
      this.state.audioCodec = codec;
      document.querySelectorAll('[data-codec]').forEach((chip) => {
        chip.classList.toggle('active', chip.dataset.codec === codec);
      });
      // Show bitrate selector only for mp3
      const mp3Row = document.getElementById('mp3QualityRow');
      if (mp3Row) {
        mp3Row.style.display = codec === 'mp3' ? 'flex' : 'none';
      }
      this.updateConvertButtonLabel();
    }

    setAudioBitrate(bitrate) {
      this.state.audioBitrate = bitrate;
      document.querySelectorAll('input[name="audioBitrate"]').forEach((inp) => {
        inp.checked = inp.value === bitrate;
        inp.closest('.radio-card').classList.toggle('active', inp.checked);
      });
      this.updateConvertButtonLabel();
    }

    setVideoFormat(vfmt) {
      this.state.videoFormat = vfmt;
      document.querySelectorAll('[data-vformat]').forEach((chip) => {
        chip.classList.toggle('active', chip.dataset.vformat === vfmt);
      });
      this.updateConvertButtonLabel();
    }

    /* ---------------- Trimmer ---------------- */
    toggleTrimmer() {
      const isHidden = this.dom.trimmerPanel.classList.contains('hidden');
      if (isHidden) {
        this.dom.trimmerPanel.classList.remove('hidden');
        this.dom.trimmerAccIcon.textContent = '\u2191';
      } else {
        this.dom.trimmerPanel.classList.add('hidden');
        this.dom.trimmerAccIcon.textContent = '\u2193';
      }
    }

    resetTrimmer() {
      this.dom.trimStartInput.value = '';
      this.dom.trimEndInput.value = '';
    }

    toggleComputeMode(isClient) {
      this.state.useClientCompute = isClient;
      const badge = document.getElementById('engineBadge');
      const desc = document.getElementById('engineDesc');
      const cpuMetric = document.getElementById('metricCpu');
      if (isClient) {
        if (badge) {
          badge.textContent = 'In-Browser Audio Processing';
          badge.classList.remove('cloud');
        }
        if (desc) {
          desc.textContent = 'MP3 and WAV encoding runs on your device. Resolution and delivery still use the server.';
        }
        if (cpuMetric) {
          cpuMetric.textContent = 'Browser Encoding';
          cpuMetric.className = 'metric-value badge-success';
        }
      } else {
        if (badge) {
          badge.textContent = 'Cloud Server (Server FFmpeg)';
          badge.classList.add('cloud');
        }
        if (desc) {
          desc.textContent = 'Legacy server-side FFmpeg processing mode (recommended only for low-spec older devices).';
        }
        if (cpuMetric) {
          cpuMetric.textContent = 'Active (Server FFmpeg)';
          cpuMetric.className = 'metric-value';
        }
      }
    }

    /* ---------------- Start Conversion & SSE Tracking ---------------- */
    async startDownload() {
      if (this.state.isProcessing) return;
      if (!this.state.currentMedia) return;
      this.state.isProcessing = true;
      const operationId = ++this.state.operationId;
      this.state.activeTaskId = null;
      if (this.state.eventSource) this.state.eventSource.close();
      if (this.state.blobUrl) URL.revokeObjectURL(this.state.blobUrl);
      this.state.blobUrl = null;
      this.dom.finalDownloadLink.classList.remove('hidden');

      const payload = {
        requestHeaders: this.cookieHeaders(),
        url: this.state.currentMedia.url,
        media_type: this.state.mediaType,
        audio_format: this.state.audioCodec,
        audio_quality: this.state.audioBitrate,
        video_format: this.state.videoFormat,
        video_quality: this.state.videoQuality,
        trim_start: this.dom.trimStartInput.value.trim() || null,
        trim_end: this.dom.trimEndInput.value.trim() || null,
        embed_metadata: this.dom.embedMetaCheck.checked,
        embed_thumbnail: true,
        subtitle_lang: this.dom.subtitleSelect.value || null,
      };

      // Playlist indices if playlist
      if (this.state.currentMedia.is_playlist) {
        const checked = [];
        this.dom.playlistList.querySelectorAll('.playlist-check:checked').forEach((cb) => {
          checked.push(parseInt(cb.dataset.idx, 10));
        });
        if (checked.length === 0) {
          this.state.isProcessing = false;
          this.showError('Select at least one playlist item.');
          return;
        }
        payload.playlist_indices = checked;
      }

      this.hideError();
      this.dom.inspectorSection.classList.add('hidden');
      this.dom.progressSection.classList.remove('hidden');
      this.dom.downloadReadyActions.classList.add('hidden');
      this.dom.cancelActionRow.classList.remove('hidden');
      this.dom.progressSection.scrollIntoView({ behavior: 'smooth', block: 'center' });

      // In-Browser Client-Side Processing (0% Server CPU)
      if (this.state.useClientCompute && window.StreamFabClientEngine && !payload.playlist_indices && !payload.subtitle_lang && (payload.media_type !== 'audio' || (payload.audio_format === 'mp3' || (payload.audio_format === 'wav' && !payload.embed_metadata)))) {
        try {
          if (this.dom.metricCpu) {
            this.dom.metricCpu.textContent = 'Browser Encoding';
            this.dom.metricCpu.className = 'metric-value badge-success';
          }
          const result = await window.StreamFabClientEngine.process(payload, (prog) => {
            if (operationId !== this.state.operationId) return;
            const pct = Math.max(0, Math.min(100, prog.percent || 0));
            this.dom.progressBarFill.style.width = `${pct}%`;
            this.dom.progressPercentBadge.textContent = `${pct}%`;
            this.dom.progressDetail.textContent = prog.detail || 'Processing in browser...';
            this.dom.metricSpeed.textContent = prog.speed || '-- MB/s';
            this.dom.metricEta.textContent = prog.percent >= 100 ? '00:00' : 'In-Browser';
            this.dom.metricStatus.textContent = prog.status === 'completed' ? 'Completed (Client)' : (prog.status === 'encoding' ? 'Encoding (Client)' : 'Client Engine');
          });

          if (operationId !== this.state.operationId) return;
          // Trigger browser file download directly
          window.downloadBlob(result.blob, result.filename);
          this.dom.downloadBtnText.textContent = `Save ${result.filename}`;
          this.state.blobUrl = URL.createObjectURL(result.blob);
          this.dom.finalDownloadLink.href = this.state.blobUrl;
          this.dom.finalDownloadLink.download = result.filename;
          this.dom.cancelActionRow.classList.add('hidden');
          this.dom.downloadReadyActions.classList.remove('hidden');
          this.dom.metricStatus.textContent = 'Completed (Client)';
          this.dom.metricStatus.className = 'metric-value status-pill status-completed';
          this.state.isProcessing = false;
          return;
        } catch (clientErr) {
          if (operationId !== this.state.operationId || clientErr.name === 'AbortError') return;
          console.warn('Client-side processing fallback to server:', clientErr);
          this.dom.progressDetail.textContent = 'Switching to server engine...';
        }
      }

      if (operationId !== this.state.operationId) return;
      if (this.dom.metricCpu) this.dom.metricCpu.textContent = 'Server FFmpeg';
      // Server-Side Fallback Mode
      try {
        const res = await fetch('/api/download', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...this.cookieHeaders() },
          body: JSON.stringify(payload),
        });

        const data = await res.json();
        if (!res.ok || !data.success) {
          throw new Error(data.detail || 'Unable to start task.');
        }

        if (operationId !== this.state.operationId) {
          await fetch(`/api/cancel/${data.task_id}`, { method: 'POST' });
          return;
        }
        this.state.activeTaskId = data.task_id;
        this.listenToProgress(data.task_id);
      } catch (err) {
        if (operationId !== this.state.operationId) return;
        this.state.isProcessing = false;
        this.showError(err.message || 'Error while starting conversion.');
        this.dom.progressSection.classList.add('hidden');
        this.dom.inspectorSection.classList.remove('hidden');
      }
    }

    listenToProgress(taskId) {
      if (this.state.eventSource) {
        this.state.eventSource.close();
      }

      const evtSource = new EventSource(`/api/progress/${taskId}`);
      this.state.eventSource = evtSource;

      evtSource.onmessage = (event) => {
        if (this.state.activeTaskId !== taskId) return;
        try {
          const data = JSON.parse(event.data);
          this.updateProgressUI(data);

          if (data.status === 'completed') {
            evtSource.close();
            this.handleCompleted(data);
          } else if (data.status === 'error') {
            evtSource.close();
            this.handleError(data.error_message || 'An error occurred.');
          } else if (data.status === 'cancelled') {
            evtSource.close();
            this.handleCancelled();
          }
        } catch (e) {
          console.error('SSE parse error:', e);
        }
      };

      evtSource.onerror = () => {
        if (evtSource.readyState === EventSource.CLOSED && this.state.activeTaskId === taskId) {
          this.handleError('Progress connection closed. The task may have expired or the server restarted.');
        }
        // EventSource automatically reconnects after transient failures.
      };
    }

    updateProgressUI(data) {
      const pct = Math.max(0, Math.min(100, data.percent || 0));
      this.dom.progressBarFill.style.width = `${pct}%`;
      this.dom.progressPercentBadge.textContent = `${pct}%`;
      this.dom.progressDetail.textContent = data.detail || 'Processing...';
      this.dom.metricSpeed.textContent = data.speed || '-- KiB/s';
      this.dom.metricEta.textContent = data.eta || '--:--';
      this.dom.metricStatus.textContent = data.status === 'downloading' ? 'Turbo Download' : (data.status === 'converting' ? 'FFmpeg Conversion' : data.status);
    }

    handleCompleted(data) {
      this.state.isProcessing = false;
      this.dom.progressBarFill.style.width = '100%';
      this.dom.progressPercentBadge.textContent = '100%';
      this.dom.progressDetail.textContent = 'Your file is ready for download!';
      this.dom.metricStatus.textContent = 'Completed';
      this.dom.metricStatus.style.background = 'rgba(16, 185, 129, 0.2)';
      this.dom.metricStatus.style.color = '#34d399';

      const mbSize = data.file_size ? ` (${(data.file_size / (1024 * 1024)).toFixed(1)} MB)` : '';
      this.dom.downloadBtnText.textContent = `Save ${data.filename || 'media'}${mbSize}`;
      this.dom.finalDownloadLink.href = data.download_url;
      this.dom.finalDownloadLink.setAttribute('download', data.filename || 'media');

      this.dom.downloadReadyActions.classList.remove('hidden');
      this.dom.cancelActionRow.classList.add('hidden');
    }

    handleError(msg) {
      this.state.isProcessing = false;
      this.showError(`Failed: ${msg}`);
      this.dom.progressDetail.textContent = `Error: ${msg}`;
      this.dom.metricStatus.textContent = 'Error';
      this.dom.metricStatus.style.background = 'rgba(239, 68, 68, 0.2)';
      this.dom.metricStatus.style.color = '#f87171';
      this.dom.cancelActionRow.classList.add('hidden');
      this.dom.downloadReadyActions.classList.remove('hidden');
      this.dom.finalDownloadLink.classList.add('hidden');
    }

    handleCancelled() {
      this.dom.progressDetail.textContent = 'Download cancelled.';
      this.dom.metricStatus.textContent = 'Cancelled';
      this.dom.cancelActionRow.classList.add('hidden');
      this.resetAll();
    }

    async cancelCurrentTask() {
      if (window.StreamFabClientEngine) window.StreamFabClientEngine.cancel();
      const taskId = this.state.activeTaskId;
      this.resetAll();
      if (!taskId) return;
      try {
        await fetch(`/api/cancel/${taskId}`, { method: 'POST' });
      } catch (e) {}
      if (this.state.eventSource) {
        this.state.eventSource.close();
      }
      this.resetAll();
    }

    /* ---------------- Cookie Session Assistant Logic ---------------- */
    cookieHeaders() {
      const token = document.getElementById('cookieAdminToken')?.value || '';
      return token ? { Authorization: `Bearer ${token}` } : {};
    }

    async refreshCookieStatus() {
      try {
        const res = await fetch('/api/cookies', { headers: this.cookieHeaders() });
        const json = await res.json();
        if (!res.ok || !json.success) {
          if (this.dom.cookieModalStatusText) this.dom.cookieModalStatusText.textContent = json.detail || 'Cookie administration unavailable.';
          return;
        }

        const data = json.data || {};
        if (data.has_cookies) {
          if (this.dom.cookieNavDot) {
            this.dom.cookieNavDot.classList.add('active');
            this.dom.cookieNavDot.title = `Active cookies loaded (${data.count} items, ${data.youtube_count} YouTube)`;
          }
          if (this.dom.cookieNavLabel) {
            this.dom.cookieNavLabel.textContent = 'Cookies Active';
          }
          if (this.dom.cookieModalDot) {
            this.dom.cookieModalDot.classList.add('active');
          }
          if (this.dom.cookieModalStatusText) {
            this.dom.cookieModalStatusText.textContent = `Active Session (${data.count} cookies, ${data.youtube_count} YouTube)`;
          }
          if (this.dom.cookieDeleteBtn) {
            this.dom.cookieDeleteBtn.classList.remove('hidden');
          }
        } else {
          if (this.dom.cookieNavDot) {
            this.dom.cookieNavDot.classList.remove('active');
            this.dom.cookieNavDot.title = 'No active cookies';
          }
          if (this.dom.cookieNavLabel) {
            this.dom.cookieNavLabel.textContent = 'Cookies';
          }
          if (this.dom.cookieModalDot) {
            this.dom.cookieModalDot.classList.remove('active');
          }
          if (this.dom.cookieModalStatusText) {
            this.dom.cookieModalStatusText.textContent = 'No active cookies loaded';
          }
          if (this.dom.cookieDeleteBtn) {
            this.dom.cookieDeleteBtn.classList.add('hidden');
          }
        }
      } catch (e) {
        // Silently tolerate network/offline quirks
      }
    }

    openCookieModal() {
      if (this.dom.cookieModal) {
        this.dom.cookieModal.classList.remove('hidden');
        this.refreshCookieStatus();
        this.hideCookieModalAlert();
      }
    }

    closeCookieModal() {
      if (this.dom.cookieModal) {
        this.dom.cookieModal.classList.add('hidden');
      }
    }

    switchCookieTab(tab) {
      if (tab === 'upload') {
        if (this.dom.tabUploadFile) this.dom.tabUploadFile.classList.add('active');
        if (this.dom.tabPasteText) this.dom.tabPasteText.classList.remove('active');
        if (this.dom.cookieUploadPane) this.dom.cookieUploadPane.classList.remove('hidden');
        if (this.dom.cookiePastePane) this.dom.cookiePastePane.classList.add('hidden');
      } else {
        if (this.dom.tabPasteText) this.dom.tabPasteText.classList.add('active');
        if (this.dom.tabUploadFile) this.dom.tabUploadFile.classList.remove('active');
        if (this.dom.cookiePastePane) this.dom.cookiePastePane.classList.remove('hidden');
        if (this.dom.cookieUploadPane) this.dom.cookieUploadPane.classList.add('hidden');
      }
      this.hideCookieModalAlert();
    }

    showCookieModalAlert(type, message) {
      if (!this.dom.cookieModalAlert) return;
      this.dom.cookieModalAlert.className = `cookie-modal-alert ${type}`;
      this.dom.cookieModalAlert.textContent = message;
      this.dom.cookieModalAlert.classList.remove('hidden');
    }

    hideCookieModalAlert() {
      if (this.dom.cookieModalAlert) {
        this.dom.cookieModalAlert.classList.add('hidden');
        this.dom.cookieModalAlert.textContent = '';
      }
    }

    async uploadCookieContent(content) {
      const clean = (content || '').trim();
      if (!clean) {
        this.showCookieModalAlert('error', 'Cookie content is empty.');
        return;
      }

      try {
        const res = await fetch('/api/cookies', {
          method: 'POST',
          body: JSON.stringify({ content: clean }),
          // Tokens are kept in memory and are never persisted.
          headers: { 'Content-Type': 'application/json', ...this.cookieHeaders() },
        });
        const json = await res.json();
        if (!res.ok || !json.success) {
          throw new Error(json.detail || 'Failed to save cookies.');
        }

        const ytCount = json.data?.youtube_count || 0;
        this.showCookieModalAlert(
          'success',
          `Cookies loaded successfully (${json.data?.count || 0} entries, ${ytCount} YouTube)! Re-analyzing video...`
        );
        await this.refreshCookieStatus();
        this.hideBotGuidance();

        // Auto-close modal and automatically re-analyze the video with zero extra clicks!
        setTimeout(() => {
          this.closeCookieModal();
          if (this.dom.urlInput && this.dom.urlInput.value.trim()) {
            this.handleAnalyze();
          }
        }, 850);
      } catch (err) {
        this.showCookieModalAlert('error', err.message || 'Error uploading cookies.');
      }
    }

    async savePastedCookies() {
      const content = this.dom.cookieTextarea ? this.dom.cookieTextarea.value.trim() : '';
      if (!content) {
        this.showCookieModalAlert('error', 'Please paste your Netscape cookie text first.');
        return;
      }
      await this.uploadCookieContent(content);
    }

    async deleteCookies() {
      if (!confirm('Are you sure you want to remove active cookies?')) return;
      try {
        const res = await fetch('/api/cookies', { method: 'DELETE', headers: this.cookieHeaders() });
        const json = await res.json();
        if (!res.ok || !json.success) {
          throw new Error(json.detail || 'Failed to remove cookies.');
        }
        this.showCookieModalAlert('success', 'Active cookies have been removed.');
        await this.refreshCookieStatus();
      } catch (err) {
        this.showCookieModalAlert('error', err.message || 'Error deleting cookies.');
      }
    }

    resetAll() {
      ++this.state.operationId;
      if (this.state.blobUrl) URL.revokeObjectURL(this.state.blobUrl);
      this.state.blobUrl = null;
      this.dom.finalDownloadLink.removeAttribute('href');
      this.dom.finalDownloadLink.classList.remove('hidden');
      if (this.state.eventSource) {
        this.state.eventSource.close();
      }
      this.state.isProcessing = false;
      this.state.activeTaskId = null;
      this.state.currentMedia = null;
      this.dom.progressSection.classList.add('hidden');
      this.dom.inspectorSection.classList.add('hidden');
      this.dom.finalDownloadLink.classList.remove('hidden');
      this.dom.previewPlayerContainer.classList.add('hidden');
      if (this.dom.previewVideoPlayer) {
        this.dom.previewVideoPlayer.pause();
        this.dom.previewVideoPlayer.src = '';
      }
      this.dom.progressBarFill.style.width = '0%';
      this.dom.progressPercentBadge.textContent = '0%';
      this.dom.urlInput.value = '';
      this.dom.clearBtn.classList.add('hidden');
      this.dom.urlInput.focus();
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  }

  // Instantiate and mount globally for HTML event handlers
  function initApp() {
    if (!window.app) {
      window.app = new StreamFabApp();
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initApp);
  } else {
    initApp();
  }
})();
