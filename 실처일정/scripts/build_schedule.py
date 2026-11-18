# -*- coding: utf-8 -*-
"""고객사업본부 주요일정 취합본 생성

사용법: python -I build_schedule.py YYYY-MM-DD   (YYYY-MM-DD = 주요일정 대상 날짜 = 공유일 다음 날)

입력
  - 양식: <프로젝트>/고객사업본부 주요일정_양식.hwpx
  - 주간 임원일정: 실처일정/주간임원일정/*.json (대상 날짜를 포함하는 가장 최근 파일)
  - 실처 회신: 실처일정/<날짜>/수신/*.hwpx  (양식 전체에 자기 실처 칸을 채운 파일)
출력
  - 실처일정/<날짜>/일정취합_<날짜>.hwpx
  - 실처일정/<날짜>/처리기록.md (실행 기록 추가)
  - 표준출력: 요약
원본 파일(양식, 수신 파일)은 수정하지 않는다.
"""
import sys, os, re, json, glob, zipfile, datetime, hashlib
from xml.sax.saxutils import escape

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
# SCHEDULE_BASE 환경변수로 작업 폴더를 바꿀 수 있다 (발표용 가상 데이터 등). 기본은 실처일정/
BASE = os.environ.get('SCHEDULE_BASE') or os.path.join(ROOT, '실처일정')
TEMPLATE = os.path.join(ROOT, '고객사업본부 주요일정_양식.hwpx')

TOP_ROWS = {  # 주요일정 위쪽 행 이름 -> rowAddr (양식 기준)
    '임원공통': 1, '사장': 2, '상임감사': 3, '경영부사장': 4, '기술부사장': 5,
    '관리': 6, '고객사업': 7, 'AI디지털': 8, '도로': 9, '교통': 10, '건설': 11, '신사업': 12, '도교원': 13,
}
WEEKLY_TO_ROW = {'사장': '사장', '감사': '상임감사', '경영부사장': '경영부사장', '관리': '관리',
                 '고객사업': '고객사업', 'AI디지털': 'AI디지털', '도로': '도로', '교통': '교통',
                 '건설': '건설', '신사업': '신사업', '도교원': '도교원'}
DEPTS = ['통행료정책처', '통행료시스템처', '통행료정산센터', '휴게사업처', '휴게소혁신추진단']
WEEKDAY = '월화수목금토일'
# 파일명에 아래 단어 중 하나가 들어 있으면 그 실처 파일로 인식
ALIASES = {
    '통행료정책처': ['통행료정책처', '정책처', '정책'],
    '통행료시스템처': ['통행료시스템처', '시스템처', '시스템'],
    '통행료정산센터': ['통행료정산센터', '정산센터', '정산'],
    '휴게사업처': ['휴게사업처', '휴게사업'],
    '휴게소혁신추진단': ['휴게소혁신추진단', '혁신추진단', '혁신'],
}


def norm(s):
    return re.sub(r'[\s/·()]', '', s)


def cell_text_paras(tc_xml):
    """셀 안 문단별 텍스트 목록"""
    out = []
    for p in re.findall(r'<hp:p [^>]*>.*?</hp:p>', tc_xml, re.S):
        ts = re.findall(r'<hp:t>(.*?)</hp:t>', p, re.S)
        txt = ''.join(re.sub(r'<[^>]+>', '', t) for t in ts)
        txt = txt.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
        out.append(txt)
    return out


def iter_tcs(sec):
    for m in re.finditer(r'<hp:tc .*?</hp:tc>', sec, re.S):
        t = m.group(0)
        a = re.search(r'colAddr="(\d+)" rowAddr="(\d+)"', t)
        yield m.start(), m.end(), int(a.group(1)), int(a.group(2)), t


def main_table_span(sec):
    """본표(colCnt=4) 범위 — 제목 표와 섞이지 않게"""
    m = re.search(r'<hp:tbl [^>]*colCnt="4"', sec)
    end = sec.find('</hp:tbl>', m.start())
    return m.start(), end


def find_cell(sec, col, row):
    s0, s1 = main_table_span(sec)
    for a, b, c, r, t in iter_tcs(sec[s0:s1]):
        if c == col and r == row:
            return s0 + a, s0 + b, t
    raise KeyError((col, row))


