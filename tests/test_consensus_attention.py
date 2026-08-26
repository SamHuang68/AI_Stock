# -*- coding: utf-8 -*-
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

import consensus_attention as ca  # noqa: E402


def signal(signal_id, state='OBSERVATION', strength=40, direction='upside', domains=2):
    return {
        'signalId': signal_id, 'label': signal_id, 'state': state,
        'tier': 'info' if state == 'WATCH' else 'observation',
        'strength': strength, 'direction': direction,
        'independentDomains': domains, 'evidenceQuality': 0.9,
        'evidenceIds': ['global.tech', 'anchor.2330', 'breadth.stock_scope'],
        'reasons': ['跨市場來源同向'], 'strongestCounterEvidence': [],
        'confirmation': '現貨與廣度同向', 'invalidation': '核心方向反轉',
        'expiresAt': '2026-08-27T08:00:00+00:00',
    }


def context(*, freshness=1.0, portfolio=None):
    return {
        'ok': True, 'market': 'TW', 'asOf': '2026-08-26T08:00:00+00:00',
        'regime': {'id': 'NARROW_RALLY', 'label': '指數偏強、結構狹窄', 'confidence': 0.82},
        'actionEnvelope': {'confirmation': ['廣度回升'], 'invalidation': ['指數轉弱']},
        'divergences': [{
            'id': 'INDEX_UP_BREADTH_DOWN', 'severity': 'warning', 'confidence': 0.79,
            'evidenceIds': ['twii.live', 'breadth.stock_scope'],
            'insight': '指數與廣度背離', 'confirmation': '廣度回升', 'invalidation': '指數轉弱',
        }],
        'earlyWarnings': {'signals': [
            signal('TW_DOWNSIDE_PRECURSOR', strength=25, direction='downside', domains=1),
            signal('TW_ATTACK_BUILDUP', state='WATCH', strength=63, direction='upside', domains=3),
            signal('AI_WAFER_DOUBLE_ARROW', strength=42, direction='upside', domains=2),
            signal('MEMORY_CYCLE_RESONANCE', strength=38, direction='mixed', domains=1),
        ]},
        'dataQuality': {'completeness': 0.91, 'freshness': freshness, 'staleFields': []},
        'portfolioOverlay': portfolio,
        'exposureLab': {},
    }


class ConsensusAttentionTest(unittest.TestCase):
    def test_contract_is_bounded_and_watch_only_counts_badge(self):
        out = ca.build_consensus_attention(context())
        self.assertEqual(out['authority'], 'attention_only')
        self.assertEqual(out['maxVisible'], 3)
        self.assertEqual(out['maxItems'], 5)
        self.assertLessEqual(len(out['items']), 5)
        self.assertEqual(out['actionableCount'], 2)  # structure + attack WATCH
        self.assertTrue(out['policy']['observationIncrementsBadge'] is False)
        self.assertTrue(all(row['authority'] == 'attention_only' for row in out['items']))

    def test_attention_score_is_not_probability_and_sources_are_deduplicated(self):
        out = ca.build_consensus_attention(context())
        attack = next(row for row in out['items'] if row['id'] == 'TW_ATTACK_BUILDUP')
        self.assertEqual(attack['sourceDomains'].count('ai_anchor_chain'), 1)
        self.assertIn('tw_breadth_participation', attack['sourceDomains'])
        self.assertNotEqual(attack['attentionScore'], attack['strength'])
        self.assertFalse(out['policy']['strengthIsProbability'])

    def test_stale_context_freezes_alert_count(self):
        out = ca.build_consensus_attention(context(freshness=0.1))
        self.assertEqual(out['actionableCount'], 0)
        self.assertTrue(all(row['freshness']['status'] == 'stale' for row in out['items']))
        self.assertFalse(out['policy']['staleDataMayAlert'])

    def test_event_generation_changes_on_lifecycle_or_session(self):
        first_context = context()
        first = ca.build_consensus_attention(first_context)
        attack_first = next(row for row in first['items'] if row['id'] == 'TW_ATTACK_BUILDUP')
        second_context = context()
        second_context['earlyWarnings']['signals'][1]['state'] = 'ARMED'
        second = ca.build_consensus_attention(second_context)
        attack_second = next(row for row in second['items'] if row['id'] == 'TW_ATTACK_BUILDUP')
        self.assertNotEqual(attack_first['eventKey'], attack_second['eventKey'])
        third_context = context()
        third_context['asOf'] = '2026-08-27T08:00:00+00:00'
        third = ca.build_consensus_attention(third_context)
        attack_third = next(row for row in third['items'] if row['id'] == 'TW_ATTACK_BUILDUP')
        self.assertNotEqual(attack_first['eventKey'], attack_third['eventKey'])

    def test_owner_exposure_never_appears_for_observation_pool(self):
        actual = context(portfolio={
            'kind': 'actual', 'available': True,
            'lookThrough': {'effectiveGrossExposurePct': 184.9},
        })
        actual['exposureLab'] = {'temperature': {'score': 86, 'tone': 'hot', 'state': '過熱', 'components': []}}
        actual_out = ca.build_consensus_attention(actual)
        self.assertTrue(any(row['id'] == 'OWNER_EXPOSURE' and row['privacyClass'] == 'owner_only'
                            for row in actual_out['items']))
        observed = context(portfolio={'kind': 'observation_pool', 'available': True})
        observed['exposureLab'] = actual['exposureLab']
        observed_out = ca.build_consensus_attention(observed)
        self.assertFalse(any(row['id'] == 'OWNER_EXPOSURE' for row in observed_out['items']))


if __name__ == '__main__':
    unittest.main()
