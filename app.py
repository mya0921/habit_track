import streamlit as st
import random
from datetime import datetime
from openai import OpenAI  # 최신 OpenAI 인터페이스

# 1. 페이지 설정
st.set_page_config(page_title="Habit Tracker", page_icon="🍏", layout="centered")

# 2. iOS 스타일 CSS 인젝션
def local_css():
    st.markdown("""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=SF+Pro+Display:wght@300;400;600&family=Inter:wght@400;600&display=swap');

        /* 배경 설정 */
        .stApp { background-color: #F2F2F7; }
        
        /* Typography */
        h1, h2, h3, p, div { font-family: 'Inter', -apple-system, sans-serif !important; }

        /* 명언 섹션: 더 애플스럽게 (Glassmorphism + Simple) */
        .quote-box {
            background: white;
            padding: 25px;
            border-radius: 20px;
            border-left: 5px solid #007AFF;
            box-shadow: 0 2px 10px rgba(0,0,0,0.03);
            margin: 20px 0;
            text-align: left;
        }
        .quote-text {
            color: #1C1C1E;
            font-size: 1.1rem;
            font-weight: 500;
            line-height: 1.5;
            margin-bottom: 8px;
        }
        .quote-author {
            color: #8E8E93;
            font-size: 0.9rem;
        }

        /* 입력창 & 버튼 */
        div.stButton > button {
            border-radius: 12px;
            background-color: #007AFF;
            color: white;
            font-weight: 600;
            border: none;
            padding: 10px 24px;
        }
        
        /* 체크박스/입력칸 간격 조정 */
        .stCheckbox, .stTextArea { margin-bottom: 15px; }
        
        /* 사이드바 */
        [data-testid="stSidebar"] {
            background-color: rgba(255, 255, 255, 0.8);
            backdrop-filter: blur(20px);
        }
        </style>
    """, unsafe_allow_html=True)

local_css()

# 3. 세션 상태 관리
if 'user_info' not in st.session_state:
    st.session_state.user_info = None
if 'habits' not in st.session_state:
    st.session_state.habits = ["물 2L 마시기", "아침 명상", "영양제 먹기"]
if 'habit_status' not in st.session_state:
    st.session_state.habit_status = {h: False for h in st.session_state.habits}

# 4. 사용자 온보딩 (이름, 나이, 성별 입력)
if st.session_state.user_info is None:
    st.markdown("# 🍏 Welcome")
    st.write("당신만의 AI 습관 트래커를 시작하기 위해 정보를 입력해주세요.")
    
    with st.container():
        name = st.text_input("이름")
        age = st.number_input("나이", min_value=1, max_value=120, value=25)
        gender = st.selectbox("성별", ["선택하지 않음", "남성", "여성"])
        
        if st.button("시작하기"):
            if name:
                st.session_state.user_info = {"name": name, "age": age, "gender": gender}
                st.rerun()
            else:
                st.warning("이름을 입력해주세요.")
    st.stop()

# --- 여기서부터는 메인 앱 ---

# 5. 사이드바 설정 (OpenAI 키 및 관리)
with st.sidebar:
    st.title("Settings")
    api_key = st.text_input("OpenAI API Key", type="password")
    st.divider()
    if st.button("데이터 초기화"):
        st.session_state.user_info = None
        st.rerun()

# 6. 상단 명언 섹션 (깔끔한 애플 스타일)
# Tip: 외부 API 대신 고퀄리티 명언 리스트 활용 (속도와 안정성 위해)
quotes = [
    {"q": "작은 반복이 거대한 차이를 만든다.", "a": "제임스 클리어"},
    {"q": "우리는 우리가 반복적으로 하는 일의 결과물이다.", "a": "아리스토텔레스"},
    {"q": "동기부여는 시작하게 하고, 습관은 계속하게 한다.", "a": "짐 론"},
    {"q": "자신을 이기는 자가 가장 강한 자다.", "a": "노자"}
]
selected_q = random.choice(quotes)
st.markdown(f"""
    <div class="quote-box">
        <div class="quote-text">{selected_q['q']}</div>
        <div class="quote-author">— {selected_q['a']}</div>
    </div>
""", unsafe_allow_html=True)