# ---------- header: 굵게 / 위첨자 글자모양 추가 ----------
def add_charprs(header, base_id):
    m = re.search(r'<hh:charPr id="%d" .*?</hh:charPr>' % base_id, header, re.S)
    base = m.group(0)
    ids = [int(x) for x in re.findall(r'<hh:charPr id="(\d+)"', header)]
    nid = max(ids) + 1
    bold = re.sub(r'id="\d+"', f'id="{nid}"', base, count=1)
    bold = re.sub(r'<hh:bold/>', '', bold)
    for anchor in ('<hh:underline', '<hh:strikeout', '<hh:outline', '<hh:shadow', '</hh:charPr>'):
        if anchor in bold:
            bold = bold.replace(anchor, '<hh:bold/>' + anchor, 1)
            break
    sup = re.sub(r'id="\d+"', f'id="{nid + 1}"', base, count=1)
    sup = re.sub(r'<hh:bold/>', '', sup)
    # 위첨자: <hh:supscript/>는 한글 2020이 열지 못해(오류 확인), 글자 크기 60%·위로 올림으로 표현
    sup = re.sub(r'<hh:relSz [^>]*/>', '<hh:relSz ' + ' '.join(f'{l}="60"' for l in
                 ['hangul', 'latin', 'hanja', 'japanese', 'other', 'symbol', 'user']) + '/>', sup)
    sup = re.sub(r'<hh:offset [^>]*/>', '<hh:offset ' + ' '.join(f'{l}="-40"' for l in
                 ['hangul', 'latin', 'hanja', 'japanese', 'other', 'symbol', 'user']) + '/>', sup)
    header = header.replace('</hh:charProperties>', bold + sup + '</hh:charProperties>')
    header = re.sub(r'<hh:charProperties itemCnt="(\d+)"',
                    lambda mm: f'<hh:charProperties itemCnt="{int(mm.group(1)) + 2}"', header, count=1)
    return header, nid, nid + 1


def runs(segments):
    """segments: [(charPrID, text)]"""
    return ''.join(f'<hp:run charPrIDRef="{c}"><hp:t>{escape(t)}</hp:t></hp:run>' for c, t in segments if t)


_pid = [900000]
def para(ppr, segments, empty_cpr):
    _pid[0] += 1
    body = runs(segments) or f'<hp:run charPrIDRef="{empty_cpr}"/>'
    return (f'<hp:p id="{_pid[0]}" paraPrIDRef="{ppr}" styleIDRef="0" pageBreak="0" '
            f'columnBreak="0" merged="0">{body}</hp:p>')


def set_cell(sec, col, row, para_specs):
    """para_specs: [[(charPrID, text), ...], ...] — 셀 문단 교체. 첫 문단의 문단모양을 유지"""
    a, b, t = find_cell(sec, col, row)
    first = re.search(r'<hp:p [^>]*paraPrIDRef="(\d+)"[^>]*>(.*?)</hp:p>', t, re.S)
    ppr = first.group(1)
    cpr = re.search(r'charPrIDRef="(\d+)"', first.group(2)).group(1)
    new_ps = ''.join(para(ppr, [(c if c is not None else cpr, x) for c, x in spec], cpr) for spec in para_specs)
    s0 = t.index('>', t.index('<hp:subList')) + 1
    s1 = t.index('</hp:subList>')
    t2 = t[:s0] + new_ps + t[s1:]
    sec = sec[:a] + t2 + sec[b:]
    # 내용이 셀 높이를 넘으면 한글 2020이 파일을 열다 멈춤(확인됨) → 행 높이를 미리 늘림
    need = len(para_specs) * LINE_H + 400
    return grow_row(sec, row, need), cpr


LINE_H = 1450  # 10~11pt, 줄간격 130% 기준 한 줄 높이(HWPUNIT) 여유값
MIN_DEPT_H = 2600  # 실처·공통 행 최소 높이


def clone_borderfill(header, bf_id, hide):
    """borderFill bf_id를 복제하고 hide에 든 변(top/bottom)을 없앤 새 id 반환"""
    m = re.search(r'<hh:borderFill id="%d" .*?</hh:borderFill>' % bf_id, header, re.S)
    nid = max(int(x) for x in re.findall(r'<hh:borderFill id="(\d+)"', header)) + 1
    bf = re.sub(r'id="\d+"', f'id="{nid}"', m.group(0), count=1)
    for side in hide:
        bf = re.sub(rf'<hh:{side}Border type="\w+"', f'<hh:{side}Border type="NONE"', bf)
    header = header.replace('</hh:borderFills>', bf + '</hh:borderFills>')
    header = re.sub(r'<hh:borderFills itemCnt="(\d+)"',
                    lambda mm: f'<hh:borderFills itemCnt="{int(mm.group(1)) + 1}"', header, count=1)
    return header, nid


