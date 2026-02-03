from pathlib import Path
import random
import pandas as pd
import streamlit as st
from supabase import create_client
from streamlit_cookies_manager import EncryptedCookieManager

cookies = EncryptedCookieManager(
    prefix="hatena_jlpt/",
    password=st.secrets.get("COOKIE_PASSWORD", "change-me-please")  # secrets에 넣는 걸 추천
)
if not cookies.ready():
    st.stop()


# ============================================================
# ✅ Streamlit 기본 설정 (반드시 가장 위, 첫 st.* 호출)
# ============================================================
st.set_page_config(page_title="JLPT Quiz", layout="centered")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Kosugi+Maru&display=swap');

:root{ --jp-rounded: "Kosugi Maru","Hiragino Sans","Yu Gothic","Meiryo",sans-serif; }
.jp, .jp *{ font-family: var(--jp-rounded) !important; line-height:1.7; letter-spacing:.2px; }
</style>
""", unsafe_allow_html=True)

st.title("하테나일본어 형용사 퀴즈")

# ============================================================
# ✅ Supabase 연결 (Secrets 필수)
# ============================================================
if "SUPABASE_URL" not in st.secrets or "SUPABASE_ANON_KEY" not in st.secrets:
    st.error("Supabase Secrets가 설정되지 않았습니다. (SUPABASE_URL / SUPABASE_ANON_KEY)")
    st.stop()

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_ANON_KEY = st.secrets["SUPABASE_ANON_KEY"]

# anon client (로그인/회원가입용)
sb = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


def get_authed_sb():
    """
    ✅ RLS 통과용: access_token을 PostgREST에 붙인 클라이언트
    """
    token = st.session_state.get("access_token")
    if not token:
        return None
    sb2 = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    sb2.postgrest.auth(token)  # 핵심
    return sb2


# ============================================================
# ✅ 상수/설정
# ============================================================
NAVER_TALK_URL = "https://talk.naver.com/W45141"
LEVEL = "N4"
N = 10
QUESTION_TYPES = ["reading", "meaning"]
mode_label_map = {"i_adj": "い형용사", "na_adj": "な형용사", "mix": "형용사 혼합"}
pos_label_for_table = {"i_adj": "い형용사", "na_adj": "な형용사", "mix": "혼합"}

# ============================================================
# ✅ 로그인 UI
# ============================================================
def auth_box():
    st.subheader("로그인")
    tab1, tab2 = st.tabs(["로그인", "회원가입"])

    with tab1:
        email = st.text_input("이메일", key="login_email")
        pw = st.text_input("비밀번호", type="password", key="login_pw")

        if st.button("로그인", use_container_width=True):
            if not email or not pw:
                st.warning("이메일과 비밀번호를 입력해주세요.")
                st.stop()

            try:
                res = sb.auth.sign_in_with_password({"email": email, "password": pw})

                # ✅ user
                st.session_state.user = res.user

                # ✅ session token (RLS용)
                if res.session and res.session.access_token:
                    st.session_state.access_token = res.session.access_token
                    st.session_state.refresh_token = res.session.refresh_token

                    # ✅✅✅ 쿠키 저장(새로고침 대비)
                    cookies["access_token"] = res.session.access_token
                    cookies["refresh_token"] = res.session.refresh_token
                    cookies.save()
                else:
                    st.warning("로그인은 되었지만 세션 토큰이 없습니다. 이메일 인증 상태를 확인해주세요.")
                    st.session_state.access_token = None
                    st.session_state.refresh_token = None

                st.success("로그인 완료!")
                st.rerun()

            except Exception:
                st.error("로그인 실패: 이메일/비밀번호 또는 이메일 인증 상태를 확인해주세요.")
                st.stop()

    with tab2:
        email = st.text_input("이메일", key="signup_email")
        pw = st.text_input("비밀번호", type="password", key="signup_pw")

        if st.button("회원가입", use_container_width=True):
            if not email or not pw:
                st.warning("이메일과 비밀번호를 입력해주세요.")
                st.stop()

            try:
                sb.auth.sign_up({"email": email, "password": pw})
                st.success("회원가입 요청 완료! 이메일 인증이 필요할 수 있어요.")
            except Exception:
                st.error("회원가입 실패: 이메일 형식/비밀번호 조건을 확인해주세요.")
                st.stop()

def restore_session_from_cookies():
    # 이미 로그인 상태면 스킵
    if st.session_state.get("user") and st.session_state.get("access_token"):
        return

    rt = cookies.get("refresh_token")
    if not rt:
        return

    try:
        # ✅ refresh_token으로 새 세션 발급
        refreshed = sb.auth.refresh_session(rt)

        # 세션이 없으면 종료
        if not refreshed or not refreshed.session:
            return

        st.session_state.user = refreshed.user
        st.session_state.access_token = refreshed.session.access_token
        st.session_state.refresh_token = refreshed.session.refresh_token

        # ✅ 쿠키도 최신으로 갱신
        cookies["access_token"] = refreshed.session.access_token
        cookies["refresh_token"] = refreshed.session.refresh_token
        cookies.save()

    except Exception:
        # 토큰 만료/형식 오류 등 → 조용히 무시하고 로그인 화면으로
        return


# ✅ 앱 시작 시 1회 복원 시도
restore_session_from_cookies()



def require_login():
    if "user" not in st.session_state or st.session_state.user is None:
        auth_box()
        st.stop()


# ============================================================
# ✅ DB 저장/조회 함수 (반드시 sb_authed로 호출)
# ============================================================
def save_attempt_to_db(sb_authed, user_id, level, pos_mode, quiz_len, score, wrong_list):
    payload = {
        "user_id": user_id,
        "level": level,
        "pos_mode": pos_mode,
        "quiz_len": int(quiz_len),
        "score": int(score),
        "wrong_count": int(len(wrong_list)),
        "wrong_list": wrong_list,  # jsonb
    }
    sb_authed.table("quiz_attempts").insert(payload).execute()


def fetch_recent_attempts(sb_authed, user_id, limit=10):
    return (
        sb_authed.table("quiz_attempts")
        .select("created_at, level, pos_mode, quiz_len, score, wrong_count")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )


# ============================================================
# ✅ 네이버톡 배너 (제출 후만)
# ============================================================
def render_naver_talk():
    st.divider()
    st.markdown(
        f"""
