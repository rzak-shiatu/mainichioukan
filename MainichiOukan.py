import os
import polars as pl
import duckdb
import re
import streamlit as st
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import pandas as pd
from matplotlib import rcParams

# フォント設定（日本語表示用）
rcParams['font.family'] = 'Meiryo'  # Windowsならメイリオ
# macOS: 'Hiragino Sans'
# Linux: 'IPAexGothic' など

st.set_page_config(page_title="毎日王冠分析（上位3頭限定）", layout="wide")

# === CSV読込 ===
csv_path = os.path.join(os.path.dirname(__file__), "mainichioukan2015-2024.csv")
df = pl.read_csv(csv_path)

# タイムを秒数に変換
def to_seconds(time_str):
    if not isinstance(time_str, str) or time_str.strip() == "":
        return None
    if ":" in time_str:
        m, s = time_str.split(":")
        return int(m) * 60 + float(s)
    try:
        return float(time_str)
    except ValueError:
        return None

df = df.with_columns(
    pl.col("タイム").map_elements(to_seconds, return_dtype=pl.Float64).alias("タイム秒")
)

# 馬体重を分割
def split_weight(w):
    if isinstance(w, str) and "(" in w:
        m = re.match(r"(\d{3})\(([+-]?\d+)\)", w)
        if m:
            base, diff = m.groups()
            return int(base), int(diff)
    return None, None

df = df.with_columns([
    pl.col("馬体重").map_elements(lambda x: split_weight(x)[0], return_dtype=pl.Int64).alias("馬体重kg"),
    pl.col("馬体重").map_elements(lambda x: split_weight(x)[1], return_dtype=pl.Int64).alias("体重増減")
])

# 性齢を分割
def split_seirei(s):
    if not isinstance(s, str) or s == "":
        return None, None
    sex = s[0]
    age = int(s[1:]) if s[1:].isdigit() else None
    return sex, age

df = df.with_columns([
    pl.col("性齢").map_elements(lambda x: split_seirei(x)[0], return_dtype=pl.Utf8).alias("性別"),
    pl.col("性齢").map_elements(lambda x: split_seirei(x)[1], return_dtype=pl.Int64).alias("年齢")
])

# 数値キャスト
df = df.with_columns([
    pl.col("人気").cast(pl.Int64, strict=False),
    pl.col("単勝").cast(pl.Float64, strict=False),
    pl.col("上がり3F").cast(pl.Float64, strict=False),
    pl.col("着順").cast(pl.Int64, strict=False)
])

# === ★ 上位3頭のみ抽出 ===
df_top3 = df.filter(pl.col("着順") <= 3)

# DuckDBに登録
con = duckdb.connect()
con.register("races", df_top3)

# Streamlit サイドバーで選択
mode = st.sidebar.radio("表示モードを選択", ["人気別勝率", "枠順別勝率", "年ごとの平均馬体重・平均上がり3F"])

# === 人気別勝率 ===
if mode == "人気別勝率":
    q_pop_stats = con.execute("""
        SELECT
            人気,
            COUNT(*) AS 出走数,
            SUM(CASE WHEN 着順 = 1 THEN 1 ELSE 0 END) AS 勝利数,
            ROUND(100.0 * SUM(CASE WHEN 着順 = 1 THEN 1 ELSE 0 END) / COUNT(*), 1) AS 勝率
        FROM races
        WHERE 人気 IS NOT NULL
        GROUP BY 人気
        ORDER BY 人気
    """).df()

    st.subheader("人気別勝率（過去10年・上位3頭対象）")
    st.dataframe(q_pop_stats.set_index("人気"))

    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.bar(q_pop_stats["人気"].astype(str), q_pop_stats["勝率"], color="orange")
    ax.set_xlabel("人気")
    ax.set_ylabel("勝率 (%)")
    ax.set_title("毎日王冠 過去10年 人気別勝率（上位3頭）")
    ax.grid(axis="y", linestyle="--", alpha=0.7)

    for bar, rate, wins in zip(bars, q_pop_stats["勝率"], q_pop_stats["勝利数"]):
        if wins > 0:
            ax.text(bar.get_x() + bar.get_width()/2,
                    bar.get_height()-0.5,
                    f"{wins}勝", ha="center", va="top", fontsize=9, color="red")

    st.pyplot(fig)

# === 枠順別勝率 ===
elif mode == "枠順別勝率":
    q_waku = con.execute("""
        SELECT
            枠番,
            COUNT(*) AS 出走数,
            SUM(CASE WHEN 着順 = 1 THEN 1 ELSE 0 END) AS 勝利数,
            ROUND(100.0 * SUM(CASE WHEN 着順 = 1 THEN 1 ELSE 0 END) / COUNT(*), 1) AS 勝率
        FROM races
        GROUP BY 枠番
        ORDER BY 枠番
    """).df()

    st.subheader("枠順別勝率（過去10年・上位3頭対象）")
    st.dataframe(q_waku.set_index("枠番"))

    fig, ax = plt.subplots(figsize=(8, 6))
    bars = ax.bar(q_waku["枠番"].astype(str), q_waku["勝率"], color="skyblue")
    ax.set_xlabel("枠番")
    ax.set_ylabel("勝率 (%)")
    ax.set_title("毎日王冠 過去10年 枠順別勝率（上位3頭）")
    ax.grid(axis="y", linestyle="--", alpha=0.7)

    for bar, rate, wins in zip(bars, q_waku["勝率"], q_waku["勝利数"]):
        if wins > 0:
            ax.text(bar.get_x() + bar.get_width()/2,
                    bar.get_height()-1.0,
                    f"{wins}勝", ha="center", va="top", fontsize=9, color="red")

    st.pyplot(fig)

# === 年ごとの平均馬体重・上がり3F ===
elif mode == "年ごとの平均馬体重・平均上がり3F":
    q_avg = con.execute("""
        SELECT year AS Year,
               ROUND(AVG(馬体重kg), 1) AS 平均馬体重,
               ROUND(AVG("上がり3F"), 1) AS 平均上がり3F
        FROM races
        WHERE 馬体重kg IS NOT NULL AND "上がり3F" IS NOT NULL
        GROUP BY year
        ORDER BY year
    """).df()

    st.subheader("年ごとの平均馬体重・平均上がり3F（上位3頭対象）")
    st.dataframe(q_avg.set_index("Year"))

    fig, ax1 = plt.subplots(figsize=(10, 6))
    ax1.plot(q_avg["Year"], q_avg["平均馬体重"], marker="o", color="green", label="平均馬体重 (kg)")
    ax1.set_ylabel("平均馬体重 (kg)")
    ax1.set_xlabel("Year")
    ax1.grid(True)

    ax2 = ax1.twinx()
    ax2.plot(q_avg["Year"], q_avg["平均上がり3F"], marker="^", color="red", label="平均上がり3F (秒)")
    ax2.set_ylabel("平均上がり3F (秒)")

    fig.legend(loc="upper left", bbox_to_anchor=(0.1, 1.0))
    plt.title("毎日王冠 過去10年 平均馬体重・平均上がり3F（上位3頭）")

    st.pyplot(fig)
