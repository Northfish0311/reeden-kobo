# 验收证据三态判读工具（community.4 / community.5）

> 定位：`docs/实机验收清单-v0.7.9-community.4.md` 的**只读取证辅助工具**。它不替代那份清单，也不代表官方测试结论。
> 适用：Kobo Clara Colour（产品码 393）/ 固件 4.46.23852 / 应用目录 `E:\.adds\reeden-kobo`；代码基准 `v0.7.9-community.4`。

community.5 保留 `.4` 日志格式，并补充识别 `[color-turn]` 彩色水波纹完成或失败记录。`.4` 基线审计仍锚定原标签，不把历史测试改写为 `.5` 实机验证。盘符 `E:` 只是示例，需换成你实际的 Kobo 磁盘；固件号是验收目标，不代表本工具已经证明该固件兼容。详细更新范围见[community.5 发布说明](../../docs/releases/v0.7.9-community.5.md)。

## 解决什么问题

验收清单是给人逐条勾的。本工具把「日志里到底有没有证据」这一步自动化，避免人工翻日志时漏看或误判：

- `Collect-Evidence.ps1`：从设备盘**只读**复制日志到电脑，并生成 `manifest.json`。
- `Check-Evidence.ps1`：对 **19 项**逐项给出 `PASS` / `FAIL` / `NEED-EVIDENCE`，同时打印命中的原始日志行。

两个脚本对设备**零写入**：只用 `Test-Path` / `Copy-Item` / `ReadAllBytes` 读取，不含 `Remove-Item`、不向设备路径 `Set-Content` / `New-Item`、不跑 `chkdsk`、不改 `SHA256SUMS`。
`-OutDir` 若落在设备卷根或 `-AppDir` 之内会直接拒绝并 `exit 3`，防止把证据写回设备。

## 与仓库其他工具的分工

| 工具 | 职责 | 边界 |
| --- | --- | --- |
| `docs/实机验收清单-v0.7.9-community.4.md` | **权威验收口径**：用例、质量门禁、安全红线、阻塞项 | 文案与合格判定以它为准 |
| `tools/Check-SuspendGate.ps1` | **深睡四联判据的严格门禁**：按 pid 配对、校验 uptime 跨度、入口行只计数 | 深睡是否真正进入内核，以它为准 |
| `tools/acceptance/`（本目录） | **19 项三态筛查**：告诉你哪些项证据齐、哪些不齐 | 是筛查工具，不是最终合格判定 |

### 关于 4.3 深睡判据

本包 4.3 **不把 `[power] invoked arg=suspend` 当通过依据**：

- `scripts/power.sh:7` 在脚本入口**无条件打印**该行，只要宿主以 `suspend` 调用就必有；
- `power.sh:89` 的供电保护在 USB 充电 / 非 `Discharging` / `external=on` 时打印 `[power] screen-only: supply guard` 后**直接 `exit 3`**，设备只锁屏、从未进内核；
- 而验收必须插 USB 才能读到 `power.log`，所以「见到入口行就算通过」在插线场景下**必然假阳性**。该口径已被 `docs/实机验收清单-v0.7.9-community.4.md` 第 4 节明确废止。

4.3 只认 `entering mem` + `mem returned=0`：

| 日志情况 | 4.3 判定 |
| --- | --- |
| `entering mem` 且 `mem returned=0` | `PASS` |
| `mem returned=[1-9]` 或 `short mem return after` | `FAIL` |
| 只有 `screen-only: supply guard`（插线充电） | `NEED-EVIDENCE`，**不判失败** |
| 只有入口行 / 显示忙 / 闹钟冲突 / Wi-Fi 未交还 | `NEED-EVIDENCE` |

需要完整四联（含 `phase=suspended` → `phase=resuming` 的 uptime 跨度 > 5 秒）时，请跑 `tools/Check-SuspendGate.ps1`。

## 快速开始

```powershell
# 1) 先在 Kobo 上退出 Reeden 回到原生主页，再插 USB 并点「连接」
cd tools\acceptance
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Collect-Evidence.ps1 `
    -AppDir "E:\.adds\reeden-kobo" -OutDir .\evidence

# 2) 判读（-EvidenceDir 默认就是 .\evidence）
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Check-Evidence.ps1 -EvidenceDir .\evidence
```

也可以跳过取证，直接只读判读设备：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Check-Evidence.ps1 -AppDir "E:\.adds\reeden-kobo"
```

设备没插时会打印 `DEVICE NOT AVAILABLE` 并以**退出码 0** 结束——这不是错误。

## 19 项检查