def split_row(sec, header, row, n):
    """본표의 row 행을 n개 행으로 나눈다. 시간·주요내용 칸은 행마다 새로 만든다.
    - 일반 행(사장 등): 구분 칸을 세로 병합(rowSpan=n)
    - 이미 세로 병합된 칸('본부') 안의 행: 한글 2020이 병합 안 병합을 열지 못해(확인됨),
      구분 칸을 행마다 따로 두고 사이 가로선만 숨겨 합친 것처럼 보이게 함"""
    add = n - 1
    s0, s1 = main_table_span(sec)
    tbl = sec[s0:s1]
    # row 행의 시간(열2)·주요내용(열3) 칸 원본과 높이
    tcs = {(c, r): t for _, _, c, r, t in iter_tcs(tbl)}
    t_time, t_cont = tcs[(2, row)], tcs[(3, row)]
    h = int(re.search(r'<hp:cellSz width="\d+" height="(\d+)"', t_time).group(1))
    def rspan(t):
        return int(re.search(r'rowSpan="(\d+)"', t).group(1))
    label_c = max(c for (c, r) in tcs if r == row and c < 2)   # 구분 칸(본부 행은 열1, 임원 행은 열0)
    t_label = tcs[(label_c, row)]
    # 구분 칸 말고 이 행을 덮는 세로 병합 칸이 있으면(본부) 병합 안 병합을 피한다
    nested = any(r <= row < r + rspan(t) and rspan(t) > 1 and (c, r) != (label_c, row)
                 for (c, r), t in tcs.items())
    if nested:
        lbf = int(re.search(r'borderFillIDRef="(\d+)"', t_label).group(1))
        header, bf_first = clone_borderfill(header, lbf, ['bottom'])
        header, bf_mid = clone_borderfill(header, lbf, ['top', 'bottom'])
        header, bf_last = clone_borderfill(header, lbf, ['top'])

    def fix(m):
        t = m.group(0)
        c = int(re.search(r'colAddr="(\d+)"', t).group(1))
        r = int(re.search(r'rowAddr="(\d+)"', t).group(1))
        rs = int(re.search(r'rowSpan="(\d+)"', t).group(1))
        if r > row:                       # 아래 행: 행 번호 밀기
            t = t.replace(f'rowAddr="{r}"', f'rowAddr="{r + add}"')
        elif (c, r) == (label_c, row) and nested:   # 본부 안 행: 구분 칸 아래선 숨김
            t = re.sub(r'borderFillIDRef="\d+"', f'borderFillIDRef="{bf_first}"', t, count=1)
        elif (c, r) == (label_c, row):    # 일반 행의 구분 칸: 세로 병합
            t = t.replace(f'rowSpan="{rs}"', f'rowSpan="{rs + add}"')
            t = re.sub(r'(<hp:cellSz width="\d+" height=")(\d+)"',
                       lambda mm: f'{mm.group(1)}{int(mm.group(2)) + add * h}"', t)
        elif r <= row < r + rs and rs > 1:   # 이 행을 덮는 병합 칸('본부')
            t = t.replace(f'rowSpan="{rs}"', f'rowSpan="{rs + add}"')
            t = re.sub(r'(<hp:cellSz width="\d+" height=")(\d+)"',
                       lambda mm: f'{mm.group(1)}{int(mm.group(2)) + add * h}"', t)
        return t
    tbl = re.sub(r'<hp:tc .*?</hp:tc>', fix, tbl, flags=re.S)

    # 새 행 추가 (시간·주요내용 칸 복제)
    new_trs = ''
    for k in range(1, n):
        a = t_time.replace(f'rowAddr="{row}"', f'rowAddr="{row + k}"')
        b = t_cont.replace(f'rowAddr="{row}"', f'rowAddr="{row + k}"')
        lab = ''
        if nested:   # 빈 구분 칸 (위·아래선 숨김)
            lab = re.sub(r'<hp:t>.*?</hp:t>', '', t_label, flags=re.S).replace(
                f'rowAddr="{row}"', f'rowAddr="{row + k}"')
            lab = re.sub(r'borderFillIDRef="\d+"',
                         f'borderFillIDRef="{bf_last if k == n - 1 else bf_mid}"', lab, count=1)
        new_trs += '<hp:tr>' + lab + a + b + '</hp:tr>'
    # row 행이 들어 있는 <hp:tr> 끝에 삽입
    pos = tbl.find(f'colAddr="3" rowAddr="{row}"')
    tr_end = tbl.find('</hp:tr>', pos) + len('</hp:tr>')
    tbl = tbl[:tr_end] + new_trs + tbl[tr_end:]

    tbl = re.sub(r'rowCnt="(\d+)"', lambda mm: f'rowCnt="{int(mm.group(1)) + add}"', tbl, count=1)
    tbl = re.sub(r'(<hp:sz width="\d+" widthRelTo="\w+" height=")(\d+)"',
                 lambda mm: f'{mm.group(1)}{int(mm.group(2)) + add * h}"', tbl, count=1)
    return sec[:s0] + tbl + sec[s1:], header


