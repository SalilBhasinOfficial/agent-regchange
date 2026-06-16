"""Resume / parse-cache primitives: key stability + best-effort offline."""

from __future__ import annotations

from pathlib import Path


def test_resume_key_stable_and_input_sensitive(tmp_path: Path):
    from app.fast_api_app import _resume_key

    a = tmp_path / "a.pdf"; a.write_bytes(b"AAA")
    b = tmp_path / "b.pdf"; b.write_bytes(b"BBB")
    k1 = _resume_key(a, b, "ns")
    k2 = _resume_key(a, b, "ns")
    assert k1 == k2 and k1 and len(k1) == 64           # stable, sha256 hex
    assert _resume_key(b, a, "ns") != k1               # order matters
    assert _resume_key(a, b, "other") != k1            # namespace matters
    b.write_bytes(b"CCC")
    assert _resume_key(a, b, "ns") != k1               # content matters


def test_resume_key_none_on_missing_file(tmp_path: Path):
    from app.fast_api_app import _resume_key

    a = tmp_path / "a.pdf"; a.write_bytes(b"AAA")
    assert _resume_key(a, tmp_path / "nope.pdf", "ns") is None


def test_cache_and_checkpoint_are_best_effort_offline(monkeypatch):
    # With no Spanner (_get_database returns None) every store call must be a
    # graceful no-op / None — never raise — so the offline path is unaffected.
    import app.observability.pipeline_store as ps

    monkeypatch.setattr(ps, "_get_database", lambda: None)
    assert ps.parse_cache_get("deadbeef") is None
    ps.parse_cache_put("deadbeef", "doc", 3, [{"text": "x", "layout_type": "p",
                                               "page_start": 1, "page_end": 1}])
    assert ps.load_run_checkpoint("k") is None
    ps.save_run_checkpoint("k", ["ingested"], '{"a":1}', "run1")
    ps.clear_run_checkpoint("k")  # must not raise
