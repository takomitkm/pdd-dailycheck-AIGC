#!/usr/bin/env bash
# vlm-attribute.sh 的验收轮：只验管线（出站闸门、请求体、解析、并排报告），不接真接口。
#
# 读结果前先看这三句：
#   1. 桩响应（`VLM_STUB`）证明不了识别质量，只证明"读回来能解析、命中能对上词表、建议落得下来"。
#      识别质量要等真端点，见 docs/api-attribution.md「还没测的」。
#   2. 全程不需要端点：端点文件不存在时，`--send` 那一项（H）要的就是 rc=78，不是失败。
#   3. C/D/E/F/G/H/I/J 都要证据帧，用的是 `~/Desktop/pdd-runs/` 里现成的场次。证据只留
#      `KEEP_DAYS=7` 天，过期后这些项会打印「跳过」并整体判过 —— 别把"跳过"读成"通过"。
#
# 用法（在主机上跑，证据本来就在主机上）：
#   scp tools/vlm-attribute.sh scripts/selftest-vlm-attribute.sh deb-h61:/tmp/
#   ssh deb-h61 'bash /tmp/selftest-vlm-attribute.sh'
# 两个目录可以用第 1、2 个参数改：selftest.sh <大场次目录> <小场次目录>
set -u

D=${1:-$HOME/Desktop/pdd-runs/2026-10-30/191958}   # 大的一场：86 张 png，有 popup / bag 两类帧
D2=${2:-$HOME/Desktop/pdd-runs/2026-10-30/202825}  # 用来抄两帧造小目录
S=${S:-/tmp/vlm-attribute.sh}
[ -f "$S" ] || { printf '找不到工具本体 %s（先 scp 上去）\n' "$S" >&2; exit 2; }

skip=0
for d in "$D" "$D2"; do
  [ -d "$d" ] || { printf '证据目录不在：%s（KEEP_DAYS=7 天，过期就没了）\n' "$d" >&2; skip=1; }
done

rm -rf /tmp/va-dry /tmp/va-stub /tmp/va-stub2 /tmp/va-err /tmp/va-gate /tmp/va-small /tmp/va-local /tmp/va-noal

echo "=== A bash -n"
bash -n "$S" && echo "语法过"

if [ "$skip" = 0 ]; then
  echo
  echo "=== C 干跑（不发，--no-local --max 3）"
  bash "$S" "$D" --no-local --max 3 --out /tmp/va-dry | tail -6
  echo "--- req.json 个数 $(find /tmp/va-dry -name '*.req.json' | wc -l)（应 3）/ err 残留 $(find /tmp/va-dry -name '*.err' | wc -l)（应 0）"

  echo
  echo "=== D req.json 完整性：URL/key 不在里面，base64 解出来 == 原图"
  python3 - "$D" /tmp/va-dry <<'PY'
import base64, hashlib, json, os, sys
src, out = sys.argv[1], sys.argv[2]
ok = True
for fn in sorted(os.listdir(out)):
    if not fn.endswith('.req.json'):
        continue
    raw = open(os.path.join(out, fn), 'rb').read()
    d = json.loads(raw)
    parts = d['messages'][0]['content']
    img = [p for p in parts if p.get('type') == 'image_url'][0]['image_url']['url']
    txt = [p for p in parts if p.get('type') == 'text'][0]['text']
    md5_new = hashlib.md5(base64.b64decode(img.split(',', 1)[1])).hexdigest()
    orig = os.path.join(src, fn.replace('.req.json', '.png'))
    md5_old = hashlib.md5(open(orig, 'rb').read()).hexdigest()
    same = md5_new == md5_old
    leak = [k for k in (b'http://', b'https://', b'authorization', b'bearer') if k in raw.lower()]
    print(f"{fn}: 图 md5 {'一致' if same else '不一致'} · 请求体 {len(raw)} 字节 · 提示词 {len(txt)} 字"
          f" · model 键 {'有' if 'model' in d else '无（VLM_MODEL 留空就不发）'}"
          f" · URL/key 字样 {'命中 ' + str(leak) if leak else '零命中'}")
    ok = ok and same and not leak
