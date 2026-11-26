// Encrypts a page behind a passphrase (AES-256-GCM, key from PBKDF2-SHA256).
// Usage:
//   GATE_PASS='...' node tools/gate.mjs encrypt <plain.html> <out.html>
//   GATE_PASS='...' node tools/gate.mjs decrypt <gated.html> <plain.html>
import { readFileSync, writeFileSync } from 'node:fs';
import { webcrypto as crypto } from 'node:crypto';
const [mode, inp, out] = process.argv.slice(2);
const pass = process.env.GATE_PASS;
if (!pass || !['encrypt', 'decrypt'].includes(mode) || !inp || !out) { console.error('usage: GATE_PASS=... node gate.mjs encrypt|decrypt in out'); process.exit(1); }
const ITER = 600000, b64 = u => Buffer.from(u).toString('base64'), unb64 = s => new Uint8Array(Buffer.from(s, 'base64'));
async function key(salt) {
  const base = await crypto.subtle.importKey('raw', new TextEncoder().encode(pass), 'PBKDF2', false, ['deriveKey']);
  return crypto.subtle.deriveKey({ name: 'PBKDF2', salt, iterations: ITER, hash: 'SHA-256' }, base, { name: 'AES-GCM', length: 256 }, true, ['decrypt', 'encrypt']);
}
const TEMPLATE = new URL('./gate-template.html', import.meta.url);
if (mode === 'encrypt') {
  const salt = crypto.getRandomValues(new Uint8Array(16)), iv = crypto.getRandomValues(new Uint8Array(12));
  const ct = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, await key(salt), new TextEncoder().encode(readFileSync(inp, 'utf8')));
  const payload = JSON.stringify({ v: 1, iter: ITER, salt: b64(salt), iv: b64(iv), ct: b64(new Uint8Array(ct)) });
  writeFileSync(out, readFileSync(TEMPLATE, 'utf8').replace('/*PAYLOAD*/null', payload));
  console.log('encrypted ->', out);
} else {
  const p = JSON.parse(readFileSync(inp, 'utf8').match(/const PAYLOAD=(\{.*?\});/s)[1]);
  const pt = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: unb64(p.iv) }, await key(unb64(p.salt)), unb64(p.ct));
  writeFileSync(out, new TextDecoder().decode(pt));
  console.log('decrypted ->', out);
}