def grow_row(sec, row, need, exact=False):
    """row 행 높이를 need 이상으로 늘림. exact=True면 need로 맞춤(줄이기 포함)"""
    s0, s1 = main_table_span(sec)
    tbl = sec[s0:s1]
    cur = None
    for _, _, c, r, t in iter_tcs(tbl):
        if r == row and re.search(r'rowSpan="1"', t):
            cur = int(re.search(r'<hp:cellSz width="\d+" height="(\d+)"', t).group(1))
            break
    if cur is None or need == cur or (need < cur and not exact):
        return sec
    delta = need - cur

    def fix(m):
        t = m.group(0)
        r = int(re.search(r'rowAddr="(\d+)"', t).group(1))
        rs = int(re.search(r'rowSpan="(\d+)"', t).group(1))
        if r <= row < r + rs:
            t = re.sub(r'(<hp:cellSz width="\d+" height=")(\d+)"',
                       lambda mm: f'{mm.group(1)}{int(mm.group(2)) + delta}"', t)
        return t
    tbl = re.sub(r'<hp:tc .*?</hp:tc>', fix, tbl, flags=re.S)
    tbl = re.sub(r'(<hp:sz width="\d+" widthRelTo="\w+" height=")(\d+)"',
                 lambda mm: f'{mm.group(1)}{int(mm.group(2)) + delta}"', tbl, count=1)
    return sec[:s0] + tbl + sec[s1:]


# ---------- 주간 임원일정 ----------
def load_weekly(target):
    files = sorted(glob.glob(os.path.join(BASE, '주간임원일정', '*.json')), key=os.path.getmtime, reverse=True)
    for f in files:
        d = json.load(open(f, encoding='utf-8-sig'))
        ev = [e for e in d['events'] if e['date'] == target]
        dates = {e['date'] for e in d['events']}
        if target in dates or ev:
            return f, d, ev
    return None, None, []


# ---------- 실처 회신 ----------
def extract_dept(path):
    """회신 파일에서 실처별 주요내용 문단 추출 → {실처: [문단...]}"""
    sec = zipfile.ZipFile(path).read('Contents/section0.xml').decode('utf-8')
    s0, s1 = main_table_span(sec)
    tcs = list(iter_tcs(sec[s0:s1]))
    labels = {}
    for _, _, c, r, t in tcs:
        if c == 0:
            labels[r] = norm(''.join(cell_text_paras(t)))
    out = {}
    for dept in DEPTS:
        rows = [r for r, l in labels.items() if l == norm(dept)]
        if not rows:
            continue
        for _, _, c, r, t in tcs:
            if c == 3 and r == rows[0]:
                ps = [p for p in cell_text_paras(t)]
                while ps and not ps[-1].strip():
                    ps.pop()
                if any(p.strip() for p in ps):
                    out[dept] = ps
    return out


COMMON_LABEL = '공통(참고)일정'


def extract_common(path):
    """파일의 공통(참고)일정 칸 문단 (비어 있으면 [])"""
    sec = zipfile.ZipFile(path).read('Contents/section0.xml').decode('utf-8')
    s0, s1 = main_table_span(sec)
    tcs = list(iter_tcs(sec[s0:s1]))
    rows = [r for _, _, c, r, t in tcs if c == 0 and norm(''.join(cell_text_paras(t))) == norm(COMMON_LABEL)]
    if not rows:
        return []
    for _, _, c, r, t in tcs:
        if c == 3 and r == rows[0]:
            return [p for p in cell_text_paras(t) if p.strip()]
    return []


