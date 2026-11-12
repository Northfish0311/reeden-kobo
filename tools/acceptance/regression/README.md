# 回归资产（离线，无需设备）

本目录用于在没有 Kobo 的情况下验证 `../scripts/Collect-Evidence.ps1` 与 `../scripts/Check-Evidence.ps1` 的行为。全部基于**合成日志 fixture**，不插 USB、不读真实设备、不写设备。

## 三条命令

先把合成设备布局造出来，再跑静态审计与动态回归：

```powershell
cd tools\acceptance\regression

# (1) 生成 17 个 fixture（幂等，会重建 cases/）
python build_fixtures.py

# (2) 静态审计：源码字符串 / 纯 ASCII / 只读令牌 / 文档一致性
python audit.py

# (3) 动态回归：造证据 → 三态判读 → 断言（默认指向 ../ 的真实交付脚本）
powershell -NoProfile -ExecutionPolicy Bypass -File .\run-regression.ps1
```

验收标准：`REGRESSION RESULT : assertions_failed = 0`。

可用 `-RunTag <名字>` 给本轮结果打标签，输出写到 `results/*-<名字>.txt`，不会覆盖历史轮次：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run-regression.ps1 -RunTag "after-my-change"
```

## 依赖

- **Windows PowerShell 5.1**（脚本按 5.1 语法编写，未使用 `?:`、`??` 等 7.x 语法）
- **Python 3.10+**（只用标准库）
- 跑 `audit.py` 的 **source** 检查需要本地有 reeden-kobo 的 git 克隆。查找顺序：环境变量 `REEDEN_REPO` → 从本目录向上找含 `.git` 且含 `src/host.c` 的目录 → 当前工作目录向上。找不到时 source 检查降级，不会崩溃。
- **不要**用 `powershell -File ... 2>&1 | Select-Object` 这类外层管道套着跑：中文路径下会触发子进程编码问题并导致假失败。直接 `& .\run-regression.ps1` 或 `-File` 不加管道。

## 17 个 fixture

| fixture | 用途 |
| --- | --- |
| `happy` | 全部证据齐全，19 项应为 16 PASS + 3 人工 NEED-EVIDENCE |
| `fail-mem-returned1` | `mem returned=1` → `1.4` / `4.3` / `6.1` 判 FAIL，退出码 2 |
| `fail-no-first-frame` | `no first frame in 20s` → `4.1` 判 FAIL |
| `fail-brightness` | `Nickel brightness update failed` → `4.2` 判 FAIL |
| `guard-supply-only` | 插线充电，只有 `screen-only: supply guard` → 休眠相关项 NEED-EVIDENCE，**不得判 FAIL、不得判 PASS** |
| `guard-display-busy` | 显示忙未进入休眠 → 同上 |
| `rotated-previous-only` | 证据只在 `previous.log` → 验证日志轮转不丢证据 |
| `missing-previous` | 无 `previous.log` |
| `empty-logs` | 空日志 → 19 项应全为 NEED-EVIDENCE |
| `accepted-only` | 只有 `arm ... accepted=1`、无 `bands=` → `3.1` PASS 但 `3.2` NEED-EVIDENCE（`accepted=1` 不等于动画已下发） |
| `frontlight-other-section` | `FrontLightLevel` 写在 `[PowerOptions]` 之外 → 两种模式结论一致且都不 FAIL |
| `powerlog-rotated` | `power.log.1` / `guardian.log` 已轮转 → 验证证据副本被一并采集 |
| `wifi-only` | 只有 `wifi.log` 有 Wi-Fi 证据 |
| `koboconf-override` | 用 `-KoboConf` 显式指定配置文件 |
| `outdir-inside-appdir` | `-OutDir` 落在 `-AppDir` 内 |
| `outdir-equals-appdir` | `-OutDir` **等于** `-AppDir` |
| `outdir-mountroot` | `-OutDir` 等于设备卷根 |

后三个用于验证 `-OutDir` 安全边界：必须 `exit 3`、**零文件写入设备**。`device-absent` 故意不创建，用于验证设备缺席时 `Collect` 退出码 0、`Check` 退出码 3。

## 关键断言口径

### 4.3 深睡判据（`4.3` 已收紧）

`4.3` 不认 `[power] invoked arg=suspend`：该行由 `scripts/power.sh:7` 无条件打印，插线充电时 `power.sh:89` 走供电保护 `exit 3`，设备根本没进内核，旧口径在插线场景必然假阳性。

| fixture | 4.3 期望 |
| --- | --- |
| `happy` | `PASS`（有 `entering mem` + `mem returned=0`） |
| `guard-supply-only` | `NEED-EVIDENCE`（插线充电，不是失败） |
| `guard-display-busy` | `NEED-EVIDENCE` |
| `fail-mem-returned1` | `FAIL` |
| `powerlog-rotated` | `NEED-EVIDENCE`（`power.log` 本身为空） |

`-Could not become idle` / 闹钟冲突 / Wi-Fi 未交还这类准备阶段失败，本包按「证据不足」处理，不判 FAIL；严格判定交给 `tools/Check-SuspendGate.ps1`。

### 三态语义

- `PASS`：必需标记齐备，或明确的设计内兜底结果已达成
- `FAIL`：命中**明确反证**（`mem returned≥1`、`no first frame in 20s`、`Nickel brightness update failed`、`display-sequence cancelled` 等）
- `NEED-EVIDENCE`：证据不足。**证据不足绝不判 FAIL**

退出码：`0` 全 PASS；`1` 有 NEED-EVIDENCE 无 FAIL；`2` 至少一项 FAIL；`3` 找不到证据源。

## `audit.py` 的三项检查

| 检查 | 内容 |
| --- | --- |
| `source` | 43 条日志字面量逐条对 `git show v0.7.9-community.4:<path>` 核对（锚定不可变 tag，**不使用会移动的 origin/main**），并校验 tag 未被重指 |
| `ascii` | 两个 `.ps1` 字节级纯 ASCII、无 BOM、无禁止的写设备令牌、Check 不做时间判定 |
| `docs` | 19 个检查 ID 在清单 / 脚本 / 报告三处一致 + README 语义主题；**三份中文文档缺失时输出 `SKIP` 而非 FAIL**（本目录作为工具集随仓库分发时，文案以 `docs/` 下清单为准） |

## 目录产物

跑完会生成 `cases/`（fixture）、`out/`（采集到的证据）、`results/`（每场景输出与断言明细）。这三者都是本地产物，**不要提交进仓库**。
