#!/usr/bin/env bash
# 离线归因：把**已经存下来的失败帧**交给外部视觉接口问一遍「这一屏到底写着什么、写在哪」，
# 和本地六档在同一帧上的判定并排打出来，用来决定 `ALIAS_` / `PILL_` / `REGION_` 怎么改。
# 它是**线索生成器，不是点击坐标的来源**：只往输出目录里写建议，一个字都不改 pdd.sh，
# 也绝不产出 `COORD_*`（那一族是要真打下去的，得人拍板）。
#
# 读结果之前先看这三句：
#   1. 只读证据目录，不碰手机、不发 adb。默认排除 `*band-*` / `*pill-*` 帧 —— 那是同一屏的
#      局部放大裁片，发出去等于把同一帧问两遍，接口还会读到半截字。
#   2. **没有 `--send` 就一个字节都不出站**：只落请求体、报"要发几帧、多大"。截图里带着账号
#      昵称和券面额，出站这件事得当场说清楚才做。
#   3. 接口地址和 key 是凭据，本仓库是公开的，所以只从 `VLM_API_URL_FILE`（默认
#      `~/Desktop/pdd-vlm.url`）读：第 1 行 URL，第 2 行可选 Bearer key。全程只报来源和长度，
#      绝不打印值；请求体里也不写 URL 和 key，所以 `*.req.json` 可以直接给人看。
#      没配端点又要 `--send` = 退出码 78，一次请求都不发。
#
# 用法（在主机上跑，证据在主机上）：
#   scp tools/vlm-attribute.sh deb-h61:/tmp/
#   ssh deb-h61 'bash /tmp/vlm-attribute.sh ~/Desktop/pdd-runs/2026-10-30/191958 --key bag --max 3'
#   bash vlm-attribute.sh <证据目录> [--key bag] [--glob "*-bag-*.png"] [--send] [--max N]
#                         [--out DIR] [--no-local]
#   目录给到"日期"或"日期/时间"那一层都行；帧的 key 默认取自文件名 `秒-key-轮.png`。
#   `--key bag` 顺手把选帧收到 `*-bag-*.png`（否则它只改标签，会拿别的屏的框出建议）；
#   要跨帧就用 `--glob` 显式覆盖。
#
# 请求按 OpenAI 兼容的 chat/completions 写（`messages` + base64 data URL，读
# `choices[0].message.content`）。**不是这个形状就只改 `vlm_post` 这一个函数** —— URL、头、
# 响应取值都在它调用处那一行，别的不用碰。
#
# 接线之前的测试后门：`VLM_STUB=<响应文件>` 不走网络，拿那个文件当接口的回答。它只证明解析
# 和报告是通的，**证明不了识别质量**（识别质量要等真接口，见 docs/api-attribution.md）。
set -u

VLM_API_URL_FILE=${VLM_API_URL_FILE:-$HOME/Desktop/pdd-vlm.url}
VLM_API_URL=${VLM_API_URL:-}
VLM_API_KEY=${VLM_API_KEY:-}
VLM_MODEL=${VLM_MODEL:-}
VLM_TIMEOUT=${VLM_TIMEOUT:-90}
PDD_SH=${PDD_SH:-$HOME/Desktop/pdd.sh}
VLM_STUB=${VLM_STUB:-}
VLM_PROMPT=${VLM_PROMPT:-'这是一张手机屏幕截图（拼多多的活动页或首页）。把你能看清的中文文本逐行列出来，每行给两个字段：
"text"：照抄屏幕上那几个字，不要补全、不要纠正错别字、不要换成别的说法；
"box"：这一行在图中的位置，写成 [x0,y0,x1,y1]，归一化到 0..1（原点在左上角，x 向右、y 向下，分别除以图片的宽高）。
只输出一个 JSON 数组，不要解释、不要 markdown 代码块。看不清的行整行省略 —— 宁可少给几行，也不要为了凑格式猜字。'}

dir= glob='*.png' glob_set=0 key_override= want_send=0 maxn=0 out= want_local=1
while [ $# -gt 0 ]; do
  case $1 in
    --key)      shift; key_override=${1:-}; shift ;;
    --glob)     shift; glob=${1:-}; glob_set=1; shift ;;
    --send)     shift; want_send=1 ;;
    --no-local) shift; want_local=0 ;;
    --max)      shift; maxn=${1:-0}; shift ;;
    --out)      shift; out=${1:-}; shift ;;
    -*)         printf '不认得参数 %s\n' "$1" >&2; exit 2 ;;
    *)          dir=$1; shift ;;
  esac
