from collections import Counter
from datetime import datetime, timedelta
import re

import pandas as pd
import plotly.express as px
import streamlit as st

from config import (
    RSS_DEFAULT_ACTIVE,
    RSS_FEEDS,
    RSS_FEED_TAGS,
    RSS_MAX_ITEMS_PER_FEED,
    RSS_MAX_TOTAL_ITEMS,
)
from data_fetch import fetch_rss_feed_health, fetch_rss_feeds_by_keys
from utils import get_ui_detail_mode, setup_page


setup_page("News Feed")
_ = get_ui_detail_mode("Summary")

st.title("📰 News Feed")
st.caption("Contextual news mapped to tracked signals and sectors.")

st.sidebar.header("Feed Filters")
FEED_GROUPS = {
    "Market Overview & Regime": ["ET Markets", "Moneycontrol Markets", "Business Standard Markets", "NSE Official Press", "SEBI Orders & Circulars"],
    "Global Macro (Fed/Rates/FX)": ["Reuters Fed/Economy", "FT Markets", "Bloomberg Economics", "WSJ Economy", "ET Rupee / Forex", "Reuters Forex"],
    "Crude Oil & Gold": ["Reuters Oil", "ET Oil & Gas", "Platts/S&P Oil", "ET Commodities", "Kitco Gold", "IEA Oil Market"],
    "RBI & Monetary Policy": ["RBI Press Releases", "ET RBI"],
    "FII/DII Flows": ["ET FII/DII Flows", "NSDL FPI Data", "Moneycontrol FII"],
    "Pre-Market / Gift Nifty": ["ET Gift Nifty / SGX", "Moneycontrol Pre-market"],
    "Banks & NBFC": ["ET Banking & Finance", "BS Banking", "RBI Banking Regulation"],
    "IT & Tech": ["ET Technology", "BS Tech", "Nasscom", "TechCrunch"],
    "Pharma": ["ET Pharma", "BS Pharma", "FDA Drug Approvals", "FDA Warning Letters"],
    "Energy & Renewables": ["ET Energy", "Ministry of Power India", "Mercom India (Renewables)"],
    "Metals": ["ET Metals", "Steel Mint", "Metal Miner"],
    "Auto": ["ET Auto", "BS Auto", "SIAM (Auto Sales Data)"],
    "Real Estate": ["ET Real Estate", "PropTiger/Housing"],
    "Capital Goods & Defence": ["ET Capital Goods", "Ministry of Defence India", "Indian Defence Review"],
    "Telecom": ["ET Telecom", "Telecom Talk"],
    "FMCG & Consumer": ["ET FMCG", "ET Consumer / Retail", "ET Hospitality"],
    "Chemicals": ["ET Chemicals", "ICIS Chemical News"],
    "Insurance & Market Infra": ["ET Insurance", "IRDA Press"],
    "Services / Ports / Aviation": ["ET Aviation", "ET Shipping & Ports"],
    "Earnings & Results": ["ET Earnings", "BS Results"],
    "Global Indices": ["Reuters World Markets", "AP Business", "Nikkei Asia"],
}

selected_feed_names = []
for group_name, group_feeds in FEED_GROUPS.items():
    with st.sidebar.expander(group_name, expanded=False):
        for feed in group_feeds:
            if feed not in RSS_FEEDS:
                continue
            default = feed in RSS_DEFAULT_ACTIVE
            if st.checkbox(feed, value=default, key=f"feed_{group_name}_{feed}"):
                selected_feed_names.append(feed)

if st.sidebar.toggle("Use Default Tag Bundle", value=False):
    default_tag_keys = [
        "regime_overview",
        "macro_us_fed",
        "fii_dii_flows",
        "gift_nifty_premarket",
    ]
    selected_feed_names = []
    for t in default_tag_keys:
        selected_feed_names.extend(RSS_FEED_TAGS.get(t, []))

