# -*- coding: utf-8 -*-
"""주요일정 취합 도우미 — 시제품 1단계 (현황 보기, 읽기 전용)

실행: python -I 웹앱/app.py   → http://127.0.0.1:8765
- 내 PC에서만 접속 (127.0.0.1)
- 실처일정/ 폴더의 데이터를 읽기만 한다. 취합·승인·발송은 하지 않는다.
"""
import os, re, json, glob, hashlib, datetime, importlib.util, mimetypes
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
# SCHEDULE_DEMO=1 이면 발표용 데이터(발표용/실처일정)를 보여 준다
DEMO = os.environ.get('SCHEDULE_DEMO') == '1'
BASE = os.environ.get('SCHEDULE_BASE') or os.path.join(ROOT, '발표용' if DEMO else '', '실처일정')
PORT = int(os.environ.get('SCHEDULE_PORT') or (8766 if DEMO else 8765))

spec = importlib.util.spec_from_file_location('build', os.path.join(ROOT, '실처일정', 'scripts', 'build_schedule.py'))
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)
DEPTS, ALIASES = build.DEPTS, build.ALIASES
DEADLINE_REPLY, DEADLINE_SHARE = '14:00', '17:30'


def fmt(ts):
    return datetime.datetime.fromtimestamp(ts).strftime('%H:%M') if ts else None


def day_dirs():
    return sorted(d for d in os.listdir(BASE) if re.fullmatch(r'\d{4}-\d{2}-\d{2}', d))


def source_dir_for(target):
    """원본 폴더(예: 261119) — 대상 날짜의 YYMMDD 이름"""
    d = datetime.date.fromisoformat(target)
    p = os.path.join(ROOT, d.strftime('%y%m%d'))
    return p if os.path.isdir(p) else None


def dept_status(target):
    ddir = os.path.join(BASE, target)
    recv = sorted(glob.glob(os.path.join(ddir, '수신', '*.hwpx')), key=os.path.getmtime)
    src = source_dir_for(target)
    per = {d: [] for d in DEPTS}
    unknown = []
    for p in recv:
        stem = os.path.splitext(os.path.basename(p))[0]
        got = {}
        try:
            got = build.extract_dept(p)
        except Exception as ex:
            unknown.append({'file': os.path.basename(p), 'reason': f'읽기 실패: {ex}'})
            continue
        fname = build.norm(os.path.basename(p))
        named = [d for d in DEPTS if any(a in fname for a in ALIASES[d])]
        dept = None
        if named and named[0] in got:
            dept = named[0]
        elif not named and len(got) == 1:
            dept = list(got)[0]
        if not dept:
            unknown.append({'file': os.path.basename(p), 'reason': '어느 실처 파일인지 판별 불가'})
            continue
        # 받은 시각: 원본 폴더의 같은 이름 파일(HWP/HWPX) 수정 시각, 없으면 수신 파일 시각
        orig = None
        if src:
            for ext in ('.hwp', '.hwpx'):
                c = os.path.join(src, stem + ext)
                if os.path.exists(c):
                    orig = c
        t = os.path.getmtime(orig or p)
        first = got[dept][0].strip() if got[dept] else ''
        per[dept].append({'file': os.path.basename(orig or p), 'time': fmt(t), 'ts': t,
                          'items': sum(1 for l in got[dept] if l.strip().startswith(('o ', 'ㅇ', '○'))),
                          'first': first})
    rows = []
    for d in DEPTS:
        fs = sorted(per[d], key=lambda x: x['ts'])
        rows.append({'dept': d, 'received': bool(fs), 'time': fs[-1]['time'] if fs else None,
                     'versions': len(fs), 'file': fs[-1]['file'] if fs else None,
                     'items': fs[-1]['items'] if fs else 0, 'first': fs[-1]['first'] if fs else ''})
    # 원본 폴더에 있지만 아직 수신/으로 변환되지 않은 파일
    pending = []
    if src:
        done = {os.path.splitext(os.path.basename(p))[0] for p in recv}
        for f in glob.glob(os.path.join(src, '*')):
            stem, ext = os.path.splitext(os.path.basename(f))
            if ext.lower() in ('.hwp', '.hwpx') and not stem.startswith('~') and stem not in done:
                pending.append({'file': os.path.basename(f), 'reason': '아직 변환·반영 전 (다음 10분 갱신 때 처리)'})
    return rows, unknown + pending


