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
#                         [--out DIR] [--no-local] [--backend local|api] [--conf <pdd-ocr.conf 的路径>]
#   提示词、模型名、超时、端点文件路径、默认取几帧这些都读 ~/Desktop/pdd-ocr.conf
#   （和 pdd.sh 共用那一份，见文件里「OCR 调用配置」那段）；`--conf` 换位置，命令行参数压过文件。
#   目录给到"日期"或"日期/时间"那一层都行；帧的 key 默认取自文件名 `秒-key-轮.png`。
#   `--key bag` 顺手把选帧收到 `*-bag-*.png`（否则它只改标签，会拿别的屏的框出建议）；
#   要跨帧就用 `--glob` 显式覆盖。
#
# 识图后端二选一（`VLM_BACKEND`，内建默认 local）：
#   local = 只用原来的：本地六档 replay，不读端点文件、不建请求体、一个字节都不出站。
#   api   = 问外部视觉接口，`--send` 才有意义（不给 --send 就只落请求体）。
#   换后端不用改代码：配置文件里写 `VLM_BACKEND=api`，或命令行 `--backend api`（命令行压过文件）。
#   11-01 定的是 local —— 现有那批模型在这份提示词下一律不回 0..1 的框，归因还是得靠 tesseract
#   六档，实测见 docs/api-attribution.md。接口留着不删，是因为哪天换上真能回框的，
#   要动的只有 `~/Desktop/pdd-vlm.url` 里那两行和配置里的 `VLM_MODEL`，代码一行不用碰。
#   两栏对不上的口径：local 后端下 `建议配置.txt` / `候选词.txt` 按设计为空 —— replay 给的是
#   「哪一档认到、点在哪个像素」，不给比例框（0..1），而那两个文件里的框是给 PILL_ 标定用的。
#
# 请求按 OpenAI 兼容的 chat/completions 写（`messages` + base64 data URL，读
# `choices[0].message.content`）。**不是这个形状就只改 `vlm_post` 这一个函数** —— URL、头、
# 响应取值都在它调用处那一行，别的不用碰。
#
# 接线之前的测试后门：`VLM_STUB=<响应文件>` 不走网络，拿那个文件当接口的回答。它只证明解析
# 和报告是通的，**证明不了识别质量**（识别质量要等真接口，见 docs/api-attribution.md）。
set -u

