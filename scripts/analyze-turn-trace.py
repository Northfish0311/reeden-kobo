#!/usr/bin/env python3
"""Analyze numeric trace events. No device access and no visual-quality inference."""
import argparse
import json
import pathlib
import statistics


def elapsed(row, before, after):
    a, b = row.get(before, 0), row.get(after, 0)
    return (b - a) / 1e6 if a and b and b >= a else None


def analyze(path):
    rows, events = [], []
    for line in path.read_text().splitlines():
        if not line.startswith('[turn-trace] '):
            continue
        event = json.loads(line[len('[turn-trace] '):])
        if event['op'] != 'summary':
            events.append(event)
            continue
        if event['events'] != len(events) or any(x['id'] != event['id'] for x in events):
            raise ValueError('incomplete or interleaved transaction trace')
        pending, peak, errors, starts = set(), 0, [], []
        for e in events:
            if e['end_ns'] < e['begin_ns']:
                raise ValueError('non-monotonic ioctl interval')
            if e['rc'] < 0:
                errors.append({'op': e['op'], 'marker': e['marker'], 'errno': e['errno']})
            elif e['op'] == 'send':
                if e['marker'] in pending:
                    raise ValueError('reused in-flight marker')
                pending.add(e['marker'])
                peak = max(peak, len(pending))
                starts.append(e['begin_ns'])
            elif e['op'] == 'wait_complete':
                pending.discard(e['marker'])
        if event['outcome'] == 'complete' and pending:
            raise ValueError('successful transaction has unfenced markers')
        gaps = [(b - a) / 1e6 for a, b in zip(starts, starts[1:])]
        rows.append({
            'id': event['id'], 'outcome': event['outcome'], 'fallback': event['fallback'],
            'profile': event.get('profile', 'unknown'),
            'requested_bands': event.get('requested_bands'), 'span_us': event.get('span_us'),
            'min_gap_us': event.get('min_gap_us'), 'max_inflight': event.get('max_inflight'),
            'send_calls': sum(e['op'] == 'send' for e in events), 'peak_inflight': peak,
            'input_to_arm_ms': elapsed(event, 'input_read_ns', 'arm_ns'),
            'arm_to_first_frame_ms': elapsed(event, 'arm_ns', 'first_frame_ns'),
            'settling_ms': elapsed(event, 'last_frame_ns', 'flush_ns'),
            'policy_and_lock_ms': elapsed(event, 'flush_ns', 'planned_ns'),
            'framebuffer_copy_ms': elapsed(event, 'copy_begin_ns', 'copied_ns'),
            'flush_to_complete_ms': elapsed(event, 'flush_ns', 'complete_ns'),
            'send_span_ms': (starts[-1] - starts[0]) / 1e6 if starts else None,
            'gap_min_ms': min(gaps) if gaps else None,
            'gap_max_ms': max(gaps) if gaps else None,
            'gap_stdev_ms': statistics.pstdev(gaps) if gaps else None,
            'ioctl_ms': {op: sum((e['end_ns'] - e['begin_ns']) / 1e6 for e in events if e['op'] == op)
                         for op in ('send', 'wait_submission', 'wait_complete')},
            'errors': errors,
        })
        events = []
    if events:
        raise ValueError('trace ends before transaction summary')
    if not rows:
        raise ValueError('no complete turn-trace transactions')
    return rows


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('log', type=pathlib.Path)
    p.add_argument('--evidence', required=True, choices=['mock', 'device'])
    p.add_argument('--output', type=pathlib.Path)
    args = p.parse_args()
    result = {'evidence': args.evidence, 'kernel_merging': 'not observable from these userspace events',
              'optical_settle': 'requires physical video/feedback', 'transactions': analyze(args.log)}
    text = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.write_text(text)
    else:
        print(text, end='')