| ID | 检查项 | 证据来源 |
| --- | --- | --- |
| 1.1 | Cover sensor recognized / enabled | `current.log` |
| 1.2 | Cover close edge recorded | `current.log` |
| 1.3 | Screen locked, front light off, engine retained | `current.log` |
| 1.4 | Kernel suspend request and return | `power.log` |
| 1.5 | Cover open restores reader | `current.log` |
| 2.1 | Power key short press locks and calls power.sh suspend | `power.log` |
| 2.2 | Power key second press wakes reader | `current.log` |
| 3.1 | armPageTurn request reached adapter | `current.log` |
| 3.2 | Water-ripple animation actually submitted（含 `.5` 彩色实验） | `current.log` |
| 3.3 | Ripple settings combination（人工） | 无日志 |
| 4.1 | First frame timing in launcher.log | `launcher.log` |
| 4.2 | Native FrontLightLevel handoff | `Kobo eReader.conf` + `launcher.log` |
| 4.3 | Deep sleep reached kernel mem（四联见 `Check-SuspendGate.ps1`） | `power.log` |
| 5.1 | Control panel opened and Wi-Fi probed | `current.log` |
| 5.2 | Wi-Fi real toggle executed | `current.log` |
| 5.3 | Panel Lock Now triggers suspend path | `current.log` |
| 5.4 | Return to reading restores latest page（人工） | 无日志 |
| 6.1 | Overnight suspend phase chain recorded | `power.log` |
| 6.2 | Overnight battery readings（人工） | 无日志 |

人工确认项 **3.3 / 5.4 / 6.2** 恒为 `NEED-EVIDENCE`，脚本不做自动判定。

## 三态与退出码

| 状态 | 含义 |
| --- | --- |
| `PASS` | 找到源码定义的必需标记，或明确的设计内兜底结果已达成 |
| `FAIL` | 找到**明确反证**（`mem returned≥1`、`no first frame in 20s`、`Nickel brightness update failed`、`display-sequence cancelled` 等） |
| `NEED-EVIDENCE` | 证据不足。**证据不足不判 FAIL**：可能没做这一步、日志被轮转、走了供电保护或显示忙兜底，或该项只能肉眼观察 |

退出码：`0` 全部 PASS；`1` 有 NEED-EVIDENCE 但无 FAIL；`2` 至少一项 FAIL；`3` 找不到证据源。

## 现场纪律

1. **先在 Kobo 上退出 Reeden 回原生主页，再插 USB**；等系统提示安全卸载再拔线。反复带电拔线曾写坏 FAT32。
2. 合盖 / 短按电源键的深睡取证，**必须在拔掉 USB、电池供电下完成并保持拔线直到唤醒**；一轮结束后退出 Reeden，再插线读日志（日志追加写入，不会丢）。插着 USB 的会话一律不判 `PASS` 也不判 `FAIL`。
3. 亮度：Reeden 用感知刻度（如 11）、sysfs / Nickel 用硬件刻度（如 46），**数字不同属正常，按观感判定**。
4. 日志时间戳通常为 UTC（比北京时间早 8 小时），源码未强制时区；实机请先核对设备 `date` 输出确认偏移，`src/host.c` 的 `wall=<epoch>` 可作绝对锚点。
5. `userdata/no-sleep-cover` 是**人工创建**的空文件，用于停用盖检测；**本工具绝不创建它**。

## 回归资产

`regression/` 下是离线自测，不需要设备：

```powershell
cd regression
python build_fixtures.py     # 生成 19 个合成 fixture
python audit.py              # 源码字符串 / 纯 ASCII / 文档一致性
powershell -NoProfile -ExecutionPolicy Bypass -File .\run-regression.ps1
```

详见 `regression/README.md`。

## 已知限制

- **6.1 只收集证据，不判定隔夜功耗是否达标**：官方明确 `mem` 返回成功、或前后相隔数小时，都不等于测得真正低功耗。
- **3.2 不判定彩字观感**：彩色条带完成日志只证明软件事务完成；淡色、接缝和残影需真机观察。彩色实验回退会记为动画未成功，不等于普通彩色刷新也失败。
- `scripts/guardian.sh` 的看门狗超时 / 心跳日志目前没有对应判据，看门狗中止启动只会得到 `NEED-EVIDENCE`（偏保守，不会误报通过）。
- 本工具的全部验证基于合成日志。**官方 release 明示 `.4` 尚未完成真实 Kobo 的合盖休眠、开盖唤醒、隔夜功耗与原生设置交接验收**；CI 全绿不等于实机通过。