done
# --key 得同时负责选帧：只管改标签的话 `--key bag --max 3` 会挑到 popup 帧再按 bag 的词表判，
# 建议配置里就会出现"从别的屏量出来的框"。没显式给 --glob 就按 `*-<key>-*.png` 收。
if [ -n "$key_override" ] && [ "$glob_set" != 1 ]; then
  glob="*-$key_override-*.png"
fi
[ -n "$dir" ] && [ -d "$dir" ] || { printf '要给证据目录，而且它得存在：%s\n' "${dir:-（空）}" >&2; exit 2; }
command -v python3 >/dev/null 2>&1 || { printf '没有 python3，请求体和响应解析都靠它\n' >&2; exit 78; }

# 端点解析：env 优先，其次文件第 1 行（URL）、第 2 行（可选 key）。只统计长度，值不外泄。
VLM_URL_SRC=env
if [ -z "$VLM_API_URL" ] && [ -r "$VLM_API_URL_FILE" ]; then
  VLM_API_URL=$(sed -n '1p' "$VLM_API_URL_FILE" | tr -d ' \t\r\n')
  [ -z "$VLM_API_KEY" ] && VLM_API_KEY=$(sed -n '2p' "$VLM_API_URL_FILE" | tr -d ' \t\r\n')
  [ -n "$VLM_API_URL" ] && VLM_URL_SRC="file:$VLM_API_URL_FILE"
fi

frames=()
while IFS= read -r f; do
  case $(basename "$f") in *band-*|*pill-*) continue ;; esac
  frames+=("$f")
  if [ "$maxn" -gt 0 ] && [ "${#frames[@]}" -ge "$maxn" ]; then break; fi
done < <(find "$dir" -type f -name "$glob" 2>/dev/null | sort)
if [ "${#frames[@]}" -eq 0 ]; then
  printf '%s 下面按 %s 挑不到帧（band/pill 裁片默认排除）\n' "$dir" "$glob" >&2; exit 2
fi

[ -n "$out" ] || out=/tmp/vlm-attr-$(date +%Y%m%d-%H%M%S)
mkdir -p "$out" || { printf '建不出输出目录 %s\n' "$out" >&2; exit 2; }
report=$out/report.txt; props=$out/建议配置.txt; cand=$out/候选词.txt; locfile=$out/本地replay.txt
: >"$report"; : >"$props"; : >"$cand"
say() { printf '%s\n' "$*" >>"$report"; printf '%s\n' "$*"; }
# lines_tsv 的分隔符（0x1f，单元分隔符）。别换成制表符：见 lines_tsv 上面那段。
US=$(printf '\037')

if [ "$want_send" = 1 ] && [ -z "$VLM_STUB" ] && [ -z "$VLM_API_URL" ]; then
  printf '要 --send 但没有端点：VLM_API_URL 是空的，%s 也不在或读不了。一次请求都不发。\n' "$VLM_API_URL_FILE" >&2
  printf '配好再跑（第 1 行 URL、第 2 行可选 key），别把值写进仓库里任何文件：\n  chmod 600 %s && printf '\''%%s\\n%%s\\n'\'' <端点> <key> >%s\n' "$VLM_API_URL_FILE" "$VLM_API_URL_FILE" >&2
  exit 78
fi