<style>
@keyframes floaty {{
  0% {{ transform: translateY(0); }}
  50% {{ transform: translateY(-6px); }}
  100% {{ transform: translateY(0); }}
}}
@keyframes ping {{
  0% {{ transform: scale(1); opacity: 0.9; }}
  70% {{ transform: scale(2.2); opacity: 0; }}
  100% {{ transform: scale(2.2); opacity: 0; }}
}}

.floating-naver-talk,
.floating-naver-talk:visited,
.floating-naver-talk:hover,
.floating-naver-talk:active {{
  position: fixed;
  right: 18px;
  bottom: 90px;
  z-index: 99999;
  text-decoration: none !important;
  color: inherit !important;
}}

.floating-wrap {{
  position: relative;
  animation: floaty 2.2s ease-in-out infinite;
}}

.talk-btn {{
  background: #03C75A;
  color: #fff;
  border: 0;
  border-radius: 999px;
  padding: 14px 18px;
  font-size: 15px;
  font-weight: 700;
  box-shadow: 0 12px 28px rgba(0,0,0,0.22);
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 10px;
  line-height: 1.1;
  text-decoration: none !important;
}}

.talk-btn:hover {{ filter: brightness(0.95); }}

.talk-text small {{
  display: block;
  font-size: 12px;
  font-weight: 600;
  opacity: 0.95;
  margin-top: 2px;
}}

.badge {{
  position: absolute;
  top: -6px;
  right: -6px;
  width: 12px;
  height: 12px;
  background: #ff3b30;
  border-radius: 999px;
  box-shadow: 0 6px 14px rgba(0,0,0,0.25);
}}

.badge::after {{
  content: "";
  position: absolute;
  left: 50%;
  top: 50%;
  width: 12px;
  height: 12px;
  transform: translate(-50%, -50%);
  border-radius: 999px;
  background: rgba(255,59,48,0.55);
  animation: ping 1.2s ease-out infinite;
}}

