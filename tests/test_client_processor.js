/**
 * Automated Test Suite for StreamFab In-Browser Client Processor
 * Runs under Node.js v24+
 */

const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

console.log('🧪 Starting StreamFab Client-Side Processor Test Suite...\n');

// 1. Load client source files
const vendorLame = fs.readFileSync(path.join(__dirname, '../src/static/js/vendor/lame.min.js'), 'utf8');
const vendorMp4box = fs.readFileSync(path.join(__dirname, '../src/static/js/vendor/mp4box.all.min.js'), 'utf8');
const clientProcessor = fs.readFileSync(path.join(__dirname, '../src/static/js/client-processor.js'), 'utf8');

// 2. Setup browser sandbox environment
const sandbox = {
  window: {},
  document: {
    createElement: (tag) => ({
      href: '',
      download: '',
      click: () => {},
    }),
    body: {
      appendChild: () => {},
      removeChild: () => {},
    },
  },
  console: console,
  navigator: {},
  TextEncoder: global.TextEncoder,
  TextDecoder: global.TextDecoder,
  Blob: global.Blob,
  Uint8Array: global.Uint8Array,
  Int16Array: global.Int16Array,
  Float32Array: global.Float32Array,
  fetch: global.fetch,
  setTimeout: setTimeout,
  clearTimeout: clearTimeout,
  URL: {
    createObjectURL: (b) => 'blob:mock-url',
    revokeObjectURL: () => {},
  },
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

// 3. Execute scripts in sandbox
vm.runInContext(vendorLame, sandbox);
vm.runInContext(vendorMp4box, sandbox);
vm.runInContext(clientProcessor, sandbox);

const engine = sandbox.StreamFabClientEngine;
assert(engine, 'StreamFabClientEngine must be defined');

// Test 1: Timestamp parsing
console.log('✓ Test 1: Timestamp parsing');
assert.strictEqual(engine.parseTimestampToSeconds('45'), 45);
assert.strictEqual(engine.parseTimestampToSeconds('01:30'), 90);
assert.strictEqual(engine.parseTimestampToSeconds('01:02:03'), 3723);
assert.strictEqual(engine.parseTimestampToSeconds('invalid'), null);
assert.strictEqual(engine.parseTimestampToSeconds(null), null);

// Test 2: Sanitize filename
console.log('✓ Test 2: Sanitize filename');
assert.strictEqual(engine.sanitizeName('Simple Name', 'mp3'), 'Simple Name.mp3');
assert.strictEqual(engine.sanitizeName('Unsafe /:*?"<>| File', 'mp4'), 'Unsafe _ File.mp4');
const longName = 'A'.repeat(100);
const sanitizedLong = engine.sanitizeName(longName, 'wav');
assert(sanitizedLong.length <= 85);
assert(sanitizedLong.endsWith('.wav'));

// Test 3: ID3v2.3 tag builder
console.log('✓ Test 3: ID3v2.3 tag builder with APIC cover art');
const mockCoverBytes = new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 0x00, 0x10]); // JPEG magic header
const id3Buf = engine.buildID3v2Tag(
  {
    title: 'Test Song Title',
    artist: 'StreamFab Artist',
    album: 'Greatest Hits',
    year: '2026',
  },
  mockCoverBytes
);
assert(id3Buf instanceof Uint8Array);
assert.strictEqual(String.fromCharCode(id3Buf[0], id3Buf[1], id3Buf[2]), 'ID3');
assert.strictEqual(id3Buf[3], 3); // ID3v2.3

// Test 4: WAV PCM 16-bit encoder
console.log('✓ Test 4: 16-bit PCM WAV encoding');
const sampleRate = 44100;
const testDurationSec = 0.5;
const numSamples = Math.round(sampleRate * testDurationSec);
const pcmLeft = new Float32Array(numSamples);
const pcmRight = new Float32Array(numSamples);

for (let i = 0; i < numSamples; i++) {
  pcmLeft[i] = Math.sin((2 * Math.PI * 440 * i) / sampleRate) * 0.5;
  pcmRight[i] = Math.sin((2 * Math.PI * 880 * i) / sampleRate) * 0.5;
}

const mockAudioBuffer = {
  numberOfChannels: 2,
  sampleRate: sampleRate,
  length: numSamples,
  getChannelData: (ch) => (ch === 0 ? pcmLeft : pcmRight),
};

const wavBlob = engine.encodeWav(mockAudioBuffer);
assert.strictEqual(wavBlob.type, 'audio/wav');
assert(wavBlob.size > numSamples * 4); // 4 bytes per stereo 16-bit sample + 44 header

// Test 5: Full In-Browser Audio Processing Pipeline
console.log('✓ Test 5: In-Browser MP3 Encoding & Precision Trimming');
let capturedTrimLength = 0;
engine.audioContext = {
  decodeAudioData: async (buf) => mockAudioBuffer,
  createBuffer: (channels, length, rate) => {
    capturedTrimLength = length;
    return {
      numberOfChannels: channels,
      length: length,
      sampleRate: rate,
      getChannelData: (ch) => new Float32Array(length),
    };
  },
};
engine.fetchStreamWithProgress = async () => new ArrayBuffer(512);

async function runAudioTest() {
  const streamInfo = {
    title: 'Synthetic Test Audio',
    uploader: 'StreamFab Test Suite',
    duration: 1,
    audio_proxy_url: '/dummy_audio',
  };
  const options = {
    mediaType: 'audio',
    audioCodec: 'mp3',
    audioBitrate: '320k',
    trimStart: '0.1',
    trimEnd: '0.4',
  };

  const progressEvents = [];
  const result = await engine.processAudio(
    streamInfo,
    options,
    0.1,
    0.4,
    (prog) => {
      progressEvents.push(prog.status);
    }
  );

  assert(result.blob);
  assert.strictEqual(result.blob.type, 'audio/mpeg');
  assert.strictEqual(result.filename, 'Synthetic Test Audio.mp3');
  assert(capturedTrimLength > 0);
  const expectedSamples = Math.floor(0.4 * sampleRate) - Math.floor(0.1 * sampleRate);
  assert.strictEqual(capturedTrimLength, expectedSamples);
  assert(progressEvents.includes('completed'));
  console.log(`  ✓ Trimmed ${capturedTrimLength} samples with exact sub-millisecond precision.`);
  console.log(`  ✓ Output MP3 size: ${result.blob.size} bytes (100% computed in browser, 0% server CPU).\n`);
}

runAudioTest().then(() => {
  console.log('=====================================================');
  console.log('🎉 ALL CLIENT-SIDE PROCESSOR TESTS PASSED (100%)');
  console.log('=====================================================');
});