# 本地那六档：逐帧从 replay 的原文里挑那一行（原样打印，不拆字段 —— 表是定宽对齐的，
# 拆字段会把带空格的标签切碎）。两件事决定了这里的写法：
#   ① `pdd.sh replay` 只认 <时间>/ 和 <日期>/<时间>/ 这两级目录，而本工具的 --dir 可以给到更上
#      一层（帧用 find 递归挑），所以得按**帧自己的父目录**分组去跑，不能直接传 $dir。
#   ② 一次 replay 扫的是整个运行目录，按帧各跑一遍等于把整目录 OCR 重做 N 遍。11-01 00:0x
#      在这台上实测过：整页 psm 6 单帧三次 1.4 / 2.3 / 3.2 秒上下（三帧分别测，字数越多越慢），
#      band 裁片 psm 7 含 ×3 放大和存盘 0.4 秒，`replay --ocr` 两帧的一场 20 秒 —— 每帧约 10 秒，
#      86 帧的一场十五分钟上下。所以按运行目录的 png 张数决定跑不跑，`--max` 限不住 replay 的范围。
: >"$locfile"
if [ "$want_local" = 1 ] && [ -f "$PDD_SH" ]; then
  parents=$(for f in "${frames[@]}"; do dirname "$f"; done | sort -u)
  np=$(printf '%s\n' "$parents" | grep -c .)
  while IFS= read -r p; do
    [ -n "$p" ] || continue
    n=$(find "$p" -maxdepth 1 -type f -name '*.png' 2>/dev/null | grep -c .)
    if [ "$n" -le 12 ]; then
      say "本地六档（$p：$n 张 png，按每帧 10 秒估 $((n * 10)) 秒上下）"
      bash "$PDD_SH" replay "$p" --ocr >>"$locfile" 2>&1 \
        || say "  replay 没跑成，$p 的本地那一栏会是空（原文在 $locfile）"
    else
      say "本地六档跳过：$p 有 $n 张 png，replay 要扫整个目录（--max 限不住它）。"
      say "  要这一栏就把目录指到单个运行目录，或先按 --glob 缩到某一步。"
    fi
  done <<<"$parents"
  [ "$np" -gt 1 ] && say "  （本地栏共 $np 个运行目录）"
  say ''
fi

# 请求体：图片 base64 成 data URL。URL 和 key 都不写进去，所以 req.json 可以随手贴给人看。
build_req() {                        # $1=png $2=输出 json -> 打印 base64 长度
  PNG=$1 REQ_OUT=$2 VLM_PROMPT=$VLM_PROMPT VLM_MODEL=$VLM_MODEL python3 - <<'PY'
import base64, json, os
b64 = base64.b64encode(open(os.environ["PNG"], "rb").read()).decode()
body = {"messages": [{"role": "user", "content": [
    {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}},
    {"type": "text", "text": os.environ["VLM_PROMPT"]}]}]}
if os.environ.get("VLM_MODEL"):
    body["model"] = os.environ["VLM_MODEL"]
json.dump(body, open(os.environ["REQ_OUT"], "w"), ensure_ascii=False)
print(len(b64))
PY
}

# 接口只在这一处发出去；不是这个形状就改这一行的取 URL / 头 / 响应文件。
vlm_post() {                         # $1=req.json $2=响应落盘 -> 打印 HTTP 码
  local hdr=(-sS -m "$VLM_TIMEOUT" -H 'Content-Type: application/json' -o "$2" -w '%{http_code}')
  [ -n "$VLM_API_KEY" ] && hdr+=(-H "Authorization: Bearer $VLM_API_KEY")
  curl "${hdr[@]}" -X POST "$VLM_API_URL" --data-binary "@$1" 2>/dev/null
}

# 响应 → 纯文本：chat/completions 取 choices[0].message.content，拿不到就整包当文本。
resp_text() {
  python3 - "$1" <<'PY'
import json, sys
raw = open(sys.argv[1], encoding="utf-8", errors="replace").read()
try:
    d = json.loads(raw)
except Exception:
    print(raw.strip()); raise SystemExit
if isinstance(d, dict):
    e = d.get("error")
    if isinstance(e, dict) and e.get("message"):
        print('[接口报错] ' + str(e['message'])); raise SystemExit
    if isinstance(e, str) and e:
        print('[接口报错] ' + e); raise SystemExit
    try:
        c = d['choices'][0]['message']['content']
    except Exception:
        c = None
    if isinstance(c, list):
        c = ''.join(x.get('text', '') for x in c if isinstance(x, dict))
    if isinstance(c, str) and c.strip():
        print(c.strip()); raise SystemExit
print(raw.strip())
PY
}

