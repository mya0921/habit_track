import os
import json
import math
import sqlite3
import datetime as dt
from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Tuple

import requests
import pandas as pd
import streamlit as st


# =========================
# App Config
# =========================
st.set_page_config(
    page_title="AI 습관 트래커",
    page_icon="✅",
    layout="wide",
)

APP_TITLE = "AI 습관 트래커"
DB_PATH = "habit_tracker.db"


# =========================
# Utilities
# =========================
def today_local() -> str:
    # Streamlit Cloud 등에서도 서버 시간이 UTC일 수 있으므로, 간단히 "오늘"은 서버 기준.
    # 필요하면 사용자 타임존 입력 받아 보정 가능.
    return dt.date.today().isoformat()


def safe_int(x, default=0):
    try:
        return int(x)
    except Exception:
        return default


def clamp(n: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, n))


def pct(numer: float, denom: float) -> int:
    if denom <= 0:
        return 0
    return int(round((numer / denom) * 100))


# =========================
# DB Layer (SQLite)
# =========================
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS habits (
            habit_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT,
            target_value INTEGER DEFAULT 1,
            target_unit TEXT DEFAULT 'times',
            difficulty INTEGER DEFAULT 3,
            frequency_type TEXT DEFAULT 'daily', -- daily / weekly
            frequency_goal INTEGER DEFAULT 0,     -- weekly일 때 목표 횟수
            created_at TEXT NOT NULL,
            is_active INTEGER DEFAULT 1
        );
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS logs (
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
        CREATE TABLE IF NOT EXISTS ai_messages (
            msg_id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            type TEXT NOT NULL,   -- coach / insight
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(date, type)
        );
        """
    )

    conn.commit()
    conn.close()


def seed_default_habits_if_empty():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM habits;")
    c = cur.fetchone()["c"]
    if c == 0:
        now = dt.datetime.now().isoformat(timespec="seconds")
        defaults = [
            ("물 마시기", "건강", 8, "cups", 2, "daily", 0),
            ("스트레칭", "건강", 10, "minutes", 2, "daily", 0),
            ("영어 공부", "공부", 20, "minutes", 3, "daily", 0),
            ("명상", "마음", 5, "minutes", 2, "daily", 0),
        ]
        cur.executemany(
            """
            INSERT INTO habits
            (name, category, target_value, target_unit, difficulty, frequency_type, frequency_goal, created_at, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            [(n, cat, tv, tu, d, ft, fg, now) for (n, cat, tv, tu, d, ft, fg) in defaults],
        )
        conn.commit()
    conn.close()


def fetch_active_habits() -> List[sqlite3.Row]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT * FROM habits
        WHERE is_active = 1
        ORDER BY habit_id ASC;
        """
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def fetch_all_habits() -> List[sqlite3.Row]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM habits ORDER BY is_active DESC, habit_id ASC;")
    rows = cur.fetchall()
    conn.close()
    return rows


def upsert_log(date: str, habit_id: int, is_done: int, memo: str):
    conn = get_conn()
    cur = conn.cursor()
    now = dt.datetime.now().isoformat(timespec="seconds")
    cur.execute(
        """
        INSERT INTO logs (date, habit_id, is_done, memo, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(date, habit_id) DO UPDATE SET
            is_done=excluded.is_done,
            memo=excluded.memo,
            updated_at=excluded.updated_at;
        """,
        (date, habit_id, is_done, memo, now),
    )
    conn.commit()
    conn.close()


def fetch_logs_for_date(date: str) -> Dict[int, sqlite3.Row]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT * FROM logs
        WHERE date = ?;
        """,
        (date,),
    )
    rows = cur.fetchall()
    conn.close()
    return {r["habit_id"]: r for r in rows}


def fetch_logs_range(start_date: str, end_date: str) -> pd.DataFrame:
    conn = get_conn()
    query = """
        SELECT l.date, l.habit_id, l.is_done, l.memo, l.updated_at, h.name, h.category
        FROM logs l
        JOIN habits h ON h.habit_id = l.habit_id
        WHERE l.date BETWEEN ? AND ?
        ORDER BY l.date DESC, l.habit_id ASC;
    """
    df = pd.read_sql_query(query, conn, params=(start_date, end_date))
    conn.close()
    return df


def save_ai_message(date: str, msg_type: str, content: str):
    conn = get_conn()
    cur = conn.cursor()
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
    conn.commit()
    conn.close()


def load_ai_message(date: str, msg_type: str) -> Optional[str]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT content FROM ai_messages
        WHERE date = ? AND type = ?;
        """,
        (date, msg_type),
    )
    row = cur.fetchone()
    conn.close()
    return row["content"] if row else None


def create_habit(
    name: str,
    category: str,
    target_value: int,
    target_unit: str,
    difficulty: int,
    frequency_type: str,
    frequency_goal: int,
):
    conn = get_conn()
    cur = conn.cursor()
    now = dt.datetime.now().isoformat(timespec="seconds")
    cur.execute(
        """
        INSERT INTO habits (name, category, target_value, target_unit, difficulty, frequency_type, frequency_goal, created_at, is_active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1);
        """,
        (name, category, target_value, target_unit, difficulty, frequency_type, frequency_goal, now),
    )
    conn.commit()
    conn.close()


def update_habit(habit_id: int, **fields):
    allowed = {
        "name", "category", "target_value", "target_unit", "difficulty",
        "frequency_type", "frequency_goal", "is_active"
    }
    sets = []
    params = []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k}=?")
            params.append(v)
    if not sets:
        return
    params.append(habit_id)

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"UPDATE habits SET {', '.join(sets)} WHERE habit_id=?;", params)
    conn.commit()
    conn.close()


# =========================
# Weather (OpenWeatherMap)
# =========================
@st.cache_data(ttl=600)
def geocode_city(city: str, api_key: str) -> Optional[Tuple[float, float, str]]:
    url = "https://api.openweathermap.org/geo/1.0/direct"
    r = requests.get(url, params={"q": city, "limit": 1, "appid": api_key}, timeout=10)
    r.raise_for_status()
    data = r.json()
    if not data:
        return None
    lat = data[0]["lat"]
    lon = data[0]["lon"]
    name = data[0].get("name", city)
    country = data[0].get("country", "")
    label = f"{name} {country}".strip()
    return lat, lon, label


@st.cache_data(ttl=600)
def fetch_current_weather(lat: float, lon: float, api_key: str) -> Dict[str, Any]:
    url = "https://api.openweathermap.org/data/2.5/weather"
    r = requests.get(url, params={"lat": lat, "lon": lon, "appid": api_key, "units": "metric", "lang": "kr"}, timeout=10)
    r.raise_for_status()
    return r.json()


def weather_summary(w: Dict[str, Any]) -> Dict[str, Any]:
    main = w.get("main", {})
    weather_list = w.get("weather", [])
    wind = w.get("wind", {})
    desc = weather_list[0].get("description", "") if weather_list else ""
    icon = weather_list[0].get("icon", "") if weather_list else ""
    temp = main.get("temp")
    feels = main.get("feels_like")
    humidity = main.get("humidity")
    wind_speed = wind.get("speed")
    return {
        "desc": desc,
        "icon": icon,
        "temp": temp,
        "feels": feels,
        "humidity": humidity,
        "wind_speed": wind_speed,
    }


def routine_reco_from_weather(desc: str, temp: Optional[float]) -> str:
    d = (desc or "").lower()
    t = temp if temp is not None else 20.0

    rainy = any(k in d for k in ["비", "소나기", "rain", "drizzle", "thunderstorm", "뇌우"])
    snowy = any(k in d for k in ["눈", "snow", "sleet"])
    foggy = any(k in d for k in ["안개", "mist", "fog", "haze"])
    windy = any(k in d for k in ["강풍", "wind", "gale"])

    if rainy or snowy:
        return "🌧️/❄️ 날씨가 좋지 않아요. **실내 대체 루틴** 추천: 스트레칭 10분 + 스쿼트 20회 + 정리 5분."
    if t >= 30:
        return "🥵 더워요. **강도 조절** 추천: 실외 대신 실내 유산소(제자리 걷기 10~15분) + 수분 보충."
    if t <= 0:
        return "🥶 추워요. **짧고 확실한 루틴** 추천: 실내 스트레칭 8분 + 코어 5분(플랭크 3세트)."
    if foggy:
        return "🌫️ 시야가 흐려요. **안전 우선**: 야외 걷기는 짧게, 대신 실내에서 가벼운 움직임 10분."
    if windy:
        return "💨 바람이 세요. **컨디션 보호**: 실외는 짧게, 실내 근력/스트레칭 위주로 진행해요."
    return "🌤️ 무난한 날씨예요. **실외 가능**: 15~30분 산책/가벼운 러닝 또는 야외 스트레칭 추천!"


# =========================
# Dog API
# =========================
def fetch_dog_image_url() -> Optional[str]:
    try:
        r = requests.get("https://dog.ceo/api/breeds/image/random", timeout=10)
        r.raise_for_status()
        data = r.json()
        return data.get("message")
    except Exception:
        return None


# =========================
# OpenAI (REST)
# =========================
def openai_chat_completion(api_key: str, model: str, system: str, user: str, temperature: float = 0.6) -> str:
    """
    OpenAI Chat Completions REST API 호출 (SDK 의존성 없이 requests로).
    """
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=30)
    r.raise_for_status()
    data = r.json()
    return data["choices"][0]["message"]["content"]


# =========================
# Analytics / Streak / Scores
# =========================
def get_last_n_days(n: int) -> List[str]:
    base = dt.date.today()
    return [(base - dt.timedelta(days=i)).isoformat() for i in range(n)][::-1]


def compute_today_stats(date: str, habits: List[sqlite3.Row], logs_map: Dict[int, sqlite3.Row]) -> Dict[str, Any]:
    total = len(habits)
    done = 0
    for h in habits:
        lr = logs_map.get(h["habit_id"])
        if lr and lr["is_done"] == 1:
            done += 1
    rate = pct(done, total)
    return {"total": total, "done": done, "rate": rate}


def compute_overall_streak(threshold_rate: int, days: int = 90) -> Tuple[int, int]:
    """
    전체 스트릭: "해당 날짜의 달성률 >= threshold_rate"가 연속인 일수.
    (최근 streak, 최장 streak) 반환
    """
    habits = fetch_active_habits()
    if not habits:
        return 0, 0

    dates = get_last_n_days(days)
    # oldest->newest
    streaks = []
    cur = 0
    best = 0
    for d in dates:
        logs_map = fetch_logs_for_date(d)
        stats = compute_today_stats(d, habits, logs_map)
        ok = stats["rate"] >= threshold_rate if stats["total"] > 0 else False
        if ok:
            cur += 1
        else:
            best = max(best, cur)
            cur = 0
        streaks.append((d, ok))
    best = max(best, cur)

    # current streak: count from today backwards
    current = 0
    for d in reversed(dates):
        logs_map = fetch_logs_for_date(d)
        stats = compute_today_stats(d, habits, logs_map)
        ok = stats["rate"] >= threshold_rate if stats["total"] > 0 else False
        if ok:
            current += 1
        else:
            break

    return current, best


def compute_ai_coach_score(today_rate: int, memo_quality_hint: int, weather_penalty: int) -> int:
    # 단순 지표: 달성률 기반 + 메모 작성 + 날씨 페널티
    score = today_rate
    score += memo_quality_hint  # 0~10
    score -= weather_penalty    # 0~15
    return int(clamp(score, 0, 100))


def summarize_recent_7days(habits: List[sqlite3.Row]) -> str:
    dates = get_last_n_days(7)
    lines = []
    for d in dates:
        logs_map = fetch_logs_for_date(d)
        stats = compute_today_stats(d, habits, logs_map)
        lines.append(f"- {d}: {stats['done']}/{stats['total']} ({stats['rate']}%)")
    return "\n".join(lines)


def build_today_ai_prompt(
    date: str,
    habits: List[sqlite3.Row],
    logs_map: Dict[int, sqlite3.Row],
    weather_info: Optional[Dict[str, Any]],
    routine_reco: str,
) -> str:
    done_items = []
    todo_items = []
    memos = []

    for h in habits:
        hid = h["habit_id"]
        lr = logs_map.get(hid)
        is_done = (lr["is_done"] == 1) if lr else False
        name = h["name"]
        target = f"{h['target_value']} {h['target_unit']}"
        cat = h["category"] or "기타"
        diff = h["difficulty"]
        memo = (lr["memo"] if lr else "") or ""
        item = f"{name} (카테고리:{cat}, 목표:{target}, 난이도:{diff})"
        if is_done:
            done_items.append(item)
        else:
            todo_items.append(item)
        if memo.strip():
            memos.append(f"- {name}: {memo.strip()}")

    weather_block = "날씨 정보 없음(키 미설정 또는 조회 실패)"
    if weather_info:
        weather_block = (
            f"도시: {weather_info.get('city_label','')}\n"
            f"설명: {weather_info.get('desc','')}\n"
            f"기온: {weather_info.get('temp','')}°C / 체감: {weather_info.get('feels','')}°C\n"
            f"습도: {weather_info.get('humidity','')}% / 바람: {weather_info.get('wind_speed','')}m/s"
        )

    recent7 = summarize_recent_7days(habits)

    user_prompt = f"""
오늘 날짜: {date}

[오늘 완료한 습관]
{chr(10).join(f"- {x}" for x in done_items) if done_items else "- (없음)"}

[오늘 미완료 습관]
{chr(10).join(f"- {x}" for x in todo_items) if todo_items else "- (없음)"}

[사용자 메모]
{chr(10).join(memos) if memos else "- (메모 없음)"}

[날씨]
{weather_block}

[날씨 기반 추천 루틴]
{routine_reco}

[최근 7일 요약]
{recent7}

요청:
1) 오늘의 성취를 인정하면서도, 미완료 습관을 부담 없이 마무리할 수 있게 "다음 행동"을 제안해줘.
2) 피드백은 한국어로, 너무 길지 않게(최대 1200자).
3) 조언은 구체적/실천형(시간, 난이도 조절, 대체 루틴 등)으로.
4) 죄책감 유발 금지. 따뜻하지만 과장된 칭찬도 금지.
"""
    return user_prompt.strip()


def build_insight_ai_prompt(habits: List[sqlite3.Row]) -> str:
    # 최근 30일 로그를 간단히 요약해서 넣기
    end = dt.date.today()
    start = end - dt.timedelta(days=29)
    df = fetch_logs_range(start.isoformat(), end.isoformat())
    if df.empty:
        recent_stats = "최근 30일 로그가 거의 없어서 인사이트가 제한적이야."
    else:
        # 습관별 성공률
        g = df.groupby("name")["is_done"].mean().sort_values(ascending=False)
        top = "\n".join([f"- {idx}: {int(round(val*100))}%" for idx, val in g.items()])
        recent_stats = f"[습관별 평균 달성률(최근 30일)]\n{top}"

    user_prompt = f"""
