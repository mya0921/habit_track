import os
import json
import sqlite3
import random
import datetime as dt
from typing import Optional, Dict, Any, List, Tuple

import requests
import pandas as pd
import streamlit as st


# =========================
# App Config
# =========================
st.set_page_config(page_title="AI 감정·습관 트래커", page_icon="", layout="wide")
DB_PATH = "mood_habit_app.db"


# =========================
# Helpers
# =========================
def iso_today() -> str:
    return dt.date.today().isoformat()


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def pct(numer: int, denom: int) -> int:
    if denom <= 0:
        return 0
    return int(round((numer / denom) * 100))


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def rgb_to_hex(r: int, g: int, b: int) -> str:
    return "#{:02x}{:02x}{:02x}".format(r, g, b)


def completion_to_bg_gradient(rate_0_100: int) -> Tuple[str, str]:
    """
    iOS-ish: 부드러운 파스텔 그라데이션.
    0%: 부드러운 핑크/라일락
    100%: 부드러운 민트/스카이
    """
    t = clamp(rate_0_100 / 100.0, 0.0, 1.0)

    # top color: pink/lilac -> mint
    top_start = (255, 234, 246)   # very light pink
    top_end   = (228, 255, 245)   # very light mint

    # bottom color: lilac -> sky
    bot_start = (241, 234, 255)   # very light lilac
    bot_end   = (231, 245, 255)   # very light sky

    top = (
        int(lerp(top_start[0], top_end[0], t)),
        int(lerp(top_start[1], top_end[1], t)),
        int(lerp(top_start[2], top_end[2], t)),
    )
    bot = (
        int(lerp(bot_start[0], bot_end[0], t)),
        int(lerp(bot_start[1], bot_end[1], t)),
        int(lerp(bot_start[2], bot_end[2], t)),
    )
    return rgb_to_hex(*top), rgb_to_hex(*bot)


def inject_ios_css(bg_top: str, bg_bottom: str):
    css = f"""
    <style>
      /* 전체 배경 그라데이션 */
      .stApp {{
        background: linear-gradient(180deg, {bg_top} 0%, {bg_bottom} 100%);
      }}

      /* iOS-like typography */
      html, body, [class*="css"] {{
        font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Segoe UI",
                     Roboto, Helvetica, Arial, "Apple Color Emoji","Segoe UI Emoji";
      }}

      /* 사이드바도 은은하게 */
      section[data-testid="stSidebar"] {{
        background: rgba(255,255,255,0.55) !important;
        backdrop-filter: blur(18px) !important;
        -webkit-backdrop-filter: blur(18px) !important;
        border-right: 1px solid rgba(0,0,0,0.06);
      }}

      /* 기본 여백 */
      .block-container {{
        padding-top: 1.25rem;
        padding-bottom: 2rem;
      }}

      /* 카드 스타일 */
      .ios-card {{
        background: rgba(255,255,255,0.72);
        border: 1px solid rgba(0,0,0,0.06);
        border-radius: 20px;
        padding: 16px 16px;
        box-shadow: 0 10px 30px rgba(0,0,0,0.06);
        backdrop-filter: blur(18px);
        -webkit-backdrop-filter: blur(18px);
      }}

      .ios-title {{
        font-size: 20px;
        font-weight: 700;
        letter-spacing: -0.02em;
        margin: 0 0 8px 0;
      }}

      .ios-subtle {{
        color: rgba(0,0,0,0.55);
        font-size: 13px;
        margin-top: 4px;
      }}

      /* pill */
      .pill {{
        display:inline-block;
        padding:6px 10px;
        border-radius: 999px;
        background: rgba(0,0,0,0.05);
        border: 1px solid rgba(0,0,0,0.06);
        margin-right: 6px;
        margin-bottom: 6px;
        font-size: 12px;
      }}

      /* 메트릭을 좀 iOS스럽게 */
      [data-testid="stMetric"] {{
        background: rgba(255,255,255,0.70);
        border: 1px solid rgba(0,0,0,0.06);
        border-radius: 18px;
        padding: 14px 14px;
        box-shadow: 0 10px 30px rgba(0,0,0,0.05);
      }}

      /* 버튼 둥글게 */
      .stButton button {{
        border-radius: 14px !important;
        padding: 0.55rem 0.85rem !important;
      }}

      /* 입력 요소 둥글게 */
      .stTextInput input, .stTextArea textarea, .stSelectbox div {{
        border-radius: 14px !important;
      }}
    </style>
    """
    st.markdown(css, unsafe_allow_html=True)


def card_open(title: str, subtitle: str = ""):
    st.markdown(
        f"""
        <div class="ios-card">
          <div class="ios-title">{title}</div>
          {f'<div class="ios-subtle">{subtitle}</div>' if subtitle else ''}
        """,
        unsafe_allow_html=True,
    )


