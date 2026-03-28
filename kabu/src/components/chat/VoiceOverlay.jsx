import React, { useState, useRef, useCallback, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, Mic, Square, Volume2, VolumeX, Gauge } from "lucide-react";
import { streamChat } from "@/api/backend";

/* ── Browser support ───────────────────────────────────── */
const HAS_RECOGNITION =
  typeof window !== "undefined" &&
  !!(window.SpeechRecognition || window.webkitSpeechRecognition);

/* ── Voice states ──────────────────────────────────────── */
const S = { IDLE: "idle", LISTENING: "listening", PROCESSING: "processing", SPEAKING: "speaking" };

/* ── Particle sphere colors per state [r, g, b] ───────── */
const P_COLORS = {
  idle:       [195, 200, 215],
  listening:  [90, 170, 255],
  processing: [175, 140, 255],
  speaking:   [40, 215, 220],
};

/* ── Turn detection — inspired by Silero VAD / OpenAI Realtime ──
   Uses a redemption-based state machine instead of raw silence timers.
   Noise floor adapts continuously (EMA) instead of one-time calibration.

   Key insight from production voice assistants:
   - Don't use volume alone. Use SpeechRecognition as primary signal.
   - Allow "redemption" pauses (user thinking mid-sentence).
   - Require minimum speech duration to avoid noise triggers.
   - Adapt to environment continuously.                              */
const NOISE_FLOOR_SAMPLES = 30;
const NOISE_FLOOR_EMA = 0.003;       /* exponential moving average weight for continuous adaptation */
const SPEECH_OFFSET = 0.08;          /* volume above noise floor to count as "loud" */
const MIN_SPEECH_MS = 350;           /* minimum speech duration before silence detection activates */
const REDEMPTION_MS = 1200;          /* allow this much silence mid-sentence before ending turn */
const FINAL_RESULT_SILENCE_MS = 600; /* after SpeechRecognition gives isFinal, wait only this long */

/* ── Barge-in ─────────────────────────────────────────────
   Primary: SpeechRecognition passive mode (requires real words).
   VAD fallback: disabled during TTS to prevent self-triggering.
   Only used when TTS is NOT playing (e.g. during PROCESSING).   */
const BARGE_IN_OFFSET = 0.25;
const BARGE_IN_FRAMES = 35;          /* ~580ms at 60fps — very sustained */
const BARGE_IN_COOLDOWN = 2500;

/* ── Fuzzy wake word matching ─────────────────────────── */
function lev(a, b) {
  if (a.length === 0) return b.length;
  if (b.length === 0) return a.length;
  const prev = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    let corner = prev[0];
    prev[0] = i;
    for (let j = 1; j <= b.length; j++) {
      const up = prev[j];
      prev[j] = a[i - 1] === b[j - 1] ? corner : 1 + Math.min(prev[j], prev[j - 1], corner);
      corner = up;
    }
  }
  return prev[b.length];
}

/* ── isWakeWord — optimised for "Mimi" ─────────────────────
   Short 2-syllable name → Chrome transcribes it reliably.
   Layers: exact → phrase → substring → fuzzy → greeting+fuzzy.
   "Mimi" is common enough that we exclude obvious non-wake uses
   like "Miami", "mimic", "minimize".                            */
function isWakeWord(transcript) {
  const t = transcript.toLowerCase().trim();
  if (!t || t.length < 2) return false;

  /* ── Layer 0: Ultra-fast exact checks ── */
  if (t === "mimi" || t === "me me" || t === "mi mi") return true;
  if (t === "hey mimi" || t === "hi mimi" || t === "hey me me" || t === "hi me me") return true;

  /* ── Layer 1: Phrase containment (word-boundary aware) ── */
  const phrases = [
    "hey mimi", "hi mimi", "yo mimi", "ok mimi", "okay mimi",
    "hey me me", "hi me me", "hey mi mi", "hi mi mi",
    "a mimi", "oh mimi", "ay mimi",
    "hey meemee", "hi meemee", "hey meme", "hey mimi's",
  ];
  if (phrases.some((p) => {
    const idx = t.indexOf(p);
    if (idx === -1) return false;
    const after = idx + p.length;
    return after >= t.length || t[after] === " " || t[after] === "'";
  })) return true;

  /* ── Layer 2: Per-word containment ── */
  const words = t.split(/\s+/);
  const exclude = new Set([
    "miami", "mimic", "mimics", "mimicking", "mimicked",
    "minimize", "minimise", "minimum", "minimal", "minimax",
    "memoir", "memory", "memo", "meme", "memes",
  ]);
  for (const w of words) {
    if (exclude.has(w)) continue;
    if (w === "mimi" || w === "meemee" || w === "mimi's") return true;
  }

  /* ── Layer 3: Fuzzy single-word (Levenshtein ≤1 from "mimi") ── */
  for (const w of words) {
    if (w.length < 3 || w.length > 7 || exclude.has(w)) continue;
    if (lev(w, "mimi") <= 1) return true;
  }

  /* ── Layer 4: Greeting + generous fuzzy ── */
  const greetings = new Set(["hey", "hi", "ok", "okay", "yo", "a", "oh", "ay", "hei"]);
  for (let i = 0; i < words.length - 1; i++) {
    if (!greetings.has(words[i])) continue;
    const w = words[i + 1];
    if (w.length < 2 || exclude.has(w)) continue;
    if (lev(w, "mimi") <= 2) return true;
  }

  /* ── Layer 5: Joined consecutive words (catches "me" "me" → "meme"→"mimi" lev 2) ── */
  for (let i = 0; i < words.length - 1; i++) {
    if (exclude.has(words[i]) || exclude.has(words[i + 1])) continue;
    const joined = words[i] + words[i + 1];
    if (joined.length < 3 || joined.length > 8) continue;
    if (joined === "mimi" || joined === "meme" || joined === "meeme") return true;
    if (lev(joined, "mimi") <= 1) return true;
  }

  return false;
}

/* ── Greetings ─────────────────────────────────────────── */
function pickGreeting() {
  const h = new Date().getHours();
  const tod = h < 12 ? "morning" : h < 17 ? "afternoon" : "evening";
  const pool = [
    `Good ${tod}. I'm Mimi, your research assistant. Say "Hey Mimi" to interrupt me, or tap the orb to stop me talking. What are we looking at today?`,
    `Hey, I'm Mimi. I'm here to help with your research. You can say "Hey Mimi" anytime to jump in, or just tap the orb. So, what's on your mind?`,
    `Good ${tod}. Mimi here. To interrupt, just say "Hey Mimi" or press the orb. What should we dig into?`,
  ];
  return pool[Math.floor(Math.random() * pool.length)];
}

/* ── TTS speed options ────────────────────────────────── */
const SPEED_OPTIONS = [
  { label: "1\u00D7", rate: "+5%" },
  { label: "1.25\u00D7", rate: "+25%" },
  { label: "1.5\u00D7", rate: "+50%" },
  { label: "0.75\u00D7", rate: "-25%" },
];

/* ── Varied status labels ─────────────────────────────── */
const STATUS_POOL = {
  listening: ["Listening\u2026", "I\u2019m all ears\u2026", "Go ahead\u2026"],
  processing: ["Thinking\u2026", "Let me check\u2026", "One sec\u2026", "On it\u2026"],
};
const pick = (arr) => arr[Math.floor(Math.random() * arr.length)];
const POST_RESPONSE_PAUSE = 400; /* pause after bot finishes speaking before listening — prevents TTS tail pickup */


/* ══════════════════════════════════════════════════════════
   SPEECH HUMANIZER — natural TTS post-processing
   (only affects spoken audio, not displayed text)

   3-pass system: contractions → breath marks → rare stutter.
   ══════════════════════════════════════════════════════════ */
function humanizeSpeech(text) {
  if (text.length < 12) return text;
  let t = text;
  const R = () => Math.random();
  /* ══ PASS 0: Contractions — essential for natural speech ══ */
  t = t.replace(/\bIt is\b/g, "It's").replace(/\bit is\b/g, "it's");
  t = t.replace(/\bThat is\b/g, "That's").replace(/\bthat is\b/g, "that's");
  t = t.replace(/\bThere is\b/g, "There's").replace(/\bthere is\b/g, "there's");
  t = t.replace(/\bWhat is\b/g, "What's").replace(/\bwhat is\b/g, "what's");
  t = t.replace(/\bHere is\b/g, "Here's").replace(/\bhere is\b/g, "here's");
  t = t.replace(/\bWho is\b/g, "Who's").replace(/\bwho is\b/g, "who's");
  t = t.replace(/\bHow is\b/g, "How's").replace(/\bhow is\b/g, "how's");
  t = t.replace(/\bdo not\b/g, "don't").replace(/\bDo not\b/g, "Don't");
  t = t.replace(/\bcannot\b/g, "can't").replace(/\bCannot\b/g, "Can't");
  t = t.replace(/\bwill not\b/g, "won't").replace(/\bWill not\b/g, "Won't");
  t = t.replace(/\bdoes not\b/g, "doesn't").replace(/\bDoes not\b/g, "Doesn't");
  t = t.replace(/\bdid not\b/g, "didn't").replace(/\bDid not\b/g, "Didn't");
  t = t.replace(/\bwould not\b/g, "wouldn't").replace(/\bshould not\b/g, "shouldn't");
  t = t.replace(/\bcould not\b/g, "couldn't").replace(/\bCould not\b/g, "Couldn't");
  t = t.replace(/\bhas not\b/g, "hasn't").replace(/\bhad not\b/g, "hadn't");
  t = t.replace(/\bI would\b/g, "I'd").replace(/\bI will\b/g, "I'll");
  t = t.replace(/\bI have\b/g, "I've").replace(/\bI am\b/g, "I'm");
  t = t.replace(/\bthey are\b/g, "they're").replace(/\bThey are\b/g, "They're");
  t = t.replace(/\bthey have\b/g, "they've").replace(/\bThey have\b/g, "They've");
  t = t.replace(/\bwe are\b/g, "we're").replace(/\bWe are\b/g, "We're");
  t = t.replace(/\bwe have\b/g, "we've").replace(/\bWe have\b/g, "We've");
  t = t.replace(/\byou are\b/g, "you're").replace(/\bYou are\b/g, "You're");
  t = t.replace(/\byou have\b/g, "you've").replace(/\bYou have\b/g, "You've");
  t = t.replace(/\bis not\b/g, "isn't").replace(/\bwas not\b/g, "wasn't");
  t = t.replace(/\bwere not\b/g, "weren't").replace(/\bhave not\b/g, "haven't");
  t = t.replace(/\blet us\b/g, "let's").replace(/\bLet us\b/g, "Let's");
  t = t.replace(/\bhe is\b/g, "he's").replace(/\bHe is\b/g, "He's");
  t = t.replace(/\bshe is\b/g, "she's").replace(/\bShe is\b/g, "She's");
  t = t.replace(/\byou will\b/g, "you'll").replace(/\bYou will\b/g, "You'll");
  t = t.replace(/\bwe will\b/g, "we'll").replace(/\bWe will\b/g, "We'll");
  t = t.replace(/\bthey will\b/g, "they'll").replace(/\bThey will\b/g, "They'll");
  t = t.replace(/\bit would\b/g, "it'd").replace(/\bthat would\b/g, "that'd");
  t = t.replace(/\bwho would\b/g, "who'd").replace(/\bwhat will\b/g, "what'll");
  t = t.replace(/\bare not\b/g, "aren't").replace(/\bAre not\b/g, "Aren't");

  /* ══ PASS 1: Breath marks — commas before conjunctions for pacing ══ */
  t = t.replace(/(\w) but /g, (_, w) => R() < 0.6 ? `${w}, but ` : `${w} but `);
  t = t.replace(/(\w) and then /g, (_, w) => R() < 0.5 ? `${w}, and then ` : `${w} and then `);
  t = t.replace(/(\w) so /g, (_, w) => R() < 0.4 ? `${w}, so ` : `${w} so `);

  /* ══ PASS 2: Rare stutter (~2%) — repeat onset of a word ══ */
  if (R() < 0.02 && t.length > 30) {
    /* Find a word 4+ chars starting with a consonant, stutter its onset.
       Only stutter once per phrase and not at the very beginning. */
    let stuttered = false;
    t = t.replace(/\b([bcdfghjklmnpqrstvwxyz])([a-z]{3,})\b/gi, (m, c, rest, off) => {
      if (stuttered || off < 3) return m;
      stuttered = true;
      return `${c}- ${c.toLowerCase()}${rest}`;
    });
  }

  return t;
}