너는 습관 코치이자 데이터 기반 멘토야. 아래 요약을 바탕으로, 사용자가 다음 주에 개선할 점을 제안해줘.

{recent_stats}

요청:
- 이번 주 개선 포인트 3가지(각각 2~3문장)
- 쉬운 실천 계획(하루 10분 내외로 가능한 것 포함)
- 한국어, 1200자 이내
- 비난/죄책감 유발 금지
"""
    return user_prompt.strip()


# =========================
# Sidebar Settings
# =========================
def load_default_setting(key: str, env_key: str, default: str = "") -> str:
    # st.secrets 우선, 그 다음 env
    if key in st.secrets:
        return str(st.secrets[key])
    return os.getenv(env_key, default)


def sidebar_settings():
    st.sidebar.title("설정")

    # API keys (secrets/env -> sidebar input)
    default_openai = load_default_setting("OPENAI_API_KEY", "OPENAI_API_KEY", "")
    default_owm = load_default_setting("OPENWEATHER_API_KEY", "OPENWEATHER_API_KEY", "")

    if "openai_key" not in st.session_state:
        st.session_state.openai_key = default_openai
    if "owm_key" not in st.session_state:
        st.session_state.owm_key = default_owm

    st.sidebar.subheader("API 키")
    st.session_state.openai_key = st.sidebar.text_input(
        "OpenAI API Key", value=st.session_state.openai_key, type="password", help="세션에만 저장됩니다."
    )
    st.session_state.owm_key = st.sidebar.text_input(
        "OpenWeatherMap API Key", value=st.session_state.owm_key, type="password", help="세션에만 저장됩니다."
    )

    st.sidebar.subheader("기본 설정")
    city = st.sidebar.text_input("도시", value=st.session_state.get("city", "Seoul"))
    st.session_state.city = city

    reward_threshold = st.sidebar.slider("보상(강아지) 기준 달성률", 0, 100, st.session_state.get("reward_threshold", 70), 5)
    st.session_state.reward_threshold = reward_threshold

    overall_threshold = st.sidebar.slider("전체 스트릭 기준 달성률", 0, 100, st.session_state.get("overall_threshold", 70), 5)
    st.session_state.overall_threshold = overall_threshold

    model = st.sidebar.text_input("OpenAI 모델", value=st.session_state.get("openai_model", "gpt-4o-mini"))
    st.session_state.openai_model = model

    auto_coach = st.sidebar.toggle("오늘 자동 코칭 생성", value=st.session_state.get("auto_coach", False))
    st.session_state.auto_coach = auto_coach

    debug = st.sidebar.toggle("디버그 모드", value=st.session_state.get("debug", False))
    st.session_state.debug = debug

    st.sidebar.divider()

    if st.sidebar.button("기본 습관 템플릿 추가(비어있을 때)"):
        seed_default_habits_if_empty()
        st.sidebar.success("기본 습관을 확인해봐!")

    st.sidebar.caption("키는 세션에만 저장되며, 코드에 하드코딩하지 마세요.")


# =========================
# UI Components
# =========================
def kpi_cards(done: int, total: int, rate: int, cur_streak: int, best_streak: int, coach_score: int):
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("오늘 완료", f"{done}/{total}", f"{rate}%")
    c2.metric("현재 스트릭", f"{cur_streak}일")
    c3.metric("최장 스트릭", f"{best_streak}일")
    c4.metric("AI 코치 점수", f"{coach_score}/100")


def warn_api_missing(openai_needed=False, weather_needed=False):
    if openai_needed and not st.session_state.get("openai_key"):
        st.warning("OpenAI API Key가 없어서 AI 기능을 사용할 수 없어요. 사이드바에 키를 입력해줘.")
    if weather_needed and not st.session_state.get("owm_key"):
        st.warning("OpenWeatherMap API Key가 없어서 날씨 기능을 사용할 수 없어요. 사이드바에 키를 입력해줘.")


def render_weather_block(weather_info: Optional[Dict[str, Any]], routine_reco: str):
    if not weather_info:
        st.info("날씨 정보를 불러오지 못했어요. (키 미설정 또는 조회 실패)")
        st.write("추천 루틴:", routine_reco)
        return

    # 간단 텍스트 위젯
    st.markdown(f"**{weather_info.get('city_label','')}**")
    st.write(f"설명: {weather_info.get('desc','')}")
    st.write(f"기온: {weather_info.get('temp','')}°C (체감 {weather_info.get('feels','')}°C)")
    st.write(f"습도: {weather_info.get('humidity','')}% / 바람: {weather_info.get('wind_speed','')} m/s")
    st.write("추천 루틴:", routine_reco)


# =========================
# Pages
# =========================
def page_today():
    st.header("오늘")
    date = today_local()

    habits = fetch_active_habits()
    if not habits:
        st.info("활성화된 습관이 없어요. '습관 설정'에서 습관을 추가해줘.")
        return

    logs_map = fetch_logs_for_date(date)

    # Weather
    weather_info = None
    routine_reco = "오늘은 가벼운 스트레칭 5~10분으로 시작해봐."
    owm_key = st.session_state.get("owm_key", "").strip()
    city = st.session_state.get("city", "Seoul").strip()

    weather_penalty = 0
    if owm_key:
        try:
            geo = geocode_city(city, owm_key)
            if geo:
                lat, lon, city_label = geo
                w = fetch_current_weather(lat, lon, owm_key)
                s = weather_summary(w)
                s["city_label"] = city_label
                weather_info = s
                routine_reco = routine_reco_from_weather(s.get("desc", ""), s.get("temp", None))
                # 페널티: 악천후/극단 온도
                desc = (s.get("desc") or "").lower()
                t = s.get("temp")
                if any(k in desc for k in ["비", "눈", "뇌우", "rain", "snow", "thunderstorm"]):
                    weather_penalty = 10
                if t is not None and (t >= 32 or t <= -2):
                    weather_penalty = max(weather_penalty, 12)
        except Exception as e:
            if st.session_state.get("debug"):
                st.exception(e)

    # Stats
    stats = compute_today_stats(date, habits, logs_map)
    # memo hint: 오늘 메모가 몇 개 있나?
    memo_count = 0
    for h in habits:
        lr = logs_map.get(h["habit_id"])
        if lr and (lr["memo"] or "").strip():
            memo_count += 1
    memo_quality_hint = int(clamp(memo_count * 3, 0, 10))
    coach_score = compute_ai_coach_score(stats["rate"], memo_quality_hint, weather_penalty)

    cur_streak, best_streak = compute_overall_streak(st.session_state.get("overall_threshold", 70), days=120)
    kpi_cards(stats["done"], stats["total"], stats["rate"], cur_streak, best_streak, coach_score)

    st.divider()

    # Checklist
    st.subheader("오늘 체크리스트")
    for h in habits:
        hid = h["habit_id"]
        lr = logs_map.get(hid)
        is_done = bool(lr["is_done"]) if lr else False
        memo = (lr["memo"] if lr else "") or ""

        with st.container(border=True):
            top = st.columns([3, 2, 1])
            with top[0]:
                st.markdown(f"### {h['name']}")
                st.caption(f"카테고리: {h['category'] or '기타'} · 목표: {h['target_value']} {h['target_unit']} · 난이도: {h['difficulty']}/5")
            with top[1]:
                new_done = st.checkbox("완료", value=is_done, key=f"done_{hid}")
            with top[2]:
                st.write("")  # spacing
                st.write("")  # spacing

            new_memo = st.text_input("메모(짧게)", value=memo, key=f"memo_{hid}")

            # 업서트 (즉시 저장)
            if (new_done != is_done) or (new_memo != memo):
                upsert_log(date, hid, 1 if new_done else 0, new_memo)

    # Recompute after edits
    logs_map = fetch_logs_for_date(date)
    stats = compute_today_stats(date, habits, logs_map)

    st.divider()

    # Motivation area
    st.subheader("동기부여: 날씨 · 추천 루틴 · 보상")
    colA, colB, colC = st.columns([1, 1, 1])
    with colA:
        st.markdown("#### 🌦️ 오늘 날씨")
        warn_api_missing(weather_needed=True)
        render_weather_block(weather_info, routine_reco)

    with colB:
        st.markdown("#### ✅ 오늘 추천 루틴")
        st.write(routine_reco)

    with colC:
        st.markdown("#### 🐶 오늘의 보상")
        threshold = st.session_state.get("reward_threshold", 70)
        if stats["rate"] >= threshold and stats["total"] > 0:
            st.success(f"달성률 {stats['rate']}% 🎉 보상 지급!")
            img = fetch_dog_image_url()
            if img:
                st.image(img, use_container_width=True)
            else:
                st.info("강아지 이미지를 불러오지 못했어요. 다시 시도해줘.")
                if st.button("보상 다시 불러오기"):
                    img2 = fetch_dog_image_url()
                    if img2:
                        st.image(img2, use_container_width=True)
        else:
            st.info(f"달성률이 {threshold}% 이상이면 보상이 나와요! (현재 {stats['rate']}%)")

    st.divider()

    # AI Coach
    st.subheader("AI 코치")
    warn_api_missing(openai_needed=True)

    existing = load_ai_message(date, "coach")
    if existing:
        st.markdown("**저장된 코치 메시지**")
        st.write(existing)

    openai_key = st.session_state.get("openai_key", "").strip()
    model = st.session_state.get("openai_model", "gpt-4o-mini").strip()

    system_msg = (
        "너는 따뜻하지만 과장하지 않는 습관 코치다. "
        "사용자의 죄책감을 유발하지 말고, 작고 구체적인 다음 행동을 제안한다. "
        "답변은 한국어로, 1200자 이내로 한다."
    )

    def generate_and_save_coach():
        if not openai_key:
            st.warning("OpenAI API Key가 필요해요.")
            return
        prompt = build_today_ai_prompt(date, habits, logs_map, weather_info, routine_reco)
        try:
            text = openai_chat_completion(openai_key, model, system_msg, prompt, temperature=0.6)
            save_ai_message(date, "coach", text.strip())
            st.success("코치 메시지를 생성해서 저장했어!")
            st.rerun()
        except Exception as e:
            st.error("AI 호출에 실패했어요. 키/모델/네트워크를 확인해줘.")
            if st.session_state.get("debug"):
                st.exception(e)

    # 자동 코칭(옵션): 오늘 메시지가 없을 때만
    if st.session_state.get("auto_coach") and openai_key and not existing:
        with st.spinner("오늘 코치 메시지를 자동 생성 중..."):
            generate_and_save_coach()

    if st.button("AI 코치 메시지 생성", type="primary"):
        generate_and_save_coach()


def page_records():
    st.header("기록")
    habits = fetch_active_habits()
    if not habits:
        st.info("습관이 없어요. 먼저 '습관 설정'에서 추가해줘.")
        return

    # Range selector
    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        days = st.selectbox("기간", [7, 14, 30, 60, 90], index=2)
    with col2:
        chosen = st.date_input("날짜 선택", value=dt.date.today())
    with col3:
        st.caption("선택 날짜 상세와 최근 기간 로그를 함께 보여줘요.")

    end = dt.date.today()
    start = end - dt.timedelta(days=days - 1)
    df = fetch_logs_range(start.isoformat(), end.isoformat())

    # Selected day details
    chosen_str = chosen.isoformat()
    st.subheader(f"선택 날짜: {chosen_str}")
    logs_map = fetch_logs_for_date(chosen_str)
    stats = compute_today_stats(chosen_str, habits, logs_map)
    st.write(f"완료: **{stats['done']}/{stats['total']} ({stats['rate']}%)**")

    # show each habit
    for h in habits:
        lr = logs_map.get(h["habit_id"])
        done = "✅" if (lr and lr["is_done"] == 1) else "⬜"
        memo = (lr["memo"] if lr else "") or ""
        st.write(f"{done} **{h['name']}** — 메모: {memo if memo else '-'}")

    # AI message
    coach = load_ai_message(chosen_str, "coach")
    if coach:
        with st.expander("저장된 AI 코치 메시지"):
            st.write(coach)

    st.divider()

    st.subheader(f"최근 {days}일 로그")
    if df.empty:
        st.info("로그가 아직 없어요. '오늘' 탭에서 체크해봐!")
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)

    # Export CSV
    if not df.empty:
        csv = df.to_csv(index=False).encode("utf-8-sig")
        st.download_button("CSV 내보내기", data=csv, file_name=f"habit_logs_{start}_{end}.csv", mime="text/csv")


def page_insights():
    st.header("인사이트")
    habits = fetch_active_habits()
    if not habits:
        st.info("습관이 없어요. 먼저 '습관 설정'에서 추가해줘.")
        return

    end = dt.date.today()
    start7 = end - dt.timedelta(days=6)
    start30 = end - dt.timedelta(days=29)

    df7 = fetch_logs_range(start7.isoformat(), end.isoformat())
    df30 = fetch_logs_range(start30.isoformat(), end.isoformat())

    colA, colB = st.columns(2)
    with colA:
        st.subheader("최근 7일 습관별 성공률")
        if df7.empty:
            st.info("최근 7일 데이터가 부족해요.")
        else:
            g = (df7.groupby("name")["is_done"].mean() * 100).round().astype(int).sort_values(ascending=False)
            st.dataframe(g.rename("성공률(%)").reset_index(), use_container_width=True, hide_index=True)

    with colB:
        st.subheader("최근 30일 요일별 패턴")
        if df30.empty:
            st.info("최근 30일 데이터가 부족해요.")
        else:
            df30c = df30.copy()
            df30c["date"] = pd.to_datetime(df30c["date"])
            df30c["weekday"] = df30c["date"].dt.day_name()
            g2 = (df30c.groupby("weekday")["is_done"].mean() * 100).round().astype(int)
            # 요일 정렬(월~일) 간단 처리
            order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            g2 = g2.reindex([d for d in order if d in g2.index])
            st.dataframe(g2.rename("평균 달성률(%)").reset_index(), use_container_width=True, hide_index=True)

    st.divider()

    st.subheader("AI 인사이트")
    warn_api_missing(openai_needed=True)
    date = today_local()

    existing = load_ai_message(date, "insight")
    if existing:
        st.markdown("**저장된 인사이트**")
        st.write(existing)

    openai_key = st.session_state.get("openai_key", "").strip()
    model = st.session_state.get("openai_model", "gpt-4o-mini").strip()

    system_msg = (
        "너는 데이터 기반 습관 코치다. 비난하지 말고, 쉽게 실천 가능한 개선 포인트를 제안한다. "
        "한국어로 1200자 이내."
    )

    def generate_and_save_insight():
        if not openai_key:
            st.warning("OpenAI API Key가 필요해요.")
            return
        prompt = build_insight_ai_prompt(habits)
        try:
            text = openai_chat_completion(openai_key, model, system_msg, prompt, temperature=0.5)
            save_ai_message(date, "insight", text.strip())
            st.success("인사이트를 생성해서 저장했어!")
            st.rerun()
        except Exception as e:
            st.error("AI 호출에 실패했어요. 키/모델/네트워크를 확인해줘.")
            if st.session_state.get("debug"):
                st.exception(e)

    if st.button("AI 인사이트 생성", type="primary"):
        generate_and_save_insight()


def page_habits():
    st.header("습관 설정")
    st.caption("습관 추가/수정/비활성화를 할 수 있어요. (삭제 대신 비활성화 권장)")

    # Create new habit
    with st.expander("➕ 습관 추가", expanded=True):
        c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
        with c1:
            name = st.text_input("습관 이름", value="")
        with c2:
            category = st.text_input("카테고리", value="건강")
        with c3:
            target_value = st.number_input("목표 값", min_value=1, max_value=10000, value=20, step=1)
        with c4:
            target_unit = st.selectbox("단위", ["minutes", "times", "cups", "pages"], index=0)

        c5, c6, c7 = st.columns([1, 1, 1])
        with c5:
            difficulty = st.slider("난이도(1~5)", 1, 5, 3)
        with c6:
            frequency_type = st.selectbox("빈도 타입", ["daily", "weekly"], index=0)
        with c7:
            frequency_goal = st.number_input("주간 목표 횟수(weekly일 때)", min_value=0, max_value=21, value=0, step=1)

        if st.button("습관 추가하기"):
            if not name.strip():
                st.warning("습관 이름은 필수예요.")
            else:
                create_habit(
                    name=name.strip(),
                    category=category.strip(),
                    target_value=int(target_value),
                    target_unit=target_unit,
                    difficulty=int(difficulty),
                    frequency_type=frequency_type,
                    frequency_goal=int(frequency_goal),
                )
                st.success("습관을 추가했어!")
                st.rerun()

    st.divider()

    # Manage existing habits
    rows = fetch_all_habits()
    if not rows:
        st.info("등록된 습관이 없어요.")
        return

    st.subheader("습관 목록")
    for h in rows:
        with st.container(border=True):
            cols = st.columns([3, 2, 1, 1])
            with cols[0]:
                st.markdown(f"### {h['name']}")
                st.caption(
                    f"카테고리: {h['category'] or '기타'} · 목표: {h['target_value']} {h['target_unit']} · "
                    f"난이도: {h['difficulty']}/5 · 빈도: {h['frequency_type']}"
                    + (f"({h['frequency_goal']}/주)" if h["frequency_type"] == "weekly" else "")
                )
            with cols[1]:
                is_active = st.toggle("활성", value=bool(h["is_active"]), key=f"active_{h['habit_id']}")
            with cols[2]:
                if st.button("수정", key=f"editbtn_{h['habit_id']}"):
                    st.session_state[f"edit_{h['habit_id']}"] = True
            with cols[3]:
                st.write("")

            # Update active state immediately
            if bool(h["is_active"]) != bool(is_active):
                update_habit(h["habit_id"], is_active=1 if is_active else 0)
                st.rerun()

            # Edit form
            if st.session_state.get(f"edit_{h['habit_id']}", False):
                with st.form(key=f"editform_{h['habit_id']}"):
                    nc1, nc2, nc3, nc4 = st.columns([2, 1, 1, 1])
                    with nc1:
                        new_name = st.text_input("이름", value=h["name"])
                    with nc2:
                        new_category = st.text_input("카테고리", value=h["category"] or "")
                    with nc3:
                        new_target_value = st.number_input("목표 값", min_value=1, max_value=10000, value=int(h["target_value"]), step=1)
                    with nc4:
                        new_target_unit = st.selectbox("단위", ["minutes", "times", "cups", "pages"], index=["minutes","times","cups","pages"].index(h["target_unit"]))

                    nc5, nc6, nc7 = st.columns([1, 1, 1])
                    with nc5:
                        new_difficulty = st.slider("난이도(1~5)", 1, 5, int(h["difficulty"]))
                    with nc6:
                        new_freq_type = st.selectbox("빈도 타입", ["daily", "weekly"], index=0 if h["frequency_type"] == "daily" else 1)
                    with nc7:
                        new_freq_goal = st.number_input("주간 목표 횟수(weekly일 때)", min_value=0, max_value=21, value=int(h["frequency_goal"]), step=1)

                    submit = st.form_submit_button("저장")
                    cancel = st.form_submit_button("취소")

                    if cancel:
                        st.session_state[f"edit_{h['habit_id']}"] = False
                        st.rerun()

                    if submit:
                        if not new_name.strip():
                            st.warning("이름은 비워둘 수 없어요.")
                        else:
                            update_habit(
                                h["habit_id"],
                                name=new_name.strip(),
                                category=new_category.strip(),
                                target_value=int(new_target_value),
                                target_unit=new_target_unit,
                                difficulty=int(new_difficulty),
                                frequency_type=new_freq_type,
                                frequency_goal=int(new_freq_goal),
                            )
                            st.success("저장했어!")
                            st.session_state[f"edit_{h['habit_id']}"] = False
                            st.rerun()


# =========================
# Main
# =========================
def main():
    init_db()
    seed_default_habits_if_empty()

    sidebar_settings()

    st.title(APP_TITLE)
    tabs = st.tabs(["오늘", "기록", "인사이트", "습관 설정"])

    with tabs[0]:
        page_today()
    with tabs[1]:
        page_records()
    with tabs[2]:
        page_insights()
    with tabs[3]:
        page_habits()


if __name__ == "__main__":
    main()
