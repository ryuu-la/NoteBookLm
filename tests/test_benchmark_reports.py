"""Verify published measurements and reject plausible-looking corrupted reports."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('benchmark_publish', ROOT / 'benchmarks/publish.py')
publish = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publish)


@pytest.fixture
def report():
    return json.loads((ROOT / 'src/local_notebook/assets/retrieval-benchmark.json').read_text(encoding='utf-8'))


def test_saved_retrieval_scores_and_latencies_match_raw_cases(report):
    publish.validate(report)


@pytest.mark.parametrize('key,value', [('recall_at_8', .5), ('p50_ms', -1), ('p95_ms', -1)])
def test_publisher_refuses_incorrect_summary(report, key, value):
    corrupted = copy.deepcopy(report)
    corrupted['results'][0][key] = value
    with pytest.raises(ValueError):
        publish.validate(corrupted)


def test_publisher_refuses_missing_measurement(report):
    report['results'][0]['cases'].pop()
    with pytest.raises(ValueError):
        publish.validate(report)


def test_documented_table_uses_saved_measurements(report):
    assert publish.table(report) in (ROOT / 'docs/RETRIEVAL_BENCHMARK.md').read_text(encoding='utf-8')


def test_scale_table_and_probes_match_saved_evidence():
    data = json.loads((ROOT / 'docs/benchmark-result.json').read_text(encoding='utf-8'))
    assert publish.scale_table(data) in (ROOT / 'docs/VERIFICATION.md').read_text(encoding='utf-8')
    data['probes'][0]['retrieved'] = []
    with pytest.raises(ValueError):
        publish.scale_table(data)