# 纯文本 → 分隔行：补齐宽度的文本 / x0 / y0 / x1 / y1 / 命中的 ALIAS 词 / 原文本。
# 分隔符用 \x1f 不用制表符：bash 的 read 把制表符当 IFS 空白，**连续两个会并成一个**，
# 于是「命中词为空」的那一行会少一个字段、原文掉进 hit、末字段为空 —— 整行被静默丢掉
# （实测 3 行只打 1 行）。补宽度也放在这儿：printf %-26s 按字节算，中文会错位。
lines_tsv() {                         # $1=文本 $2=该 key 的词表（a|b|c）
  python3 - "$1" "${2:-}" <<'PY'
import json, re, sys, unicodedata
US = '\x1f'
text, alias = sys.argv[1], sys.argv[2]
words = [re.sub(r'\s+', '', w) for w in alias.split('|') if w.strip()]

def clean(s):
    return re.sub(r'[\x00-\x1f]', ' ', str(s))

def cols(s):
    return sum(2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1 for c in s)

def pad(s, n):
    return s + ' ' * max(0, n - cols(s))

text = re.sub(r'^```[a-zA-Z]*|```$', '', text.strip(), flags=re.M).strip()
rows = []
m = re.search(r'\[.*\]', text, flags=re.S)
arr = None
if m:
    try:
        arr = json.loads(m.group(0))
    except Exception:
        arr = None
if isinstance(arr, list):
    for it in arr:
        if not isinstance(it, dict):
            continue
        t = clean(it.get('text', '')).strip()
        if not t:
            continue
        bx = it.get('box') or it.get('bbox') or []
        b = [''] * 4
        warn = ''
        if isinstance(bx, list) and len(bx) >= 4:
            try:
                vals = [float(v) for v in bx[:4]]
                if all(0.0 <= v <= 1.0 for v in vals):
                    b = ['%.5f' % v for v in vals]
                else:
                    # 越界就不当比例：不少接口给像素或千分度，照抄进 PILL_ 会把点击点到场外。
                    warn = '框不在 0..1（' + ','.join('%.4g' % v for v in vals) + '）—— 不是比例，别抄进配置'
            except Exception:
                warn = '框读不出数'
        rows.append([t] + b + [warn])
else:
    for ln in text.splitlines():
        ln = clean(ln).strip()
        if ln:
            rows.append([ln] + [''] * 4 + [''])
for r in rows:
    flat = re.sub(r'\s+', '', r[0])
    hit = next((w for w in words if w and w in flat), '')
    print(US.join([pad(r[0], 26)] + r[1:5] + [hit, clean(r[0]), r[5]]))
PY
}

alias_of() { [ -f "$PDD_SH" ] && grep -m1 "^ALIAS_$1=" "$PDD_SH" 2>/dev/null | cut -d= -f2- | sed "s/[\"']//g"; }

say "帧 ${#frames[@]} 张 · 输出目录 $out"
say "端点 ${VLM_URL_SRC}（长度 ${#VLM_API_URL} 字符）· send=$([ "$want_send" = 1 ] && echo 是 || echo '否 —— 只落请求体，一个字节都不出站')"
[ "$want_send" = 1 ] || say '确认要出站就加 --send 重跑。'
say ''

