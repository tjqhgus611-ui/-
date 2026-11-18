# -*- coding: utf-8 -*-
"""발표용 정지 화면(배포용/) 만들기

실행: python -I 웹앱/export_demo.py
- 발표용/실처일정/ 의 날짜별 예시 데이터로 배포용/status-YYYY-MM-DD.json, preview-YYYY-MM-DD.png 생성
- 웹앱/index.html 을 정지 화면용으로 고쳐 배포용/index.html 로 저장
- 실제 업무 데이터(실처일정/)는 읽지 않는다
"""
import os, json, shutil, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, '배포용')
os.environ['SCHEDULE_DEMO'] = '1'
os.environ.pop('SCHEDULE_BASE', None)

sp = importlib.util.spec_from_file_location('app', os.path.join(HERE, 'app.py'))
app = importlib.util.module_from_spec(sp); sp.loader.exec_module(app)
assert app.BASE.endswith(os.path.join('발표용', '실처일정')), app.BASE
assert app.build.BASE == app.BASE

os.makedirs(OUT, exist_ok=True)
for f in os.listdir(OUT):   # 이전 결과 정리 (설정 파일은 유지)
    if f.startswith(('status', 'preview', 'hwpx-')) and f.endswith(('.json', '.png', '.hwpx')):
        os.remove(os.path.join(OUT, f))

days = app.day_dirs()
for d in days:
    st = app.status(d)
    st['days'] = days
    # 발표용 수신 파일에는 원본 폴더가 없으므로 원본 폴더 관련 항목은 쓰지 않음
    json.dump(st, open(os.path.join(OUT, f'status-{d}.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    hw = os.path.join(app.BASE, d, f'일정취합_{d}.hwpx')
    if os.path.exists(hw):
        shutil.copy2(hw, os.path.join(OUT, f'hwpx-{d}.hwpx'))
    if st['preview']:
        shutil.copy2(os.path.join(app.BASE, d, st['preview']), os.path.join(OUT, f'preview-{d}.png'))
    print('exported', d)

h = open(os.path.join(HERE, 'index.html'), encoding='utf-8').read()
reps = [
    ("const url = '/api/status' + (selected ? '?date=' + selected : '');",
     f"const url = 'status-' + (selected || '{days[-1]}') + '.json';"),
    ("`<img alt=\"취합본 미리보기\" src=\"/preview?date=${s.target}&name=${encodeURIComponent(s.preview)}&t=${Date.now()}\">`",
     "`<img alt=\"취합본 미리보기\" src=\"preview-${s.target}.png\">`"),
    ('<span class="tag" id="modeTag">시제품 · 현황 보기 (읽기 전용)</span>',
     '<span class="tag" id="modeTag">발표용 화면 (예시 데이터, 저장된 화면)</span>'),
    ("  if (s.demo) { $('modeTag').textContent = '발표용'; $('modeTag').style.background = 'var(--wait-bg)'; }\n", ""),
    ("<title>주요일정 취합 도우미</title>",
     "<title>주요일정 취합 도우미 (발표용)</title>\n<meta name=\"robots\" content=\"noindex, nofollow\">"),
    ("setInterval(load, 60000);\n", ""),
    ("[한글로 열기] 외의 버튼은 화면 배치를 보기 위한 자리입니다. 시제품에서는 동작하지 않습니다.",
     "발표용 화면입니다. 표시된 일정은 모두 예시이며, [한글 파일 내려받기] 외의 버튼은 동작하지 않습니다."),
    # 인터넷 화면에서는 PC의 한글을 실행할 수 없으므로 예시 취합본 내려받기로 대신함
    ("const STATIC_DOWNLOAD = false;", "const STATIC_DOWNLOAD = true;"),
    ('title="취합본을 PC의 한글로 엽니다">한글로 열기</button>', 'title="예시 취합본(HWPX)을 내려받습니다">한글 파일 내려받기</button>'),
    # 발송까지 끝난 날짜는 남은 시간 대신 '완료' 표시
    ("  if (!state) return;\n",
     "  if (!state) return;\n  if (state.steps[state.steps.length - 1].done) {\n"
     "    $('deadlines').innerHTML = ['회신 기한', '메일 공유'].map((l) => `<div class=\"dl past\"><div class=\"t\">${l}</div><div class=\"v\">완료</div></div>`).join('');\n"
     "    return;\n  }\n"),
]
for a, b in reps:
    assert a in h, a
    h = h.replace(a, b)
open(os.path.join(OUT, 'index.html'), 'w', encoding='utf-8').write(h)

# 실제 자료 단어 검사: 검사할 단어는 GitHub에 올리지 않는 로컬 파일(웹앱/검사단어.txt, 한 줄에 하나)에 둔다
bad_words = ['Users\\', 'Users/']
wl = os.path.join(HERE, '검사단어.txt')
if os.path.exists(wl):
    bad_words += [w.strip() for w in open(wl, encoding='utf-8-sig') if w.strip()]
else:
    print('경고: 웹앱/검사단어.txt 가 없어 PC 경로만 검사합니다')
import zipfile
for f in os.listdir(OUT):
    if f.endswith(('.json', '.html', '.hwpx')):
        if f.endswith('.hwpx'):   # 한글 파일은 압축 안의 글자(본문·미리보기 글) 전체 검사
            z = zipfile.ZipFile(os.path.join(OUT, f))
            t = ''.join(z.read(n).decode('utf-8', 'replace') for n in z.namelist() if n.endswith(('.xml', '.txt', '.hpf', '.rdf')))
        else:
            t = open(os.path.join(OUT, f), encoding='utf-8').read()
        hit = [w for w in bad_words if w in t]
        assert not hit, (f, hit)
print('check ok:', sorted(os.listdir(OUT)))