def exec_status(target):
    wfile, wdata, events = build.load_weekly(target)
    if not wfile:
        return {'file': None}
    return {'file': os.path.basename(wfile), 'updated': datetime.datetime.fromtimestamp(
        os.path.getmtime(wfile)).strftime('%m/%d %H:%M'), 'source': wdata.get('source', ''),
        'count': len(events),
        'events': [{'time': e['time'], 'title': e['title'], 'who': e['who']} for e in sorted(events, key=lambda e: e['time'])]}


def stage(target):
    ddir = os.path.join(BASE, target)
    out = os.path.join(ddir, f'일정취합_{target}.hwpx')
    log = open(os.path.join(ddir, '처리기록.md'), encoding='utf-8').read() if os.path.exists(os.path.join(ddir, '처리기록.md')) else ''
    approved_ok = False
    appr = os.path.join(ddir, '발송승인.txt')
    if os.path.exists(appr) and os.path.exists(out):
        m = re.search(r'sha256=([0-9a-f]{64})', open(appr, encoding='utf-8').read())
        approved_ok = bool(m) and m.group(1) == hashlib.sha256(open(out, 'rb').read()).hexdigest()
    steps = [
        {'name': '요청', 'done': True, 'note': '09:00 메신저 (수동)'},
        {'name': '취합', 'done': os.path.exists(out),
         'note': '최종 갱신 ' + fmt(os.path.getmtime(out)) if os.path.exists(out) else '아직 없음'},
        {'name': '승인', 'done': approved_ok,
         'note': '승인됨' if approved_ok else ('승인 후 파일 변경됨' if os.path.exists(appr) else '대기')},
        {'name': '발송', 'done': '메일 발송' in log, 'note': '완료' if '메일 발송' in log else '대기'},
    ]
    return steps


def changes(target):
    ddir = os.path.join(BASE, target)
    items = []
    p = os.path.join(ddir, '처리기록.md')
    if os.path.exists(p):
        for block in open(p, encoding='utf-8').read().split('## ')[1:]:
            lines = block.strip().splitlines()
            head = lines[0]
            detail = [l[2:] for l in lines[1:] if l.startswith(('- 실처 반영', '- 미회신', '- 주간 임원일정', '- 출력'))]
            items.append({'time': head, 'detail': detail})
    p = os.path.join(ddir, '갱신_상태.md')
    upd = [l[2:] for l in open(p, encoding='utf-8').read().splitlines() if l.startswith('- ')] if os.path.exists(p) else []
    return items[-6:][::-1], upd[-8:][::-1]


def status(target):
    rows, check = dept_status(target)
    log, upd = changes(target)
    ddir = os.path.join(BASE, target)
    prev = None
    for n in ('미리보기_최신.png', '미리보기_사전.png'):
        if os.path.exists(os.path.join(ddir, n)):
            prev = n
            break
    d = datetime.date.fromisoformat(target)
    return {'target': target, 'target_label': f'{d.month}/{d.day}({"월화수목금토일"[d.weekday()]})',
            'days': day_dirs(), 'depts': rows, 'exec': exec_status(target), 'steps': stage(target),
            'check': check, 'log': log, 'updates': upd, 'preview': prev,
            'deadlines': {'reply': DEADLINE_REPLY, 'share': DEADLINE_SHARE},
            'demo': DEMO,
            'now': datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}


class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        days = day_dirs()
        target = q.get('date', [days[-1] if days else datetime.date.today().isoformat()])[0]
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', target):
            return self._send(400, b'bad date', 'text/plain')
        if u.path == '/':
            return self._send(200, open(os.path.join(HERE, 'index.html'), 'rb').read(), 'text/html; charset=utf-8')
        if u.path == '/api/status':
            try:
                body = json.dumps(status(target), ensure_ascii=False).encode('utf-8')
                return self._send(200, body, 'application/json; charset=utf-8')
            except Exception as ex:
                return self._send(500, json.dumps({'error': repr(ex)}, ensure_ascii=False).encode('utf-8'),
                                  'application/json; charset=utf-8')
        if u.path == '/preview':
            name = q.get('name', [''])[0]
            if name not in ('미리보기_최신.png', '미리보기_사전.png'):
                return self._send(404, b'', 'text/plain')
            p = os.path.join(BASE, target, name)
            if os.path.exists(p):
                return self._send(200, open(p, 'rb').read(), 'image/png')
        return self._send(404, b'not found', 'text/plain')

    def log_message(self, *a):
        pass


if __name__ == '__main__':
    print(f'주요일정 취합 도우미 시제품: http://127.0.0.1:{PORT}', flush=True)
    ThreadingHTTPServer(('127.0.0.1', PORT), H).serve_forever()
