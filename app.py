import os
import csv
import time
from datetime import datetime
import threading
import webbrowser
import matplotlib
matplotlib.use('Agg') # GUI 없이 이미지 생성 (필수)
import matplotlib.pyplot as plt
from flask import Flask, request, jsonify, render_template, send_from_directory

app = Flask(__name__)

# --- 1. 환경 설정 및 폴더 자동 생성 ---
BASE_DIR = os.path.dirname(os.path.abspath(__name__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
RESULTS_DIR = os.path.join(BASE_DIR, 'results')
GRAPHS_DIR = os.path.join(BASE_DIR, 'graphs')
TEMPLATE_DIR = os.path.join(BASE_DIR, 'templates')
CSV_FILE = os.path.join(DATA_DIR, 'autoscore.csv')

# 필요한 폴더들이 없으면 알아서 만듭니다.
for directory in [DATA_DIR, RESULTS_DIR, GRAPHS_DIR, TEMPLATE_DIR]:
    if not os.path.exists(directory):
        os.makedirs(directory)

# 데이터베이스 역할을 할 CSV 파일 초기화
if not os.path.exists(CSV_FILE):
    with open(CSV_FILE, mode='w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['date', 'subject', 'qcnt', 'ac', 'wrong', 'timer', 'qpm', 'mpq', 'accuracy'])

# --- 2. 타이머 상태 변수 ---
# 주의: time.sleep() 금지 요구사항 반영! time.time()으로 timestamp만 기록합니다.
session_state = {
    "start_time": None,
    "is_running": False
}

# --- 3. 라우팅 (화면 및 이미지 제공) ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/graphs/<path:filename>')
def serve_graphs(filename):
    return send_from_directory(GRAPHS_DIR, filename)

@app.route('/results/<path:filename>')
def serve_results(filename):
    return send_from_directory(RESULTS_DIR, filename)

# --- 4. API 엔드포인트 ---
@app.route('/api/start', methods=['POST'])
def api_start():
    data = request.get_json()
    subject = data.get('subject', '').strip()
    if not subject:
        return jsonify({"success": False, "error": "과목을 입력해주세요."}), 400
        
    session_state["start_time"] = time.time()
    session_state["is_running"] = True
    return jsonify({"success": True, "message": "Timer started."})

@app.route('/api/stop', methods=['POST'])
def api_stop():
    if not session_state["is_running"] or session_state["start_time"] is None:
        return jsonify({"success": False, "error": "타이머가 실행 중이 아닙니다."}), 400
        
    # 실제 소요 시간(초) 계산
    elapsed_time = time.time() - session_state["start_time"]
    session_state["is_running"] = False
    session_state["start_time"] = None
    
    return jsonify({"success": True, "timer": elapsed_time})

@app.route('/api/analyze', methods=['POST'])
def api_analyze():
    data = request.get_json()
    subject = data.get('subject', '').strip()
    
    try:
        qcnt = int(data.get('qcnt', 0))
        ac = int(data.get('ac', 0))
        timer = float(data.get('timer', 0.0))
    except ValueError:
        return jsonify({"success": False, "error": "숫자를 입력해주세요."}), 400
        
    # 방어 로직
    if qcnt < 1: return jsonify({"success": False, "error": "문제 수는 1 이상입니다."}), 400
    if ac < 0 or ac > qcnt: return jsonify({"success": False, "error": "정답 수를 확인하세요."}), 400
    
    # [수정됨] 타이머가 0초일 때 발생하는 0 나누기(ZeroDivisionError) 에러 방지
    timer = max(timer, 0.001)
    
    # 통계 계산 (소수점 정밀 계산 / 사용)
    wrong = qcnt - ac
    accuracy = (ac / qcnt) * 100
    qpm = qcnt / (timer / 60)
    mpq = timer / qcnt
    
    now = datetime.now()
    date_str_csv = now.strftime('%Y-%m-%d')
    date_str_file = now.strftime('%Y-%m-%d_%H-%M-%S')
    
    # [데이터 저장] 껐다 켜도 안 날아가게 CSV에 누적 기록합니다!
    with open(CSV_FILE, mode='a', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([date_str_csv, subject, qcnt, ac, wrong, timer, qpm, mpq, accuracy])
        
    # TXT 리포트 생성
    txt_filename = f"{date_str_file}.txt"
    report_content = f"""================================\n        AUTOSCORE V2\n================================\n과목           : {subject}\n[RESULT]\n문제 수        : {qcnt}\n정답 수        : {ac}\n오답 수        : {wrong}\n정답률         : {accuracy:.2f}%\n[TIME]\n총 소요 시간   : int({timer//60})분 int({timer%60})초\n분당 문제 수   : {qpm:.2f}문제\n1문제당 시간   : {mpq:.2f}초\n================================"""
    with open(os.path.join(RESULTS_DIR, txt_filename), mode='w', encoding='utf-8') as f:
        f.write(report_content)
        
    # 그래프 갱신
    generate_graphs()
    
    return jsonify({
        "success": True,
        "results": {
            "subject": subject, "qcnt": qcnt, "ac": ac, "wrong": wrong,
            "accuracy": accuracy, "timer": timer, "qpm": qpm, "mpq": mpq, "txt_file": txt_filename
        }
    })

@app.route('/api/dashboard', methods=['GET'])
def api_dashboard():
    # CSV 파일을 읽어서 대시보드 데이터를 프론트로 넘겨줍니다.
    records = []
    if os.path.exists(CSV_FILE):
        with open(CSV_FILE, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            records = list(reader)
    return jsonify({"success": True, "records": records})

# --- 5. Matplotlib 그래프 생성 엔진 ---
def generate_graphs():
    sessions, accuracies, qpms, mpqs, corrects, wrongs = [], [], [], [], [], []
    try:
        with open(CSV_FILE, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for idx, row in enumerate(reader):
                sessions.append(idx + 1)
                accuracies.append(float(row['accuracy']))
                qpms.append(float(row['qpm']))
                mpqs.append(float(row['mpq']))
                corrects.append(int(row['ac']))
                wrongs.append(int(row['wrong']))
    except Exception as e:
        return

    if not sessions: return

    plt.style.use('bmh')
    
    # 1. Accuracy Graph
    plt.figure(figsize=(6, 4))
    plt.plot(sessions, accuracies, marker='o', color='#4f46e5', linewidth=2)
    plt.title('Accuracy (%)')
    plt.tight_layout()
    plt.savefig(os.path.join(GRAPHS_DIR, 'accuracy.png'))
    plt.close()

    # 2. QPM Graph
    plt.figure(figsize=(6, 4))
    plt.plot(sessions, qpms, marker='o', color='#10b981', linewidth=2)
    plt.title('QPM (Questions Per Min)')
    plt.tight_layout()
    plt.savefig(os.path.join(GRAPHS_DIR, 'qpm.png'))
    plt.close()

    # [추가됨] 3. MPQ Graph
    plt.figure(figsize=(6, 4))
    plt.plot(sessions, mpqs, marker='o', color='#f59e0b', linewidth=2)
    plt.title('MPQ (Sec Per Question)')
    plt.tight_layout()
    plt.savefig(os.path.join(GRAPHS_DIR, 'mpq.png'))
    plt.close()

    # [추가됨] 4. Correct vs Wrong Bar Graph
    plt.figure(figsize=(6, 4))
    width = 0.35
    x = range(len(sessions))
    plt.bar([i - width/2 for i in x], corrects, width, label='Correct', color='#3b82f6')
    plt.bar([i + width/2 for i in x], wrongs, width, label='Wrong', color='#ef4444')
    plt.title('Correct vs Wrong')
    plt.legend()
    plt.tight_layout()
    plt.savefig(os.path.join(GRAPHS_DIR, 'correct_wrong.png'))
    plt.close()
    
    # [추가됨] Matplotlib 메모리 누수 방지
    plt.close('all')

def open_browser():
    time.sleep(1.5)
    webbrowser.open_new("http://127.0.0.1:5000")

if __name__ == '__main__':
    threading.Thread(target=open_browser).start()
    app.run(host='127.0.0.1', port=5000, debug=False)