VLM_BACKEND_ENV=${VLM_BACKEND:-}       # 有值 = 环境变量占了这一层（压过配置文件，见文件头那段）
VLM_BACKEND=${VLM_BACKEND:-local}      # local = 只用原来的六档；api = 问视觉接口
VLM_API_URL_FILE=${VLM_API_URL_FILE:-$HOME/Desktop/pdd-vlm.url}
VLM_API_URL=${VLM_API_URL:-}
VLM_API_KEY=${VLM_API_KEY:-}
VLM_MODEL=${VLM_MODEL:-}
VLM_TIMEOUT=${VLM_TIMEOUT:-90}
VLM_MAX=${VLM_MAX:-0}
VLM_LOCAL_MAX_PNG=${VLM_LOCAL_MAX_PNG:-12}
PDD_SH=${PDD_SH:-$HOME/Desktop/pdd.sh}
VLM_STUB=${VLM_STUB:-}
VLM_PROMPT=${VLM_PROMPT:-'这是一张手机屏幕截图（拼多多的活动页或首页）。把你能看清的中文文本逐行列出来，每行给两个字段：
"text"：照抄屏幕上那几个字，不要补全、不要纠正错别字、不要换成别的说法；
"box"：这一行在图中的位置，写成 [x0,y0,x1,y1]，归一化到 0..1（原点在左上角，x 向右、y 向下，分别除以图片的宽高）。
只输出一个 JSON 数组，不要解释、不要 markdown 代码块。看不清的行整行省略 —— 宁可少给几行，也不要为了凑格式猜字。'}

# ---------------------------------------------------------------- OCR 调用配置（和 pdd.sh 共用那一份）
# 上面那一整排是内建默认：这份文件不在时，行为和没做过这次改动之前一字不差。
# 装了 pdd-ocr.conf 之后里面的同名键盖掉默认，环境变量又盖过文件：
#   优先级 内建默认 < $OCR_CONF_FILE（`--conf` 给的就是它）< 环境变量 < 命令行参数
# 一处改两处生效：这边读的是 VLM_ 那批（问接口怎么问），pdd.sh 读的是 OCR_/BAND_/PILL_/PEND_PSM
# （六档 tesseract 怎么读）。两边读的都是命令行给的那个路径 —— 下面跑本地 replay 时会把
# OCR_CONF_FILE 原样传给子进程，免得"本地那一栏"和"接口那一栏"用的不是同一份配置。
# 名单之外的键当场停（78）：写了却不生效的配置比没写更坏。
OCR_CONF_FILE=${OCR_CONF_FILE:-$HOME/Desktop/pdd-ocr.conf}
VLM_CONF_STATE=absent        # absent 没这个文件 / unreadable 在但读不了 / loaded 读成了
VLM_CONF_APPLIED=0           # 从文件里真的取用了几个键
VLM_CONF_FOREIGN=0           # OCR_ 那批：认得，归 pdd.sh
VLM_CONF_ENVHOLD=0           # 环境变量已经占了，文件里同名的键被跳过
VLM_CONF_ERR=

load_vlm_conf() {            # 0 = 文件不在或用成了；1 = 有一行看不懂（VLM_CONF_ERR 里带着行号）
  [ -e "$OCR_CONF_FILE" ] || { VLM_CONF_STATE=absent; return 0; }
  [ -r "$OCR_CONF_FILE" ] || { VLM_CONF_STATE=unreadable; return 0; }
  VLM_CONF_STATE=loaded
  local envn line s k v ln=0
  envn=" $(compgen -e | tr '\n' ' ') "     # 环境变量名单：这一层压过文件
  while IFS= read -r line || [ -n "$line" ]; do
    ln=$((ln + 1))
    line=${line%$'\r'}
    s=${line#"${line%%[![:space:]]*}"}     # 抹掉行首空白
    [ -n "$s" ] || continue
    case $s in '#'*) continue ;; esac
    case $s in
      '='*) VLM_CONF_ERR="第 $ln 行「$s」的键名是空的（格式是一行一个 KEY=VALUE）"; return 1 ;;
      *=*) ;;
      *)    VLM_CONF_ERR="第 $ln 行「$s」不是 KEY=VALUE"; return 1 ;;
    esac
    k=${s%%=*}; v=${s#*=}
    case $k in [A-Za-z_][A-Za-z0-9_]*) ;; *) VLM_CONF_ERR="第 $ln 行的键名「$k」不合法（只许字母、数字、下划线，`=` 两边不要留空格）"; return 1 ;; esac
    v=${v%"${v##*[![:space:]]}"}           # 抹掉行尾空白
    case $k in
      # 这边能用的键也是逐个列出来的，不走 VLM_* 前缀：按前缀放行就等于允许
      # VLM_API_URL= / VLM_API_KEY= / VLM_STUB= 写进这份文件 —— 那两个是凭据、第三个是不走网络的
      # 后门，端点值只放 $HOME/Desktop/pdd-vlm.url（600，不进 git），名单只留真正该调的参数。
      VLM_BACKEND|VLM_API_URL_FILE|VLM_MODEL|VLM_TIMEOUT|VLM_PROMPT|VLM_PROMPT_FILE|\
      VLM_MAX|VLM_LOCAL_MAX_PNG|PDD_SH) ;;
      VLM_API_URL|VLM_API_KEY|VLM_STUB)
        VLM_CONF_ERR="第 $ln 行的键「$k」不许写在这份文件里：它是凭据或本地后门，不是可调参数。端点 URL 和 key 只写进 $HOME/Desktop/pdd-vlm.url（第 1 行 URL、第 2 行可选 key，权限 600），这份配置里只许出现它的路径 VLM_API_URL_FILE。"; return 1 ;;
      OCR_LANG|OCR_PSM|OCR_PSM_PAGE|OCR_MINCONF|OCR_PSM_BAND|OCR_PSM_BAND_*|\
      PEND_PSM|BAND_SCALE|BAND_CUTOFF|PILL_TH|PILL_SCALES|PILL_MODE_*)
        VLM_CONF_FOREIGN=$((VLM_CONF_FOREIGN + 1)); continue ;;
      *) VLM_CONF_ERR="第 $ln 行的键「$k」不在这份配置的名单里。这份只管两处 OCR 调用：这边认 VLM_BACKEND VLM_API_URL_FILE VLM_MODEL VLM_TIMEOUT VLM_PROMPT VLM_PROMPT_FILE VLM_MAX VLM_LOCAL_MAX_PNG PDD_SH，pdd.sh 认 OCR_/BAND_/PILL_/PEND_PSM 那批（见文件头）。端点的值、词表、区域、坐标都不许写进来。"; return 1 ;;
    esac
    case " $envn " in *" $k "*) VLM_CONF_ENVHOLD=$((VLM_CONF_ENVHOLD + 1)); continue ;; esac
    case $v in '~/'*) v=$HOME/${v#\~/} ;; esac
    v=${v//\$HOME/$HOME}
    printf -v "$k" '%s' "$v" || { VLM_CONF_ERR="第 $ln 行赋不进「$k」"; return 1; }
    VLM_CONF_APPLIED=$((VLM_CONF_APPLIED + 1))
  done <"$OCR_CONF_FILE"
  return 0
}

vlm_conf_check() {   # 值的形状闸门：这几个数飞了不会报错，只会静默给错答案
  VLM_CONF_BAD=
  case ${VLM_BACKEND:-} in
    local|api) ;;
    *) VLM_CONF_BAD="${VLM_CONF_BAD}  VLM_BACKEND=${VLM_BACKEND:-（空）}  只许两个值：local（只用原来的六档，一个字节都不出站）/ api（问视觉接口）"$'\n' ;;
  esac
  case ${VLM_TIMEOUT:-} in ''|*[!0-9]*) VLM_CONF_BAD="${VLM_CONF_BAD}  VLM_TIMEOUT=${VLM_TIMEOUT:-（空）}  要一个整数秒"$'\n' ;;
    *) [ "$VLM_TIMEOUT" -ge 1 ] && [ "$VLM_TIMEOUT" -le 600 ] \
         || VLM_CONF_BAD="${VLM_CONF_BAD}  VLM_TIMEOUT=$VLM_TIMEOUT  要在 1..600 秒里（curl -m）"$'\n' ;;
  esac
  case ${VLM_MAX:-} in ''|*[!0-9]*) VLM_CONF_BAD="${VLM_CONF_BAD}  VLM_MAX=${VLM_MAX:-（空）}  要一个非负整数（0 = 不限）"$'\n' ;; esac
  case ${VLM_LOCAL_MAX_PNG:-} in ''|*[!0-9]*) VLM_CONF_BAD="${VLM_CONF_BAD}  VLM_LOCAL_MAX_PNG=${VLM_LOCAL_MAX_PNG:-（空）}  要一个正整数（超过这个张数就不跑本地 replay）"$'\n' ;;
    *) [ "$VLM_LOCAL_MAX_PNG" -ge 1 ] || VLM_CONF_BAD="${VLM_CONF_BAD}  VLM_LOCAL_MAX_PNG=$VLM_LOCAL_MAX_PNG  至少得是 1"$'\n' ;;
  esac
  [ -z "$VLM_CONF_BAD" ]
}