# 7. 메인 헤더
st.title(f"{st.session_state.user_info['name']}님의 오늘")

# 8. Daily Habits (습관 추가 기능 포함)
st.subheader("✅ Daily Habits")

# 습관 추가 영역
new_habit = st.text_input("새로운 습관 추가", placeholder="예: 매일 만보 걷기", label_visibility="collapsed")
if st.button("추가"):
    if new_habit and new_habit not in st.session_state.habits:
        st.session_state.habits.append(new_habit)
        st.session_state.habit_status[new_habit] = False
        st.rerun()

# 습관 리스트 출력
completed_count = 0
for habit in st.session_state.habits:
    is_checked = st.checkbox(habit, key=habit, value=st.session_state.habit_status.get(habit, False))
    st.session_state.habit_status[habit] = is_checked
    if is_checked:
        completed_count += 1

# 진척도
progress = completed_count / len(st.session_state.habits) if st.session_state.habits else 0
st.progress(progress)

# 습관 추천 기능 (간단한 로직 또는 AI 활용 가능)
with st.expander("💡 추천 습관 보기"):
    recommendations = ["10분 스트레칭", "디지털 디톡스", "감사 일기 쓰기", "외국어 단어 5개 암기"]
    rec_habit = random.choice(recommendations)
    st.write(f"오늘은 **[{rec_habit}]** 어떠신가요?")
    if st.button("이 습관 추가하기"):
        if rec_habit not in st.session_state.habits:
            st.session_state.habits.append(rec_habit)
            st.rerun()

# 9. Today's Reflection
st.subheader("📝 Today's Reflection")
reflection = st.text_area("오늘의 생각이나 기분을 기록해보세요.", placeholder="여기에 작성...", height=100)

# 10. 타로 및 AI 분석 (API 연동)
if st.button("🔮 AI 코칭 및 타로 결과 보기"):
    if not api_key:
        st.info("사이드바에 OpenAI API Key를 입력하면 AI 분석을 받을 수 있습니다.")
    else:
        client = OpenAI(api_key=api_key) # 최신 버전 객체 선언
        
        with st.spinner("운명의 카드를 뽑는 중..."):
            # Tarot API 시뮬레이션 (공용 API는 불안정한 경우가 많아 78장 로직 내장 권장)
            # 여기서는 예시로 고퀄리티 타로 데이터 사용
            cards = ["The Fool", "The Magician", "The High Priestess", "The Empress", "The Lovers", "Strength"]
            card_drawn = random.choice(cards)
            
            try:
                # GPT-4o 호출 (최신 문법)
                response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": "당신은 iOS 감성의 따뜻하고 세련된 라이프 코치입니다."},
                        {"role": "user", "content": f"""
                            사용자 정보: {st.session_state.user_info}
                            습관 달성률: {progress*100}%
                            오늘의 일기: {reflection}
                            뽑은 타로 카드: {card_drawn}
                            
                            1. 타로 카드의 의미를 오늘 하루와 연결해줘.
                            2. 칭찬과 함께 내일 더 잘할 수 있는 다정한 조언을 해줘.
                            3. 아주 심플하고 간결하게 애플 스타일로 답변해줘.
                        """}
                    ]
                )
                
                # 결과 출력
                st.divider()
                c1, c2 = st.columns([1, 2])
                with c1:
                    st.markdown(f"### 🃏 Tarot\n**{card_drawn}**")
                    st.image(f"https://www.trustedtarot.com/img/cards/{card_drawn.lower().replace(' ', '-')}.png")
                with c2:
                    st.markdown("### 🕊️ AI Coach")
                    st.write(response.choices[0].message.content)
                st.balloons()
                
            except Exception as e:
                st.error(f"AI 분석 중 오류가 발생했습니다: {e}")
