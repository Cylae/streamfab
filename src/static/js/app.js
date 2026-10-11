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
      };

      this.dom = {};
      this.init();
    }

    init() {
      this.cacheDom();
      this.bindEvents();
      this.initTheme();
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
    }

    bindEvents() {
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
    }

    /* ---------------- Theme Management ---------------- */
    initTheme() {
      const saved = localStorage.getItem('streamfab_theme');
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
      localStorage.setItem('streamfab_theme', theme);
    }

    toggleTheme() {
      const current = this.dom.html.getAttribute('data-theme') || 'dark';
      const next = current === 'dark' ? 'light' : 'dark';
      this.setTheme(next);
    }

    /* ---------------- Analysis & Metadata ---------------- */
    async handleAnalyze() {
      const url = this.dom.urlInput.value.trim();
      if (!url) return;

      this.hideError();
      this.setAnalyzeLoading(true);

      try {
        const res = await fetch('/api/info', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url }),
        });

        const data = await res.json();
        if (!res.ok || !data.success) {
          throw new Error(data.detail || 'Unable to extract media information.');
        }

        this.renderMediaInfo(data.data);
      } catch (err) {
        this.showError(err.message || 'An unexpected error occurred.');
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

    renderMediaInfo(info) {
      this.state.currentMedia = info;

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
        const isDefault = idx === 0;
        const card = document.createElement('label');
        card.className = `radio-card ${isDefault ? 'active' : ''}`;
        card.innerHTML = `
          <input type="radio" name="videoRes" value="${res.value}" ${isDefault ? 'checked' : ''}>
          <span class="card-content">
            <span class="card-title">${res.label}</span>
            <span class="card-desc">${res.height ? res.height + 'p Original stream' : 'Optimal'}</span>
          </span>
        `;
        card.querySelector('input').addEventListener('change', () => {
          this.dom.videoResolutionsGrid.querySelectorAll('.radio-card').forEach((c) => c.classList.remove('active'));
          card.classList.add('active');
          this.state.videoQuality = res.value;
          this.updateConvertButtonLabel();
        });
        this.dom.videoResolutionsGrid.appendChild(card);
      });

      if (resolutions[0]) {
        this.state.videoQuality = resolutions[0].value;
      }
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
        div.innerHTML = `
          <input type="checkbox" class="playlist-check" data-idx="${item.index}" checked>
          <span class="playlist-idx">#${item.index}</span>
          <span class="playlist-item-title" style="flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${item.title}</span>
          <span class="playlist-item-dur" style="font-family:var(--font-mono); color:var(--text-muted); font-size:0.75rem;">${item.duration_formatted}</span>
        `;
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
        inp.closest('.radio-card').classList.toggle('active', inp.value === bitrate);
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
          badge.textContent = 'In-Browser Client (0% Server CPU)';
          badge.classList.remove('cloud');
        }
        if (desc) {
          desc.textContent = 'Computations (decoding, trimming, MP3 encoding & tagging) run 100% on your device CPU for maximum privacy & zero server load.';
        }
        if (cpuMetric) {
          cpuMetric.textContent = '0.0% (Zero Load)';
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
      if (!this.state.currentMedia) return;

      const payload = {
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
        if (checked.length > 0) {
          payload.playlist_indices = checked;
        }
      }

      this.hideError();
      this.dom.inspectorSection.classList.add('hidden');
      this.dom.progressSection.classList.remove('hidden');
      this.dom.downloadReadyActions.classList.add('hidden');
      this.dom.cancelActionRow.classList.remove('hidden');
      this.dom.progressSection.scrollIntoView({ behavior: 'smooth', block: 'center' });

      // In-Browser Client-Side Processing (0% Server CPU)
      if (this.state.useClientCompute && window.StreamFabClientEngine) {
        try {
          if (this.dom.metricCpu) {
            this.dom.metricCpu.textContent = '0.0% (Zero Load)';
            this.dom.metricCpu.className = 'metric-value badge-success';
          }
          const result = await window.StreamFabClientEngine.process(payload, (prog) => {
            const pct = Math.max(0, Math.min(100, prog.percent || 0));
            this.dom.progressBarFill.style.width = `${pct}%`;
            this.dom.progressPercentBadge.textContent = `${pct}%`;
            this.dom.progressDetail.textContent = prog.detail || 'Processing in browser...';
            this.dom.metricSpeed.textContent = prog.speed || '-- MB/s';
            this.dom.metricEta.textContent = prog.percent >= 100 ? '00:00' : 'In-Browser';
            this.dom.metricStatus.textContent = prog.status === 'completed' ? 'Completed (Client)' : (prog.status === 'encoding' ? 'Encoding (Client)' : 'Client Engine');
          });

          // Trigger browser file download directly
          window.downloadBlob(result.blob, result.filename);
          this.dom.downloadBtnText.textContent = `Save ${result.filename}`;
          this.dom.finalDownloadLink.href = URL.createObjectURL(result.blob);
          this.dom.finalDownloadLink.download = result.filename;
          this.dom.cancelActionRow.classList.add('hidden');
          this.dom.downloadReadyActions.classList.remove('hidden');
          this.dom.metricStatus.textContent = 'Completed (Client)';
          this.dom.metricStatus.className = 'metric-value status-pill status-completed';
          return;
        } catch (clientErr) {
          console.warn('Client-side processing fallback to server:', clientErr);
          this.dom.progressDetail.textContent = 'Switching to server engine...';
        }
      }

      // Server-Side Fallback Mode
      try {
        const res = await fetch('/api/download', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });

        const data = await res.json();
        if (!res.ok || !data.success) {
          throw new Error(data.detail || 'Unable to start task.');
        }

        this.state.activeTaskId = data.task_id;
        this.listenToProgress(data.task_id);
      } catch (err) {
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
        // EventSource will automatically attempt reconnection if transient
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
      if (!this.state.activeTaskId) return;
      try {
        await fetch(`/api/cancel/${this.state.activeTaskId}`, { method: 'POST' });
      } catch (e) {}
      if (this.state.eventSource) {
        this.state.eventSource.close();
      }
      this.resetAll();
    }

    resetAll() {
      if (this.state.eventSource) {
        this.state.eventSource.close();
      }
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
  document.addEventListener('DOMContentLoaded', () => {
    window.app = new StreamFabApp();
  });
})();