@media (max-width: 600px) {{
  .floating-naver-talk {{ bottom: 110px; right: 14px; }}
  .talk-btn {{ padding: 13px 16px; font-size: 14px; }}
  .talk-text small {{ font-size: 11px; }}
}}
</style>

<a class="floating-naver-talk" href="{NAVER_TALK_URL}" target="_blank" rel="noopener noreferrer">
  <div class="floating-wrap">
    <span class="badge"></span>
    <button class="talk-btn" type="button">
      <span>💬</span>
      <span class="talk-text">
        1:1 하테나쌤 상담
        <small>수강신청 문의하기</small>
      </span>
    </button>
  </div>
</a>
""",
        unsafe_allow_html=True,
    )


# ============================================================
# ✅ 로그인 강제 + 상단 UI
# ============================================================
require_login()
user = st.session_state.user
user_id = user.id

# ✅✅✅ (저장 관련) sb_authed는 쓰기 전에 먼저 만들어야 함
sb_authed = get_authed_sb()

st.write("token 있음?", bool(st.session_state.get("access_token")))
st.write("sb_authed None?", sb_authed is None)
st.write("user_id:", user_id)


# 로그인 표시 + 로그아웃
colA, colB = st.columns([7, 3])
with colA:
    st.caption("환영합니다 🙂")
with colB:
    if st.button("🚪 로그아웃", use_container_width=True):
        # 1) Supabase sign out (실패해도 계속 진행)
        try:
            sb.auth.sign_out()
        except Exception:
            pass

        # 2) ✅ 쿠키 제거 (핵심: refresh_token 제거)
        try:
            cookies["access_token"] = ""
            cookies["refresh_token"] = ""
            cookies.save()
        except Exception:
            pass

        # 3) ✅ 세션 제거
        for k in [
            "user", "access_token", "refresh_token",
            "quiz", "answers", "submitted", "wrong_list",
            "quiz_version", "pos_mode", "saved_this_attempt",
            "history", "wrong_counter", "total_counter",
        ]:
            st.session_state.pop(k, None)

        st.rerun()


# ============================================================
# ✅ CSV 로드
# ============================================================
BASE_DIR = Path(__file__).resolve().parent
CSV_PATH = BASE_DIR / "data" / "words_adj_300.csv"

df = pd.read_csv(CSV_PATH)
if len(df.columns) == 1 and "\t" in df.columns[0]:
    df = pd.read_csv(CSV_PATH, sep="\t")

df.columns = df.columns.astype(str).str.replace("\ufeff", "", regex=False).str.strip()

pool = df[df["level"] == LEVEL].copy()
if len(pool) < N:
    st.error(f"단어가 부족합니다: pool={len(pool)}")
    st.stop()

# ============================================================
# ✅ 퀴즈 로직
# ============================================================
def get_base_pool_for_mode(mode: str) -> pd.DataFrame:
    if mode == "i_adj":
        return pool[pool["pos"] == "i_adj"].copy()
    if mode == "na_adj":
        return pool[pool["pos"] == "na_adj"].copy()
    return pool[pool["pos"].isin(["i_adj", "na_adj"])].copy()


def make_question(row: pd.Series, base_pool: pd.DataFrame) -> dict:
    qtype = random.choice(QUESTION_TYPES)

    target_pos = row["pos"]
    same_pos_pool = base_pool[base_pool["pos"] == target_pos]

    if qtype == "reading":
        prompt = f"{row['jp_word']}의 발음은?"
        correct = row["reading"]
        candidates = (
            same_pos_pool[same_pos_pool["reading"] != correct]["reading"]
            .dropna()
            .drop_duplicates()
            .tolist()
        )
    else:
        prompt = f"{row['jp_word']}의 뜻은?"
        correct = row["meaning"]
        candidates = (
            same_pos_pool[same_pos_pool["meaning"] != correct]["meaning"]
            .dropna()
            .drop_duplicates()
            .tolist()
        )

    if len(candidates) < 3:
        st.error(f"오답 후보 부족: pos={target_pos}, 후보={len(candidates)}개")
        st.stop()

    wrongs = random.sample(candidates, 3)
    choices = wrongs + [correct]
    random.shuffle(choices)

    return {
        "prompt": prompt,
        "choices": choices,
        "correct_text": correct,
        "jp_word": row["jp_word"],
        "reading": row["reading"],
        "meaning": row["meaning"],
        "pos": row["pos"],
        "quiz_type": qtype,   # ✅(저장 관련) quiz_type 보관
    }


def build_quiz(mode: str) -> list:
    base_pool = get_base_pool_for_mode(mode)

    if mode == "mix":
        i_pool = base_pool[base_pool["pos"] == "i_adj"].copy()
        na_pool = base_pool[base_pool["pos"] == "na_adj"].copy()

        if len(i_pool) < 5 or len(na_pool) < 5:
            st.error(f"혼합 모드 단어 부족: i={len(i_pool)}, na={len(na_pool)}")
            st.stop()

        sampled = pd.concat([i_pool.sample(n=5), na_pool.sample(n=5)], ignore_index=True)
        sampled = sampled.sample(frac=1).reset_index(drop=True)
    else:
        filtered = base_pool[base_pool["pos"] == mode].copy()
        if len(filtered) < N:
            st.error(f"단어가 부족합니다: mode={mode}, pool={len(filtered)}")
            st.stop()
        sampled = filtered.sample(n=N).reset_index(drop=True)

    return [make_question(sampled.iloc[i], base_pool) for i in range(len(sampled))]


def build_quiz_from_wrongs(wrong_list: list, mode: str) -> list:
    base_pool = get_base_pool_for_mode(mode)
    wrong_words = list({w["단어"] for w in wrong_list})

    retry_df = base_pool[base_pool["jp_word"].isin(wrong_words)].copy()
    if len(retry_df) == 0:
        st.error("오답 단어를 풀에서 찾지 못했습니다. (jp_word 매칭 확인 필요)")
        st.stop()

    retry_df = retry_df.sample(frac=1).reset_index(drop=True)
    return [make_question(retry_df.iloc[i], base_pool) for i in range(len(retry_df))]


# ============================================================
# ✅ 세션 초기화
# ============================================================
if "pos_mode" not in st.session_state:
    st.session_state.pos_mode = "mix"
if "quiz_version" not in st.session_state:
    st.session_state.quiz_version = 0
if "submitted" not in st.session_state:
    st.session_state.submitted = False
if "wrong_list" not in st.session_state:
    st.session_state.wrong_list = []
if "saved_this_attempt" not in st.session_state:
    st.session_state.saved_this_attempt = False

# 누적(세션) 통계
if "history" not in st.session_state:
    st.session_state.history = []
if "wrong_counter" not in st.session_state:
    st.session_state.wrong_counter = {}
if "total_counter" not in st.session_state:
    st.session_state.total_counter = {}

if "quiz" not in st.session_state:
    st.session_state.quiz = build_quiz(st.session_state.pos_mode)

# ============================================================
# ✅ 상단 UI (출제 유형/새문제/초기화)
# ============================================================
selected = st.radio(
    "출제 유형",
    options=["i_adj", "na_adj", "mix"],
    format_func=lambda x: mode_label_map[x],
    horizontal=True,
    index=["i_adj", "na_adj", "mix"].index(st.session_state.pos_mode),
)

if selected != st.session_state.pos_mode:
    st.session_state.pos_mode = selected
    st.session_state.quiz = build_quiz(selected)
    st.session_state.submitted = False
    st.session_state.wrong_list = []
    st.session_state.saved_this_attempt = False
    st.session_state.quiz_version += 1
    st.rerun()

st.divider()
if st.button("🧪 RPC 테스트(1회)"):
    sb_authed = get_authed_sb()
    st.write("sb_authed:", sb_authed is not None)
    try:
        sb_authed.rpc("record_word_result", {
            "p_word_key": "TEST_WORD",
            "p_level": LEVEL,
            "p_pos": "i_adj",
            "p_quiz_type": "debug",
            "p_is_correct": True
        }).execute()
        st.success("✅ RPC 호출 성공")
    except Exception as e:
        st.error("❌ RPC 호출 실패")
        st.write(getattr(e, "args", e))


st.caption(f"현재 선택: **{mode_label_map[st.session_state.pos_mode]}**")
st.divider()

col1, col2 = st.columns(2)
with col1:
    if st.button("🔄 새 문제(랜덤 10문항)", use_container_width=True):
        st.session_state.quiz = build_quiz(st.session_state.pos_mode)
        st.session_state.submitted = False
        st.session_state.wrong_list = []
        st.session_state.saved_this_attempt = False
        st.session_state.quiz_version += 1
        st.rerun()

with col2:
    if st.button("🧹 선택 초기화", use_container_width=True):
        st.session_state.submitted = False
        st.session_state.quiz_version += 1
        st.rerun()

st.divider()

# ============================================================
# ✅ answers 길이 자동 맞춤 (오답 재도전 대비)
# ============================================================
quiz_len = len(st.session_state.quiz)
if "answers" not in st.session_state or len(st.session_state.answers) != quiz_len:
    st.session_state.answers = [None] * quiz_len

# ============================================================
# ✅ 문제 표시
# ============================================================
for idx, q in enumerate(st.session_state.quiz):
    st.subheader(f"Q{idx+1}")

    # ✅ 한 줄만 출력 (일본어/한자 포함되는 문자열을 jp로 감싼다)
    st.markdown(
        f'<div class="jp" style="font-size:18px; font-weight:500;">{q["prompt"]}</div>',
        unsafe_allow_html=True
    )

    choice = st.radio(
        label="보기",
        options=q["choices"],
        index=None,
        key=f"q_{st.session_state.quiz_version}_{idx}",
        label_visibility="collapsed",
    )
    st.session_state.answers[idx] = choice
    st.divider()

# ============================================================
# ✅ 제출/채점
# ============================================================
all_answered = all(a is not None for a in st.session_state.answers)

if st.button("✅ 제출하고 채점하기", disabled=not all_answered, type="primary", use_container_width=True):
    st.session_state.submitted = True

if not all_answered:
    st.info("모든 문제에 답을 선택하면 제출 버튼이 활성화됩니다.")

if st.session_state.submitted:

    # 🔥 FIX 1: sb_authed를 여기서 먼저 확보 (가장 중요)
    sb_authed = get_authed_sb()

    if sb_authed is None:
        st.error("❌ 인증된 Supabase 클라이언트를 가져오지 못했습니다.")
        st.stop()

    score = 0
    wrong_list = []

    for idx, q in enumerate(st.session_state.quiz):
        picked = st.session_state.answers[idx]
        correct = q["correct_text"]
        is_correct = (picked == correct)

        if is_correct:
            score += 1
        else:
            wrong_list.append({
                "No": idx + 1,
                "문제": q["prompt"],
                "내 답": picked,
                "정답": correct,
                "단어": q["jp_word"],
                "읽기": q["reading"],
                "뜻": q["meaning"],
            })

        # 🔥 FIX 2: sb_authed가 보장된 상태에서만 RPC 호출
        try:
            sb_authed.rpc(
                "record_word_result",
                {
                    "p_word_key": q["jp_word"],
                    "p_level": LEVEL,
                    "p_pos": q["pos"],
                    "p_quiz_type": q.get("quiz_type", "adj_quiz"),
                    "p_is_correct": is_correct,
                }
            ).execute()
        except Exception as e:
            st.error("❌ 단어 통계(stats) 저장 실패")
            st.exception(e)

    st.session_state.wrong_list = wrong_list
    quiz_len = len(st.session_state.quiz)

    # ✅ 결과 표시
    st.success(f"점수: {score} / {quiz_len}")
    ratio = score / quiz_len if quiz_len else 0

    if ratio == 1:
        st.balloons()
        st.success("🎉 완벽해요! 전부 정답입니다. 정말 잘했어요!")
    elif ratio >= 0.7:
        st.info("👍 잘하고 있어요! 조금만 더 다듬으면 완벽해질 거예요.")
    else:
        st.warning("💪 괜찮아요! 틀린 문제는 성장의 재료예요. 다시 한 번 도전해봐요.")

    # ✅ DB 저장/조회는 sb_authed로만 (RLS 정책 통과)
    if sb_authed is None:
        st.warning("DB 저장/조회용 토큰이 없습니다. (로그인 세션 토큰 확인 필요)")
    else:
        # ✅ DB 저장(한 번만)
        if not st.session_state.saved_this_attempt:
            try:
                save_attempt_to_db(
                    sb_authed=sb_authed,
                    user_id=user_id,
                    level=LEVEL,
                    pos_mode=st.session_state.pos_mode,
                    quiz_len=quiz_len,
                    score=score,
                    wrong_list=wrong_list,
                )
                st.session_state.saved_this_attempt = True
            except Exception as e:
                st.error("DB 저장에 실패했습니다. (테이블/컬럼/권한/RLS 정책 확인 필요)")
                st.write(getattr(e, "args", e))

        # ✅ 내 최근 기록 (예쁘게: 요약 + 카드 리스트)
        st.subheader("📌 내 최근 기록")

        try:
            res = fetch_recent_attempts(sb_authed, user_id, limit=10)

            if not res.data:
                st.info("아직 저장된 기록이 없습니다. 문제를 풀고 제출하면 기록이 쌓여요.")
            else:
                hist = pd.DataFrame(res.data).copy()

                # 정리/가공
                hist["created_at"] = pd.to_datetime(hist["created_at"]).dt.tz_localize(None)
                hist["유형"] = hist["pos_mode"].map(lambda x: pos_label_for_table.get(x, x))
                hist["정답률"] = (hist["score"] / hist["quiz_len"]).fillna(0)

                # ✅ 요약 카드(최근 10회)
                avg_rate = float(hist["정답률"].mean() * 100)
                best = int(hist["score"].max())
                last_score = int(hist.iloc[0]["score"])
                last_total = int(hist.iloc[0]["quiz_len"])

                c1, c2, c3 = st.columns(3)
                c1.metric("최근 10회 평균", f"{avg_rate:.0f}%")
                c2.metric("최고 점수", f"{best} / {N}")
                c3.metric("최근 점수", f"{last_score} / {last_total}")

                st.divider()

                # ✅ 카드 스타일 (streamlit theme에 어울리게)
                st.markdown(
                    """