print('D 结论：' + ('全部通过' if ok else '有问题'))
PY

  echo
  echo "=== E 桩响应 + --key bag（只该挑到 bag 帧；四行都要出现：命中 / 无命中 / 无框 / 越界框）"
  printf '%s\n' '{"choices":[{"message":{"content":"[{\"text\": \"抽福袋\", \"box\": [0.412, 0.861, 0.588, 0.904]}, {\"text\": \"现金大转盘 免费拿\", \"box\": [0.11, 0.22, 0.90, 0.26]}, {\"text\": \"关闭\", \"box\": []}, {\"text\": \"多多买菜\", \"box\": [600, 1100, 780, 1180]}]"}}]}' > /tmp/va-stub-openai.json
  VLM_STUB=/tmp/va-stub-openai.json bash "$S" "$D" --key bag --max 2 --send --no-local --out /tmp/va-stub
  echo "--- 挑到的帧：$(ls /tmp/va-stub | grep '\.raw$' | tr '\n' ' ')"
  echo "--- 建议配置.txt"; cat /tmp/va-stub/建议配置.txt
  echo "--- 候选词.txt 行数 $(grep -c . /tmp/va-stub/候选词.txt)（每帧只算「有框且在 0..1」的行）"
  echo "--- pdd.sh 一字未动：md5 $(md5sum "$HOME/Desktop/pdd.sh" | cut -c1-12)…"

  echo
  echo "=== F 形状 2（content 是分段数组 + markdown 代码块，词=去抢购）"
  printf '%s\n' '{"choices":[{"message":{"content":[{"type":"text","text":"```json\n[{\"text\": \"去抢购\", \"box\": [0.05, 0.70, 0.30, 0.78]}]\n```"}]}}]}' > /tmp/va-stub-fence.json
  VLM_STUB=/tmp/va-stub-fence.json bash "$S" "$D" --key bag --max 1 --send --no-local --out /tmp/va-stub2 >/dev/null
  cat /tmp/va-stub2/建议配置.txt

  echo
  echo "=== G 形状 3（接口报错，不该出建议）"
  printf '%s\n' '{"error":{"message":"invalid api key"}}' > /tmp/va-stub-err.json
  VLM_STUB=/tmp/va-stub-err.json bash "$S" "$D" --key bag --max 1 --send --no-local --out /tmp/va-err | sed -n '4,8p'
  echo "  建议配置.txt 有内容的行数 $(grep -c . /tmp/va-err/建议配置.txt)（应为 0）"

  echo
  echo "=== K 文件名推不出词表的帧（key=prove，pdd.sh 里没这个词表）"
  VLM_STUB=/tmp/va-stub-openai.json bash "$S" "$D" --glob "*count-prove-bag.png" --max 1 --send --no-local --out /tmp/va-noal | sed -n '3,6p'

else
  skip=$((skip + 4))
  echo
  echo "=== C/D/E/F/G/K/H/I/J 跳过：证据目录不在，需要现成的场次"
fi

echo
echo "=== H 端点留空时 --send 必须挡掉（这条要的就是 78）"
if [ -e "$HOME/Desktop/pdd-vlm.url" ]; then
  echo "  跳过：$HOME/Desktop/pdd-vlm.url 存在，端点已经配上了，这条会在真端点上发请求"
elif [ "$skip" != 0 ]; then
  # 工具的 78 闸门排在"挑帧"之后（挑不到帧先 exit 2），所以这一项也得有现成场次才测得到。
  echo "  跳过：没有证据目录，测不到 78（会被前面那句「挑不到帧」先挡下，rc=2）"
else
  ls -l "$HOME/Desktop/pdd-vlm.url" 2>&1 | tail -1
  bash "$S" "$D" --key bag --max 1 --send --no-local --out /tmp/va-gate >/dev/null 2>&1
  echo "  rc=$?（应 78）；输出目录里 req.json 数 $(find /tmp/va-gate -name '*.req.json' 2>/dev/null | wc -l)（挡在建请求体之前，应 0）"
fi

if [ "$skip" = 0 ]; then
  echo
  echo "=== I 本地那一栏：造一个只有 2 帧的运行目录，真跑 pdd.sh replay --ocr（约 20 秒）"
  mkdir -p /tmp/va-small/202843
  ls "$D2"/*-bag-1.png 2>/dev/null | head -1 | while IFS= read -r p; do cp "$p" /tmp/va-small/202843/; done
  ls "$D2"/*-browse-1.png 2>/dev/null | head -1 | while IFS= read -r p; do cp "$p" /tmp/va-small/202843/; done
  cp "$D2/run.log" /tmp/va-small/202843/ 2>/dev/null
  ls -1 /tmp/va-small/202843
  VLM_STUB=/tmp/va-stub-openai.json bash "$S" /tmp/va-small --key bag --max 2 --send --out /tmp/va-local
  echo "--- replay 原文里的帧行"; grep -E '^[0-9]{6}-' /tmp/va-local/本地replay.txt | head -3
  echo "--- 建议配置.txt 第一行（尾部该带上同一行）"
  # 别用 cut -c：GNU cut 按字节切，UTF-8 会在半个汉字上断掉，打出来是乱码。
  head -1 /tmp/va-local/建议配置.txt

  echo
  echo "=== J 大目录（>12 张）不启动 replay，只报为什么"
  VLM_STUB=/tmp/va-stub-openai.json bash "$S" "$D" --key bag --max 1 --send --out /tmp/va-big 2>&1 | sed -n '1,2p'
fi

echo
echo "selftest: 跳过项 $skip（0 = 全跑）。桩响应证明不了识别质量 —— 那一栏永远是空的，直到接上真端点。"