def card_close():
    st.markdown("</div>", unsafe_allow_html=True)


# =========================
# DB
# =========================
def conn():
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    c = conn()
    cur = c.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS habits (
          habit_id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          category TEXT,
          target_value INTEGER DEFAULT 1,
          target_unit TEXT DEFAULT 'times',
          is_active INTEGER DEFAULT 1,
          created_at TEXT NOT NULL
        );
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS habit_logs (
          log_id INTEGER PRIMARY KEY AUTOINCREMENT,
          date TEXT NOT NULL,
          habit_id INTEGER NOT NULL,
          is_done INTEGER DEFAULT 0,
          memo TEXT,
          updated_at TEXT NOT NULL,
          UNIQUE(date, habit_id),
          FOREIGN KEY(habit_id) REFERENCES habits(habit_id)
        );
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS mood_logs (
          date TEXT PRIMARY KEY,
          mood_score INTEGER NOT NULL,              -- 1~5
          mood_label TEXT,
          keywords TEXT,                            -- csv
          note TEXT,
          weather_desc TEXT,
          weather_temp REAL,
          tarot_name TEXT,
          tarot_orientation TEXT,                   -- upright / reversed
          tarot_meaning TEXT,
          ai_analysis TEXT,                         -- 감정 분석
          ai_recommendation TEXT,                   -- 활동 추천
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_messages (
          msg_id INTEGER PRIMARY KEY AUTOINCREMENT,
          date TEXT NOT NULL,
          type TEXT NOT NULL,                       -- quote / coach / insight
          content TEXT NOT NULL,
          created_at TEXT NOT NULL,
          UNIQUE(date, type)
        );
        """
    )

    c.commit()
    c.close()


def seed_habits_if_empty():
    c = conn()
    cur = c.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM habits;")
    if cur.fetchone()["c"] == 0:
        now = dt.datetime.now().isoformat(timespec="seconds")
        defaults = [
            ("물 마시기", "건강", 8, "cups"),
            ("스트레칭", "건강", 10, "minutes"),
            ("산책", "건강", 20, "minutes"),
            ("명상", "마음", 5, "minutes"),
        ]
        cur.executemany(
            """
            INSERT INTO habits (name, category, target_value, target_unit, is_active, created_at)
            VALUES (?, ?, ?, ?, 1, ?);
            """,
            [(n, cat, tv, tu, now) for (n, cat, tv, tu) in defaults],
        )
        c.commit()
    c.close()


def fetch_active_habits() -> List[sqlite3.Row]:
    c = conn()
    cur = c.cursor()
    cur.execute("SELECT * FROM habits WHERE is_active=1 ORDER BY habit_id ASC;")
    rows = cur.fetchall()
    c.close()
    return rows


def fetch_all_habits() -> List[sqlite3.Row]:
    c = conn()
    cur = c.cursor()
    cur.execute("SELECT * FROM habits ORDER BY is_active DESC, habit_id ASC;")
    rows = cur.fetchall()
    c.close()
    return rows


def upsert_habit_log(date: str, habit_id: int, is_done: int, memo: str):
    c = conn()
    cur = c.cursor()
    now = dt.datetime.now().isoformat(timespec="seconds")
    cur.execute(
        """
        INSERT INTO habit_logs (date, habit_id, is_done, memo, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(date, habit_id) DO UPDATE SET
          is_done=excluded.is_done,
          memo=excluded.memo,
          updated_at=excluded.updated_at;
        """,
        (date, habit_id, is_done, memo, now),
    )
    c.commit()
    c.close()


def fetch_habit_logs_for_date(date: str) -> Dict[int, sqlite3.Row]:
    c = conn()
    cur = c.cursor()
    cur.execute("SELECT * FROM habit_logs WHERE date=?;", (date,))
    rows = cur.fetchall()
    c.close()
    return {r["habit_id"]: r for r in rows}


def habit_completion_rate(date: str) -> Tuple[int, int, int]:
    habits = fetch_active_habits()
    logs = fetch_habit_logs_for_date(date)
    total = len(habits)
    done = 0
    for h in habits:
        r = logs.get(h["habit_id"])
        if r and r["is_done"] == 1:
            done += 1
    rate = pct(done, total)
    return done, total, rate


def upsert_mood_log(payload: Dict[str, Any]):
    c = conn()
    cur = c.cursor()
    now = dt.datetime.now().isoformat(timespec="seconds")

    payload = dict(payload)
    payload.setdefault("created_at", now)
    payload["updated_at"] = now

    cur.execute(
        """
        INSERT INTO mood_logs
        (date, mood_score, mood_label, keywords, note,
         weather_desc, weather_temp,
         tarot_name, tarot_orientation, tarot_meaning,
         ai_analysis, ai_recommendation,
         created_at, updated_at)
        VALUES
        (:date, :mood_score, :mood_label, :keywords, :note,
         :weather_desc, :weather_temp,
         :tarot_name, :tarot_orientation, :tarot_meaning,
         :ai_analysis, :ai_recommendation,
         :created_at, :updated_at)
        ON CONFLICT(date) DO UPDATE SET
          mood_score=excluded.mood_score,
          mood_label=excluded.mood_label,
          keywords=excluded.keywords,
          note=excluded.note,
          weather_desc=excluded.weather_desc,
          weather_temp=excluded.weather_temp,
          tarot_name=excluded.tarot_name,
          tarot_orientation=excluded.tarot_orientation,
          tarot_meaning=excluded.tarot_meaning,
          ai_analysis=excluded.ai_analysis,
          ai_recommendation=excluded.ai_recommendation,
          updated_at=excluded.updated_at;
        """,
        payload,
    )
    c.commit()
    c.close()


def load_mood_log(date: str) -> Optional[sqlite3.Row]:
    c = conn()
    cur = c.cursor()
    cur.execute("SELECT * FROM mood_logs WHERE date=?;", (date,))
    row = cur.fetchone()
    c.close()
    return row


def save_ai_message(date: str, msg_type: str, content: str):
    c = conn()
    cur = c.cursor()
    now = dt.datetime.now().isoformat(timespec="seconds")
    cur.execute(
        """
        INSERT INTO ai_messages (date, type, content, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(date, type) DO UPDATE SET
          content=excluded.content,
          created_at=excluded.created_at;
        """,
        (date, msg_type, content, now),
    )
    c.commit()
    c.close()


def load_ai_message(date: str, msg_type: str) -> Optional[str]:
    c = conn()
    cur = c.cursor()
    cur.execute("SELECT content FROM ai_messages WHERE date=? AND type=?;", (date, msg_type))
    row = cur.fetchone()
    c.close()
    return row["content"] if row else None


def fetch_range_table(start_date: str, end_date: str) -> pd.DataFrame:
    c = conn()
    q = """
    SELECT
      m.date,
      m.mood_score, m.mood_label, m.keywords,
      m.weather_desc, m.weather_temp,
      m.tarot_name, m.tarot_orientation,
      substr(m.ai_recommendation, 1, 120) as ai_reco_preview
    FROM mood_logs m
    WHERE m.date BETWEEN ? AND ?
    ORDER BY m.date DESC;
    """
    df = pd.read_sql_query(q, c, params=(start_date, end_date))
    c.close()
    return df


# =========================
# External APIs
# =========================
# OpenWeatherMap
@st.cache_data(ttl=600)
def geocode_city(city: str, api_key: str) -> Optional[Tuple[float, float, str]]:
    url = "https://api.openweathermap.org/geo/1.0/direct"
    r = requests.get(url, params={"q": city, "limit": 1, "appid": api_key}, timeout=10)
    r.raise_for_status()
    data = r.json()
    if not data:
        return None
    lat, lon = data[0]["lat"], data[0]["lon"]
    name = data[0].get("name", city)
    country = data[0].get("country", "")
    return lat, lon, f"{name} {country}".strip()


@st.cache_data(ttl=600)
def fetch_weather(lat: float, lon: float, api_key: str) -> Dict[str, Any]:
    url = "https://api.openweathermap.org/data/2.5/weather"
    r = requests.get(
        url,
        params={"lat": lat, "lon": lon, "appid": api_key, "units": "metric", "lang": "kr"},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def parse_weather(w: Dict[str, Any]) -> Dict[str, Any]:
    main = w.get("main", {})
    wlist = w.get("weather", [])
    desc = wlist[0].get("description", "") if wlist else ""
    icon = wlist[0].get("icon", "") if wlist else ""
    temp = main.get("temp", None)
    feels = main.get("feels_like", None)
    humidity = main.get("humidity", None)
    return {"desc": desc, "icon": icon, "temp": temp, "feels": feels, "humidity": humidity}


def weather_keywords(desc: str, temp: Optional[float]) -> List[str]:
    keys = []
    d = (desc or "").lower()
    if any(k in d for k in ["비", "소나기", "rain", "drizzle", "뇌우"]):
        keys.append("🌧️ 비/젖음")
    if any(k in d for k in ["눈", "snow", "sleet"]):
        keys.append("❄️ 눈/추움")
    if any(k in d for k in ["안개", "mist", "fog", "haze"]):
        keys.append("🌫️ 안개/흐림")
    if "구름" in d or "cloud" in d:
        keys.append("☁️ 구름")
    if temp is not None:
        if temp >= 30:
            keys.append("🥵 더움")
        elif temp <= 2:
            keys.append("🥶 추움")
        else:
            keys.append("🌤️ 무난")
    return keys[:5]


# Tarot API (tarotapi.dev)
@st.cache_data(ttl=60)
def tarot_random_card() -> Dict[str, Any]:
    url = "https://tarotapi.dev/api/v1/cards/random"
    r = requests.get(url, params={"n": 1}, timeout=12)
    r.raise_for_status()
    data = r.json()
    card = (data.get("cards") or [{}])[0]
    return card


def pick_tarot_with_orientation() -> Dict[str, Any]:
    card = tarot_random_card()
    orientation = "upright" if random.random() < 0.72 else "reversed"
    meaning = card.get("meaning_up") if orientation == "upright" else card.get("meaning_rev")
    return {
        "name": card.get("name", "Unknown"),
        "name_short": card.get("name_short", ""),
        "orientation": orientation,
        "meaning": meaning or "",
        "desc": card.get("desc", ""),
        "type": card.get("type", ""),
        "value": card.get("value", ""),
    }


# ZenQuotes (Quote of the day)
@st.cache_data(ttl=60 * 60)
def zenquotes_today() -> Optional[Dict[str, str]]:
    # https://zenquotes.io/api/today returns array of {q,a,h}
    r = requests.get("https://zenquotes.io/api/today", timeout=12)
    r.raise_for_status()
    arr = r.json()
    if not arr:
        return None
    return {"quote": arr[0].get("q", ""), "author": arr[0].get("a", "")}


# OpenAI (Chat Completions REST)
def openai_chat(api_key: str, model: str, system: str, user: str, temperature: float = 0.7) -> str:
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "temperature": temperature,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=40)
    r.raise_for_status()
    data = r.json()
    return data["choices"][0]["message"]["content"]


# =========================
# UX / Sidebar
# =========================
def sidebar():
    st.sidebar.markdown("### 설정")

    # Secrets/env default
    default_openai = st.secrets.get("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY", ""))
    default_owm = st.secrets.get("OPENWEATHER_API_KEY", os.getenv("OPENWEATHER_API_KEY", ""))

    st.session_state.setdefault("openai_key", default_openai)
    st.session_state.setdefault("owm_key", default_owm)
    st.session_state.setdefault("city", "Seoul")
    st.session_state.setdefault("openai_model", "gpt-4o-mini")
    st.session_state.setdefault("debug", False)

    st.session_state.openai_key = st.sidebar.text_input("OpenAI API Key", value=st.session_state.openai_key, type="password")
    st.session_state.owm_key = st.sidebar.text_input("OpenWeatherMap API Key", value=st.session_state.owm_key, type="password")
    st.session_state.city = st.sidebar.text_input("도시", value=st.session_state.city)
    st.session_state.openai_model = st.sidebar.text_input("OpenAI 모델", value=st.session_state.openai_model)
    st.session_state.debug = st.sidebar.toggle("디버그 모드", value=st.session_state.debug)

    st.sidebar.divider()
    if st.sidebar.button("기본 습관 템플릿 채우기(처음 1회)"):
        seed_habits_if_empty()
        st.sidebar.success("완료!")

    st.sidebar.caption("API 키는 세션에만 저장(코드에 하드코딩 금지).")


# =========================
# AI Prompt (감정 분석 + 활동 추천)
# =========================
def build_emotion_tarot_prompt(
    date: str,
    mood_score: int,
    mood_label: str,
    keywords_csv: str,
    note: str,
    weather_desc: str,
    weather_temp: Optional[float],
    tarot_name: str,
    tarot_orientation: str,
    tarot_meaning: str,
    habit_done: int,
    habit_total: int,
    habit_rate: int,
) -> str:
    return f"""
날짜: {date}

[오늘 기분 체크인]
- 기분 점수(1~5): {mood_score}
- 기분 라벨: {mood_label}
- 키워드(사용자): {keywords_csv or "(없음)"}
- 한 줄 일기: {note or "(없음)"}

[날씨]
- 설명: {weather_desc or "(없음)"}
- 온도: {weather_temp if weather_temp is not None else "(알 수 없음)"}°C

[타로 카드]
- 카드: {tarot_name}
- 방향: {tarot_orientation}
- 해석 키워드: {tarot_meaning}

[습관 진행률]
- 완료: {habit_done}/{habit_total} ({habit_rate}%)

요청:
1) 위 정보로 "감정 분석"을 5~7문장으로: (현재 감정 상태 + 원인 추정 + 주의할 함정 1개)
2) 이어서 "오늘의 활동 추천" 5개를 bullet로: (실내/실외 섞고, 10~25분짜리 위주)
3) 마지막에 "아주 작은 다음 행동" 1개를 한 문장으로.
규칙:
- 죄책감/비난 금지, 과장 칭찬 금지
- 한국어
- 전체 900자 이내
""".strip()


# =========================
# Pages
# =========================
def page_today():
    date = iso_today()

    # Habit completion drives background
    done, total, rate = habit_completion_rate(date)
    bg_top, bg_bottom = completion_to_bg_gradient(rate)
    inject_ios_css(bg_top, bg_bottom)

    st.markdown(f"##  오늘 · {date}")
    st.caption("감정 체크인 → 날씨/타로 → AI가 오늘의 컨디션과 행동을 추천해줘요.")

    # Top KPIs (minimal)
    c1, c2, c3 = st.columns([1, 1, 2])
    c1.metric("습관 완료", f"{done}/{total}", f"{rate}%")
    c2.metric("오늘 기분", "—" if not load_mood_log(date) else f"{load_mood_log(date)['mood_score']}/5")
    c3.metric("오늘의 테마", "잔잔하게 정리하기" if rate < 50 else "가볍게 확장하기")

    # Load existing mood log
    existing = load_mood_log(date)

    # Weather block (quiet)
    weather_desc, weather_temp, weather_city = "", None, st.session_state.get("city", "Seoul")
    w_keywords: List[str] = []
    if st.session_state.get("owm_key"):
        try:
            geo = geocode_city(weather_city, st.session_state.owm_key)
            if geo:
                lat, lon, label = geo
                w = fetch_weather(lat, lon, st.session_state.owm_key)
                wp = parse_weather(w)
                weather_desc = wp.get("desc", "")
                weather_temp = wp.get("temp", None)
                w_keywords = weather_keywords(weather_desc, weather_temp)
        except Exception as e:
            if st.session_state.get("debug"):
                st.exception(e)

    # Quote of the day
    quote = None
    try:
        quote = zenquotes_today()
        if quote and quote.get("quote"):
            save_ai_message(date, "quote", f"“{quote['quote']}” — {quote.get('author','')}".strip())
    except Exception:
        pass

    # Layout: 2 columns
    left, right = st.columns([1.05, 0.95], gap="large")

    with left:
        card_open("감정 일기", "기분·키워드를 적어두면 AI가 해석을 더 잘해요.")
        mood_map = {1: "😣 힘듦", 2: "😕 애매", 3: "🙂 보통", 4: "😄 좋음", 5: "🤩 최고"}
        default_mood = int(existing["mood_score"]) if existing else 3
        mood_score = st.slider("기분 점수", 1, 5, default_mood, format="%d")
        mood_label = st.selectbox("기분 라벨", list(mood_map.values()), index=list(mood_map.keys()).index(mood_score))
        default_keywords = (existing["keywords"] or "") if existing else ""
        keywords_csv = st.text_input("키워드(쉼표로 구분)", value=default_keywords, placeholder="예: 지침, 기대, 불안")
        default_note = (existing["note"] or "") if existing else ""
        note = st.text_area("한 줄 일기", value=default_note, height=90, placeholder="오늘 어떤 일이 있었나요?")

        # Save mood (without AI yet)
        if st.button("감정 일기 저장", type="primary"):
            upsert_mood_log(
                {
                    "date": date,
                    "mood_score": mood_score,
                    "mood_label": mood_label,
                    "keywords": keywords_csv.strip(),
                    "note": note.strip(),
                    "weather_desc": weather_desc,
                    "weather_temp": weather_temp,
                    "tarot_name": existing["tarot_name"] if existing else None,
                    "tarot_orientation": existing["tarot_orientation"] if existing else None,
                    "tarot_meaning": existing["tarot_meaning"] if existing else None,
                    "ai_analysis": existing["ai_analysis"] if existing else None,
                    "ai_recommendation": existing["ai_recommendation"] if existing else None,
                }
            )
            st.success("저장했어요.")
            st.rerun()

        st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
        st.markdown("**오늘의 날씨 키워드**", unsafe_allow_html=True)
        if w_keywords:
            st.markdown("".join([f"<span class='pill'>{k}</span>" for k in w_keywords]), unsafe_allow_html=True)
        else:
            st.markdown("<span class='pill'>날씨 정보 없음</span>", unsafe_allow_html=True)
        card_close()

        st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

        # Habits: compact
        habits = fetch_active_habits()
        logs = fetch_habit_logs_for_date(date)

        card_open("습관 체크", "토글만 딱. 메모는 필요할 때만.")
        if not habits:
            st.info("활성 습관이 없어요. '설정' 탭에서 추가해줘.")
        else:
            for h in habits:
                hid = h["habit_id"]
                r = logs.get(hid)
                is_done = bool(r["is_done"]) if r else False
                memo = (r["memo"] or "") if r else ""

                row = st.columns([0.22, 0.78])
                with row[0]:
                    new_done = st.toggle("", value=is_done, key=f"h_done_{hid}")
                with row[1]:
                    st.markdown(f"**{h['name']}** <span class='ios-subtle'>· {h['target_value']} {h['target_unit']}</span>", unsafe_allow_html=True)
                    with st.expander("메모", expanded=False):
                        new_memo = st.text_input("메모", value=memo, key=f"h_memo_{hid}", label_visibility="collapsed")
                        if (new_done != is_done) or (new_memo != memo):
                            upsert_habit_log(date, hid, 1 if new_done else 0, new_memo)
                    if (new_done != is_done) and ("h_memo_" not in st.session_state):
                        upsert_habit_log(date, hid, 1 if new_done else 0, memo)

            # refresh completion
            done, total, rate = habit_completion_rate(date)
            st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
            st.progress(rate / 100.0, text=f"오늘 완성률 {rate}%")
        card_close()

    with right:
        # Quote card
        qtext = load_ai_message(date, "quote")
        card_open("오늘의 명언", "짧게 읽고, 오늘의 톤을 잡아봐요.")
        if qtext:
            st.markdown(f"**{qtext}**")
        else:
            st.markdown("오늘의 명언을 불러오지 못했어요.")
        st.caption("Inspirational quotes provided by ZenQuotes API")
        card_close()

        st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

        # Tarot + AI reading
        card_open("타로 리딩 · 감정 분석 + 활동 추천", "카드 한 장으로 오늘의 방향을 가볍게 잡아줘요.")
        existing = load_mood_log(date)

        if st.button("타로 카드 뽑기", use_container_width=True):
            try:
                t = pick_tarot_with_orientation()
                # merge into mood log (create if missing)
                base = {
                    "date": date,
                    "mood_score": int(existing["mood_score"]) if existing else 3,
                    "mood_label": (existing["mood_label"] if existing else "🙂 보통"),
                    "keywords": (existing["keywords"] if existing else ""),
                    "note": (existing["note"] if existing else ""),
                    "weather_desc": weather_desc,
                    "weather_temp": weather_temp,
                    "tarot_name": t["name"],
                    "tarot_orientation": t["orientation"],
                    "tarot_meaning": t["meaning"],
                    "ai_analysis": (existing["ai_analysis"] if existing else None),
                    "ai_recommendation": (existing["ai_recommendation"] if existing else None),
                }
                upsert_mood_log(base)
                st.success("카드를 뽑았어요.")
                st.rerun()
            except Exception as e:
                st.error("타로 API 호출에 실패했어요.")
                if st.session_state.get("debug"):
                    st.exception(e)

        existing = load_mood_log(date)
        if existing and (existing["tarot_name"] or ""):
            ori = "정방향" if existing["tarot_orientation"] == "upright" else "역방향"
            st.markdown(f"**🃏 {existing['tarot_name']} · {ori}**")
            if existing["tarot_meaning"]:
                st.markdown(f"<span class='pill'>의미</span> {existing['tarot_meaning']}", unsafe_allow_html=True)
        else:
            st.markdown("<span class='pill'>아직 카드 없음</span>", unsafe_allow_html=True)

        st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

        # Generate AI reading
        need_openai = not bool(st.session_state.get("openai_key"))
        if need_openai:
            st.info("OpenAI API Key를 사이드바에 넣으면 AI 리딩을 생성할 수 있어요.")

        if st.button("AI 리딩 생성", type="primary", use_container_width=True, disabled=need_openai):
            try:
                existing = load_mood_log(date)  # refresh
                if not existing:
                    st.warning("먼저 감정 일기를 저장해줘.")
                elif not existing["tarot_name"]:
                    st.warning("먼저 타로 카드를 뽑아줘.")
                else:
                    done, total, rate = habit_completion_rate(date)
                    prompt = build_emotion_tarot_prompt(
                        date=date,
                        mood_score=int(existing["mood_score"]),
                        mood_label=existing["mood_label"] or "",
                        keywords_csv=existing["keywords"] or "",
                        note=existing["note"] or "",
                        weather_desc=existing["weather_desc"] or weather_desc,
                        weather_temp=existing["weather_temp"] if existing["weather_temp"] is not None else weather_temp,
                        tarot_name=existing["tarot_name"] or "",
                        tarot_orientation=existing["tarot_orientation"] or "",
                        tarot_meaning=existing["tarot_meaning"] or "",
                        habit_done=done, habit_total=total, habit_rate=rate,
                    )

                    system = (
                        "너는 과장하지 않는 감정 코치이자 타로 리더다. "
                        "타로를 '운명 단정'이 아니라 '성찰 도구'로 다룬다. "
                        "사용자를 비난하거나 죄책감을 유발하지 않는다."
                    )

                    with st.spinner("AI가 리딩을 생성 중..."):
                        out = openai_chat(
                            api_key=st.session_state.openai_key,
                            model=st.session_state.openai_model,
                            system=system,
                            user=prompt,
                            temperature=0.7,
                        )

                    # split into analysis + recommendation loosely
                    # (간단: 첫 줄부터 '활동 추천' 이전까지를 분석, 이후를 추천)
                    txt = out.strip()
                    analysis = txt
                    reco = ""
                    if "활동 추천" in txt:
                        parts = txt.split("활동 추천", 1)
                        analysis = parts[0].strip()
                        reco = ("활동 추천" + parts[1]).strip()

                    upsert_mood_log(
                        {
                            "date": date,
                            "mood_score": int(existing["mood_score"]),
                            "mood_label": existing["mood_label"],
                            "keywords": existing["keywords"],
                            "note": existing["note"],
                            "weather_desc": existing["weather_desc"],
                            "weather_temp": existing["weather_temp"],
                            "tarot_name": existing["tarot_name"],
                            "tarot_orientation": existing["tarot_orientation"],
                            "tarot_meaning": existing["tarot_meaning"],
                            "ai_analysis": analysis,
                            "ai_recommendation": reco if reco else txt,
                        }
                    )
                    st.success("완료!")
                    st.rerun()

            except Exception as e:
                st.error("AI 호출에 실패했어요. 키/모델/네트워크를 확인해줘.")
                if st.session_state.get("debug"):
                    st.exception(e)

        # Show saved AI reading
        existing = load_mood_log(date)
        if existing and (existing["ai_recommendation"] or existing["ai_analysis"]):
            st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
            with st.expander("📖 저장된 AI 리딩 보기", expanded=True):
                if existing["ai_analysis"]:
                    st.markdown("**감정 분석**")
                    st.write(existing["ai_analysis"])
                if existing["ai_recommendation"]:
                    st.markdown("**활동 추천**")
                    st.write(existing["ai_recommendation"])

        card_close()


def page_history():
    date = iso_today()
    done, total, rate = habit_completion_rate(date)
    bg_top, bg_bottom = completion_to_bg_gradient(rate)
    inject_ios_css(bg_top, bg_bottom)

    st.markdown("## 기록")
    st.caption("감정·타로·추천을 날짜별로 간단하게 봐요.")

    col1, col2 = st.columns([1, 1])
    with col1:
        days = st.selectbox("기간", [7, 14, 30, 60, 90], index=2)
    with col2:
        chosen = st.date_input("날짜 선택", value=dt.date.today())

    end = dt.date.today()
    start = end - dt.timedelta(days=days - 1)

    card_open("선택 날짜 상세", chosen.isoformat())
    row = load_mood_log(chosen.isoformat())
    if not row:
        st.info("이 날의 감정 기록이 없어요.")
    else:
        st.markdown(f"**기분**: {row['mood_score']}/5 · {row['mood_label']}")
        if row["keywords"]:
            st.markdown("".join([f"<span class='pill'>{k.strip()}</span>" for k in row["keywords"].split(",") if k.strip()]), unsafe_allow_html=True)
        st.markdown(f"**한 줄 일기**: {row['note'] or '-'}")
        st.markdown(f"**날씨**: {row['weather_desc'] or '-'} / {row['weather_temp'] if row['weather_temp'] is not None else '-'}°C")
        if row["tarot_name"]:
            ori = "정방향" if row["tarot_orientation"] == "upright" else "역방향"
            st.markdown(f"**타로**: {row['tarot_name']} · {ori}")
            st.markdown(f"<span class='pill'>의미</span> {row['tarot_meaning'] or '-'}", unsafe_allow_html=True)

        if row["ai_recommendation"] or row["ai_analysis"]:
            with st.expander("AI 리딩", expanded=False):
                if row["ai_analysis"]:
                    st.markdown("**감정 분석**")
                    st.write(row["ai_analysis"])
                if row["ai_recommendation"]:
                    st.markdown("**활동 추천**")
                    st.write(row["ai_recommendation"])
    card_close()

    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

    card_open(f"최근 {days}일 요약", f"{start.isoformat()} ~ {end.isoformat()}")
    df = fetch_range_table(start.isoformat(), end.isoformat())
    if df.empty:
        st.info("기록이 아직 충분하지 않아요.")
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)
        csv = df.to_csv(index=False).encode("utf-8-sig")
        st.download_button("CSV 내보내기", data=csv, file_name=f"mood_tarot_{start}_{end}.csv", mime="text/csv")
    card_close()


def page_settings():
    date = iso_today()
    done, total, rate = habit_completion_rate(date)
    bg_top, bg_bottom = completion_to_bg_gradient(rate)
    inject_ios_css(bg_top, bg_bottom)

    st.markdown("## 설정")
    st.caption("습관을 깔끔하게 관리해요. 삭제 대신 비활성화 추천.")

    rows = fetch_all_habits()

    # Add habit (minimal)
    card_open("습관 추가", "짧게 추가하고, 필요하면 나중에 바꿔요.")
    c1, c2, c3 = st.columns([1.4, 1, 1])
    with c1:
        name = st.text_input("이름", value="", placeholder="예: 독서")
    with c2:
        target_value = st.number_input("목표", min_value=1, max_value=10000, value=20, step=1)
    with c3:
        target_unit = st.selectbox("단위", ["minutes", "times", "cups", "pages"], index=0)

    category = st.text_input("카테고리", value="기타")
    if st.button("추가", type="primary"):
        if not name.strip():
            st.warning("이름은 필수예요.")
        else:
            c = conn()
            cur = c.cursor()
            now = dt.datetime.now().isoformat(timespec="seconds")
            cur.execute(
                """
                INSERT INTO habits (name, category, target_value, target_unit, is_active, created_at)
                VALUES (?, ?, ?, ?, 1, ?);
                """,
                (name.strip(), category.strip(), int(target_value), target_unit, now),
            )
            c.commit()
            c.close()
            st.success("추가했어요.")
            st.rerun()
    card_close()

    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

    card_open("습관 목록", "토글로 활성/비활성만 빠르게.")
    if not rows:
        st.info("습관이 없어요.")
    else:
        for h in rows:
            cols = st.columns([1.2, 1.0, 0.8])
            with cols[0]:
                st.markdown(f"**{h['name']}**  <span class='ios-subtle'>· {h['category'] or '기타'}</span>", unsafe_allow_html=True)
                st.markdown(f"<span class='ios-subtle'>목표: {h['target_value']} {h['target_unit']}</span>", unsafe_allow_html=True)
            with cols[1]:
                new_active = st.toggle("활성", value=bool(h["is_active"]), key=f"active_{h['habit_id']}")
            with cols[2]:
                if st.button("이름/목표 수정", key=f"edit_{h['habit_id']}"):
                    st.session_state[f"edit_open_{h['habit_id']}"] = True

            if bool(h["is_active"]) != bool(new_active):
                c = conn()
                cur = c.cursor()
                cur.execute("UPDATE habits SET is_active=? WHERE habit_id=?;", (1 if new_active else 0, h["habit_id"]))
                c.commit()
                c.close()
                st.rerun()

            if st.session_state.get(f"edit_open_{h['habit_id']}", False):
                with st.form(key=f"form_{h['habit_id']}"):
                    nn = st.text_input("이름", value=h["name"])
                    nc = st.text_input("카테고리", value=h["category"] or "")
                    ntv = st.number_input("목표", min_value=1, max_value=10000, value=int(h["target_value"]), step=1)
                    ntu = st.selectbox("단위", ["minutes", "times", "cups", "pages"],
                                       index=["minutes", "times", "cups", "pages"].index(h["target_unit"]))
                    s1, s2 = st.columns(2)
                    save = s1.form_submit_button("저장", type="primary")
                    cancel = s2.form_submit_button("취소")
                    if cancel:
                        st.session_state[f"edit_open_{h['habit_id']}"] = False
                        st.rerun()
                    if save:
                        if not nn.strip():
                            st.warning("이름은 필수예요.")
                        else:
                            c = conn()
                            cur = c.cursor()
                            cur.execute(
                                """
                                UPDATE habits
                                SET name=?, category=?, target_value=?, target_unit=?
                                WHERE habit_id=?;
                                """,
                                (nn.strip(), nc.strip(), int(ntv), ntu, h["habit_id"]),
                            )
                            c.commit()
                            c.close()
                            st.session_state[f"edit_open_{h['habit_id']}"] = False
                            st.success("저장했어요.")
                            st.rerun()

            st.markdown("<hr style='border:none;border-top:1px solid rgba(0,0,0,0.06);margin:10px 0;'>", unsafe_allow_html=True)

    card_close()


# =========================
# Main
# =========================
def main():
    init_db()
    seed_habits_if_empty()
    sidebar()

    # default bg (if page doesn't inject yet)
    date = iso_today()
    done, total, rate = habit_completion_rate(date)
    bg_top, bg_bottom = completion_to_bg_gradient(rate)
    inject_ios_css(bg_top, bg_bottom)

    st.markdown("# AI 감정·습관 트래커")
    tabs = st.tabs(["오늘", "기록", "설정"])

    with tabs[0]:
        page_today()
    with tabs[1]:
        page_history()
    with tabs[2]:
        page_settings()


if __name__ == "__main__":
    main()
