#!/usr/bin/env python3
"""Check that incomplete, failed and missing traces cannot become fake wins."""
import importlib.util
import json
import pathlib
import tempfile

root = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('turn_trace', root / 'scripts/analyze-turn-trace.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

send = dict(id=1, op='send', begin_ns=10, end_ns=20, marker=7, rc=0, errno=0)
wait = dict(id=1, op='wait_complete', begin_ns=30, end_ns=40, marker=7, rc=0, errno=0)
summary = dict(id=1, op='summary', events=2, outcome='complete', fallback='none')
with tempfile.TemporaryDirectory() as tmp:
    path = pathlib.Path(tmp) / 'log'

    def parse(rows):
        path.write_text(''.join('[turn-trace] ' + json.dumps(row) + '\n' for row in rows))
        return module.analyze(path)

    assert parse([send, wait, summary])[0]['peak_inflight'] == 1
    for rows in [[], [send], [send, summary],
                 [send, dict(wait, marker=8), summary],
                 [send, dict(wait, end_ns=29), summary]]:
        try:
            parse(rows)
        except ValueError:
            pass
        else:
            raise AssertionError('bad trace accepted')
    row = parse([send, dict(wait, rc=-1, errno=5), dict(summary, outcome='complete-error')])[0]
    assert row['errors'][0]['errno'] == 5 and row['input_to_arm_ms'] is None
print('PASS: trace integrity, no missing-data wins, failed completions and unavailable input timings')