dir= glob='*.png' glob_set=0 key_override= want_send=0 maxn= maxn_set=0 out= want_local=1
backend= backend_set=0
while [ $# -gt 0 ]; do
  case $1 in
    --key)      shift; key_override=${1:-}; shift ;;
    --glob)     shift; glob=${1:-}; glob_set=1; shift ;;
    --conf)     shift; OCR_CONF_FILE=${1:-}; shift ;;
    --send)     shift; want_send=1 ;;
    --no-local) shift; want_local=0 ;;
    --backend)  shift; backend=${1:-}; backend_set=1; shift ;;
    --max)      shift; maxn=${1:-0}; maxn_set=1; shift ;;
    --out)      shift; out=${1:-}; shift ;;
    -*)         printf '不认得参数 %s\n' "$1" >&2; exit 2 ;;
    *)          dir=$1; shift ;;
  esac
done
load_vlm_conf || {
  printf 'OCR 配置读不动，不带半套配置开跑。\n  文件：%s\n  %s\n' "$OCR_CONF_FILE" "$VLM_CONF_ERR" >&2
  exit 78
}
vlm_conf_check || {
  printf 'OCR 配置里的值不成形，改对了再跑：\n%s' "$VLM_CONF_BAD" >&2
  printf '  文件：%s\n' "$OCR_CONF_FILE" >&2
  exit 78
}
[ -n "$maxn" ] || maxn=0
[ "$maxn_set" = 1 ] || maxn=${VLM_MAX:-0}
# 后端是谁定的：内建默认 < 配置文件 < 环境变量 < 命令行（和装载那层的口径一致，报出来好核）。
VLM_BACKEND_SRC=内建默认
[ "$VLM_CONF_STATE" = loaded ] && grep -qE '^[[:space:]]*VLM_BACKEND=' "$OCR_CONF_FILE" && VLM_BACKEND_SRC="conf:$OCR_CONF_FILE"
[ -n "$VLM_BACKEND_ENV" ] && VLM_BACKEND_SRC=环境变量
if [ "$backend_set" = 1 ]; then
  case $backend in
    local|api) VLM_BACKEND=$backend; VLM_BACKEND_SRC=命令行 ;;
    *) printf '不认得 --backend 的值「%s」：只许 local（只用原来的六档）或 api（问视觉接口）\n' "$backend" >&2; exit 2 ;;
  esac