/* ══════════════════════════════════════════════════════════
   3D PARTICLE SPHERE SYSTEM
   ══════════════════════════════════════════════════════════ */
const PARTICLE_COUNT = 1200;
const AMBIENT_COUNT = 40;

function createParticles(count) {
  const particles = [];
  const golden = Math.PI * (3 - Math.sqrt(5));
  for (let i = 0; i < count; i++) {
    const y = 1 - (i / (count - 1)) * 2;
    const r = Math.sqrt(1 - y * y);
    const theta = golden * i;
    const x = Math.cos(theta) * r;
    const z = Math.sin(theta) * r;
    particles.push({
      bx: x, by: y, bz: z,
      vx: 0, vy: 0, vz: 0,
      size: 0.5 + Math.random() * 1.1,
      phase: Math.random() * Math.PI * 2,
      hueShift: (Math.random() - 0.5) * 30,
      twinkleSpeed: 3 + Math.random() * 8,
      driftOffset: Math.random() * Math.PI * 2,
    });
  }
  return particles;
}

/* Pre-compute constellation edge pairs (nearby particles on sphere surface) */
function buildEdges(particles, step = 4, maxDist = 0.25, maxEdges = 350) {
  const edges = [];
  const indices = [];
  for (let i = 0; i < particles.length; i += step) indices.push(i);
  for (let a = 0; a < indices.length; a++) {
    const i = indices[a];
    const pi = particles[i];
    for (let b = a + 1; b < indices.length; b++) {
      const j = indices[b];
      const pj = particles[j];
      const dx = pi.bx - pj.bx, dy = pi.by - pj.by, dz = pi.bz - pj.bz;
      const d2 = dx * dx + dy * dy + dz * dz;
      if (d2 < maxDist * maxDist) {
        edges.push([i, j]);
        if (edges.length >= maxEdges) return edges;
      }
    }
  }
  return edges;
}

/* Ambient floating background particles */
function createAmbientParticles(count) {
  return Array.from({ length: count }, () => ({
    x: Math.random(), y: Math.random(),
    vx: (Math.random() - 0.5) * 0.00015,
    vy: (Math.random() - 0.5) * 0.0001,
    size: 1.2 + Math.random() * 2,
    alpha: 0.015 + Math.random() * 0.035,
    phase: Math.random() * Math.PI * 2,
  }));
}

function rotY(x, y, z, a) {
  const c = Math.cos(a), s = Math.sin(a);
  return [x * c + z * s, y, -x * s + z * c];
}
function rotX(x, y, z, a) {
  const c = Math.cos(a), s = Math.sin(a);
  return [x, y * c - z * s, y * s + z * c];
}

/* ── Helpers ────────────────────────────────────────────── */
/* Batch 2-3 sentences per phrase for smoother TTS prosody.
   Short phrases cause the voice to reset intonation on each clip,
   sounding choppy. Longer phrases flow naturally like real speech. */
function extractPhrases(buf) {
  const phrases = [];
  let start = 0;
  for (let i = 0; i < buf.length; i++) {
    const ch = buf[i];
    const next = buf[i + 1];
    const phraseLen = i - start;
    if ((ch === "." || ch === "!" || ch === "?") && next === " ") {
      if (ch === "." && i > 0 && buf[i - 1] >= "0" && buf[i - 1] <= "9") continue;
      /* Emit after ~1.5 sentences for snappy first response */
      if (phraseLen >= 40) {
        phrases.push(buf.slice(start, i + 1).trim());
        start = i + 2;
        i = start - 1;
      }
      continue;
    }
    if (phraseLen >= 120 && next === " ") {
      if (ch === "," || ch === ";" || ch === "\u2014" || ch === ":") {
        phrases.push(buf.slice(start, i + 1).trim());
        start = i + 2;
        i = start - 1;
      }
    }
  }
  return { phrases: phrases.filter(Boolean), remaining: buf.slice(start) };
}

/* Strip markdown formatting so TTS doesn't read "asterisk" or "dash dash" aloud */
function stripMarkdown(text) {
  return text
    .replace(/\*\*(.+?)\*\*/g, "$1")   // **bold**
    .replace(/\*(.+?)\*/g, "$1")        // *italic*
    .replace(/__(.+?)__/g, "$1")        // __bold__
    .replace(/_(.+?)_/g, "$1")          // _italic_
    .replace(/~~(.+?)~~/g, "$1")        // ~~strikethrough~~
    .replace(/`([^`]+)`/g, "$1")        // `code`
    .replace(/^#{1,6}\s+/gm, "")        // # headings
    .replace(/^[-*+]\s+/gm, "")         // - bullet lists
    .replace(/^\d+\.\s+/gm, "")         // 1. numbered lists
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1") // [link](url)
    .replace(/^>\s+/gm, "")             // > blockquotes
    .replace(/^[-*_]{3,}\s*$/gm, "")    // --- horizontal rules
    .replace(/^\|.*\|$/gm, "")          // | table rows |
    .replace(/^[\s|:-]+$/gm, "")        // table separator lines
    .replace(/\n{2,}/g, " ")            // collapse double newlines
    .replace(/\n/g, " ")                // remaining newlines to spaces
    .replace(/\s{2,}/g, " ")            // collapse multiple spaces
    .trim();
}

const _pick = (arr) => arr[Math.floor(Math.random() * arr.length)];

/* Short labels for on-screen tool chips & status bar */
function toolChipLabel(tool, input) {
  const code = input?.stock_code || "";
  switch (tool) {
    case "lookup_company": return `Looking up ${code}`;
    case "get_stock_prices": return `Prices for ${code}`;
    case "get_financials": return `Financials`;
    case "search_edinet_filings": return `EDINET filings`;
    case "web_search": return `Web search`;
    case "get_directors": return `Board data`;
    case "get_voting_results": return `AGM votes`;
    case "get_large_shareholders": return `Large holders`;
    case "analyze_technicals": return `Technicals`;
    case "score_company": return `Scoring ${code}`;
    case "get_company_peers": return `Peer comparison`;
    case "get_market_context": return `Market data`;
    case "screen_sector": return `Sector screen`;
    case "analyze_risk": return `Risk analysis`;
    case "detect_red_flags": return `Red flag scan`;
    case "get_shareholder_structure": return `Shareholder data`;
    case "search_fund_holdings": return `Fund holdings`;
    default: return tool.replace(/_/g, " ");
  }
}

/* Natural conversational phrases for TTS — spoken only when Claude didn't
   provide its own filler text before calling the tool. */
function toolVoicePhrase(tool, input) {
  const code = input?.stock_code || "";
  const name = input?.company_name || code;
  switch (tool) {
    case "lookup_company":
      return _pick([`Let me look up ${code} for you.`, `One moment, pulling up ${code}.`]);
    case "get_stock_prices":
      return _pick([`Let me grab the latest stock price.`, `Pulling up the price data now.`, `Checking the market for ${code}.`]);
    case "get_financials":
      return _pick([`Let me pull the financial statements.`, `Loading the quarterly numbers now.`, `Checking the earnings data.`]);
    case "search_edinet_filings":
      return _pick([`Let me scan the EDINET filings.`, `Searching EDINET for relevant documents.`, `Checking the regulatory filings now.`]);
    case "web_search":
      return _pick([`Let me search the web for that.`, `Running a quick web search.`, `Searching for the latest info.`]);
    case "get_directors":
      return _pick([`Let me pull up the board of directors.`, `Checking the board composition now.`, `Looking up the director data from EDINET.`]);
    case "get_voting_results":
      return _pick([`Let me check the AGM voting results.`, `Pulling up the shareholder meeting results.`]);
    case "get_large_shareholders":
      return _pick([`Let me check EDINET for any large holder filings.`, `Searching for five-percent filings on EDINET.`, `Checking who holds major stakes.`]);
    case "analyze_technicals":
      return _pick([`Running the technical analysis now.`, `Let me check the technical indicators.`]);
    case "score_company":
      return _pick([`Let me score ${code} across the key metrics.`, `Running the quantitative scoring model.`]);
    case "get_company_peers":
      return _pick([`Let me find the peer companies for comparison.`, `Looking up sector peers now.`]);
    case "get_market_context":
      return _pick([`Let me check the broader market context.`, `Pulling up the market overview.`]);
    case "screen_sector":
      return _pick([`Screening the sector now.`, `Let me scan the sector for top companies.`]);
    case "analyze_risk":
      return _pick([`Let me analyze the risk profile.`, `Running the risk analytics now.`]);
    case "detect_red_flags":
      return _pick([`Let me run a forensic accounting scan.`, `Checking for any red flags in the financials.`]);
    case "get_shareholder_structure":
      return _pick([`Let me pull the shareholder data from the annual report.`, `Checking the ownership structure via EDINET. This one takes a moment.`, `Pulling up the major shareholders from the latest filing.`]);
    case "search_fund_holdings":
      return _pick([`Searching the fund holdings now.`, `Let me check the fund's portfolio.`]);
    default:
      return `Working on that now.`;
  }
}

/* ── Audio cue utilities ───────────────────────────────── */
let _toneCtx = null;
function getToneCtx() {
  if (!_toneCtx || _toneCtx.state === "closed") {
    try { _toneCtx = new (window.AudioContext || window.webkitAudioContext)(); }
    catch { return null; }
  }
  if (_toneCtx.state === "suspended") _toneCtx.resume().catch(() => {});
  return _toneCtx;
}
function closeToneCtx() {
  if (_toneCtx && _toneCtx.state !== "closed") { _toneCtx.close().catch(() => {}); _toneCtx = null; }
}

function playTone(freq, endFreq, durationMs = 150, vol = 0.12) {
  const ctx = getToneCtx();
  if (!ctx) return;
  try {
    const t = ctx.currentTime;
    const dur = durationMs / 1000;
    const osc1 = ctx.createOscillator();
    const gain1 = ctx.createGain();
    osc1.type = "sine";
    osc1.frequency.setValueAtTime(freq, t);
    if (endFreq !== freq) osc1.frequency.linearRampToValueAtTime(endFreq, t + dur);
    gain1.gain.setValueAtTime(0.001, t);
    gain1.gain.linearRampToValueAtTime(vol, t + 0.015);
    gain1.gain.exponentialRampToValueAtTime(0.001, t + dur);
    osc1.connect(gain1);
    gain1.connect(ctx.destination);
    osc1.start(t);
    osc1.stop(t + dur + 0.02);
    const osc2 = ctx.createOscillator();
    const gain2 = ctx.createGain();
    osc2.type = "sine";
    osc2.frequency.setValueAtTime(freq * 1.003, t);
    if (endFreq !== freq) osc2.frequency.linearRampToValueAtTime(endFreq * 1.003, t + dur);
    gain2.gain.setValueAtTime(0.001, t);
    gain2.gain.linearRampToValueAtTime(vol * 0.4, t + 0.015);
    gain2.gain.exponentialRampToValueAtTime(0.001, t + dur);
    osc2.connect(gain2);
    gain2.connect(ctx.destination);
    osc2.start(t);
    osc2.stop(t + dur + 0.02);
  } catch {}
}

