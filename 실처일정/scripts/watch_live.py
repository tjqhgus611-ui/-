# -*- coding: utf-8 -*-
"""주요일정 1차 초안 10분 단위 갱신

사용법: python -I watch_live.py YYYY-MM-DD HH:MM [원본폴더]
  YYYY-MM-DD : 주요일정 대상 날짜
  HH:MM      : 오늘 이 시각의 확인까지 하고 종료 (확인은 매시 00·10·20·30·40·50분, 시작 시 1회)
  원본폴더    : (선택) 사용자가 실처 HWP/HWPX를 넣는 폴더. 새로 들어오거나 바뀐 파일을
               수신/ 폴더로 HWPX 변환·복사한다 (원본은 그대로)

10분마다(매시 00·10·20·30·40·50분) 입력(원본폴더, 수신/, 주간 임원일정, 양식)을 확인해 바뀌었으면
취합본과 미리보기(미리보기_최신.png)를 다시 만든다.
승인 후에 들어온 변경도 반영한다. 취합본이 바뀌면 발송승인.txt 해시와 달라져 승인이 풀리고, 다시 승인해야 발송된다.
"""
import sys, os, glob, time, shutil, subprocess, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
ROOT = os.path.dirname(BASE)
target, end_hm = sys.argv[1], sys.argv[2]
src_dir = os.path.abspath(sys.argv[3]) if len(sys.argv) > 3 else None
ddir = os.path.join(BASE, target)
recv = os.path.join(ddir, '수신')
os.makedirs(recv, exist_ok=True)
end = datetime.datetime.combine(datetime.date.today(), datetime.time.fromisoformat(end_hm))
status_path = os.path.join(ddir, '갱신_상태.md')
env = dict(os.environ, PYTHONIOENCODING='utf-8')
INTERVAL = 10   # 확인 주기(분). 60의 약수로 둔다


def log(msg):
    line = f"{datetime.datetime.now():%H:%M:%S} {msg}"
    print(line, flush=True)
    with open(status_path, 'a', encoding='utf-8') as f:
        f.write(f'- {line}\n')


def sync_source():
    """원본폴더의 새/변경 파일을 수신/으로 (HWP는 HWPX로 변환)"""
    if not src_dir or not os.path.isdir(src_dir):
        return
    for f in glob.glob(os.path.join(src_dir, '*')):
        name, ext = os.path.splitext(os.path.basename(f))
        ext = ext.lower()
        if name.startswith('~') or ext not in ('.hwp', '.hwpx'):
            continue
        dst = os.path.join(recv, name + '.hwpx')
        if os.path.exists(dst) and os.path.getmtime(dst) >= os.path.getmtime(f):
            continue
        if ext == '.hwpx':
            shutil.copy2(f, dst)
            log(f'복사: {os.path.basename(f)}')
            continue
        r = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                            os.path.join(HERE, 'hwp_to_hwpx.ps1'), f, dst], capture_output=True, timeout=200)
        out = r.stdout.decode('cp949', 'replace')
        if 'converted' in out and os.path.exists(dst):
            os.utime(dst)   # 변환본이 원본보다 새로움을 표시
            log(f'HWP→HWPX 변환: {os.path.basename(f)}')
        else:
            log(f'변환 실패(다음 확인 때 재시도): {os.path.basename(f)}')


def signature():
    files = glob.glob(os.path.join(recv, '*')) + glob.glob(os.path.join(BASE, '주간임원일정', '*.json')) \
        + [os.path.join(ROOT, '고객사업본부 주요일정_양식.hwpx')]
    return tuple(sorted((f, os.path.getmtime(f), os.path.getsize(f)) for f in files if os.path.isfile(f)))


def rebuild():
    r = subprocess.run([sys.executable, '-I', os.path.join(HERE, 'build_schedule.py'), target],
                       capture_output=True, env=env, timeout=120)
    out = r.stdout.decode('utf-8', 'replace')
    if r.returncode != 0:
        err = r.stderr.decode('utf-8', 'replace')
        if 'PermissionError' in err:
            log('취합본이 한글에서 열려 있어 바꾸지 못함 — 파일을 닫으면 다음 확인 때 반영')
        else:
            log('취합 오류: ' + err[-300:].replace('\n', ' '))
        return False
    if 'CHANGED=True' not in out:
        return True
    summary = [l for l in out.splitlines() if l.startswith(('- 실처 반영', '- 미회신', '- 확인 필요'))]
    log('초안 갱신 → ' + ' / '.join(s[2:] for s in summary))
    hw = os.path.join(ddir, f'일정취합_{target}.hwpx')
    bmp = os.path.join(ddir, '미리보기_최신.bmp')
    try:
        rr = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                             os.path.join(HERE, 'render_page.ps1'), hw, bmp], capture_output=True, timeout=200)
        if 'open=True' in rr.stdout.decode('cp949', 'replace') and os.path.exists(bmp):
            from PIL import Image
            Image.open(bmp).save(os.path.join(ddir, '미리보기_최신.png'))
            os.remove(bmp)
            log('미리보기_최신.png 갱신 (한글에서 열림 확인)')
        else:
            log('미리보기 생성 실패 (한글 열기 실패) — 다음 변경 때 재시도')
    except subprocess.TimeoutExpired:
        log('미리보기 생성 시간 초과')
    return True


log(f'{INTERVAL}분 단위 갱신 시작 (대상 {target}, {end_hm} 종료, 원본폴더 {src_dir or "없음"})')
last = None


def check():
    global last
    try:
        sync_source()
        sig = signature()
        approved = os.path.exists(os.path.join(ddir, '발송승인.txt'))
        if sig == last:
            log('변경 없음')
        else:
            if approved and last is not None:
                log('승인 후 새 변경 감지 — 취합본을 다시 만듦. 바뀐 취합본은 승인이 풀리므로 다시 승인해야 발송됨')
            if rebuild():   # 실패(파일 열림 등)면 다음 확인 때 다시 시도
                last = sig
    except Exception as ex:
        log(f'오류: {ex!r}')


def next_slot(now):
    m = (now.minute // INTERVAL + 1) * INTERVAL
    return now.replace(minute=0, second=0, microsecond=0) + datetime.timedelta(minutes=m)


check()   # 시작 시 1회
while True:
    slot = next_slot(datetime.datetime.now())
    if slot > end:
        break
    time.sleep(max(0, (slot - datetime.datetime.now()).total_seconds()))
    check()
log(f'{INTERVAL}분 단위 갱신 종료')
