#!/bin/sh
# Reeden on Kobo -- 接设备第一件事：枚举 /dev/input/event*
#
# 目的：确认 event2 是否就是内部 GPIO 电源键（host.c 首选该节点，但不要求）、
#       src/input.c:26 默认的 event1 确实是触摸，并预判 src/cover.c
#       能否识别到 SW_LID 或 gpio-keys/ntx_event0 上的 KEY_F1。
#       若没有任何内部设备上报 KEY_POWER，host.c 会退回 event2（与旧版一致），
#       此时电源键不可用，不要在错误的设备上跑 C/D/F 组用例。
#
# 用法（必须在【拔线、Nickel 主页】下执行；USB mass storage 时 NickelMenu 点不了）：
#   1. 把本文件放到 E:\.adds\reeden-kobo\ 下（插 USB、点「连接」后复制）
#   2. 安全弹出并拔线
#   3. 在 NickelMenu 里加一次性条目调用：sh /mnt/onboard/.adds/reeden-kobo/kobo-input-enum.sh
#      （或用 docs/SSH.md 的诊断 SSH 登录后直接执行）
#   4. 再插 USB，读取 E:\.adds\reeden-kobo\logs\input-enum.txt
#   5. 用完删除本脚本与输出文件（S11：原始枚举结果不公开上传）
#
# 写入范围：仅 $OUT 一个文件；不写系统分区、不改任何配置、不加载模块。
# 自测覆盖：INPUT_ENUM_DEVICES / INPUT_ENUM_OUT 两个环境变量，可在电脑上用合成样本演练。

set -u
APP=/mnt/onboard/.adds/reeden-kobo
DEVICES=${INPUT_ENUM_DEVICES:-/proc/bus/input/devices}
OUT=${INPUT_ENUM_OUT:-$APP/logs/input-enum.txt}

outdir=$(dirname -- "$OUT")
[ -d "$outdir" ] || mkdir -p "$outdir" || { echo "cannot create $outdir" >&2; exit 1; }