<style>
.record-card{
  border: 1px solid rgba(120,120,120,0.25);
  border-radius: 16px;
  padding: 14px 14px;
  margin-bottom: 10px;
  background: rgba(255,255,255,0.02);
}
.record-top{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:12px;
  margin-bottom: 8px;
}
.record-title{
  font-weight: 800;
  font-size: 16px;
}
.record-sub{
  opacity: 0.75;
  font-size: 12px;
}
.pill{
  display:inline-flex;
  align-items:center;
  gap:6px;
  padding: 6px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  border: 1px solid rgba(120,120,120,0.25);
  background: rgba(255,255,255,0.03);
}
.row{
  display:flex;
  gap:10px;
  flex-wrap:wrap;
  margin-top: 8px;
}
.kv{
  display:flex;
  gap:8px;
  align-items:baseline;
}
.k{
  opacity: 0.7;
  font-size: 12px;
}
.v{
  font-weight: 800;
  font-size: 14px;
}
.small{
  opacity:0.75;
  font-size: 12px;
  margin-top: 6px;
}
</style>
""",
                    unsafe_allow_html=True,
                )

                # ✅ 카드로 10개 표시
                for _, r in hist.iterrows():
                    dt = r["created_at"].strftime("%Y-%m-%d %H:%M")
                    mode = r["유형"]
                    score2 = int(r["score"])
                    total = int(r["quiz_len"])
                    wrong = int(r["wrong_count"])
                    pct = float(r["정답률"] * 100)

                    # 점수에 따른 배지 이모지(가독성)
                    if pct >= 90:
                        badge = "🏆"
                    elif pct >= 70:
                        badge = "👍"
                    else:
                        badge = "💪"

                    st.markdown(
                        f"""
