import streamlit as st
import random
from datetime import datetime
import openai

# 1. 페이지 기본 설정 및 iOS 스타일 CSS 인젝션
st.set_page_config(page_title="Habit Tracker", page_icon="🍏", layout="centered")

def local_css():
    st.markdown("""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600&display=swap');

        /* 전체 배경 및 폰트 설정 */
        html, body, [class*="css"] {
            font-family: 'Inter', sans-serif;
            background-color: #F2F2F7; /* iOS System Gray 6 */
        }

        /* 메인 컨테이너 카드 스타일 */
        .stApp {
            background-color: #F2F2F7;
        }

        /* 카드형 섹션 스타일 */
        .ios-card {
            background-color: white;
            padding: 20px;
            border-radius: 20px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
            margin-bottom: 20px;
        }

        /* 명언 섹션 (감성적 배경) */
        .quote-section {
            background: linear-gradient(135deg, #A2C2E1 0%, #E2E2E2 100%);
            color: white;
            padding: 30px;
            border-radius: 25px;
            text-align: center;
            margin-bottom: 25px;
            font-style: italic;
        }

        /* iOS 스타일 버튼 커스텀 */
        div.stButton > button {
            width: 100%;
            border-radius: 12px;
            border: none;
            background-color: #007AFF; /* iOS System Blue */
            color: white;
            padding: 12px;
            font-weight: 600;
            transition: all 0.2s;
        }
        div.stButton > button:hover {
            background-color: #0051A8;
            transform: scale(0.98);
        }

        /* 사이드바 블러 효과 */
        [data-testid="stSidebar"] {
            background-color: rgba(255, 255, 255, 0.7);
            backdrop-filter: blur(10px);
            border-right: 1px solid rgba(0,0,0,0.05);
        }

        /* 입력창 둥글게 */
        .stTextInput > div > div > input, .stTextArea > div > div > textarea {
            border-radius: 12px;
            border: 1px solid #E5E5EA;
        }
        </style>
    """, unsafe_allow_html=True)

local_css()

# 2. 세션 상태 초기화 (데이터 유지)
if 'habits' not in st.session_state:
    st.session_state.habits = {"운동하기": False, "독서 30분": False, "물 2L 마시기": False, "명상하기": False}
if 'analysis_result' not in st.session_state:
    st.session_state.analysis_result = None

# 3. 사이드바 (설정)
with st.sidebar:
    st.title("⚙️ Settings")
    user_name = st.text_input("사용자 이름", value="민수")
    api_key = st.text_input("OpenAI API Key", type="password")
    st.divider()
    st.caption("Designed with iOS Design Guideline")

# 4. 메인 헤더
st.markdown(f"### 🍏 안녕하세요, {user_name}님.")
st.markdown("<h1 style='margin-top:-15px;'>오늘 당신의 여정은 어떤가요?</h1>", unsafe_allow_html=True)

# 5. 명언 영역 (Quote of the day)
quotes = [
    "당신의 습관이 당신의 미래를 만든다.",
    "어제보다 나은 오늘을 만드는 것은 작은 실천입니다.",
    "완벽함이 아니라 성장에 집중하세요.",
    "천천히 가는 것을 두려워 말고, 멈추는 것을 두려워하라."
]
st.markdown(f'<div class="quote-section">"{random.choice(quotes)}"</div>', unsafe_allow_html=True)

# 6. 습관 트래커 섹션
st.markdown('<div class="ios-card">', unsafe_allow_html=True)
st.subheader("✅ Daily Habits")

cols = st.columns(len(st.session_state.habits))
completed_count = 0
for i, habit in enumerate(st.session_state.habits):
    st.session_state.habits[habit] = st.checkbox(habit, value=st.session_state.habits[habit])
    if st.session_state.habits[habit]:
        completed_count += 1

# 진척도 계산 및 표시
progress = completed_count / len(st.session_state.habits)
st.progress(progress)
st.write(f"오늘의 달성률: **{int(progress*100)}%**")
st.markdown('</div>', unsafe_allow_html=True)

# 7. 오늘의 회고
st.markdown('<div class="ios-card">', unsafe_allow_html=True)
st.subheader("📝 Today's Reflection")
reflection = st.text_area("오늘 하루는 어땠나요? 느낀 점을 자유롭게 적어주세요.", placeholder="여기에 작성하세요...")
st.markdown('</div>', unsafe_allow_html=True)

# 8. 분석 및 타로 섹션
if st.button("✨ 오늘의 여정 분석 시작"):
    if not api_key:
        st.error("OpenAI API 키를 사이드바에 입력해주세요!")
    else:
        with st.spinner("AI가 타로 카드를 읽고 당신의 하루를 분석 중입니다..."):
            # 임의의 타로 카드 데이터 (Tarot API 대체용)
            tarot_cards = [
                {"name": "The Sun", "meaning": "밝은 미래, 성공, 긍정적인 에너지", "img": "☀️"},
                {"name": "The Moon", "meaning": "직관, 혼란 속의 길, 무의식", "img": "🌙"},
                {"name": "The Star", "meaning": "희망, 영감, 평온", "img": "⭐"},
                {"name": "The Magician", "meaning": "준비된 능력, 창조력, 새로운 시작", "img": "🪄"}
            ]
            selected_card = random.choice(tarot_cards)
            
            # OpenAI API 호출 (GPT-4o)
            try:
                openai.api_key = api_key
                prompt = f"""
                사용자 이름: {user_name}
                오늘의 습관 달성률: {progress*100}%
                오늘의 일기: {reflection}
                오늘의 타로 카드: {selected_card['name']} ({selected_card['meaning']})
                
                위 정보를 바탕으로 사용자에게 다정한 멘토처럼 피드백을 해줘. 
                타로 카드의 의미를 습관 달성과 연결해서 내일의 조언을 해줘. 
                문체는 부드럽고 격려하는 말투로 작성해줘.
                """
                
                response = openai.ChatCompletion.create(
                    model="gpt-4o",
                    messages=[{"role": "system", "content": "당신은 따뜻한 AI 인생 코치입니다."},
                              {"role": "user", "content": prompt}]
                )
                
                st.session_state.analysis_result = {
                    "card": selected_card,
                    "ai_text": response.choices[0].message.content
                }
            except Exception as e:
                st.error(f"오류가 발생했습니다: {e}")

# 결과 출력 (데이터가 있을 때만)
if st.session_state.analysis_result:
    st.markdown('<div class="ios-card">', unsafe_allow_html=True)
    res = st.session_state.analysis_result
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.markdown(f"<div style='text-align:center; font-size: 80px;'>{res['card']['img']}</div>", unsafe_allow_html=True)
        st.markdown(f"<h3 style='text-align:center;'>{res['card']['name']}</h3>", unsafe_allow_html=True)
    
    with col2:
        st.markdown("### 🔮 AI Coach's Insight")
        st.write(res['ai_text'])
    st.markdown('</div>', unsafe_allow_html=True)
    st.balloons()