const AUDIO_CUES = {
  listen:  () => playTone(380, 720, 160, 0.14),
  process: () => { playTone(520, 520, 80, 0.12); setTimeout(() => playTone(620, 620, 80, 0.12), 120); },
  speak:   () => playTone(800, 420, 220, 0.12),
  idle:    () => playTone(420, 220, 170, 0.10),
};

/* ══════════════════════════════════════════════════════════
   DRAW PARTICLE SPHERE — Full visual pipeline
   ══════════════════════════════════════════════════════════ */
function drawParticleSphere(
  ctx, w, h, time, vol, state, particles, color,
  orbCy, orbRadius, scatterT, audioData, mouseX, mouseY,
  edges, ambientParticles, gravityT, accumRot,
) {
  ctx.clearRect(0, 0, w, h);

  const cx = w / 2;
  const cy = orbCy;
  const baseR = orbRadius;
  const [cr, cg, cb] = color;
  const fov = 350;

  /* State-dependent animation */
  const isListening = state === S.LISTENING;
  let breathAmp = 0.03, noiseAmp = 0, torusFactor = 0, exhaleAmp = 0, voiceExpand = 0;
  if (state === S.IDLE) { breathAmp = 0.04; }
  else if (isListening) {
    breathAmp = 0.02;           /* very subtle baseline pulse */
    noiseAmp = 0;               /* perfectly smooth sphere */
    voiceExpand = vol * 0.45;   /* sphere grows/shrinks with voice */
  }
  else if (state === S.PROCESSING) { torusFactor = 0.7 + Math.sin(time * 2) * 0.15; breathAmp = 0.02; }
  else if (state === S.SPEAKING) { breathAmp = 0.06 + vol * 0.08; exhaleAmp = 0.15; }

  const scale = baseR * (1 + Math.sin(time * 0.7) * breathAmp + voiceExpand);

  /* Rotation: use accumulated angle (freezes instantly when LISTENING) */
  const mouseInfluence = isListening ? 0 : 0.4;
  const baseRotY = accumRot != null ? accumRot : time * 0.2;
  const baseRotX = isListening ? 0 : Math.sin(time * 0.15) * 0.25;
  const rotAngleY = baseRotY + (mouseX - 0.5) * mouseInfluence;
  const rotAngleX = baseRotX + (mouseY - 0.5) * mouseInfluence * 0.6;

  /* ── Background aurora arcs ── */
  for (let i = 0; i < 3; i++) {
    const at = time * 0.08 + i * 2.094;
    const ax = cx + Math.sin(at) * w * 0.25;
    const ay = cy + Math.cos(at * 0.6 + i) * h * 0.12;
    const ar = scale * (3 + i * 0.7);
    const intensity = state === S.IDLE ? 0.012 : state === S.LISTENING ? 0.015 + vol * 0.04 : 0.015;
    const ag = ctx.createRadialGradient(ax, ay, 0, ax, ay, ar);
    const hr = Math.max(0, Math.min(255, cr + (i - 1) * 35));
    const hg = Math.max(0, Math.min(255, cg + (i - 1) * 20));
    ag.addColorStop(0, `rgba(${hr},${hg},${cb},${intensity})`);
    ag.addColorStop(0.5, `rgba(${hr},${hg},${cb},${intensity * 0.3})`);
    ag.addColorStop(1, `rgba(${hr},${hg},${cb},0)`);
    ctx.fillStyle = ag;
    ctx.fillRect(0, 0, w, h);
  }

  /* ── Core glow ── */
  const glowR = scale * 2.2;
  const glowA = state === S.IDLE ? 0.035 : state === S.LISTENING ? 0.05 + vol * 0.08 : 0.05;
  const bgG = ctx.createRadialGradient(cx, cy, 0, cx, cy, glowR);
  bgG.addColorStop(0, `rgba(${cr},${cg},${cb},${glowA})`);
  bgG.addColorStop(0.6, `rgba(${cr},${cg},${cb},${glowA * 0.3})`);
  bgG.addColorStop(1, `rgba(${cr},${cg},${cb},0)`);
  ctx.fillStyle = bgG;
  ctx.fillRect(0, 0, w, h);

  /* ── Ambient background particles ── */
  if (ambientParticles) {
    for (const ap of ambientParticles) {
      ap.x += ap.vx + Math.sin(time * 0.3 + ap.phase) * 0.00008;
      ap.y += ap.vy + Math.cos(time * 0.2 + ap.phase) * 0.00006;
      if (ap.x < -0.05) ap.x = 1.05;
      if (ap.x > 1.05) ap.x = -0.05;
      if (ap.y < -0.05) ap.y = 1.05;
      if (ap.y > 1.05) ap.y = -0.05;
      const pulse = 0.7 + 0.3 * Math.sin(time * 0.5 + ap.phase);
      const ax = ap.x * w;
      const ay = ap.y * h;
      ctx.beginPath();
      ctx.arc(ax, ay, ap.size * 2.5 * pulse, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(${cr},${cg},${cb},${ap.alpha * 0.3 * pulse})`;
      ctx.fill();
      ctx.beginPath();
      ctx.arc(ax, ay, ap.size * 0.5, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(${cr},${cg},${cb},${ap.alpha * pulse})`;
      ctx.fill();
    }
  }

  /* ── Project particles (reuse projection slots on particle objects to avoid GC) ── */
  const noiseT = time * (isListening ? 0 : 0.4);
  const organicAmp = isListening ? 0 : (0.03 + (state === S.IDLE ? 0.02 : state === S.SPEAKING ? 0.04 : 0));

  /* Pre-compute LISTENING voice field parameters (hoisted) */
  const hasFft = isListening && audioData && audioData.length > 0;
  const fftLen = hasFft ? audioData.length : 0;
  const listenT1 = time * 0.25;
  const listenT2 = time * 0.4;
  const vSq = vol * vol;

  for (let idx = 0; idx < particles.length; idx++) {
    const p = particles[idx];
    let px = p.bx, py = p.by, pz = p.bz;

    /* Organic noise deformation (non-LISTENING states) */
    px += Math.sin(px * 4 + noiseT + p.phase) * organicAmp;
    py += Math.sin(py * 4 + noiseT * 1.1 + p.driftOffset) * organicAmp;
    pz += Math.sin(pz * 4 + noiseT * 0.9 + p.phase * 0.7) * organicAmp;

    /* Torus deformation for PROCESSING (with twist) */
    if (torusFactor > 0) {
      py *= (1 - torusFactor * 0.85);
      const flatR = Math.sqrt(px * px + pz * pz);
      if (flatR > 0.01) {
        const targetR = Math.max(flatR, 0.6 + torusFactor * 0.4);
        const twist = Math.sin(py * 8 + time * 4) * 0.06 * torusFactor;
        const npx = px * targetR / flatR + twist * pz / flatR;
        const npz = pz * targetR / flatR - twist * px / flatR;
        px = npx;
        pz = npz;
      }
    }

    /* ═══ LISTENING: per-particle voice-reactive displacement ═══
       Three layers combine for complex, random, volume-synced motion:
       1. Multi-octave noise → each particle has unique organic drift
       2. FFT frequency-band mapping → voice spectrum drives sphere regions
       3. Volume-reactive radial pulse → overall expansion on speech
    */
    if (isListening) {
      /* Layer 1: Multi-octave per-particle noise (always alive, subtle baseline) */
      const n1 = Math.sin(p.phase * 7.3 + listenT1) * Math.cos(p.driftOffset * 5.1 + listenT2 * 0.7);
      const n2 = Math.sin(p.bx * 6 + listenT2 + p.phase) * Math.cos(p.by * 5 + listenT1 * 1.5);
      const n3 = Math.cos(p.bz * 4 + listenT1 * 1.3 + p.driftOffset);
      const noise = n1 * 0.5 + n2 * 0.35 + n3 * 0.15;

      /* Baseline drift (sphere breathes organically even when silent) */
      const baseDrift = noise * 0.02;

      /* Voice-reactive push (squared volume for punchy dynamics) */
      const voicePush = Math.abs(noise) * vSq * 0.35;

      /* Layer 2: FFT frequency-band mapping
         Low freq (bass/vowels) → bottom of sphere
         High freq (sibilants) → top of sphere
         Each particle resonates at its own strength */
      let freqPush = 0;
      if (hasFft) {
        const yNorm = (p.by + 1) * 0.5;
        const binIdx = Math.min(Math.floor(yNorm * fftLen * 0.6), fftLen - 1);
        const binVal = audioData[binIdx] / 255;
        const resonance = 0.55 + 0.45 * Math.sin(p.phase * 5 + p.driftOffset);
        freqPush = binVal * binVal * resonance * 0.2;
      }

      /* Layer 3: Global volume expansion (uniform baseline) */
      const globalPulse = vSq * 0.08;

      const totalPush = baseDrift + voicePush + freqPush + globalPulse;
      px *= (1 + totalPush);
      py *= (1 + totalPush);
      pz *= (1 + totalPush);
    }
    /* Volume-reactive noise for other states */
    else if (noiseAmp > 0) {
      const n = Math.sin(p.phase + time * 3.5) * noiseAmp;
      px += px * n; py += py * n; pz += pz * n;
    }

    /* Exhale drift during SPEAKING (top particles breathe outward) */
    if (exhaleAmp > 0 && p.by > 0.2) {
      const drift = Math.sin(time * 1.8 + p.phase) * exhaleAmp * (p.by - 0.2);
      py += drift;
      const spread = Math.sin(time * 2.3 + p.driftOffset) * exhaleAmp * 0.25 * (p.by - 0.2);
      px += px * spread;
      pz += pz * spread;
    }

    /* Gravity drop when returning to IDLE (particles fall then reform) */
    if (gravityT >= 0 && gravityT < 2.0) {
      const fallPhase = Math.min(1, gravityT / 0.6);
      const reformPhase = Math.max(0, (gravityT - 0.5) / 1.5);
      const amount = fallPhase * Math.pow(1 - reformPhase, 2);
      py += (0.4 + Math.sin(p.phase * 7) * 0.3) * amount;
      px += Math.sin(p.driftOffset * 5) * 0.15 * amount;
      pz += Math.cos(p.phase * 3) * 0.15 * amount;
    }

    /* Scatter effect on interrupt */
    if (scatterT >= 0 && scatterT < 1.2) {
      const decay = Math.pow(Math.max(0, 1 - scatterT / 1.2), 2.5);
      px += p.vx * decay;
      py += p.vy * decay;
      pz += p.vz * decay;
    }

    /* 3D rotation */
    let [rx, ry, rz] = rotY(px, py, pz, rotAngleY);
    [rx, ry, rz] = rotX(rx, ry, rz, rotAngleX);

    /* Perspective projection */
    const perspective = fov / (fov + rz * scale);
    const sx = cx + rx * scale * perspective;
    const sy = cy + ry * scale * perspective;

    /* Depth-based brightness + voice-reactive shimmer + volume-peak sparkles */
    const depthFactor = 0.2 + 0.8 * ((rz + 1) / 2);
    const shimmer = isListening
      ? 0.78 + 0.22 * vol + 0.06 * Math.sin(time * 0.4 + p.phase)
      : 0.75 + 0.25 * Math.sin(time * 1.5 + p.phase);
    const twinkle = isListening
      ? (vol > 0.3 && Math.sin(time * p.twinkleSpeed * 0.4 + p.phase * 10) > 0.94 ? 1.2 + vol * 0.4 : 1.0)
      : (Math.sin(time * p.twinkleSpeed + p.phase * 10) > 0.92 ? 1.8 : 1.0);
    const brightness = depthFactor * shimmer * twinkle;

    /* Per-particle color variation */
    const pr = Math.max(0, Math.min(255, cr + p.hueShift));
    const pg = Math.max(0, Math.min(255, cg + p.hueShift * 0.5));
    const pb = Math.max(0, Math.min(255, cb - p.hueShift * 0.3));

    /* Per-particle size: grows with voice volume, each particle unique */
    const voiceSizeBoost = isListening ? 1 + vol * 0.35 * (0.6 + 0.4 * Math.sin(p.phase * 3 + time * 0.5)) : 1;

    /* Store projection directly on particle (avoids 1200 object allocations per frame) */
    p._sx = sx; p._sy = sy; p._sz = p.size * perspective * voiceSizeBoost;
    p._br = brightness; p._dz = rz;
    p._cr = pr; p._cg = pg; p._cb = pb;
  }

  /* ── Constellation lines (batched by alpha for performance) ── */
  if (edges && edges.length > 0) {
    const batches = [
      { path: new Path2D(), alpha: 0.03, count: 0 },
      { path: new Path2D(), alpha: 0.07, count: 0 },
      { path: new Path2D(), alpha: 0.13, count: 0 },
    ];
    for (const [i, j] of edges) {
      const a = particles[i], b = particles[j];
      if (a._dz < -0.2 || b._dz < -0.2) continue;
      const dx = a._sx - b._sx, dy = a._sy - b._sy;
      const sd = Math.sqrt(dx * dx + dy * dy);
      if (sd > 55) continue;
      const lineAlpha = Math.min(a._br, b._br) * 0.15 * (1 - sd / 55);
      const batch = lineAlpha > 0.08 ? batches[2] : lineAlpha > 0.04 ? batches[1] : batches[0];
      batch.path.moveTo(a._sx, a._sy);
      batch.path.lineTo(b._sx, b._sy);
      batch.count++;
    }
    ctx.lineWidth = 0.5;
    for (const b of batches) {
      if (b.count === 0) continue;
      ctx.strokeStyle = `rgba(${cr},${cg},${cb},${b.alpha})`;
      ctx.stroke(b.path);
    }
  }

  /* ── Draw particles ── */
  for (const p of particles) {
    const alpha = p._br * 0.85;
    const r = Math.max(0.4, p._sz * 1.1);
    ctx.beginPath();
    ctx.arc(p._sx, p._sy, r, 0, Math.PI * 2);
    ctx.fillStyle = `rgba(${p._cr},${p._cg},${p._cb},${alpha})`;
    ctx.fill();
  }

  /* ── Additive glow pass for bright front-facing particles ── */
  ctx.globalCompositeOperation = "lighter";
  for (const p of particles) {
    if (p._br < 0.82 || p._dz < 0.2) continue;
    const glowAlpha = (p._br - 0.82) * 0.8;
    const gr = p._sz * 3.5;
    ctx.beginPath();
    ctx.arc(p._sx, p._sy, gr, 0, Math.PI * 2);
    ctx.fillStyle = `rgba(${p._cr},${p._cg},${p._cb},${glowAlpha})`;
    ctx.fill();
  }
  ctx.globalCompositeOperation = "source-over";

  /* ── Flash overlay on interrupt ── */
  if (scatterT >= 0 && scatterT < 0.4) {
    const flashAlpha = (1 - scatterT / 0.4) * 0.15;
    ctx.fillStyle = `rgba(255,255,255,${flashAlpha})`;
    ctx.fillRect(0, 0, w, h);
  }
}

/* ══════════════════════════════════════════════════════════
   VOICE OVERLAY COMPONENT
   ══════════════════════════════════════════════════════════ */
export default function VoiceOverlay({ isOpen, onClose }) {
  const [voiceState, setVoiceState] = useState(S.IDLE);
  const [interimText, setInterimText] = useState("");
  const [currentPhrase, setCurrentPhrase] = useState(""); /* phrase currently being spoken */
  const [phraseKey, setPhraseKey] = useState(0);           /* animation key for phrase transitions */
  const [statusLabel, setStatusLabel] = useState("");
  const [activeTools, setActiveTools] = useState([]);
  const [historyVersion, setHistoryVersion] = useState(0);
  const [isMuted, setIsMuted] = useState(false);
  const [ttsSpeedIdx, setTtsSpeedIdx] = useState(0);

  /* ── Refs ── */
  const canvasRef = useRef(null);
  const animRef = useRef(null);
  const volumeRef = useRef(0);
  const stateRef = useRef(S.IDLE);

  /* Particle system */
  const particlesRef = useRef(null);
  const edgesRef = useRef(null);
  const ambientRef = useRef(null);
  const colorRef = useRef([...P_COLORS.idle]);
  const targetColorRef = useRef(P_COLORS.idle);
  const orbCyRef = useRef(0.40);
  const orbRadRef = useRef(90);
  const targetCyRef = useRef(0.40);
  const targetRadRef = useRef(90);
  const mouseRef = useRef({ x: 0.5, y: 0.5 });
  const smoothVolRef = useRef(0);
  const gravityFlashRef = useRef(0);
  const accumRotRef = useRef(0);
  const lastTimeRef = useRef(0);

  /* Mic audio pipeline */
  const audioCtxRef = useRef(null);
  const analyserRef = useRef(null);
  const micStreamRef = useRef(null);
  const audioDataRef = useRef(null);
  const volAnimRef = useRef(null);
  const micVolumeRef = useRef(0);

  /* Silence / turn detection */
  const noiseFloorRef = useRef(0.05);
  const calibratingRef = useRef(true);
  const calibrationSamplesRef = useRef([]);
  const speechDetectedRef = useRef(false);
  const speechStartTimeRef = useRef(0);    /* when speech volume first exceeded threshold */
  const lastSpeechTimeRef = useRef(0);
  const hasWordsRef = useRef(false);
  const hasFinalResultRef = useRef(false); /* SpeechRecognition gave isFinal=true */
  const lastRecognitionEventRef = useRef(0); /* timestamp of last onresult event */

  /* Speech recognition */
  const recognitionRef = useRef(null);
  const accumulatedTextRef = useRef("");
  const lastInterimRef = useRef("");
  const passiveModeRef = useRef(false);

  /* Stable ref for onClose */
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  /* TTS */
  const ttsQueueRef = useRef([]);
  const isSpeakingTTSRef = useRef(false);
  const phraseBufferRef = useRef("");
  const streamDoneRef = useRef(false);
  const ttsSourceRef = useRef(null);
  const ttsAbortRef = useRef(null);
  const ttsCacheRef = useRef(new Map()); /* pre-fetched TTS AudioBuffers */
  const ttsGainRef = useRef(null); /* live gain node for dynamic ducking */
  const speakWaiterRef = useRef(null); /* resolve fn to wake speakNext when new phrases arrive */

  /* AI streaming */
  const abortRef = useRef(null);
  const historyRef = useRef([]);
  const fullResponseRef = useRef("");
  const activeRef = useRef(false);

  /* Function refs */
  const sendToAIRef = useRef(null);
  const startRecognitionRef = useRef(null);
  const cancelTTSRef = useRef(null);
  const toggleMuteRef = useRef(null);
  const cycleSpeedRef = useRef(null);
  const speakNextRef = useRef(null);
  const requestIdRef = useRef(0);

  /* Controls */
  const mutedRef = useRef(false);
  const ttsSpeedRef = useRef(SPEED_OPTIONS[0].rate);
  const greetedRef = useRef(false);
  const pttRef = useRef(false);
  const wakeFlashRef = useRef(0);
  const scatteredRef = useRef(false);

  /* Barge-in */
  const bargeInCountRef = useRef(0);
  const lastBargeInRef = useRef(0);
  const wakeTriggeredRef = useRef(false);
  const stuckSpeakingCountRef = useRef(0);
  const duckTimerRef = useRef(null);

  /* ── Transition helper ── */
  const transition = useCallback((newState) => {
    const prev = stateRef.current;
    if (prev === newState) return;
    stateRef.current = newState;
    setVoiceState(newState);
    bargeInCountRef.current = 0;

    /* Target color */
    targetColorRef.current = P_COLORS[newState];

    /* Cancel gravity animation when leaving IDLE (prevents bleed into LISTENING) */
    if (prev === S.IDLE && gravityFlashRef.current > 0) {
      gravityFlashRef.current = 0;
    }

    /* Orb position: SPEAKING → smaller + lower, else centered + large */
    if (newState === S.SPEAKING) {
      targetCyRef.current = 0.46;
      targetRadRef.current = 50;
    } else {
      targetCyRef.current = 0.40;
      targetRadRef.current = 90;
    }

    /* Gravity drop: particles fall and reform when going to IDLE after speaking */
    if (newState === S.IDLE && (prev === S.SPEAKING || prev === S.PROCESSING)) {
      gravityFlashRef.current = performance.now();
    }

    if (newState === S.LISTENING) AUDIO_CUES.listen();
    else if (newState === S.PROCESSING) AUDIO_CUES.process();
    else if (newState === S.SPEAKING) AUDIO_CUES.speak();
    else if (newState === S.IDLE && prev !== S.IDLE) AUDIO_CUES.idle();

    if (newState === S.IDLE) {
      setStatusLabel("");
      setTimeout(() => {
        if (activeRef.current && stateRef.current === S.IDLE) {
          startRecognitionRef.current?.(true);
        }
      }, 150);
    }
    else if (newState === S.LISTENING) setStatusLabel(pick(STATUS_POOL.listening));
    else if (newState === S.PROCESSING) setStatusLabel(pick(STATUS_POOL.processing));
    else if (newState === S.SPEAKING) setStatusLabel(mutedRef.current ? "Speaking (muted)\u2026" : "Tap orb to stop\u2026");
  }, []);

  /* ══════════════════════════════════════════════════════
     CANVAS ANIMATION LOOP
     ══════════════════════════════════════════════════════ */
  const startCanvas = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx2d = canvas.getContext("2d");

    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      if (!canvas.parentElement) return;
      const rect = canvas.parentElement.getBoundingClientRect();
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      ctx2d.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();

    if (!particlesRef.current) particlesRef.current = createParticles(PARTICLE_COUNT);
    if (!edgesRef.current) edgesRef.current = buildEdges(particlesRef.current);
    if (!ambientRef.current) ambientRef.current = createAmbientParticles(AMBIENT_COUNT);
    const t0 = performance.now();

    const tick = () => {
      const dpr = window.devicePixelRatio || 1;
      const now = performance.now();
      const time = (now - t0) / 1000;
      const w = canvas.width / dpr;
      const h = canvas.height / dpr;

      /* Smooth lerp color */
      const cc = colorRef.current;
      const tc = targetColorRef.current;
      cc[0] += (tc[0] - cc[0]) * 0.08;
      cc[1] += (tc[1] - cc[1]) * 0.08;
      cc[2] += (tc[2] - cc[2]) * 0.08;

      /* Asymmetric volume smoothing: fast expand on speech, slow graceful deflation */
      const rawVol = volumeRef.current;
      const volLerp = rawVol > smoothVolRef.current ? 0.18 : 0.04;
      smoothVolRef.current += (rawVol - smoothVolRef.current) * volLerp;

      /* Smooth lerp position + radius */
      orbCyRef.current += (targetCyRef.current - orbCyRef.current) * 0.06;
      orbRadRef.current += (targetRadRef.current - orbRadRef.current) * 0.06;

      /* Scatter detection: when barge-in flash triggers, set scatter velocities */
      let scatterT = -1;
      if (wakeFlashRef.current > 0) {
        scatterT = (now - wakeFlashRef.current) / 1000;
        if (scatterT < 0.05 && !scatteredRef.current) {
          scatteredRef.current = true;
          for (const p of particlesRef.current) {
            p.vx = p.bx * (2.0 + Math.random() * 3.0);
            p.vy = p.by * (2.0 + Math.random() * 3.0);
            p.vz = p.bz * (2.0 + Math.random() * 3.0);
          }
        }
        if (scatterT > 1.2) {
          wakeFlashRef.current = 0;
          scatteredRef.current = false;
        }
      }

      /* Gravity drop timing */
      const gravT = gravityFlashRef.current > 0 ? (now - gravityFlashRef.current) / 1000 : -1;
      if (gravT > 2.0) gravityFlashRef.current = 0;

      /* Accumulated rotation — slow drift when LISTENING+silent, freezes when speaking */
      const dt = time - lastTimeRef.current;
      lastTimeRef.current = time;
      const curState = stateRef.current;
      const listenSpin = smoothVolRef.current < 0.08 ? 0.04 * (1 - smoothVolRef.current / 0.08) : 0;
      const frameRotSpeed = curState === S.LISTENING ? listenSpin : curState === S.IDLE ? 0.15 : curState === S.PROCESSING ? 0.7 : curState === S.SPEAKING ? 0.25 : 0.2;
      accumRotRef.current += dt * frameRotSpeed;

      drawParticleSphere(
        ctx2d, w, h, time, smoothVolRef.current, stateRef.current,
        particlesRef.current,
        [Math.round(cc[0]), Math.round(cc[1]), Math.round(cc[2])],
        orbCyRef.current * h,
        orbRadRef.current,
        scatterT,
        audioDataRef.current,
        mouseRef.current.x,
        mouseRef.current.y,
        edgesRef.current,
        ambientRef.current,
        gravT,
        accumRotRef.current,
      );

      animRef.current = requestAnimationFrame(tick);
    };
    animRef.current = requestAnimationFrame(tick);
    return resize;
  }, []);

  /* ══════════════════════════════════════════════════════
     MICROPHONE + AUDIO ANALYSIS + SILENCE / BARGE-IN
     ══════════════════════════════════════════════════════ */
  const startMic = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      if (!activeRef.current) {
        stream.getTracks().forEach((t) => t.stop());
        return false;
      }
      micStreamRef.current = stream;

      const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      audioCtxRef.current = audioCtx;
      const source = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.5; /* Lower = faster response to voice changes */
      source.connect(analyser);
      analyserRef.current = analyser;
      audioDataRef.current = new Uint8Array(analyser.frequencyBinCount);

      calibratingRef.current = true;
      calibrationSamplesRef.current = [];
      noiseFloorRef.current = 0.05;

      const volTick = () => {
        if (!analyserRef.current) return;

        analyserRef.current.getByteFrequencyData(audioDataRef.current);
        const sum = audioDataRef.current.reduce((a, b) => a + b, 0);
        const micVol = Math.min(1, (sum / audioDataRef.current.length / 255) * 3);
        micVolumeRef.current = micVol;

        /* Noise floor — initial calibration then continuous EMA adaptation */
        if (calibratingRef.current) {
          calibrationSamplesRef.current.push(micVol);
          if (calibrationSamplesRef.current.length >= NOISE_FLOOR_SAMPLES) {
            noiseFloorRef.current =
              calibrationSamplesRef.current.reduce((a, b) => a + b, 0) /
              calibrationSamplesRef.current.length;
            calibratingRef.current = false;
          }
        } else if (stateRef.current !== S.SPEAKING) {
          /* Continuously adapt noise floor when not speaking (EMA).
             This handles environment changes (AC, fan, door opens). */
          const floor = noiseFloorRef.current;
          if (micVol < floor + SPEECH_OFFSET * 2) {
            noiseFloorRef.current = floor * (1 - NOISE_FLOOR_EMA) + micVol * NOISE_FLOOR_EMA;
          }
        }

        /* Orb volume source */
        if (stateRef.current === S.SPEAKING && isSpeakingTTSRef.current) {
          const t = Date.now();
          volumeRef.current = 0.3 + Math.sin(t / 200) * 0.15 + Math.sin(t / 317) * 0.1;
        } else {
          volumeRef.current = micVol;
        }

        const now = Date.now();

        /* ── Turn detection (LISTENING) — dual-signal like production voice UIs ──

           PATH A (volume-based): Track when mic is loud, end turn after silence.
           PATH B (recognition-based): Track when SpeechRecognition last gave results.
                  If no new results arrive for the timeout period, end turn.
                  This catches the case where volume is low but speech IS recognized.

           Either path can trigger turn end. Both require hasWords (SpeechRecognition
           confirmed actual speech, not just noise). */
        if (stateRef.current === S.LISTENING && !calibratingRef.current && !pttRef.current) {
          const threshold = noiseFloorRef.current + SPEECH_OFFSET;

          /* PATH A: Volume tracking */
          if (micVol > threshold) {
            if (!speechDetectedRef.current) {
              speechDetectedRef.current = true;
              speechStartTimeRef.current = now;
            }
            lastSpeechTimeRef.current = now;
          }

          if (hasWordsRef.current) {
            let shouldEnd = false;

            /* PATH A: Volume went quiet after sustained speech */
            if (speechDetectedRef.current && lastSpeechTimeRef.current > 0) {
              const speechDuration = lastSpeechTimeRef.current - speechStartTimeRef.current;
              const silenceMs = now - lastSpeechTimeRef.current;
              if (speechDuration >= MIN_SPEECH_MS) {
                const maxSilence = hasFinalResultRef.current ? FINAL_RESULT_SILENCE_MS : REDEMPTION_MS;
                if (silenceMs > maxSilence) shouldEnd = true;
              }
            }

            /* PATH B: SpeechRecognition stopped producing results (works even if mic is quiet).
               This is the key fix for soft speakers / low-gain mics. */
            if (lastRecognitionEventRef.current > 0) {
              const sinceLastResult = now - lastRecognitionEventRef.current;
              const maxWait = hasFinalResultRef.current ? FINAL_RESULT_SILENCE_MS : REDEMPTION_MS;
              if (sinceLastResult > maxWait) shouldEnd = true;
            }

            if (shouldEnd) {
              try { recognitionRef.current?.stop(); } catch {}
              speechDetectedRef.current = false;
              hasWordsRef.current = false;
              hasFinalResultRef.current = false;
              lastRecognitionEventRef.current = 0;
            }
          }
        }

        /* Barge-in: only wake word ("Hey Mimi") or orb tap can interrupt */

        /* ── Pre-emptive TTS duck — faster than speechstart event ──
           When the analyser detects a sudden volume spike during TTS,
           immediately duck the TTS gain. This happens in the animation frame
           loop (~60fps) so it's faster than waiting for Chrome's speechstart
           event (~200-500ms delay). Gives the recognition engine a head start. */
        if (stateRef.current === S.SPEAKING && isSpeakingTTSRef.current) {
          const g = ttsGainRef.current;
          if (g) {
            const duckThreshold = noiseFloorRef.current + 0.04; /* Lower threshold for "Mimi" */
            if (micVol > duckThreshold) {
              /* User is speaking — duck TTS immediately */
              if (g.gain.value > 0.2) {
                g.gain.setValueAtTime(0.12, g.context.currentTime);
              }
            } else if (g.gain.value < 0.3) {
              /* User stopped — smoothly restore TTS volume */
              g.gain.linearRampToValueAtTime(0.7, g.context.currentTime + 0.5);
            }
          }
        }

        /* Stuck-state detector: if SPEAKING with nothing playing or queued, force LISTENING.
           Two tiers:
           - 120 frames (~2s) if stream is done (normal post-speech transition)
           - 600 frames (~10s) even if stream isn't done (catches network failures)
           This catches ANY stuck scenario — more robust than setTimeout watchdogs. */
        if (stateRef.current === S.SPEAKING
            && !isSpeakingTTSRef.current
            && ttsQueueRef.current.length === 0) {
          stuckSpeakingCountRef.current++;
          const threshold = streamDoneRef.current ? 120 : 600;
          if (stuckSpeakingCountRef.current > threshold) {
            stuckSpeakingCountRef.current = 0;
            startRecognitionRef.current?.(false);
          }
        } else {
          stuckSpeakingCountRef.current = 0;
        }

        volAnimRef.current = requestAnimationFrame(volTick);
      };
      volAnimRef.current = requestAnimationFrame(volTick);
      return true;
    } catch {
      return false;
    }
  }, []);

  const stopMic = useCallback(() => {
    if (volAnimRef.current) { cancelAnimationFrame(volAnimRef.current); volAnimRef.current = null; }
    if (micStreamRef.current) { micStreamRef.current.getTracks().forEach((t) => t.stop()); micStreamRef.current = null; }
    if (audioCtxRef.current) { audioCtxRef.current.close().catch(() => {}); audioCtxRef.current = null; }
    analyserRef.current = null;
    volumeRef.current = 0;
  }, []);

  /* ══════════════════════════════════════════════════════
     SPEECH RECOGNITION (active + passive wake word mode)
     ══════════════════════════════════════════════════════ */
  const startRecognition = useCallback((passive = false) => {
    if (!HAS_RECOGNITION) return;
    /* Null out ref BEFORE abort so the old recognition's onend handler
       sees recognitionRef.current !== oldRecognition and bails out,
       preventing it from restarting passive mode over our new instance. */
    const oldRecognition = recognitionRef.current;
    recognitionRef.current = null;
    try { oldRecognition?.abort(); } catch {}

    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    const recognition = new SR();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = "en-US";
    recognition.maxAlternatives = passive ? 10 : 1;

    passiveModeRef.current = passive;

    if (!passive) {
      accumulatedTextRef.current = "";
      lastInterimRef.current = "";
      speechDetectedRef.current = false;
      speechStartTimeRef.current = 0;
      lastSpeechTimeRef.current = 0;
      hasWordsRef.current = false;
      hasFinalResultRef.current = false;
      lastRecognitionEventRef.current = 0;
    }

    /* ── Dynamic TTS ducking — the "Alexa trick" ──────────────────────────
       When Chrome detects ANY speech starting during TTS playback, immediately
       drop TTS volume to 15% so the mic gets a clean signal to hear the wake word.
       This is the single most impactful change for wake word responsiveness.
       Restore to 70% after 1.5s if it wasn't a wake word. */
    if (passive) {
      recognition.onspeechstart = () => {
        const g = ttsGainRef.current;
        if (g && isSpeakingTTSRef.current) {
          /* Only duck if mic volume shows actual user speech, not just TTS
             leaking into the mic. The bot's own audio triggers onspeechstart
             in Chrome, which previously dropped the self-trigger guard threshold
             from 0.03 to 0.01 — making false wake-word triggers much more likely.
             NOTE: must use micVolumeRef (raw mic), NOT volumeRef (animated sine
             wave during SPEAKING state for orb display). */
          const vol = micVolumeRef.current || 0;
          const floor = noiseFloorRef.current || 0;
          if (vol < floor + 0.04) return; /* TTS leakage, not real speech — lower threshold for "Mimi" */
          g.gain.setValueAtTime(0.12, g.context.currentTime); /* Duck harder (12% vs 15%) for cleaner mic signal */
          if (duckTimerRef.current) clearTimeout(duckTimerRef.current);
          duckTimerRef.current = setTimeout(() => {
            const g2 = ttsGainRef.current;
            if (g2 && isSpeakingTTSRef.current) {
              g2.gain.linearRampToValueAtTime(0.7, g2.context.currentTime + 0.3);
            }
            duckTimerRef.current = null;
          }, 2000); /* Hold duck longer (2s vs 1.5s) to capture full "Hey Mimi" */
        }
      };
      recognition.onspeechend = () => {
        /* Speech ended without wake word — restore volume quickly */
        if (duckTimerRef.current) { clearTimeout(duckTimerRef.current); duckTimerRef.current = null; }
        const g = ttsGainRef.current;
        if (g && isSpeakingTTSRef.current) {
          g.gain.linearRampToValueAtTime(0.7, g.context.currentTime + 0.15);
        }
      };
    }

    recognition.onresult = (event) => {
      if (passiveModeRef.current) {
        let wakeHit = false;

        /* Scan each new result + all alternatives */
        for (let i = event.resultIndex; i < event.results.length; i++) {
          const alts = event.results[i];
          for (let a = 0; a < alts.length; a++) {
            if (isWakeWord(alts[a].transcript)) { wakeHit = true; break; }
          }
          if (wakeHit) break;
        }

        /* Also scan the FULL concatenated transcript across all results.
           Chrome sometimes splits "hey" into one result and "mimi" into
           the next — checking individual results misses that. */
        if (!wakeHit) {
          let full = "";
          for (let i = 0; i < event.results.length; i++) {
            full += event.results[i][0].transcript + " ";
          }
          if (isWakeWord(full)) wakeHit = true;
        }

        /* During TTS, require real mic activity to avoid self-trigger
           (bot's own audio being picked up by its own mic and matched as wake word).
           Use a higher threshold (0.06) to filter out TTS speaker leakage.
           When ducked (confirmed user speech), use lower threshold (0.02).
           When TTS is NOT playing, no volume gate at all. */
        if (wakeHit) {
          if (isSpeakingTTSRef.current) {
            const g = ttsGainRef.current;
            const isDucked = g && g.gain.value < 0.5;
            /* "Mimi" is short/soft — use lower thresholds for faster detection.
               When already ducked (confirmed user speech), near-zero threshold.
               When not ducked, still lower than before (0.04 vs 0.06). */
            const guardThreshold = isDucked ? 0.01 : 0.04;
            const selfTriggerGuard = micVolumeRef.current > noiseFloorRef.current + guardThreshold;
            if (!selfTriggerGuard) wakeHit = false;
          }
        }

        if (wakeHit) {
          wakeFlashRef.current = performance.now();
          wakeTriggeredRef.current = true;
          cancelTTSRef.current?.();
          if (abortRef.current) abortRef.current.abort();
          recognition.abort();
          /* Near-instant transition — 50ms is enough for Chrome to clean up */
          setTimeout(() => {
            if (activeRef.current) startRecognitionRef.current?.(false);
          }, 50);
          return;
        }

        /* Non-wake-word speech does NOT interrupt — only "Hey Mimi" or orb tap */
        return;
      }

      /* ACTIVE MODE */
      let finalText = "";
      let interim = "";
      for (let i = 0; i < event.results.length; i++) {
        const transcript = event.results[i][0].transcript;
        if (event.results[i].isFinal) finalText += transcript;
        else interim += transcript;
      }

      if (finalText) {
        accumulatedTextRef.current = finalText;
        hasFinalResultRef.current = true;
      }
      if (interim) lastInterimRef.current = interim;
      if (finalText || interim) {
        hasWordsRef.current = true;
        lastRecognitionEventRef.current = Date.now();
      }

      const display = finalText ? finalText + (interim ? " " + interim : "") : interim;
      setInterimText(display);
    };

    recognition.onend = () => {
      if (recognitionRef.current !== recognition) return;
      recognitionRef.current = null;

      if (passiveModeRef.current) {
        /* Restart passive recognition INSTANTLY — zero gap means zero missed wake words.
           Only restart when bot is speaking/processing (wake word needed). */
        const st = stateRef.current;
        if (activeRef.current && (st === S.SPEAKING || st === S.PROCESSING)) {
          /* Use Promise.resolve().then() instead of setTimeout for near-zero delay.
             This fires on the microtask queue (~0.1ms) vs setTimeout (~4ms minimum). */
          Promise.resolve().then(() => {
            const st2 = stateRef.current;
            if (activeRef.current && (st2 === S.SPEAKING || st2 === S.PROCESSING)) {
              startRecognitionRef.current?.(true);
            }
          });
        }
        return;
      }

      const text = (accumulatedTextRef.current || lastInterimRef.current).trim();
      if (text && stateRef.current === S.LISTENING) {
        wakeTriggeredRef.current = false;
        sendToAIRef.current?.(text);
      } else if (stateRef.current === S.LISTENING) {
        /* User said the wake word but nothing else — acknowledge and keep listening */
        if (wakeTriggeredRef.current && activeRef.current) {
          wakeTriggeredRef.current = false;
          const ack = pick(["I'm listening. What do you need?", "Yeah, what's up?", "I'm here. Go ahead.", "Yes? What can I help with?"]);
          streamDoneRef.current = true;
          fullResponseRef.current = ack;
          setCurrentPhrase(ack);
          setPhraseKey((k) => k + 1);
          historyRef.current.push({ role: "assistant", content: ack });
          setHistoryVersion((v) => v + 1);
          transition(S.SPEAKING);
          startRecognitionRef.current?.(true);
          ttsQueueRef.current.push(ack);
          isSpeakingTTSRef.current = true;
          speakNextRef.current?.();
        } else if (activeRef.current) {
          setTimeout(() => {
            if (activeRef.current && stateRef.current === S.LISTENING) {
              startRecognitionRef.current?.(false);
            }
          }, 150);
        } else {
          transition(S.IDLE);
        }
      }
    };

    recognition.onerror = (e) => {
      if (recognitionRef.current !== recognition) return;
      if (e.error === "no-speech" || e.error === "aborted") { /* normal */ }
      else if (e.error === "not-allowed") setStatusLabel("Mic permission denied");
      else if (e.error === "network" || e.error === "service-not-allowed") {
        /* Network/service error — retry recognition after delay */
        recognitionRef.current = null;
        setTimeout(() => {
          if (activeRef.current) startRecognitionRef.current?.(passiveModeRef.current);
        }, 1000);
      }
      else { /* unhandled recognition error — silently ignored */ }
    };

    recognitionRef.current = recognition;
    try {
      recognition.start();
    } catch (e) {
      recognitionRef.current = null;
      /* Use `passive` from closure, not passiveModeRef which can be overwritten by race */
      setTimeout(() => {
        if (activeRef.current) startRecognitionRef.current?.(passive);
      }, 500);
      return;
    }

    if (!passive) {
      transition(S.LISTENING);
      setInterimText("");
      setCurrentPhrase("");
      setActiveTools([]);
    }
  }, [transition]);

  startRecognitionRef.current = startRecognition;

  const stopRecognition = useCallback(() => {
    try { recognitionRef.current?.abort(); } catch {}
    recognitionRef.current = null;
  }, []);

  /* ══════════════════════════════════════════════════════
     TTS — edge-tts neural voice via Web Audio API
     Plays through the same AudioContext used for mic analysis,
     which is already unlocked — bypasses <audio> autoplay issues.
     ══════════════════════════════════════════════════════ */
  const setCurrentPhraseRef = useRef(setCurrentPhrase);
  setCurrentPhraseRef.current = setCurrentPhrase;
  const setPhraseKeyRef = useRef(setPhraseKey);
  setPhraseKeyRef.current = setPhraseKey;

  /* ── TTS pre-fetch pipeline ──────────────────────────────────
     Fetches the NEXT phrase's audio while the current one plays,
     eliminating the gap between phrases for fluid speech.        */
  const fetchTTSBuffer = useCallback(async (text, signal) => {
    const spokenText = humanizeSpeech(stripMarkdown(text));
    try {
      const opts = {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: spokenText, voice: "en-US-AvaNeural", rate: ttsSpeedRef.current }),
      };
      if (signal) opts.signal = signal;
      const res = await fetch("/api/tts", opts);
      if (!res.ok) return null;
      const ab = await res.arrayBuffer();
      if (!ab || ab.byteLength === 0) return null;
      const ctx = audioCtxRef.current;
      if (!ctx) return null;
      if (ctx.state === "suspended") try { await ctx.resume(); } catch {}
      return await ctx.decodeAudioData(ab.slice(0));
    } catch {
      return null;
    }
  }, []);

  const playTTSPhrase = useCallback(async (text) => {
    setCurrentPhraseRef.current(stripMarkdown(text));
    setPhraseKeyRef.current((k) => k + 1);

    if (mutedRef.current) {
      const ms = Math.min(Math.max(text.length * 30, 400), 2000);
      await new Promise((r) => setTimeout(r, ms));
      return;
    }

    const controller = new AbortController();
    ttsAbortRef.current = controller;

    /* Use pre-fetched audio if available */
    let audioBuffer = null;
    const cached = ttsCacheRef.current.get(text);
    if (cached) {
      ttsCacheRef.current.delete(text);
      try { audioBuffer = await cached; } catch {}
      if (controller.signal.aborted) return;
    }

    /* Fetch if not pre-cached */
    if (!audioBuffer) {
      audioBuffer = await fetchTTSBuffer(text, controller.signal);
      if (controller.signal.aborted) return;
    }

    if (!audioBuffer) {
      const ms = Math.min(Math.max(text.length * 50, 800), 3000);
      await new Promise((r) => setTimeout(r, ms));
      return;
    }

    const ctx = audioCtxRef.current;
    if (!ctx) return;
    if (ctx.state === "suspended") try { await ctx.resume(); } catch {}

    return new Promise((resolve) => {
      const source = ctx.createBufferSource();
      source.buffer = audioBuffer;
      /* Audio ducking: play TTS at 70% volume so mic can pick up wake word better.
         Smart speakers do this — slightly quieter output = much better wake word detection.
         The gain node is stored in ttsGainRef so it can be dynamically ducked further
         when the user starts speaking (speechstart event). */
      const gain = ctx.createGain();
      gain.gain.value = mutedRef.current ? 0 : 0.7;
      source.connect(gain);
      gain.connect(ctx.destination);
      ttsSourceRef.current = source;
      ttsGainRef.current = gain;
      let resolved = false;
      const done = () => {
        if (resolved) return;
        resolved = true;
        ttsSourceRef.current = null;
        ttsGainRef.current = null;
        resolve();
      };
      source.onended = done;
      controller.signal.addEventListener("abort", () => { try { source.stop(); } catch {} done(); }, { once: true });
      source.start(0);
    });
  }, [fetchTTSBuffer]);

  const speakNext = useCallback(async () => {
    /* Outer loop: keeps draining the queue even if new items arrive
       between the inner while-loop exit and the isSpeakingTTS check.
       KEY FIX: when queue empties but stream isn't done (tools still executing),
       we WAIT instead of exiting. This keeps isSpeakingTTSRef=true, preventing
       the stuck-state detector from firing and ensuring the response text
       gets spoken seamlessly after the filler phrase. */
    let phraseCount = 0;
    for (;;) {
      while (ttsQueueRef.current.length > 0) {
        if (!activeRef.current || !isSpeakingTTSRef.current) return;
        const text = ttsQueueRef.current.shift();

        /* Pre-fetch next phrase while current one plays */
        const nextText = ttsQueueRef.current[0];
        if (nextText && !ttsCacheRef.current.has(nextText)) {
          ttsCacheRef.current.set(nextText, fetchTTSBuffer(nextText));
        }

        await playTTSPhrase(text);
        phraseCount++;
      }
      if (!isSpeakingTTSRef.current) return;
      /* Re-check: items may have been added during the last playTTSPhrase await */
      if (ttsQueueRef.current.length > 0) continue;

      /* Stream still active (tools executing) → wait for more phrases.
         This is the critical fix: without it, speakNext exits after the filler,
         isSpeakingTTSRef goes false, and the stuck-state detector can fire
         before the response text arrives. */
      if (!streamDoneRef.current && activeRef.current) {
        await new Promise((resolve) => {
          speakWaiterRef.current = resolve;
          /* Safety: don't wait forever if backend hangs */
          setTimeout(() => { if (speakWaiterRef.current === resolve) { speakWaiterRef.current = null; resolve(); } }, 30000);
        });
        speakWaiterRef.current = null;
        if (!activeRef.current || !isSpeakingTTSRef.current) return;
        if (ttsQueueRef.current.length > 0) continue;
      }

      break;
    }

    isSpeakingTTSRef.current = false;

    if (streamDoneRef.current && activeRef.current && stateRef.current === S.SPEAKING) {
      /* Single transition point: only speakNext triggers SPEAKING→LISTENING.
         The onDone handler sets streamDoneRef but does NOT call startRecognition
         to avoid duplicate calls. */
      setTimeout(() => {
        if (activeRef.current && stateRef.current === S.SPEAKING && !isSpeakingTTSRef.current) {
          startRecognitionRef.current?.(false);
        }
      }, POST_RESPONSE_PAUSE);
    }
  }, [playTTSPhrase, fetchTTSBuffer]);

  const enqueuePhrase = useCallback((phrase) => {
    ttsQueueRef.current.push(phrase);
    /* Pre-fetch audio for queued phrases while TTS is already playing */
    if (isSpeakingTTSRef.current && ttsQueueRef.current.length <= 3 && !ttsCacheRef.current.has(phrase)) {
      ttsCacheRef.current.set(phrase, fetchTTSBuffer(phrase));
    }
    /* Wake up speakNext if it's waiting for more phrases (stream still active) */
    if (speakWaiterRef.current) {
      const resolve = speakWaiterRef.current;
      speakWaiterRef.current = null;
      resolve();
      return; /* speakNext is already running, it will process the new item */
    }
    if (!isSpeakingTTSRef.current) {
      isSpeakingTTSRef.current = true;
      speakNext();
    }
  }, [speakNext, fetchTTSBuffer]);

  const cancelTTS = useCallback(() => {
    ttsQueueRef.current = [];
    isSpeakingTTSRef.current = false;
    ttsCacheRef.current.clear();
    ttsGainRef.current = null;
    /* Wake up speakNext if waiting so it can exit cleanly */
    if (speakWaiterRef.current) { const r = speakWaiterRef.current; speakWaiterRef.current = null; r(); }
    if (ttsAbortRef.current) { ttsAbortRef.current.abort(); ttsAbortRef.current = null; }
    if (ttsSourceRef.current) { try { ttsSourceRef.current.stop ? ttsSourceRef.current.stop() : ttsSourceRef.current.pause(); } catch {} ttsSourceRef.current = null; }
  }, []);

  cancelTTSRef.current = cancelTTS;
  speakNextRef.current = speakNext;

  /* ── Controls ── */
  const toggleMute = useCallback(() => {
    const next = !mutedRef.current;
    mutedRef.current = next;
    setIsMuted(next);
    if (next) {
      cancelTTS();
      if (stateRef.current === S.SPEAKING) setStatusLabel("Speaking (muted)\u2026");
    } else {
      if (stateRef.current === S.SPEAKING) setStatusLabel("");
    }
  }, [cancelTTS]);

  const cycleSpeed = useCallback(() => {
    setTtsSpeedIdx((prev) => {
      const next = (prev + 1) % SPEED_OPTIONS.length;
      ttsSpeedRef.current = SPEED_OPTIONS[next].rate;
      return next;
    });
  }, []);

  toggleMuteRef.current = toggleMute;
  cycleSpeedRef.current = cycleSpeed;

  /* ══════════════════════════════════════════════════════
     SEND TO AI
     ══════════════════════════════════════════════════════ */
  const sendToAI = useCallback(async (text) => {
    if (!text.trim()) { transition(S.IDLE); return; }

    transition(S.PROCESSING);
    setCurrentPhrase("");
    setActiveTools([]);
    fullResponseRef.current = "";
    phraseBufferRef.current = "";
    streamDoneRef.current = false;
    ttsQueueRef.current = [];
    /* Kill any waiting speakNext from previous request */
    if (speakWaiterRef.current) { const r = speakWaiterRef.current; speakWaiterRef.current = null; r(); }
    isSpeakingTTSRef.current = false;

    const thisRequestId = ++requestIdRef.current;
    historyRef.current.push({ role: "user", content: text.trim() });
    setHistoryVersion((v) => v + 1);

    stopRecognition();

    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    const messages = historyRef.current.map((m) => ({ role: m.role, content: m.content }));
    let startedSpeaking = false;
    let hitFollowups = false;

    try {
      await streamChat(messages, {
        signal: controller.signal,
        mode: "voice",
        onText: (chunk) => {
          if (controller.signal.aborted || hitFollowups) return;

          fullResponseRef.current += chunk;

          const fIdx = fullResponseRef.current.indexOf("---follow-ups");
          if (fIdx !== -1) {
            hitFollowups = true;
            fullResponseRef.current = fullResponseRef.current.slice(0, fIdx).trimEnd();
            const bufCut = phraseBufferRef.current.indexOf("---follow-ups");
            const clean = (bufCut !== -1 ? phraseBufferRef.current.slice(0, bufCut) : phraseBufferRef.current).trim();
            phraseBufferRef.current = "";
            if (clean) {
              if (!startedSpeaking) { startedSpeaking = true; transition(S.SPEAKING); startRecognitionRef.current?.(true); }
              enqueuePhrase(clean);
            }
            return;
          }

          phraseBufferRef.current += chunk;
          const { phrases, remaining } = extractPhrases(phraseBufferRef.current);
          phraseBufferRef.current = remaining;

          if (phrases.length > 0) {
            if (!startedSpeaking) {
              startedSpeaking = true;
              transition(S.SPEAKING);
              startRecognitionRef.current?.(true);
            }
            phrases.forEach((p) => enqueuePhrase(p));
          }
        },
        onToolCall: (data) => {
          if (controller.signal.aborted) return;
          const chipLabel = toolChipLabel(data.tool, data.input);
          const voicePhrase = toolVoicePhrase(data.tool, data.input);
          setActiveTools((prev) => [...prev, { id: data.id, desc: chipLabel, done: false }]);
          /* Don't override status label — the chips already show tool names.
             Keep the speaking-state label ("Tap orb to stop...") visible. */

          /* ── Flush pre-tool text OR auto-speak natural filler so user
               isn't left in silence while tools execute (can take 5-30s) ── */
          const buffered = phraseBufferRef.current.trim();
          phraseBufferRef.current = "";
          if (!startedSpeaking) {
            startedSpeaking = true;
            transition(S.SPEAKING);
            startRecognitionRef.current?.(true);
            /* Speak whatever Claude wrote before calling tools, or a
               natural conversational filler if Claude stayed silent. */
            const toSpeak = buffered || voicePhrase;
            enqueuePhrase(toSpeak);
          } else if (buffered) {
            enqueuePhrase(buffered);
          }
        },
        onToolResult: (data) => {
          if (controller.signal.aborted) return;
          setActiveTools((prev) => prev.map((t) => t.id === data.id ? { ...t, done: true } : t));
        },
        onError: (msg) => {
          if (controller.signal.aborted) return;
          setStatusLabel(`Error: ${msg.slice(0, 60)}`);
        },
        onDone: () => {
          if (controller.signal.aborted) return;

          const leftover = phraseBufferRef.current.trim();
          if (leftover) {
            if (!startedSpeaking) {
              transition(S.SPEAKING);
              startRecognitionRef.current?.(true);
            }
            enqueuePhrase(leftover);
            phraseBufferRef.current = "";
          }
          streamDoneRef.current = true;
          /* Wake speakNext if it's waiting for stream to finish */
          if (speakWaiterRef.current) { const r = speakWaiterRef.current; speakWaiterRef.current = null; r(); }

          if (fullResponseRef.current.trim()) {
            historyRef.current.push({ role: "assistant", content: fullResponseRef.current });
            if (historyRef.current.length > 20) historyRef.current = historyRef.current.slice(-20);
            setHistoryVersion((v) => v + 1);
          }

          if (!startedSpeaking && !leftover) {
            transition(S.IDLE);
            if (!fullResponseRef.current.trim()) setStatusLabel("No response \u2014 tap to try again");
          }

          /* NOTE: Do NOT call startRecognition here. speakNext handles the
             SPEAKING→LISTENING transition when the TTS queue empties.
             Calling it here AND in speakNext causes duplicate recognition
             instances that fight each other. */

          setTimeout(() => {
            if (requestIdRef.current === thisRequestId) setActiveTools([]);
          }, 1500);
        },
      });
    } catch (e) {
      /* stream exception silently caught (AbortError is normal) */
    }

    if (controller.signal.aborted) return;

    /* Mark stream as done — handles both normal completion (onDone already fired)
       and error paths (stream threw before onDone). Idempotent if already true. */
    streamDoneRef.current = true;
    if (speakWaiterRef.current) { const r = speakWaiterRef.current; speakWaiterRef.current = null; r(); }

    if (stateRef.current === S.PROCESSING) {
      if (fullResponseRef.current.trim()) {
        transition(S.SPEAKING);
        startRecognitionRef.current?.(true); /* passive wake word during speech */
        enqueuePhrase(fullResponseRef.current.trim());
      } else {
        transition(S.IDLE);
        setStatusLabel("No response \u2014 tap to try again");
      }
    }
  }, [transition, enqueuePhrase, stopRecognition]);

  sendToAIRef.current = sendToAI;

  /* ── Tap handlers ── */
  const handleInteract = useCallback(() => {
    const s = stateRef.current;
    if (s === S.IDLE) {
      startRecognition(false);
    } else if (s === S.SPEAKING) {
      /* Tapping the orb/mic while bot is speaking = STOP + immediately listen */
      cancelTTS();
      if (abortRef.current) abortRef.current.abort();
      startRecognition(false); /* goes directly SPEAKING→LISTENING, no gap */
    } else if (s === S.PROCESSING) {
      cancelTTS();
      if (abortRef.current) abortRef.current.abort();
      transition(S.IDLE);
    } else if (s === S.LISTENING) {
      try { recognitionRef.current?.stop(); } catch {}
    }
  }, [startRecognition, cancelTTS, transition]);

  /* ══════════════════════════════════════════════════════
     LIFECYCLE
     ══════════════════════════════════════════════════════ */
  useEffect(() => {
    if (!isOpen) return;
    activeRef.current = true;
    let resizeHandler = null;

    const init = async () => {
      resizeHandler = startCanvas();
      const micOk = await startMic();
      if (!micOk) {
        transition(S.IDLE);
        setStatusLabel("Microphone unavailable");
        return;
      }
      if (!HAS_RECOGNITION) {
        setStatusLabel("Voice not supported in this browser");
        return;
      }

      if (!greetedRef.current) {
        greetedRef.current = true;
        const greeting = pickGreeting();
        streamDoneRef.current = true;
        fullResponseRef.current = greeting;
        setCurrentPhrase(greeting);
        setPhraseKey((k) => k + 1);
        historyRef.current.push({ role: "assistant", content: greeting });
        setHistoryVersion((v) => v + 1);
        transition(S.SPEAKING);
        startRecognitionRef.current?.(true);
        ttsQueueRef.current.push(greeting);
        isSpeakingTTSRef.current = true;
        speakNextRef.current?.();
        /* Safety: ensure we leave SPEAKING after greeting even if TTS pipeline hiccups */
        setTimeout(() => {
          if (activeRef.current && stateRef.current === S.SPEAKING
              && !isSpeakingTTSRef.current && ttsQueueRef.current.length === 0) {
            startRecognitionRef.current?.(false);
          }
        }, 12000);
      } else {
        setTimeout(() => {
          if (activeRef.current && stateRef.current === S.IDLE)
            startRecognitionRef.current?.(true);
        }, 500);
      }
    };
    init();

    /* Keyboard shortcuts */
    const onKey = (e) => {
      if (e.key === "Escape") { onCloseRef.current(); return; }
      if ((e.key === "m" || e.key === "M") && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        toggleMuteRef.current?.();
        return;
      }
      if ((e.key === "s" || e.key === "S") && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        cycleSpeedRef.current?.();
        return;
      }
      if (e.code === "Space" && !e.repeat && !pttRef.current) {
        e.preventDefault();
        pttRef.current = true;
        if (stateRef.current === S.SPEAKING || stateRef.current === S.PROCESSING) {
          cancelTTSRef.current?.();
          if (abortRef.current) abortRef.current.abort();
        }
        startRecognitionRef.current?.(false);
      }
    };

    const onKeyUp = (e) => {
      if (e.code === "Space" && pttRef.current) {
        e.preventDefault();
        pttRef.current = false;
        try { recognitionRef.current?.stop(); } catch {}
      }
    };

    /* Mouse tracking for interactive sphere rotation */
    const onMouseMove = (e) => {
      mouseRef.current = { x: e.clientX / window.innerWidth, y: e.clientY / window.innerHeight };
    };

    const onVisibility = () => {
      if (!activeRef.current) return;
      if (document.hidden) {
        try { recognitionRef.current?.abort(); } catch {}
        recognitionRef.current = null;
      } else {
        setTimeout(() => {
          if (!activeRef.current) return;
          const st = stateRef.current;
          if (st === S.SPEAKING || st === S.PROCESSING) {
            startRecognitionRef.current?.(true); /* passive wake word */
          }
          /* IDLE and LISTENING don't need restart — they handle their own recognition */
        }, 300);
      }
    };

    const onResize = () => resizeHandler?.();
    window.addEventListener("keydown", onKey);
    window.addEventListener("keyup", onKeyUp);
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("resize", onResize);
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      activeRef.current = false;
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("keyup", onKeyUp);
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("resize", onResize);
      document.removeEventListener("visibilitychange", onVisibility);
      if (animRef.current) cancelAnimationFrame(animRef.current);
      stopRecognition();
      if (duckTimerRef.current) { clearTimeout(duckTimerRef.current); duckTimerRef.current = null; }
      cancelTTS();
      if (abortRef.current) abortRef.current.abort();
      stopMic();
      closeToneCtx();
      mutedRef.current = false;
      pttRef.current = false;
      wakeTriggeredRef.current = false;
      greetedRef.current = false;
      scatteredRef.current = false;
      bargeInCountRef.current = 0;
      lastBargeInRef.current = 0;
      stuckSpeakingCountRef.current = 0;
      setCurrentPhrase("");
      setPhraseKey(0);
      stateRef.current = S.IDLE;
      colorRef.current = [...P_COLORS.idle];
      targetColorRef.current = P_COLORS.idle;
      volumeRef.current = 0;
      accumRotRef.current = 0;
      lastTimeRef.current = 0;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, startCanvas, startMic, stopRecognition, stopMic, cancelTTS, transition]);

  /* ══════════════════════════════════════════════════════
     RENDER
     ══════════════════════════════════════════════════════ */
  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          className="fixed inset-0 z-[70] flex flex-col"
          style={{ background: "#0e0e0e" }}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.4 }}
        >
          {/* ── Full-screen canvas ── */}
          <canvas
            ref={canvasRef}
            className="absolute inset-0 w-full h-full"
            style={{ display: "block" }}
          />

          {/* ── Orb tap target (invisible, over particle sphere) ── */}
          <motion.div
            className="absolute left-1/2 -translate-x-1/2 w-[220px] h-[220px] cursor-pointer select-none rounded-full z-10"
            style={{ top: `calc(${voiceState === S.SPEAKING ? "46%" : "40%"} - 110px)`, transition: "top 0.6s cubic-bezier(0.16, 1, 0.3, 1)" }}
            onClick={handleInteract}
            whileTap={{ scale: 0.96 }}
          />

          {/* ── Text area ── */}
          <div
            className="absolute left-0 right-0 z-10 flex flex-col items-center px-6"
            style={{
              top: voiceState === S.SPEAKING ? "calc(46% + 130px)" : "calc(40% + 130px)",
              maxHeight: "30%",
              transition: "top 0.6s cubic-bezier(0.16, 1, 0.3, 1)",
              overflow: "hidden",
            }}
          >
            {/* Currently spoken phrase — clean single-sentence display */}
            <AnimatePresence mode="wait">
              {voiceState === S.SPEAKING && currentPhrase && (
                <motion.div
                  key={`phrase-${phraseKey}`}
                  className="max-w-[560px] w-full text-center"
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -8 }}
                  transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
                >
                  <p className="text-[17px] text-white/70 leading-[1.8] font-light tracking-wide"
                     style={{ textShadow: "0 0 30px rgba(40,215,220,0.05)" }}>
                    {currentPhrase}
                  </p>
                </motion.div>
              )}
            </AnimatePresence>

            {/* User speech (interim text) */}
            {voiceState === S.LISTENING && interimText && (
              <motion.p
                className="text-[17px] text-white/50 leading-relaxed italic text-center max-w-[500px] mt-2"
                style={{ textShadow: "0 0 20px rgba(90,170,255,0.08)" }}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
              >
                {interimText}
              </motion.p>
            )}

            {/* Processing — show what user said */}
            {voiceState === S.PROCESSING && (
              <motion.p
                className="text-[16px] text-white/35 leading-relaxed text-center max-w-[500px]"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
              >
                &ldquo;{accumulatedTextRef.current || lastInterimRef.current || interimText}&rdquo;
              </motion.p>
            )}

            {/* Tool chips */}
            <AnimatePresence>
              {activeTools.length > 0 && (
                <motion.div
                  className="mt-3 flex flex-wrap justify-center gap-1.5"
                  initial={{ opacity: 0, y: -4 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                >
                  {activeTools.map((t) => (
                    <motion.span
                      key={t.id}
                      className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] tracking-wide ${
                        t.done
                          ? "bg-emerald-500/10 text-emerald-400/60 border border-emerald-500/20"
                          : "bg-white/[0.05] text-white/50 border border-white/[0.08]"
                      }`}
                      initial={{ opacity: 0, scale: 0.8 }}
                      animate={{ opacity: 1, scale: 1 }}
                      layout
                    >
                      <span className={`w-1.5 h-1.5 rounded-full ${
                        t.done ? "bg-emerald-400/60" : "bg-white/30 animate-pulse"
                      }`} />
                      {t.desc}
                    </motion.span>
                  ))}
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          {/* ── Bottom section: status + buttons ── */}
          <div className="absolute bottom-0 left-0 right-0 z-10 flex flex-col items-center pb-6">
            {/* Status text */}
            <motion.p
              className="mb-4 text-[14px] font-light tracking-wider uppercase"
              style={{ color: "rgba(120, 190, 180, 0.4)", letterSpacing: "0.12em" }}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.3 }}
            >
              {statusLabel || (voiceState === S.IDLE ? "Tap the orb to begin" : voiceState === S.LISTENING ? "Listening\u2026" : "")}
            </motion.p>

            {/* Buttons — glass floating bar */}
            <motion.div
              className="flex items-center gap-3 px-4 py-2 rounded-full bg-white/[0.03] border border-white/[0.06] backdrop-blur-md"
              initial={{ opacity: 0, y: 15 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.4, duration: 0.5 }}
            >
              {/* Close */}
              <motion.button
                onClick={onClose}
                className="w-10 h-10 rounded-full flex items-center justify-center text-white/25 hover:text-white/50 hover:bg-white/[0.06] transition-all duration-300"
                whileTap={{ scale: 0.88 }}
                title="Close (Esc)"
              >
                <X className="w-[16px] h-[16px]" />
              </motion.button>

              {/* Mute toggle */}
              <motion.button
                onClick={toggleMute}
                className={`w-10 h-10 rounded-full flex items-center justify-center transition-all duration-300 ${
                  isMuted ? "text-orange-400/60 bg-orange-500/[0.08]" : "text-white/25 hover:text-white/50 hover:bg-white/[0.06]"
                }`}
                whileTap={{ scale: 0.88 }}
                title={isMuted ? "Unmute (M)" : "Mute (M)"}
              >
                {isMuted ? <VolumeX className="w-[16px] h-[16px]" /> : <Volume2 className="w-[16px] h-[16px]" />}
              </motion.button>

              {/* Mic / Stop button — primary action */}
              <motion.button
                onClick={handleInteract}
                className={`w-14 h-14 rounded-full flex items-center justify-center transition-all duration-500 ${
                  voiceState === S.LISTENING
                    ? "bg-blue-500/[0.15] text-white/90 shadow-[0_0_20px_rgba(90,170,255,0.1)]"
                    : voiceState === S.SPEAKING
                    ? "bg-red-500/[0.12] text-red-300/80 hover:text-red-300 hover:bg-red-500/[0.2]"
                    : "bg-white/[0.06] text-white/40 hover:text-white/60 hover:bg-white/[0.1]"
                }`}
                whileTap={{ scale: 0.9 }}
                animate={voiceState === S.LISTENING ? {
                  boxShadow: ["0 0 0px rgba(90,170,255,0)", "0 0 30px rgba(90,170,255,0.15)", "0 0 0px rgba(90,170,255,0)"],
                } : voiceState === S.SPEAKING ? {
                  boxShadow: ["0 0 0px rgba(255,100,100,0)", "0 0 20px rgba(255,100,100,0.1)", "0 0 0px rgba(255,100,100,0)"],
                } : {}}
                transition={voiceState === S.LISTENING || voiceState === S.SPEAKING ? { duration: 2, repeat: Infinity, ease: "easeInOut" } : {}}
              >
                {voiceState === S.SPEAKING ? <Square className="w-4 h-4" /> : <Mic className="w-5 h-5" />}
              </motion.button>

              {/* Speed toggle */}
              <motion.button
                onClick={cycleSpeed}
                className="w-10 h-10 rounded-full flex items-center justify-center text-white/25 hover:text-white/50 hover:bg-white/[0.06] transition-all duration-300 relative"
                whileTap={{ scale: 0.88 }}
                title="TTS speed (S)"
              >
                <Gauge className="w-[16px] h-[16px]" />
                <span className="absolute -top-0.5 -right-0.5 text-[8px] text-cyan-400/60 font-medium">
                  {SPEED_OPTIONS[ttsSpeedIdx].label}
                </span>
              </motion.button>
            </motion.div>

            {/* Keyboard hints */}
            <motion.p
              className="mt-3 text-[10px] text-white/15 tracking-wider"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 1 }}
            >
              Space = push-to-talk &middot; M = mute &middot; S = speed &middot; Esc = close
            </motion.p>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