for f in "${frames[@]}"; do
  stem=$(basename "$f"); stem=${stem%.*}
  key=$key_override
  [ -n "$key" ] || key=$(printf '%s' "$stem" | awk -F'-' '{print $(NF-1)}')
  req=$out/$stem.req.json
  # 建不出来必须把 python 那行的原因带出来，不然只能看见"没建出来"四个字。
  bytes=$(build_req "$f" "$req" 2>"$out/$stem.err") \
    || { say "### $stem（key=$key）：请求体没建出来，跳过";
         say "  原因 $(tail -1 "$out/$stem.err")"; say ''; rm -f "$out/$stem.err"; continue; }
  rm -f "$out/$stem.err"
  if [ "$want_send" != 1 ]; then
    say "### $stem（key=$key）：请求体 $(wc -c <"$req") 字节（图 base64 $bytes），未发"
    say ''
    continue
  fi
  loc=$(grep -F -- "$stem" "$locfile" | head -1)
  code_note=''
  if [ -n "$VLM_STUB" ]; then
    cp "$VLM_STUB" "$out/$stem.raw" || { say "### $stem：桩响应 $VLM_STUB 读不到"; say ''; continue; }
    code_note='（桩响应：只验管线，证明不了识别质量）'
  else
    code=$(vlm_post "$req" "$out/$stem.raw")
    # HTTP 码别写进 raw：混在响应原文里会让 resp_text 的 json 解析整个失败。
    [ "$code" = 200 ] || code_note="（HTTP $code，原文见 $stem.raw）"
  fi
  txt=$(resp_text "$out/$stem.raw")
  [ -n "$txt" ] || txt='（接口没吐内容）'
  al=$(alias_of "$key")
  al_note=''
  [ -n "$al" ] || al_note="（$PDD_SH 里没有 ALIAS_$key —— 只列接口读到的行，不出建议）"
  tsv=$(lines_tsv "$txt" "$al")
  say "### $stem（key=$key）$code_note$al_note"
  say "  本地 $(printf '%s' "${loc:-（本地那一栏没跑）}")"
  say "  接口读回 $(printf '%s\n' "$tsv" | grep -c .) 行："
  while IFS=$US read -r tp x0 y0 x1 y1 hit t warn; do
    [ -n "$t" ] || continue
    box=''
    [ -n "$x0" ] && box=$(printf '[%s,%s,%s,%s]' "$x0" "$y0" "$x1" "$y1")
    note=''
    [ -n "$hit" ] && note=$(printf '← ALIAS_%s 里有「%s」' "$key" "$hit")
    [ -n "$warn" ] && note="$note $warn"
    # 引号包起来：识别文本里带空格时，不加引号会被拆成多段再拿空格拼回，对齐就废了。
    say "$(printf '    %s %-33s %s' "$tp" "$box" "$note")"
    if [ -n "$box" ]; then
      printf '%s\t%s\t%s\n' "$key" "$box" "$t" >>"$cand"
      if [ -n "$hit" ]; then
        printf 'PILL_%s=%s,%s,%s,%s   # %s 这一屏接口读到「%s」；本地那一档是 %s\n' \
          "$key" "$x0" "$y0" "$x1" "$y1" "$stem" "$hit" "${loc:-没跑}" >>"$props"
        printf '# REGION_%s 得把这个框包进去（比例是 0..1，换屏不用重量）\n' "$key" >>"$props"
      fi
    fi
  done <<<"$tsv"
  say ''
done

nreq=$(find "$out" -maxdepth 1 -name '*.req.json' 2>/dev/null | wc -l)
nresp=$(find "$out" -maxdepth 1 -name '*.raw' 2>/dev/null | wc -l)
# grep -c 在空文件上自己就打印 0 并且返回 1 —— 再 `|| echo 0` 会变成两个 0，把汇总行撑成三行。
ncand=$(grep -c . "$cand" 2>/dev/null); ncand=${ncand:-0}
nprop=$(grep -c '^PILL_' "$props" 2>/dev/null); nprop=${nprop:-0}
say "汇总：帧 ${#frames[@]} / 请求体 $nreq / 响应 $nresp / 接口带框的行 $ncand / 能对上现有词表 $nprop"
say ''
say '抄进配置之前做两件事：'
say "  ① 拿同一帧跑 pdd.sh replay <目录> --ocr --label <key> <那个词>，看本地 band/pill 档认不认得到 —— 接口给的框只是位置线索，不等于本地读得出；"
say "  ② 改完跑 scripts/run-sandbox.sh（两个分辨率）和 scripts/negative-control.sh，测试还得有牙。"
say '这一版只出建议，不改 pdd.sh，也不出 COORD_*。'