time_filter = st.sidebar.selectbox("Time Window", ["Last 1h", "Last 6h", "Last 24h", "Last 48h", "Last 7d"], index=2)
keyword = st.sidebar.text_input("Keyword Filter", placeholder="NIFTY, RBI, inflation")

window_hours = {"Last 1h": 1, "Last 6h": 6, "Last 24h": 24, "Last 48h": 48, "Last 7d": 168}[time_filter]
cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=window_hours)

selected_feed_names = list(dict.fromkeys([x for x in selected_feed_names if x in RSS_FEEDS]))
if not selected_feed_names:
    st.warning("Select at least one feed from the sidebar.")
    st.stop()

with st.spinner("Fetching latest headlines..."):
    news_df = fetch_rss_feeds_by_keys(
        selected_feed_names,
        max_per_feed=RSS_MAX_ITEMS_PER_FEED,
        max_total=RSS_MAX_TOTAL_ITEMS,
    )

if not news_df.empty:
    news_df["published"] = pd.to_datetime(news_df["published"], utc=True, errors="coerce")
    news_df = news_df[news_df["published"].isna() | (news_df["published"] >= cutoff)]
    if keyword.strip():
        pat = keyword.strip().lower()
        mask = (
            news_df["title"].astype(str).str.lower().str.contains(pat, na=False)
            | news_df["summary"].astype(str).str.lower().str.contains(pat, na=False)
        )
        news_df = news_df[mask]
    news_df = news_df.sort_values("published", ascending=False, na_position="last")

st.metric("Articles", int(len(news_df)))


def _tokenize(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9\-]{2,}", str(text or "").lower())
    stop = {
        "the", "and", "for", "with", "from", "that", "this", "will", "has", "are", "its", "into",
        "over", "after", "amid", "more", "than", "market", "markets", "india", "indian", "news",
        "times", "economic", "reuters", "business", "update",
    }
    return [w for w in words if w not in stop]


if not news_df.empty:
    tokens = []
    for t in news_df["title"].astype(str):
        tokens.extend(_tokenize(t))
    top_words = Counter(tokens).most_common(15)
    if top_words:
        kw_df = pd.DataFrame(top_words, columns=["word", "count"])
        fig = px.bar(kw_df, x="count", y="word", orientation="h", title="Top Keywords (Headlines)")
        fig.update_layout(height=350, yaxis={"categoryorder": "total ascending"})
        st.plotly_chart(fig, width="stretch")

st.markdown("### Headlines")
if news_df.empty:
    st.info("No matching articles for selected filters.")
else:
    now = pd.Timestamp.now(tz="UTC")
    for _, row in news_df.iterrows():
        with st.container(border=True):
            title = str(row.get("title", "")).strip()
            link = str(row.get("link", "")).strip()
            source = str(row.get("source", "")).strip()
            published = pd.to_datetime(row.get("published"), utc=True, errors="coerce")
            summary = str(row.get("summary", "")).strip()

            if link:
                st.markdown(f"**[{title}]({link})**")
            else:
                st.markdown(f"**{title}**")

            if pd.isna(published):
                age_txt = "time unknown"
            else:
                age_h = max(0, int((now - published).total_seconds() // 3600))
                age_txt = f"{age_h}h ago"
            st.caption(f"{source} · {age_txt}")
            if summary:
                st.caption((summary[:200] + "...") if len(summary) > 200 else summary)

with st.expander("Feed Health", expanded=False):
    rows = []
    fetched_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for name in selected_feed_names:
        url = RSS_FEEDS.get(name, "")
        health = fetch_rss_feed_health(name, url, max_items=RSS_MAX_ITEMS_PER_FEED)
        rows.append(
            {
                "feed": name,
                "last_fetch_time": fetched_at,
                "item_count": int(health.get("item_count", 0) or 0),
                "latency_ms": health.get("latency_ms"),
                "fetch_errors": int(health.get("fetch_errors", 0) or 0),
                "parse_errors": int(health.get("parse_errors", 0) or 0),
                "status": str(health.get("status", "Error")),
                "error_detail": str(health.get("error_detail", "") or ""),
            }
        )
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
