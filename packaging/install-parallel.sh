# pddcheck 并行观察模式安装脚本（h61，用户级；不动旧 pdd.timer）
# 用法：bash install-parallel.sh [device-serial]   默认 192.168.1.110:16132
set -eu
SERIAL="${1:-192.168.1.110:16132}"
ROOT="${PDDCHECK_ROOT:-$HOME/pddcheck-staging}"
SHARE="$HOME/Desktop/pdd-runs"
LIB="$HOME/.local/share/pddcheck"
CONF="$HOME/.config/pddcheck"
UNITDIR="$HOME/.config/systemd/user"

mkdir -p "$LIB" "$CONF" "$UNITDIR" "$SHARE"

# 1) launcher（一次解析 current 后 exec）
cat > "$LIB/launcher.sh" <<EOF
#!/bin/sh
set -eu
ROOT="$ROOT"
CUR=\$(cat "\$ROOT/current")
[ -n "\$CUR" ] || { echo "current 指针为空" >&2; exit 78; }
if [ -e "\$ROOT/paused" ]; then echo "paused：跳过本次" >&2; exit 0; fi
SITE="\$ROOT/releases/\$CUR/site"
[ -d "\$SITE" ] || { echo "release \$CUR 未展开" >&2; exit 78; }
exec env PYTHONPATH="\$SITE" python3 -m pddcheck.cli.app "\$@"
EOF
chmod +x "$LIB/launcher.sh"

# 2) 环境文件：共享证据根（日标记与旧流程同源）、取证不推送
cat > "$CONF/env" <<EOF
PDDCHECK_ROOT=$ROOT
PDDCHECK_DEVICE=$SERIAL
PDDCHECK_EVIDENCE=$SHARE
PDDCHECK_STATE=$HOME/.local/share/pddcheck-state
PDDCHECK_NO_PUSH=1
EOF
chmod 600 "$CONF/env"

# 3) 单元（从候选生成正式名，顺手把「候选」标记改成「并行观察」）
sed 's/（候选，未安装）/（并行观察）/g' \
    "$ROOT/pddcheck.service.candidate" > "$UNITDIR/pddcheck.service"
cp "$ROOT/pddcheck.timer.candidate" "$UNITDIR/pddcheck.timer"

systemctl --user daemon-reload
systemctl --user enable --now pddcheck.timer
echo "== installed =="
systemctl --user list-timers pddcheck.timer --no-pager | head -4
