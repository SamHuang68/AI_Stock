'use strict';
const fs = require('fs');
const path = require('path');
const assert = require('assert');

const root = path.resolve(__dirname, '..');
const radar = fs.readFileSync(path.join(root, 'src/ui/consensus_attention_v5.js'), 'utf8');
const shell = fs.readFileSync(path.join(root, 'src/ui/shell_v5.js'), 'utf8');
const decision = fs.readFileSync(path.join(root, 'src/ui/decision_v5.js'), 'utf8');
const build = fs.readFileSync(path.join(root, 'build_v2.py'), 'utf8');

assert(!/\bfetch\s*\(/.test(radar), 'Consensus Radar must not own a fetch/poll path');
assert(radar.includes("window.addEventListener('decisionData', syncProjection)"), 'Radar must subscribe to DecisionData');
assert(radar.includes("var MAX_VISIBLE = 3") && radar.includes("var MAX_ITEMS = 5"), '3/5 attention budget missing');
assert(radar.includes("var ACK_KEY = 'st_consensus_ack_v1'"), 'per-generation acknowledgement storage missing');
assert(radar.includes("ACTIONABLE[item.lifecycleState]") && radar.includes("freshness.status === 'fresh'"),
  'badge must require WATCH+ and fresh evidence');
assert(radar.includes('(orientation:portrait)') && radar.includes('(orientation:landscape)'),
  'portrait bottom sheet / landscape side overlay rules missing');
assert(shell.includes('window.ConsensusAttentionV5.open()'), 'existing FAB is not routed to Consensus Radar');
assert(decision.includes('applyPendingFocus()') && decision.includes('data-dc-section="divergences"'),
  'Decision deep-link focus contract missing');
const evidenceArtifact = '/assets/docs/archify/st-decision-evidence-lineage.html';
assert(radar.includes(evidenceArtifact) && decision.includes(evidenceArtifact),
  'Decision and Radar must expose the same frozen evidence-lineage artifact');
assert(radar.includes('target="_blank"') && radar.includes('rel="noopener noreferrer"'),
  'Radar artifact link must open safely in a new tab');
assert(decision.includes('target="_blank"') && decision.includes('rel="noopener noreferrer"'),
  'Decision artifact link must open safely in a new tab');
assert(!/<iframe\b/i.test(radar) && !/<iframe\b/i.test(decision),
  'Archify documentation must not be embedded in the runtime');
assert(build.includes("'src/ui/consensus_attention_v5.js'"), 'build bundle omits Consensus Radar');

console.log('consensus_attention_v5 self-test PASSED');
