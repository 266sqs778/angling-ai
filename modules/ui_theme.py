"""Apple 风格毛玻璃（glassmorphism）主题 —— 集中式 CSS 注入。

设计要点：
- 背景铺柔和径向渐变光晕，作为毛玻璃「可透过」的底层；
- 卡片、侧边栏、表单、提示框、表格等统一为半透明白玻璃（backdrop-filter）；
- 字体走 Apple 系统字栈，标题收紧字距，主色沿用项目水青蓝 #0d7ea8。

兼容性：Streamlit 内部 class 名随版本漂移，本文件一律以 `data-testid` /
`data-baseweb` 属性做选择器；当前线上为 Streamlit 1.50。
"""
from __future__ import annotations

import streamlit as st

GLASS_CSS = """
<style>
:root{
  --glass-bg: rgba(255,255,255,0.55);
  --glass-bg-strong: rgba(255,255,255,0.74);
  --glass-border: rgba(255,255,255,0.70);
  --glass-stroke: rgba(120,160,180,0.28);
  --glass-shadow: 0 10px 32px rgba(16,52,72,0.10);
  --glass-blur: blur(22px) saturate(170%);
  --radius-lg: 22px;
  --radius-md: 16px;
  --radius-sm: 12px;
  --accent: #0d7ea8;
  --accent-2: #12a0c9;
  --accent-soft: rgba(13,126,168,0.12);
  --ink: #12303c;
  --ink-soft: #55707d;
}

/* ---------------- 全局字体：Apple 系统字栈 ---------------- */
html, body, .stApp, [data-testid="stAppViewContainer"]{
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text",
    "Helvetica Neue", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  color: var(--ink);
  -webkit-font-smoothing: antialiased;
}

/* ---------------- 背景：柔和渐变光晕 ---------------- */
.stApp, [data-testid="stAppViewContainer"]{
  background:
    radial-gradient(1100px 760px at 6% -6%, rgba(13,126,168,0.20), transparent 62%),
    radial-gradient(900px 700px at 98% 8%, rgba(94,214,196,0.24), transparent 60%),
    radial-gradient(1000px 820px at 46% 108%, rgba(150,158,255,0.20), transparent 64%),
    linear-gradient(180deg, #f8fbfd 0%, #eef5f9 100%);
  background-attachment: fixed;
}
[data-testid="stMain"], [data-testid="stSidebarContent"],
[data-testid="stVerticalBlock"], [data-testid="stHorizontalBlock"]{
  background: transparent;
}

/* 顶栏 / 顶部装饰条 */
[data-testid="stHeader"]{ background: transparent; }
[data-testid="stDecoration"]{
  background: linear-gradient(90deg, rgba(13,126,168,0.92), rgba(94,214,196,0.85));
  height: 3px;
}

/* 主内容容器留白 */
[data-testid="stMainBlockContainer"]{
  max-width: 1180px;
  padding-top: 2.2rem;
  padding-bottom: 3.2rem;
}

/* ---------------- 侧边栏玻璃 ---------------- */
[data-testid="stSidebar"]{
  background: rgba(255,255,255,0.46);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border-right: 1px solid var(--glass-border);
  box-shadow: 8px 0 32px rgba(16,52,72,0.06);
}

/* ---------------- 通用玻璃卡片 ---------------- */
[data-testid="stMetric"],
[data-testid="stAlert"],
[data-testid="stForm"],
[data-testid="stChatMessage"]{
  background: var(--glass-bg);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  box-shadow: var(--glass-shadow);
}
[data-testid="stMetric"]{ border-radius: var(--radius-lg); padding: 18px 20px; }
[data-testid="stMetricLabel"]{ color: var(--ink-soft); font-weight: 500; }
[data-testid="stMetricValue"]{ font-weight: 650; letter-spacing: -0.02em; }
[data-testid="stAlert"]{ border-radius: var(--radius-md); }
[data-testid="stChatMessage"]{ border-radius: var(--radius-md); padding: 12px 14px; }
[data-testid="stForm"]{
  border-radius: var(--radius-lg);
  padding: 18px 18px 8px;
}

/* ---------------- 展开器 ---------------- */
[data-testid="stExpander"]{
  background: var(--glass-bg);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border) !important;
  border-radius: var(--radius-md);
  box-shadow: var(--glass-shadow);
  overflow: hidden;
}
[data-testid="stExpander"] details{ background: transparent; border: none; }

/* ---------------- 表格与图表 ---------------- */
[data-testid="stDataFrame"], [data-testid="stTable"],
[data-testid="stVegaLiteChart"], [data-testid="stArrowVegaLiteChart"]{
  background: var(--glass-bg-strong);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-md);
  box-shadow: var(--glass-shadow);
  overflow: hidden;
}
[data-testid="stVegaLiteChart"]{ padding: 10px 10px 2px; }

/* ---------------- Tabs：胶囊玻璃 ---------------- */
[data-baseweb="tab-list"]{
  gap: 6px;
  background: var(--glass-bg);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  border-radius: 999px;
  padding: 6px;
  box-shadow: var(--glass-shadow);
}
[data-baseweb="tab"]{
  border-radius: 999px !important;
  padding: 6px 16px !important;
  font-weight: 550;
}
[data-baseweb="tab"][aria-selected="true"]{
  background: var(--glass-bg-strong);
  box-shadow: 0 2px 10px rgba(16,52,72,0.10);
}
[data-testid="stTabs"] [data-baseweb="tab-highlight"],
[data-testid="stTabs"] [data-baseweb="tab-border"]{ display: none; }

/* ---------------- 按钮 ---------------- */
[data-testid^="stBaseButton"]{ transition: all .18s ease; }
[data-testid^="stBaseButton"]:hover{ transform: translateY(-1px); }
[data-testid="stBaseButton-primary"],
[data-testid="stBaseButton-primaryFormSubmit"]{
  background: linear-gradient(135deg, var(--accent), var(--accent-2));
  border: none;
  border-radius: 999px;
  color: #fff;
  font-weight: 600;
  box-shadow: 0 6px 18px rgba(13,126,168,0.28);
}
[data-testid="stBaseButton-secondary"],
[data-testid="stBaseButton-secondaryFormSubmit"]{
  background: var(--glass-bg-strong);
  backdrop-filter: blur(12px) saturate(160%);
  -webkit-backdrop-filter: blur(12px) saturate(160%);
  border: 1px solid var(--glass-border);
  border-radius: 999px;
  color: var(--ink);
  font-weight: 550;
}

/* ---------------- 输入控件 ---------------- */
[data-baseweb="input"],
[data-baseweb="textarea"],
[data-baseweb="select"] > div{
  background: rgba(255,255,255,0.72) !important;
  border: 1px solid var(--glass-stroke) !important;
  border-radius: var(--radius-sm) !important;
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
}
[data-baseweb="input"]:focus-within,
[data-baseweb="textarea"]:focus-within{
  box-shadow: 0 0 0 3px var(--accent-soft);
}

/* ---------------- 进度条 ---------------- */
[data-testid="stProgress"] div[role="progressbar"]{
  background: rgba(255,255,255,0.62);
  border-radius: 999px;
}
[data-testid="stProgress"] div[role="progressbar"] > div{
  background: linear-gradient(90deg, var(--accent), #5ed6c4);
  border-radius: 999px;
}

/* ---------------- 排版与细节 ---------------- */
h1{ letter-spacing: -0.03em; font-weight: 700; }
h2, h3{ letter-spacing: -0.02em; }
[data-testid="stCaptionContainer"]{ color: var(--ink-soft); }
hr{ border-color: rgba(18,48,60,0.10) !important; }

/* ---------------- 滚动条 ---------------- */
::-webkit-scrollbar{ width: 10px; height: 10px; }
::-webkit-scrollbar-thumb{
  background: rgba(13,126,168,0.25);
  border-radius: 999px;
  border: 2px solid transparent;
  background-clip: content-box;
}
::-webkit-scrollbar-thumb:hover{ background: rgba(13,126,168,0.42); background-clip: content-box; }

/* ---------------- 地图（iframe 无法毛玻璃，只做外框）---------------- */
[data-testid="stCustomComponentV1"]{
  background: var(--glass-bg-strong);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--glass-shadow);
  overflow: hidden;
}
</style>
"""


def inject() -> None:
    """注入毛玻璃主题。

    在 `st.set_page_config` 之后调用；每次 rerun 都会重新注入（幂等，无副作用）。
    """
    st.markdown(GLASS_CSS, unsafe_allow_html=True)