fi
# local 后端下这两个参数都是自相矛盾，当场停 —— 别等本地 replay 跑完好几分钟才说白跑了。
if [ "$VLM_BACKEND" != api ]; then
  if [ "$want_send" = 1 ]; then
    printf '后端是 %s（来源：%s），--send 不予执行：一个请求体都不建、一个字节都不出站。\n' "$VLM_BACKEND" "$VLM_BACKEND_SRC" >&2
    printf '  真要出站就把配置里的 VLM_BACKEND 改成 api（或加 --backend api），端点文件不动、代码一行不用改。\n' >&2
    exit 78
  fi
  if [ "$want_local" != 1 ]; then
    printf '后端是 %s，又给了 --no-local：本地这一栏就是全部内容，关掉之后报告里不会有任何判定。\n' "$VLM_BACKEND" >&2
    exit 2
  fi
fi
# 提示词文件优先：整份读进来当提示词（配置文件的值不能跨行，长提示词只能这么给）。
VLM_PROMPT_SRC=内建默认
if [ "$VLM_CONF_STATE" = loaded ] && grep -qE '^[[:space:]]*VLM_PROMPT=' "$OCR_CONF_FILE"; then
  VLM_PROMPT_SRC="conf:$OCR_CONF_FILE"
fi
if [ -n "${VLM_PROMPT_FILE:-}" ]; then
  [ -r "$VLM_PROMPT_FILE" ] || { printf 'VLM_PROMPT_FILE 指到了 %s，但它不存在或读不了。\n' "$VLM_PROMPT_FILE" >&2; exit 78; }
  VLM_PROMPT=$(cat "$VLM_PROMPT_FILE")
  VLM_PROMPT_SRC="file:$VLM_PROMPT_FILE"
fi
# --key 得同时负责选帧：只管改标签的话 `--key bag --max 3` 会挑到 popup 帧再按 bag 的词表判，
# 建议配置里就会出现"从别的屏量出来的框"。没显式给 --glob 就按 `*-<key>-*.png` 收。
if [ -n "$key_override" ] && [ "$glob_set" != 1 ]; then
  glob="*-$key_override-*.png"
fi
[ -n "$dir" ] && [ -d "$dir" ] || { printf '要给证据目录，而且它得存在：%s\n' "${dir:-（空）}" >&2; exit 2; }
command -v python3 >/dev/null 2>&1 || { printf '没有 python3，请求体和响应解析都靠它\n' >&2; exit 78; }

# 端点解析：env 优先，其次文件第 1 行（URL）、第 2 行（可选 key）。只统计长度，值不外泄。
# 后端是 local 时连那个文件都不打开 —— 凭据文件只在真要用接口时才碰。
VLM_URL_SRC=env
if [ "$VLM_BACKEND" != api ]; then
  VLM_URL_SRC='没读（后端 local）'
elif [ -z "$VLM_API_URL" ] && [ -r "$VLM_API_URL_FILE" ]; then
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
#   ② 一次 replay 扫的是整个运行目录，按帧各跑一遍等于把整目录 OCR 重做 N 遍。单帧的分量 11-01 量过：
#      整页 psm 6 单帧三次 1.4 / 2.3 / 3.2 秒上下（三帧分别测，字数越多越慢），band 裁片 psm 7 含 ×3
#      放大和存盘 0.4 秒。整场按帧数摊：空闲主机上 32 帧那一跑 2 分 11 秒、17 帧那一跑 1 分 25 秒，
#      也就是 4~5 秒一帧，86 帧的一场六到七分钟 —— 这里原先写的是"每帧约 10 秒、86 帧十五分钟"，
#      那个数是拿一个两帧的目录（20 秒）量的，进程启动占大头，样本太小，作废。
#      所以按运行目录的 png 张数决定跑不跑，`--max` 限不住 replay 的范围。
: >"$locfile"
if [ "$want_local" = 1 ] && [ -f "$PDD_SH" ]; then
  parents=$(for f in "${frames[@]}"; do dirname "$f"; done | sort -u)
  np=$(printf '%s\n' "$parents" | grep -c .)
  while IFS= read -r p; do
    [ -n "$p" ] || continue
    n=$(find "$p" -maxdepth 1 -type f -name '*.png' 2>/dev/null | grep -c .)
    if [ "$n" -le "$VLM_LOCAL_MAX_PNG" ]; then
      # 每帧 5 秒不是拍脑袋：11-01 主机空闲时两个数摊出来的 —— 32 帧那跑 2 分 11 秒、17 帧那跑 1 分 25 秒。
      say "本地六档（$p：$n 张 png，按每帧 5 秒估 $((n * 5)) 秒上下；闸门是配置里的 VLM_LOCAL_MAX_PNG=$VLM_LOCAL_MAX_PNG）"
      # OCR_CONF_FILE 原样传给子进程：本地那一栏是 pdd.sh 的 replay 跑的，它读同一份配置，
      # 不然"并排"的两栏用的是两套参数，比较就没意义了。
      OCR_CONF_FILE="$OCR_CONF_FILE" bash "$PDD_SH" replay "$p" --ocr >>"$locfile" 2>&1 \
        || say "  replay 没跑成，$p 的本地那一栏会是空（原文在 $locfile）"
    else
      say "本地六档跳过：$p 有 $n 张 png，超过配置里的 VLM_LOCAL_MAX_PNG=$VLM_LOCAL_MAX_PNG（replay 要扫整个目录，--max 限不住它）。"
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
say "识图后端 $VLM_BACKEND（来源：$VLM_BACKEND_SRC）"
if [ "$VLM_BACKEND" = api ]; then
  say "端点 ${VLM_URL_SRC}（长度 ${#VLM_API_URL} 字符）· send=$([ "$want_send" = 1 ] && echo 是 || echo '否 —— 只落请求体，一个字节都不出站')"