<div class="record-card">
  <div class="record-top">
    <div>
      <div class="record-title">{badge} {score2} / {total}</div>
      <div class="record-sub">{dt} · {mode} · 레벨 {LEVEL}</div>
    </div>
    <div class="pill">오답 {wrong}개</div>
  </div>
</div>
""",
                        unsafe_allow_html=True,
                    )
                    # 진행바는 streamlit 컴포넌트가 더 예쁨
                    st.progress(min(max(pct / 100.0, 0.0), 1.0))
                    st.caption(f"정답률 {pct:.0f}%")
                    st.write("")  # 카드 사이 여백

                # (선택) “표로 보기” 토글
                with st.expander("표로도 보기(관리자/디버그용)"):
                    show = hist.rename(columns={
                        "created_at": "일시",
                        "level": "레벨",
                        "pos_mode": "pos_mode(원값)",
                        "quiz_len": "문항",
                        "score": "점수",
                        "wrong_count": "오답",
                    })
                    show["일시"] = show["일시"].dt.strftime("%Y-%m-%d %H:%M")
                    st.dataframe(
                        show[["일시", "레벨", "유형", "문항", "점수", "오답", "pos_mode(원값)"]],
                        use_container_width=True,
                        hide_index=True,
                    )

        except Exception as e:
            st.info("기록을 불러오지 못했습니다. (DB/RLS 확인 필요)")
            st.write(getattr(e, "args", e))


    # ✅ 세션 누적 통계(원래 기능 유지)
    st.session_state.history.append({"mode": st.session_state.pos_mode, "score": score, "total": quiz_len})

    for idx, q in enumerate(st.session_state.quiz):
        word = q["jp_word"]
        st.session_state.total_counter[word] = st.session_state.total_counter.get(word, 0) + 1
        if st.session_state.answers[idx] != q["correct_text"]:
            st.session_state.wrong_counter[word] = st.session_state.wrong_counter.get(word, 0) + 1

    # ✅ 오답 있을 때만: 오답 재도전 + 오답 노트
    if st.session_state.wrong_list:
        st.subheader("❌ 오답 노트")

        if st.button("❌ 틀린 문제만 다시 풀기", type="primary", use_container_width=True, key="retry_wrong"):
            st.session_state.quiz = build_quiz_from_wrongs(st.session_state.wrong_list, st.session_state.pos_mode)
            st.session_state.submitted = False
            st.session_state.wrong_list = []
            st.session_state.saved_this_attempt = False
            st.session_state.quiz_version += 1
            st.rerun()

        for w in st.session_state.wrong_list:
            st.markdown(
                f"""