def main():
    target = sys.argv[1]
    day = datetime.date.fromisoformat(target)
    ddir = os.path.join(BASE, target)
    os.makedirs(os.path.join(ddir, '수신'), exist_ok=True)

    z = zipfile.ZipFile(TEMPLATE)
    sec = z.read('Contents/section0.xml').decode('utf-8')
    header = z.read('Contents/header.xml').decode('utf-8')

    # 날짜
    date_txt = f'{day.year}. {day.month}. {day.day}.({WEEKDAY[day.weekday()]})'
    sec, n = re.subn(r'<hp:t>\s*20\d\d\.[^<]*\)\s*</hp:t>', f'<hp:t>{date_txt}</hp:t>', sec, count=1)
    notes = [] if n else ['양식에서 날짜 칸을 찾지 못함']

    # 굵게/위첨자 글자모양: 실처 내용 셀(행 14, 열 3)의 글자모양 기준
    _, _, t = find_cell(sec, 3, 14)
    base_cpr = int(re.search(r'charPrIDRef="(\d+)"', t).group(1))
    header, BOLD, SUP = add_charprs(header, base_cpr)

    # 위쪽 13행: 주간 임원일정
    wfile, wdata, events = load_weekly(target)
    filled_top = {}
    for e in sorted(events, key=lambda e: e['time']):
        for w in e['who']:
            row = WEEKLY_TO_ROW.get(w)
            if row:
                filled_top.setdefault(row, []).append(e)
    # (위쪽 행은 행 나누기로 행 번호가 밀리므로 실처 5행을 먼저 채운 뒤 아래 행부터 채운다)

    # 실처 5행: 수신 파일
    recv = sorted(glob.glob(os.path.join(ddir, '수신', '*.hwpx')), key=os.path.getmtime)
    skipped = [os.path.basename(p) for p in glob.glob(os.path.join(ddir, '수신', '*')) if not p.lower().endswith('.hwpx')]
    latest = {}   # 실처 -> (파일, 문단)
    unknown = []
    common_named, common_any = None, []   # 공통일정: 파일명에 '공통'이 있는 파일 우선, 없으면 실처 파일들의 공통칸 합침
    for p in recv:
        try:
            cm = extract_common(p)
        except Exception:
            cm = []
        if '공통' in norm(os.path.basename(p)):
            common_named = (p, cm)
            continue
        for l in cm:
            if l.strip() not in [x.strip() for x in common_any]:
                common_any.append(l)
        try:
            got = extract_dept(p)
        except Exception as ex:
            unknown.append(f'{os.path.basename(p)} (읽기 실패: {ex})'); continue
        fname = norm(os.path.basename(p))
        named = [d for d in DEPTS if any(a in fname for a in ALIASES[d])]
        if named:
            for d in named:
                if d in got:
                    latest[d] = (p, got[d])
                else:
                    unknown.append(f'{os.path.basename(p)} ({d} 칸이 비어 있음)')
        elif len(got) == 1:
            d = list(got)[0]; latest[d] = (p, got[d])
        else:
            unknown.append(f'{os.path.basename(p)} (어느 실처 파일인지 판별 불가: 채워진 칸 {list(got) or "없음"})')
    for i, dept in enumerate(DEPTS):
        if dept in latest:
            ps = latest[dept][1]
            specs = []
            for line in ps:
                s = line.strip()
                bold = s.startswith(('o ', 'ㅇ ', '○', 'o ')) or s == 'o'
                specs.append([(BOLD if bold else None, line)])
            sec, _ = set_cell(sec, 3, 14 + i, specs)
    common = common_named[1] if common_named else common_any
    if common:
        sec, _ = set_cell(sec, 3, 14 + len(DEPTS), [[(None, l)] for l in common])
    # 실처·공통 행 높이를 내용에 맞춤 (양식의 고정 높이로 표가 한 쪽을 넘어 통째로 다음 쪽으로 밀리는 것 방지)
    for i, dept in enumerate(DEPTS):
        lines = len(latest[dept][1]) if dept in latest else 0
        sec = grow_row(sec, 14 + i, max(MIN_DEPT_H, lines * LINE_H + 400), exact=True)
    sec = grow_row(sec, 14 + len(DEPTS), max(MIN_DEPT_H, len(common) * LINE_H + 400), exact=True)   # 공통(참고)일정
    # 그래도 한 쪽을 넘으면 표가 쪽 경계에서 나뉘도록 '글자처럼 취급' 해제
    s0, _ = main_table_span(sec)
    pos_end = sec.find('/>', sec.find('<hp:pos ', s0))
    sec = sec[:s0] + sec[s0:pos_end].replace('treatAsChar="1"', 'treatAsChar="0"') + sec[pos_end:]

    # 위쪽 13행 채우기: 아래 행부터. 한 행에 일정이 여러 건이면 건마다 행을 나눠 가로줄로 구분
    for row, evs in sorted(filled_top.items(), key=lambda kv: -TOP_ROWS[kv[0]]):
        r = TOP_ROWS[row]
        if len(evs) > 1:
            sec, header = split_row(sec, header, r, len(evs))
        for k, e in enumerate(evs):
            sec, _ = set_cell(sec, 2, r + k, [[(None, e['time'])]])
            sec, _ = set_cell(sec, 3, r + k, [[(None, f"o {e['title']}({e['place']}"),
                                               (SUP, e.get('sup', '')), (None, ')')]])

    # 저장
    out = os.path.join(ddir, f'일정취합_{target}.hwpx')
    # 같은 입력이면 같은 파일(같은 해시)이 나오도록 zip 시각을 고정 → 승인 후 재실행해도 승인이 유지됨
    tmp = out + '.tmp'
    with zipfile.ZipFile(tmp, 'w') as zo:
        for item in z.infolist():
            data = z.read(item.filename)
            if item.filename == 'Contents/section0.xml':
                data = sec.encode('utf-8')
            elif item.filename == 'Contents/header.xml':
                data = header.encode('utf-8')
            elif item.filename == 'Preview/PrvImage.png':
                continue  # 미리보기 이미지는 양식 것이라 제외
            elif item.filename == 'Contents/content.hpf':
                data = re.sub(r'<opf:item [^>]*PrvImage[^>]*/>', '', data.decode('utf-8')).encode('utf-8')
            zi = zipfile.ZipInfo(item.filename, date_time=(2026, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_STORED if item.filename == 'mimetype' else zipfile.ZIP_DEFLATED
            zo.writestr(zi, data)
    new_bytes = open(tmp, 'rb').read()
    if os.path.exists(out) and open(out, 'rb').read() == new_bytes:
        os.remove(tmp)          # 내용 변화 없음: 기존 파일 유지
        changed = False
    else:
        os.replace(tmp, out)
        changed = True

    import xml.dom.minidom
    with zipfile.ZipFile(out) as zc:
        for n_ in zc.namelist():
            if n_.endswith(('.xml', '.hpf')):
                xml.dom.minidom.parseString(zc.read(n_))

    sha = hashlib.sha256(open(out, 'rb').read()).hexdigest()
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    missing = [d for d in DEPTS if d not in latest]
    lines = [f'## {now} 취합 실행',
             f'- 대상 날짜: {date_txt}',
             f'- 주간 임원일정: {os.path.basename(wfile) if wfile else "없음"} / 반영 {len(events)}건 → ' +
             (', '.join(f"{k} {len(v)}건" for k, v in filled_top.items()) or '해당 없음'),
             f'- 실처 반영: ' + (', '.join(f"{d}({os.path.basename(latest[d][0])})" for d in DEPTS if d in latest) or '없음'),
             f'- 미회신: ' + (', '.join(missing) or '없음'),
             f'- 공통일정: ' + ((f"{len(common)}줄 ({os.path.basename(common_named[0]) if common_named else '실처 파일 공통칸'})") if common else '없음'),
             f'- 확인 필요: ' + ('; '.join(unknown + [f"{s} (HWPX 아님, 처리 안 함)" for s in skipped] + notes) or '없음'),
             '- 주간 표에 열이 없어 비워 둔 행: 임원공통, 기술부사장',
             f'- 출력: {os.path.basename(out)} (sha256 {sha[:12]})', '']
    if changed:   # 내용이 바뀐 경우만 기록 (실시간 감시로 자주 실행되므로)
        with open(os.path.join(ddir, '처리기록.md'), 'a', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')
    print('\n'.join(lines))
    print('OUTPUT=' + out)
    print('SHA256=' + sha)
    print('CHANGED=' + str(changed))


if __name__ == '__main__':
    main()
