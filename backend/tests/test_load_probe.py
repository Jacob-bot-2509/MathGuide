"""tools/load_probe.py:探针的判定逻辑必须能被离线验证。

这些函数决定了「这台机器扛不扛得住」,一旦算错,结论就会把 2.4 的内存上限指到反方向
(比如把"没采到内存"当成"内存很低")。所以纯计算部分逐个钉住。
"""
from __future__ import annotations

from tools import load_probe

MEMINFO = """MemTotal:       16316384 kB
MemFree:          512000 kB
MemAvailable:    8123456 kB
Buffers:          120000 kB
"""

STATUS = """Name:\tuvicorn
VmPeak:\t 3200000 kB
VmSize:\t 3100000 kB
VmRSS:\t 412345 kB
Threads:\t9
"""


def test_parse_rss_kb_reads_vmrss():
    assert load_probe.parse_rss_kb(STATUS) == 412345


def test_parse_rss_kb_missing_key_is_none_not_zero():
    # 0 会被上层当成"采到了,内存很低",必须区分「没有数据」
    assert load_probe.parse_rss_kb("Name:\tuvicorn\n") is None


def test_meminfo_parsing_prefers_memavailable():
    assert load_probe.mem_available_kb(MEMINFO) == 8123456
    assert load_probe.total_mem_kb(MEMINFO) == 16316384
    assert load_probe.mem_available_kb("") is None


def test_percentile_uses_nearest_rank():
    values = [float(i) for i in range(1, 11)]  # 1..10
    assert load_probe.percentile(values, 50) == 5.0
    assert load_probe.percentile(values, 95) == 10.0
    assert load_probe.percentile(values, 100) == 10.0
    assert load_probe.percentile([], 50) == 0.0
    assert load_probe.percentile([7.0], 95) == 7.0


def test_mem_verdict_flags_over_limit():
    ok, detail = load_probe.mem_verdict(8 * 1024 * 1024, 10 * 1024 * 1024, 70.0)
    assert ok is False and "80.0%" in detail


def test_mem_verdict_passes_under_limit():
    ok, detail = load_probe.mem_verdict(2 * 1024 * 1024, 10 * 1024 * 1024, 70.0)
    assert ok is True and "20.0%" in detail


def test_mem_verdict_without_samples_is_skip_not_pass():
    """没采到内存时给 SKIP 文案:结论只剩延迟,不能让人误读成"内存很省"。"""
    ok, detail = load_probe.mem_verdict(None, 10 * 1024 * 1024, 70.0)
    assert ok is True and "SKIP" in detail
    ok, detail = load_probe.mem_verdict(1024, None, 70.0)
    assert ok is True and "无法算比例" in detail


def test_build_long_doc_has_requested_sections():
    doc = load_probe.build_long_doc(60)
    assert len(doc["sections"]) == 60
    assert doc["sections"][0]["heading"].startswith("1.")
    paragraphs = doc["sections"][0]["paragraphs"]
    assert any("\\lim" in item or "\\int" in item or "\\forall" in item for item in paragraphs), \
        "带公式才是真实负载(KaTeX 排版是耗时大头)"
    assert len(paragraphs) >= 5, "每节要够长,否则量出来的耗时不代表长文档"
    assert len(load_probe.build_long_doc(0)["sections"]) == 1  # 至少一节,不能是空文档


def test_count_pages_ignores_page_tree_node():
    data = b"/Type /Page/MediaBox" + b"/Type/Page " + b"/Type /Pages/Kids"
    assert load_probe.count_pages(data) == 2
    assert load_probe.count_pages(b"") == 0


def test_classify_429_separates_gate_from_rate_limit():
    """闸门的 429 与接口限流的 429 必须分开:前者是容量信号,后者让测量无效。"""
    assert load_probe.classify_429(b'{"detail":"pdf export busy, retry later"}') == "gate"
    assert load_probe.classify_429(b'{"detail":"rate limited"}') == "ratelimit"
    assert load_probe.classify_429(b"") == "unknown"


def test_classify_429_ignores_case_and_extra_text():
    assert load_probe.classify_429(b'{"detail":"PDF EXPORT BUSY"}') == "gate"
    assert load_probe.classify_429(b'{"detail":"Rate Limited"}') == "ratelimit"


def test_login_reports_connection_failure_without_traceback(capsys):
    """连不上时要给一条人话结论,而不是在主线程抛 URLError(那会吞掉整轮探测)。"""

    class DeadCtx:
        base = "http://127.0.0.1:8099"

        def call(self, method, path, body=None, timeout=None):
            return 0, {}, b"connection refused"

    assert load_probe.login(DeadCtx(), "13900000000", "x") is False
    out = capsys.readouterr().out
    assert "连不上" in out and "api/health" in out


def test_rss_sampler_without_pid_stays_silent():
    with load_probe.RssSampler(0) as sampler:
        pass
    assert sampler.peak == 0 and sampler.samples == 0


def test_rss_sampler_tracks_peak_not_last_value(monkeypatch):
    """峰值 ≠ 最后一次读数:导出结束浏览器退出后内存会掉回去,只看末次会漏掉尖峰。"""
    readings = iter([100, 900, 300])
    monkeypatch.setattr(load_probe, "read_rss_kb", lambda pid: next(readings, 300))
    sampler = load_probe.RssSampler(1234)
    for _ in range(3):
        sampler._sample()
    assert sampler.peak == 900
    assert sampler.samples == 3