else
  say "端点：后端是 local，不打开 $VLM_API_URL_FILE、不建请求体（send=否，一个字节都不出站）"
fi
case $VLM_CONF_STATE in
  loaded)     _cs="在用：从文件取了 $VLM_CONF_APPLIED 个键（另外 $VLM_CONF_FOREIGN 个是 pdd.sh 那批，这边只认不用；环境变量占了 $VLM_CONF_ENVHOLD 个，那几个的文件值没生效）" ;;
  absent)     _cs="没有这份文件 —— 用的是工具里的内建默认" ;;
  unreadable) _cs="文件在但读不了（看权限），用的是内建默认" ;;
esac
say "配置 $OCR_CONF_FILE · $_cs"
say "  提示词来自 $VLM_PROMPT_SRC（${#VLM_PROMPT} 字符）· model=${VLM_MODEL:-（不发）}· 超时 ${VLM_TIMEOUT}s · 本地栏闸门 $VLM_LOCAL_MAX_PNG 张"
if [ "$VLM_BACKEND" = api ]; then
  [ "$want_send" = 1 ] || say '确认要出站就加 --send 重跑。'
else
  say '  这一栏只有本地六档：接口那半开着要把配置里的 VLM_BACKEND 改成 api（或加 --backend api）。'
fi
say ''

for f in "${frames[@]}"; do
  stem=$(basename "$f"); stem=${stem%.*}
  key=$key_override
  [ -n "$key" ] || key=$(printf '%s' "$stem" | awk -F'-' '{print $(NF-1)}')
  if [ "$VLM_BACKEND" != api ]; then
    # 后端 local：一帧一个标题，把 replay 里属于这一帧的行原样贴出来。
    # 不建请求体、不解析、不写 建议配置.txt / 候选词.txt —— replay 给的是像素点不是比例框。
    say "### $stem（key=$key）本地六档："
    _rows=$(grep -F -- "$stem" "$locfile" 2>/dev/null)
    if [ -n "$_rows" ]; then
      while IFS= read -r _l; do [ -n "$_l" ] && say "  $_l"; done <<<"$_rows"
    else
      say "  （本地这一栏没跑成或没有这帧的行，原文在 $locfile）"
    fi
    say ''
    continue
  fi
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
if [ "$VLM_BACKEND" = api ]; then
  say '抄进配置之前做两件事：'
  say "  ① 拿同一帧跑 pdd.sh replay <目录> --ocr --label <key> <那个词>，看本地 band/pill 档认不认得到 —— 接口给的框只是位置线索，不等于本地读得出；"
  say "  ② 改完跑 scripts/run-sandbox.sh（两个分辨率）和 scripts/negative-control.sh，测试还得有牙。"
  say '这一版只出建议，不改 pdd.sh，也不出 COORD_*。'
else
  say "后端 local：上面那四个数按设计全是 0 —— 这一栏的内容都在「### <帧> 本地六档」那些行里（replay 原文 $locfile），"
  say '  给的是「哪一档认到、点在哪个像素」，不给 0..1 的框，所以没有要抄进配置的东西，也不出 COORD_*。'
  say '  要接口那一栏就把配置里的 VLM_BACKEND 改成 api（或加 --backend api）。'
fi