{
  echo '=== input enumeration (read-only) ==='
  echo "utc=$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  echo "kernel=$(uname -a 2>/dev/null)"
  echo "version=$(tr -d '\r\n' < /mnt/onboard/.kobo/version 2>/dev/null || echo unknown)"
  echo
  echo '=== /proc/bus/input/devices (raw) ==='
  cat "$DEVICES" 2>&1
  echo
  echo '=== /dev/input/event* ==='
  ls -l /dev/input/event* 2>&1
  echo
  echo '=== /proc/bus/input/handlers ==='
  cat /proc/bus/input/handlers 2>&1
  echo
  echo '=== structured view + verdict ==='

  awk '
    function hexval(c) { return index("0123456789abcdef", tolower(c)) - 1 }
    function pow2(n,   r, i) { r = 1; for (i = 0; i < n; i++) r = r * 2; return r }
    # B: 行是十六进制位图：kernel input_print_bitmap() 从【最高字往前】打印，
    # 且跳过前导零字、每个字不补前导零。所以最后一个字才是 bit0 所在字，
    # 字长由最长字推断（ARMHF 32-bit -> 8 hex/字；64-bit -> 16 hex/字）。
    function hasbit(s, n,   a, cnt, i, maxlen, wb, idx, hex, v, j, b) {
      cnt = split(s, a, /[ \t]+/)
      if (cnt == 0 || a[1] == "") return 0
      maxlen = 0
      for (i = 1; i <= cnt; i++) if (length(a[i]) > maxlen) maxlen = length(a[i])
      wb = (maxlen > 8) ? 64 : 32
      idx = cnt - int(n / wb)          # 倒数第 (n/wb + 1) 个字
      if (idx < 1 || idx > cnt) return 0
      hex = a[idx]; v = 0
      for (j = 1; j <= length(hex); j++) v = v * 16 + hexval(substr(hex, j, 1))
      b = n % wb
      return int(v / pow2(b)) % 2
    }
    function emit(   n, h, i, ev, lid, f1, ka, mt, gpio, pw, internal, role) {
      if (name == "" && handlers == "") return
      n = split(handlers, h, /[ \t]+/)
      if (n == 0) return
      lid = hasbit(sw, 0)          # SW_LID = 0x00
      f1  = hasbit(key, 59)        # KEY_F1 = 0x3b
      ka  = hasbit(key, 30)        # KEY_A = 0x1e
      mt  = hasbit(absb, 53)       # ABS_MT_POSITION_X = 0x35
      pw  = hasbit(key, 116)       # KEY_POWER = 0x74, the bit host.c actually tests
      internal = (bus ~ /^(0019|0018|001c)$/)   # BUS_HOST / BUS_I2C / BUS_SPI
      gpio = (name == "gpio-keys" || name == "ntx_event0") && f1 && !ka
      for (i = 1; i <= n; i++) {
        if (h[i] !~ /^event[0-9]+$/) continue
        ev = substr(h[i], 6)
        role = ""
        if (mt || name ~ /[Tt]ouch|cyttsp|epd|ft5|goodix|elan/) role = role " TOUCH"
        if (name ~ /gpio-keys|ntx_event0|[Pp]ower/) role = role " GPIO_POWER"
        if (pw) role = role " KEY_POWER"
        if (internal) role = role " internal-bus"
        if (lid) role = role " SW_LID"
        if (gpio) role = role " INTERNAL_KEY_F1"
        printf "event%-2s | Name=%-24s | SW_LID=%d KEY_F1=%d KEY_A=%d ABS_MT=%d KEY_POWER=%d |%s\n", \
               ev, name, lid, f1, ka, mt, pw, role
        if (ev == "1" && (mt || name ~ /[Tt]ouch|cyttsp|epd|ft5|goodix|elan/)) event1_touch = 1
        # host.c 首选 event2，但只在它真的上报 KEY_POWER 时才直接用
        if (ev == "2" && pw) event2_power = 1
        if (pw && internal && power_src == "") power_src = ev
        # cover_open() 遇到 EV_SW 就 break，SW_LID 优先于 gpio-keys KEY_F1
        if (lid) cover_src = ev ":SW_LID"
        else if (gpio && cover_src == "") cover_src = ev ":internal KEY_F1"
      }
      name = ""; handlers = ""; key = ""; sw = ""; absb = ""; bus = ""
    }
    /^[[:space:]]*$/ { emit(); next }
    /^I: Bus=/       { bus = $0; sub(/^I: Bus=/, "", bus); bus = substr(bus, 1, 4); next }
    /^N: Name=/      { name = $0; sub(/^N: Name=/, "", name); gsub(/"/, "", name); next }
    /^H: Handlers=/  { handlers = $0; sub(/^H: Handlers=/, "", handlers); next }
    /^B: KEY=/       { key = $0; sub(/^B: KEY=/, "", key); next }
    /^B: SW=/        { sw = $0; sub(/^B: SW=/, "", sw); next }
    /^B: ABS=/       { absb = $0; sub(/^B: ABS=/, "", absb); next }
    END {
      emit()
      print "---"
      if (event2_power) print "PASS  event2 reports KEY_POWER -> host.c takes it directly and never scans"
      else if (power_src != "") print "PASS  KEY_POWER is on event" power_src " (internal bus) -> host.c scans and takes it; expect [power] exclusive power key acquired (event" power_src " scanned ...)"
      else print "STOP  no internal device reports KEY_POWER -> host.c falls back to event2, so the power key will not sleep or exit; rely on the both-corner touch escape and do NOT run C/D/F cases"
      if (event1_touch) print "PASS  event1 matches src/input.c:26 (touch)"
      else              print "WARN  event1 is not recognisably touch -> set REEDEN_TOUCH before testing"
      if (cover_src != "") print "INFO  cover.c candidate expected at " cover_src
      else                 print "INFO  no SW_LID / internal KEY_F1 found -> cover.c will report [no supported internal lid input]; only the unsupported branch can be tested"
      print "NOTE  raw devices dump above is authoritative; cross-check [cover] candidate lines in current.log"
    }
  ' "$DEVICES" 2>&1
} > "$OUT" 2>&1

echo "written: $OUT"
