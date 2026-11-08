"""可选运维看板(Streamlit,只读)。

用法(backend 目录下):
    pip install -r requirements-dashboard.txt
    streamlit run tools/dashboard.py

看板只读 SQLite(账号、令牌、用量、诊断),不修改线上数据,也不启动 Web 服务。
主站不依赖 Streamlit;未安装时主服务与测试都不受影响。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import dashboard_data  # noqa: E402


def main() -> None:
    import streamlit as st

    st.set_page_config(page_title="MathGuide 运维看板", page_icon="📊", layout="wide")
    st.title("MathGuide 运维看板")
    st.caption(f"只读 SQLite:{dashboard_data.db_path()}")

    summary = dashboard_data.overview()
    columns = st.columns(5)
    columns[0].metric("账号", summary["users"])
    columns[1].metric("游客", summary["guests"])
    columns[2].metric("有效令牌", summary["tokens"])
    columns[3].metric("调用次数", summary["usage_calls"])
    columns[4].metric("回复字数", summary["usage_chars"])

    left, right = st.columns(2)
    with left:
        st.subheader("模型角色分布")
        st.bar_chart(summary["roles"] or {"暂无": 0})
    with right:
        st.subheader("工作区分布")
        st.bar_chart(summary["workspaces"] or {"暂无": 0})

    st.subheader("薄弱知识点(每个知识点取最后一次诊断)")
    rows = dashboard_data.weak_points(limit=20)
    if rows:
        st.dataframe(rows, use_container_width=True)
    else:
        st.info("暂无薄弱点记录")
    st.caption(f"诊断记录 {summary['diagnoses']} 条,其中薄弱 {summary['weak']} 条。")


if __name__ == "__main__":
    main()
