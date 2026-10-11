/**
 * StreamFab Client-Side Media Processor
 *
 * Executes 100% of the media computation (decoding, trimming, audio encoding,
 * ID3 tagging and cover art embedding) inside the user's browser.
 * Compatible combined MP4 streams are copied without remuxing.
 * Media resolution and network delivery still use server CPU and bandwidth.
 */

(function (window) {
  'use strict';

  // --- Utility: Parse timestamp string to seconds ---
  function parseTimestampToSeconds(str) {
    if (!str || typeof str !== 'string') return null;
    const clean = str.trim();
    if (!clean) return null;
    if (!/^(?:\d{1,5}(?:\.\d{1,3})?|(?:\d{1,2}:)?\d{1,2}:\d{1,2}(?:\.\d{1,3})?)$/.test(clean)) return null;
    const parts = clean.split(':').map(Number);
    if (parts.length > 1 && (parts.at(-1) >= 60 || parts.at(-2) >= 60)) return null;
    const seconds = parts.reduce((total, n) => total * 60 + n, 0);
    return Number.isFinite(seconds) && seconds <= 86400 ? seconds : null;
  }

  // --- Utility: Sanitize filename ---
  function sanitizeName(name, ext) {
    let clean = (name || 'StreamFab_Media').replace(/[\x00-\x1f\x7f\\/:*?"<>|]+/g, '_').trim();
    if (clean.length > 80) clean = clean.substring(0, 80).trim();
    return `${clean}.${ext}`;
  }

  // --- ID3v2.3 Tag Builder (Pure JavaScript) ---
  function buildID3v2Tag(metadata, imageUint8Array) {
    function encodeUtf16(text) {
      const result = new Uint8Array(2 + text.length * 2);
      result[0] = 0xff; result[1] = 0xfe;
      for (let i = 0; i < text.length; i++) {
        const code = text.charCodeAt(i);
        result[2 + i * 2] = code & 0xff;
        result[3 + i * 2] = code >> 8;
      }
      return result;
    }

    function makeTextFrame(id, text) {
      const textBytes = encodeUtf16(String(text));
      const bodyLen = 1 + textBytes.length;
      const frame = new Uint8Array(10 + bodyLen);
      // Frame ID (4 bytes)
      for (let i = 0; i < 4; i++) frame[i] = id.charCodeAt(i);
      // Size (4 bytes big-endian)
      frame[4] = (bodyLen >> 24) & 0xff;
      frame[5] = (bodyLen >> 16) & 0xff;
      frame[6] = (bodyLen >> 8) & 0xff;
      frame[7] = bodyLen & 0xff;
      // Flags (2 bytes) = 0
      frame[8] = 0;
      frame[9] = 0;
      // Body
      frame[10] = 0x01; // ID3v2.3 UTF-16 with BOM
      frame.set(textBytes, 11);
      return frame;
    }

    function makeApicFrame(imgBytes) {
      if (!imgBytes || imgBytes.length === 0) return new Uint8Array(0);
      const imageMime = imgBytes[0] === 0xff && imgBytes[1] === 0xd8 ? 'image/jpeg' : imgBytes[0] === 0x89 && imgBytes[1] === 0x50 ? 'image/png' : null;
      if (!imageMime) return new Uint8Array(0);
      const mime = new TextEncoder().encode(imageMime + '\0');
      const desc = new Uint8Array([0x00]); // empty description
      const bodyLen = 1 + mime.length + 1 + desc.length + imgBytes.length;
      const frame = new Uint8Array(10 + bodyLen);
      // Frame ID 'APIC'
      const id = 'APIC';
      for (let i = 0; i < 4; i++) frame[i] = id.charCodeAt(i);
      frame[4] = (bodyLen >> 24) & 0xff;
      frame[5] = (bodyLen >> 16) & 0xff;
      frame[6] = (bodyLen >> 8) & 0xff;
      frame[7] = bodyLen & 0xff;
      frame[8] = 0;
      frame[9] = 0;

      let offset = 10;
      frame[offset++] = 0x00; // ISO-8859-1 for mime/desc
      frame.set(mime, offset);
      offset += mime.length;
      frame[offset++] = 0x03; // Picture type: Cover (front)
      frame.set(desc, offset);
      offset += desc.length;
      frame.set(imgBytes, offset);
      return frame;
    }

    const frames = [];
    if (metadata.title) frames.push(makeTextFrame('TIT2', metadata.title));
    if (metadata.artist) frames.push(makeTextFrame('TPE1', metadata.artist));
    if (metadata.album) frames.push(makeTextFrame('TALB', metadata.album));
    if (metadata.year) frames.push(makeTextFrame('TYER', String(metadata.year)));
    if (imageUint8Array) frames.push(makeApicFrame(imageUint8Array));

    let totalFramesLen = 0;
    for (const f of frames) totalFramesLen += f.length;

    // Synchsafe integer encoding (7 bits per byte)
    const s0 = (totalFramesLen >> 21) & 0x7f;
    const s1 = (totalFramesLen >> 14) & 0x7f;
    const s2 = (totalFramesLen >> 7) & 0x7f;
    const s3 = totalFramesLen & 0x7f;

    const id3Header = new Uint8Array(10);
    id3Header[0] = 0x49; // 'I'
    id3Header[1] = 0x44; // 'D'
    id3Header[2] = 0x33; // '3'
    id3Header[3] = 0x03; // version 2.3
    id3Header[4] = 0x00;
    id3Header[5] = 0x00; // flags
    id3Header[6] = s0;
    id3Header[7] = s1;
    id3Header[8] = s2;
    id3Header[9] = s3;

    const result = new Uint8Array(10 + totalFramesLen);
    result.set(id3Header, 0);
    let curOffset = 10;
    for (const f of frames) {
      result.set(f, curOffset);
      curOffset += f.length;
    }
    return result;
  }

  // --- WAV Container Builder (Pure JavaScript) ---
  function encodeWav(audioBuffer) {
    const numChannels = audioBuffer.numberOfChannels;
    const sampleRate = audioBuffer.sampleRate;
    const format = 1; // PCM
    const bitDepth = 16;

    const numSamples = audioBuffer.length;
    const bytesPerSample = bitDepth / 8;
    const blockAlign = numChannels * bytesPerSample;
    const byteRate = sampleRate * blockAlign;
    const dataSize = numSamples * blockAlign;
    const buffer = new ArrayBuffer(44 + dataSize);
    const view = new DataView(buffer);

    function writeString(offset, string) {
      for (let i = 0; i < string.length; i++) {
        view.setUint8(offset + i, string.charCodeAt(i));
      }
    }

    writeString(0, 'RIFF');
    view.setUint32(4, 36 + dataSize, true);
    writeString(8, 'WAVE');
    writeString(12, 'fmt ');
    view.setUint32(16, 16, true);
    view.setUint16(20, format, true);
    view.setUint16(22, numChannels, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, byteRate, true);
    view.setUint16(32, blockAlign, true);
    view.setUint16(34, bitDepth, true);
    writeString(36, 'data');
    view.setUint32(40, dataSize, true);

    const channels = [];
    for (let c = 0; c < numChannels; c++) {
      channels.push(audioBuffer.getChannelData(c));
    }

    let offset = 44;
    for (let i = 0; i < numSamples; i++) {
      for (let c = 0; c < numChannels; c++) {
        const s = Math.max(-1, Math.min(1, channels[c][i]));
        const int16 = s < 0 ? s * 0x8000 : s * 0x7fff;
        view.setInt16(offset, int16, true);
        offset += 2;
      }
    }

    return new Blob([buffer], { type: 'audio/wav' });
  }

  // --- Client Media Engine ---
  class ClientMediaEngine {
    constructor() {
      this.audioContext = null;
      this.abortController = null;
      this.maxStreamBytes = 128 * 1024 * 1024;
    }

    cancel() {
      if (this.abortController) this.abortController.abort();
    }

    checkCancelled() {
      if (this.abortController?.signal.aborted) {
        const error = new Error('Processing cancelled.'); error.name = 'AbortError'; throw error;
      }
    }

    _normalizeOptions(opts) {
      const o = opts || {};
      return {
        requestHeaders: o.requestHeaders || {},
        url: o.url,
        mediaType: (o.mediaType || o.media_type || 'audio').toLowerCase(),
        audioCodec: (o.audioCodec || o.audio_format || 'mp3').toLowerCase(),
        audioBitrate: String(o.audioBitrate || o.audio_quality || '320k'),
        videoFormat: (o.videoFormat || o.video_format || 'mp4').toLowerCase(),
        videoQuality: String(o.videoQuality || o.video_quality || 'best'),
        trimStart: o.trimStart !== undefined ? o.trimStart : (o.trim_start !== undefined ? o.trim_start : null),
        trimEnd: o.trimEnd !== undefined ? o.trimEnd : (o.trim_end !== undefined ? o.trim_end : null),
        embedMetadata: o.embedMetadata !== undefined ? o.embedMetadata : (o.embed_metadata !== undefined ? o.embed_metadata : true),
        embedThumbnail: o.embedThumbnail !== undefined ? o.embedThumbnail : (o.embed_thumbnail !== undefined ? o.embed_thumbnail : true),
        subtitleLang: o.subtitleLang || o.subtitle_lang || null,
      };
    }

    getAudioContext() {
      if (!this.audioContext) {
        const AudioCtx = window.AudioContext || window.webkitAudioContext;
        this.audioContext = new AudioCtx();
      }
      return this.audioContext;
    }

    async fetchStreamWithProgress(url, label, onProgress, startPct, endPct, maxBytes = this.maxStreamBytes) {
      const response = await fetch(url, { signal: this.abortController?.signal, headers: this.requestHeaders || {} });
      if (!response.ok) {
        throw new Error(`Failed to stream media: HTTP ${response.status}`);
      }

      const contentLength = +response.headers.get('Content-Length') || 0;
      if (contentLength > maxBytes) {
        await response.body.cancel();
        throw new Error('Stream exceeds the browser memory limit. Use server mode.');
      }
      const reader = response.body.getReader();
      const chunks = [];
      let receivedBytes = 0;
      let startTime = Date.now();

      while (true) {
        this.checkCancelled();
        const { done, value } = await reader.read();
        if (done) break;
        receivedBytes += value.length;
        if (receivedBytes > maxBytes) {
          await reader.cancel();
          throw new Error('Stream exceeds the browser memory limit. Use server mode.');
        }
        chunks.push(value);

        if (contentLength > 0 && onProgress) {
          const ratio = receivedBytes / contentLength;
          const currentPct = startPct + ratio * (endPct - startPct);
          const elapsedSec = (Date.now() - startTime) / 1000;
          const speed = elapsedSec > 0 ? (receivedBytes / (1024 * 1024)) / elapsedSec : 0;
          onProgress({
            status: 'streaming',
            percent: Math.round(currentPct),
            speed: `${speed.toFixed(2)} MB/s`,
            detail: `${label}: ${(receivedBytes / (1024 * 1024)).toFixed(1)} MB (${Math.round(ratio * 100)}%)`,
          });
        }
      }

      const totalBuf = new Uint8Array(receivedBytes);
      let pos = 0;
      for (const chunk of chunks) {
        totalBuf.set(chunk, pos);
        pos += chunk.length;
      }
      return totalBuf.buffer;
    }

    async process(rawOptions, onProgress) {
      // Each call owns its cancellation state. A new call must not revive an
      // older decode/encode operation that is still unwinding after cancellation.
      const operation = new ClientMediaEngine();
      operation.getAudioContext = () => this.getAudioContext();
      operation.maxStreamBytes = this.maxStreamBytes;
      operation.abortController = new AbortController();
      this.abortController = operation.abortController;
      return operation._process(rawOptions, onProgress);
    }

    async _process(rawOptions, onProgress) {
      this.requestHeaders = rawOptions.requestHeaders || {};
      const options = this._normalizeOptions(rawOptions);
      for (const raw of [options.trimStart, options.trimEnd]) {
        if (raw && parseTimestampToSeconds(raw) === null) throw new Error('Invalid trim timestamp.');
      }
      if (options.subtitleLang) throw new Error('Subtitles require server-side FFmpeg engine.');

      // 1. Resolve direct stream URLs (Zero server CPU)
      if (onProgress) {
        onProgress({
          status: 'resolving',
          percent: 5,
          speed: 'Instant',
          detail: 'Connecting to direct stream CDN (browser encoding)...',
        });
      }

      const res = await fetch('/api/stream-urls', {
        method: 'POST',
        signal: this.abortController?.signal,
        headers: { 'Content-Type': 'application/json', ...options.requestHeaders },
        body: JSON.stringify({
          url: options.url,
          media_type: options.mediaType,
          audio_format: options.audioCodec,
          audio_quality: options.audioBitrate,
          video_quality: options.videoQuality,
          video_format: options.videoFormat,
        }),
      });

      const json = await res.json();
      this.checkCancelled();
      if (!res.ok || !json.success) {
        throw new Error(json.detail || 'Could not resolve media stream URLs.');
      }

      const streamInfo = json.data;
      const trimStartSec = parseTimestampToSeconds(options.trimStart);
      const trimEndSec = parseTimestampToSeconds(options.trimEnd);

      if (options.mediaType === 'audio') {
        return await this.processAudio(streamInfo, options, trimStartSec, trimEndSec, onProgress);
      } else {
        return await this.processVideo(streamInfo, options, trimStartSec, trimEndSec, onProgress);
      }
    }

    async processAudio(streamInfo, options, trimStartSec, trimEndSec, onProgress) {
      const normalizedOpts = this._normalizeOptions(options);
      if (typeof trimStartSec === 'function') {
        onProgress = trimStartSec;
        trimStartSec = parseTimestampToSeconds(normalizedOpts.trimStart);
        trimEndSec = parseTimestampToSeconds(normalizedOpts.trimEnd);
      } else {
        if (trimStartSec === undefined || trimStartSec === null) {
          trimStartSec = parseTimestampToSeconds(normalizedOpts.trimStart);
        }
        if (trimEndSec === undefined || trimEndSec === null) {
          trimEndSec = parseTimestampToSeconds(normalizedOpts.trimEnd);
        }
      }

      const targetCodec = (normalizedOpts.audioCodec || 'mp3').toLowerCase();
      if (targetCodec !== 'mp3' && targetCodec !== 'wav') {
        throw new Error(`In-browser encoding for '${targetCodec}' requires server-side FFmpeg engine.`);
      }

      const audioUrl = streamInfo.audio_proxy_url || streamInfo.combined_proxy_url;
      if (!audioUrl) {
        throw new Error('No audio stream URL available for this media.');
      }

      // Stream raw audio bytes
      const audioBuffer = await this.fetchStreamWithProgress(
        audioUrl,
        'Streaming audio track',
        onProgress,
        10,
        50
      );

      // Decode audio in browser Web Audio engine
      if (onProgress) {
        onProgress({
          status: 'decoding',
          percent: 55,
          speed: 'Client AudioContext',
          detail: 'Hardware decoding audio stream on client CPU...',
        });
      }

      const ctx = this.getAudioContext();
      if (ctx.state === 'suspended') {
        try {
          await ctx.resume();
        } catch (e) {}
      }
      // decodeAudioData consumes the ArrayBuffer so slice a copy
      const decoded = await ctx.decodeAudioData(audioBuffer.slice(0));
      this.checkCancelled();

      // Precision Sample Trimming
      let startSample = 0;
      let endSample = decoded.length;
      if (trimStartSec !== null && trimStartSec > 0) {
        startSample = Math.min(Math.floor(trimStartSec * decoded.sampleRate), decoded.length);
      }
      if (trimEndSec !== null && trimEndSec > 0) {
        endSample = Math.min(Math.floor(trimEndSec * decoded.sampleRate), decoded.length);
      }
      if (endSample <= startSample) throw new Error('Trim range is empty or outside the media duration.');
      if (trimEndSec === 0) throw new Error('End time must be greater than start time.');

      const trimmedLength = endSample - startSample;
      const trimmedAudioBuffer = ctx.createBuffer(
        decoded.numberOfChannels,
        trimmedLength,
        decoded.sampleRate
      );

      for (let ch = 0; ch < decoded.numberOfChannels; ch++) {
        const srcData = decoded.getChannelData(ch);
        const destData = trimmedAudioBuffer.getChannelData(ch);
        destData.set(srcData.subarray(startSample, endSample));
      }

      // Case A: WAV output
      if (targetCodec === 'wav') {
        if (normalizedOpts.embedMetadata) throw new Error('WAV metadata requires server-side FFmpeg engine.');
        if (onProgress) {
          onProgress({
            status: 'encoding',
            percent: 90,
            speed: 'Instant PCM',
            detail: 'Packaging 16-bit PCM WAV in browser memory...',
          });
        }
        const wavBlob = encodeWav(trimmedAudioBuffer);
        const fileName = sanitizeName(streamInfo.title, 'wav');
        return { blob: wavBlob, filename: fileName };
      }

      // Case B: MP3 Encoding (via lamejs on client CPU)
      if (onProgress) {
        onProgress({
          status: 'encoding',
          percent: 65,
          speed: 'In-Browser MP3',
          detail: 'Encoding high-definition MP3 on client CPU (browser encoding)...',
        });
      }

      const channels = trimmedAudioBuffer.numberOfChannels;
      if (channels > 2) throw new Error('Multichannel MP3 encoding requires server-side FFmpeg engine.');
      const sampleRate = trimmedAudioBuffer.sampleRate;
      let kbps = 320;
      if (normalizedOpts.audioBitrate) {
        const parsedBitrate = parseInt(normalizedOpts.audioBitrate.replace('k', ''), 10);
        if ([128, 192, 256, 320].includes(parsedBitrate)) kbps = parsedBitrate;
      }

      const LameModule = window.lamejs;
      if (!LameModule) {
        throw new Error('In-browser MP3 encoder (lamejs) not loaded.');
      }

      const mp3Encoder = new LameModule.Mp3Encoder(channels, sampleRate, kbps);
      const leftFloat = trimmedAudioBuffer.getChannelData(0);
      const rightFloat = channels > 1 ? trimmedAudioBuffer.getChannelData(1) : leftFloat;

      const numSamples = trimmedLength;
      const left16 = new Int16Array(numSamples);
      const right16 = new Int16Array(numSamples);

      for (let i = 0; i < numSamples; i++) {
        let sl = Math.max(-1, Math.min(1, leftFloat[i]));
        left16[i] = sl < 0 ? sl * 0x8000 : sl * 0x7fff;
        let sr = Math.max(-1, Math.min(1, rightFloat[i]));
        right16[i] = sr < 0 ? sr * 0x8000 : sr * 0x7fff;
      }

      const blockSize = 1152;
      const mp3Chunks = [];

      for (let i = 0; i < numSamples; i += blockSize) {
        if (i % (blockSize * 20) === 0) {
          await new Promise((resolve) => setTimeout(resolve, 0));
          this.checkCancelled();
        }
        const leftChunk = left16.subarray(i, i + blockSize);
        const rightChunk = right16.subarray(i, i + blockSize);
        const encodedChunk = mp3Encoder.encodeBuffer(leftChunk, rightChunk);
        if (encodedChunk.length > 0) {
          mp3Chunks.push(new Uint8Array(encodedChunk));
        }

        if (i % (blockSize * 20) === 0 && onProgress) {
          const encPct = 65 + Math.round((i / numSamples) * 25);
          onProgress({
            status: 'encoding',
            percent: encPct,
            speed: `${kbps} kbps`,
            detail: `Encoding MP3 frames: ${Math.round((i / numSamples) * 100)}%`,
          });
        }
      }

      const flush = mp3Encoder.flush();
      if (flush.length > 0) {
        mp3Chunks.push(new Uint8Array(flush));
      }

      // Download Cover Art for ID3v2 tagging if requested
      let coverArtBytes = null;
      if (normalizedOpts.embedThumbnail && streamInfo.thumbnail) {
        try {
          const thumbBuf = await this.fetchStreamWithProgress(
            `/api/proxy-stream?url=${encodeURIComponent(streamInfo.thumbnail)}`,
            'Cover art', null, 0, 0, 8 * 1024 * 1024
          );
          coverArtBytes = new Uint8Array(thumbBuf);
        } catch (e) {
          // Non-fatal if thumbnail blocked
        }
      }

      if (onProgress) {
        onProgress({
          status: 'tagging',
          percent: 95,
          speed: 'ID3v2 Engine',
          detail: 'Injecting ID3v2 tags & album artwork on client...',
        });
      }

      const id3Header = buildID3v2Tag(
        normalizedOpts.embedMetadata ? {
          title: streamInfo.title,
          artist: streamInfo.uploader,
          album: 'StreamFab Client Master',
          year: new Date().getFullYear(),
        } : {},
        coverArtBytes
      );

      this.checkCancelled();
      const finalBlob = new Blob([id3Header, ...mp3Chunks], { type: 'audio/mpeg' });
      const finalName = sanitizeName(streamInfo.title, 'mp3');

      if (onProgress) {
        onProgress({
          status: 'completed',
          percent: 100,
          speed: 'Complete',
          detail: 'Process complete! 100% computed on your client device (browser encoding).',
        });
      }

      return { blob: finalBlob, filename: finalName };
    }

    async processVideo(streamInfo, options, trimStartSec, trimEndSec, onProgress) {
      const normalizedOpts = this._normalizeOptions(options);
      if (typeof trimStartSec === 'function') {
        onProgress = trimStartSec;
        trimStartSec = parseTimestampToSeconds(normalizedOpts.trimStart);
        trimEndSec = parseTimestampToSeconds(normalizedOpts.trimEnd);
      } else {
        if (trimStartSec === undefined || trimStartSec === null) {
          trimStartSec = parseTimestampToSeconds(normalizedOpts.trimStart);
        }
        if (trimEndSec === undefined || trimEndSec === null) {
          trimEndSec = parseTimestampToSeconds(normalizedOpts.trimEnd);
        }
      }

      // Video trimming requires server-side FFmpeg engine
      if (trimStartSec !== null || trimEndSec !== null) {
        throw new Error('Video trimming requires server-side FFmpeg engine.');
      }

      // Combined audio/video stream check
      const videoUrl = streamInfo.combined_proxy_url;
      if (!videoUrl) {
        throw new Error('Multi-track video/audio muxing requires server-side FFmpeg engine.');
      }

      if (streamInfo.combined_ext !== normalizedOpts.videoFormat || normalizedOpts.videoFormat !== 'mp4') {
        throw new Error('Container conversion requires server-side FFmpeg engine.');
      }
      if (streamInfo.video_height && streamInfo.combined_height < streamInfo.video_height) {
        throw new Error('Requested video quality requires server-side FFmpeg engine.');
      }
      if (normalizedOpts.embedMetadata || normalizedOpts.subtitleLang) {
        throw new Error('Video metadata and subtitles require server-side FFmpeg engine.');
      }
      const videoBuffer = await this.fetchStreamWithProgress(
        videoUrl,
        'Streaming HD video track',
        onProgress,
        10,
        80
      );

      if (onProgress) {
        onProgress({
          status: 'muxing',
          percent: 90,
          speed: 'Client Container',
          detail: 'Packaging MP4 container on client device...',
        });
      }

      const finalBlob = new Blob([videoBuffer], { type: 'video/mp4' });
      const finalName = sanitizeName(streamInfo.title, 'mp4');

      if (onProgress) {
        onProgress({
          status: 'completed',
          percent: 100,
          speed: 'Complete',
          detail: 'Video ready! 100% processed on client device (browser encoding).',
        });
      }

      return { blob: finalBlob, filename: finalName };
    }
  }

  // --- Auto Trigger Download Function ---
  function downloadBlob(blob, filename) {
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    setTimeout(() => URL.revokeObjectURL(link.href), 30000);
  }

  // Expose to window
  const engineInstance = new ClientMediaEngine();
  engineInstance.buildID3v2Tag = buildID3v2Tag;
  engineInstance.encodeWav = encodeWav;
  engineInstance.parseTimestampToSeconds = parseTimestampToSeconds;
  engineInstance.sanitizeName = sanitizeName;
  window.StreamFabClientEngine = engineInstance;
  window.downloadBlob = downloadBlob;
})(typeof window !== 'undefined' ? window : globalThis);

