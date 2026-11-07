#!/bin/sh
# 生产接管（用户 2026-11-07 批准）：停旧 pdd.timer，pddcheck 10:00 接管。
set -eu
ROOT="${PDDCHECK_ROOT:-$HOME/pddcheck-staging}"
CONF="$HOME/.config/pddcheck"
UNITDIR="$HOME/.config/systemd/user"
LIB="$HOME/.local/share/pddcheck"
SHARE="$HOME/Desktop/pdd-runs"

mkdir -p "$LIB" "$CONF" "$UNITDIR" "$SHARE"

# 1) 停旧生产 timer（旧流程保留在磁盘，可回滚）
systemctl --user disable --now pdd.timer 2>/dev/null || true
systemctl --user stop pdd.service 2>/dev/null || true

# 2) launcher（生产）
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

# 3) env：生产模式（允许推送，端点读 ~/Desktop/pdd-push.url；共享证据根）
cat > "$CONF/env" <<EOF
PDDCHECK_ROOT=$ROOT
PDDCHECK_DEVICE=192.168.1.110:16132
PDDCHECK_EVIDENCE=$SHARE
PDDCHECK_STATE=$HOME/.local/share/pddcheck-state
EOF
chmod 600 "$CONF/env"

# 4) 单元：生产口径（10:00，无 dry-run）
cat > "$UNITDIR/pddcheck.service" <<'EOF'
[Unit]
Description=PDD 每日签到（pddcheck，生产）
After=network-online.target

[Service]
Type=oneshot
Environment=LANG=C.UTF-8
EnvironmentFile=%h/.config/pddcheck/env
ExecStart=%h/.local/share/pddcheck/launcher.sh run --device ${PDDCHECK_DEVICE} --stages
Nice=10
Restart=no
EOF

cat > "$UNITDIR/pddcheck.timer" <<'EOF'
[Unit]
Description=PDD 每日签到（pddcheck）

[Timer]
OnCalendar=Mon..Sun *-*-* 10:00:00
Persistent=true
AccuracySec=1min
Unit=pddcheck.service

[Install]
WantedBy=timers.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now pddcheck.timer

echo "== takeover =="
systemctl --user is-enabled pdd.timer 2>&1 | sed 's/^/old_pdd_timer=/'
systemctl --user is-enabled pddcheck.timer 2>&1 | sed 's/^/pddcheck_timer=/'
systemctl --user list-timers 'pdd*' --no-pager 2>&1 | head -6
grep -n 'PDDCHECK_NO_PUSH\|PDDCHECK_DEVICE\|dry-run' "$CONF/env" "$UNITDIR/pddcheck.service" || echo "env/service: no NO_PUSH, no dry-run"