**Q{w['No']}**

- 문제: {w['문제']}
- ❌ 내 답: **{w['내 답']}**
- ✅ 정답: **{w['정답']}**

📌 단어 정리  
- 표기: **{w['단어']}**  
- 읽기: {w['읽기']}  
- 뜻: {w['뜻']}

---
"""
            )

    # ✅ 누적 현황(이번 세션)
    st.divider()
    st.subheader("📊 누적 학습 현황 (이번 세션)")

    total_attempts = sum(x["total"] for x in st.session_state.history) if st.session_state.history else 0
    total_score = sum(x["score"] for x in st.session_state.history) if st.session_state.history else 0
    acc = (total_score / total_attempts) if total_attempts else 0

    c1, c2, c3 = st.columns(3)
    c1.metric("누적 회차", len(st.session_state.history))
    c2.metric("누적 점수", f"{total_score} / {total_attempts}")
    c3.metric("누적 정답률", f"{acc*100:.0f}%")

    if st.session_state.wrong_counter:
        st.markdown("#### ❌ 자주 틀리는 단어 TOP 5")
        top5 = sorted(st.session_state.wrong_counter.items(), key=lambda x: x[1], reverse=True)[:5]
        for rank, (w, cnt) in enumerate(top5, start=1):
            total_seen = st.session_state.total_counter.get(w, 0)
            st.write(f"{rank}. **{w}**  —  {cnt}회 오답 / {total_seen}회 출제")
    else:
        st.info("아직 오답 누적 데이터가 없습니다.")

    if st.button("🗑️ 누적 기록 초기화", use_container_width=True):
        st.session_state.history = []
        st.session_state.wrong_counter = {}
        st.session_state.total_counter = {}
        st.rerun()

    # ✅ 제출 후 상담 배너
    render_naver_talk()
