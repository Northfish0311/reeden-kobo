# Reeden Kobo 兼容层 (0.7.0 Experimental)

在 **Kobo Clara Colour（产品代码 393）** 上原字节运行官方 **Reeden Kindle 1.43.1+780** 核心的开源 C 宿主与硬件兼容层。

> **合规与版权说明**：本仓库仅包含 MIT 协议的 Kobo 宿主适配代码、预编译适配层二进制及 SIL OFL 开源字体，**不包含任何 Reeden 官方闭源二进制或 Debian 发行版运行库文件**。安装脚本会在本地电脑上结合你自己下载的 `Reeden-kindle.zip`（原字节不改）与 Debian 官方镜像源一键完成组包与安装。

---

## 一、支持环境与前提条件

| 项目 | 要求 |
|---|---|
| **支持设备** | Kobo Clara Colour（产品代码 `393`，MT8113T，1072×1448 32bpp，旋转 `3`） |
| **已测固件** | `4.46.23836`（ARMHF Linux 4.9.77） |
| **前置插件** | Kobo 已安装 [NickelMenu](https://pgaskin.net/NickelMenu/)（存在 `/mnt/onboard/.adds/nm/` 目录） |
| **官方核心** | 自行从 [Reeden 官网](https://reeden.app/cn/download/kindle) 下载 **Kindle 1.43.1+780** (`Reeden-kindle.zip`) |
| **电脑环境** | macOS / Windows / Linux，安装有 Python 3（仅用标准库，无需安装 Zig、C 编译器或第三方包） |

---

## 二、一键安装与升级（普通用户）

### 第 1 步：准备官方包
从 [Reeden 官方下载页](https://reeden.app/cn/download/kindle) 下载 `Reeden-kindle.zip`（版本 `1.43.1+780`），直接放在本目录或电脑的「下载 (`Downloads`)」文件夹中（无需手动解压）。

### 第 2 步：选择任一方式一键安装

#### 方式 A：USB 数据线一键安装 / 升级（推荐，免 SSH）
1. 用 USB 数据线将 Kobo Clara Colour 连接到电脑，在 Kobo 屏幕点击「连接」（电脑出现 `KOBOeReader` 盘符）。
2. 直接双击运行对应系统的启动脚本：
   - **macOS**：双击 `一键安装-macOS.command`
   - **Windows**：双击 `一键安装-Windows.bat`
   - **Linux / 终端**：运行 `python3 install.py --usb`（若已安装旧版需保留书库与阅读进度升级，可加 `--upgrade`，交互模式下会自动识别并保留数据）
3. 脚本会自动完成：
   - 校验官方 `Reeden-kindle.zip`（`libflutter_engine.so` 与 `libapp.so` SHA-256）
   - 下载并校验 10 个固定版本的 Debian Bullseye ARMHF 运行库与 Mozilla 根证书
   - 合成 `ui-assets` 中文字体与数学符号覆盖层
   - 校验 Kobo 机型码（`393`），将 457 个文件写入 `.adds/reeden-kobo` 并逐文件校验 SHA-256（升级时自动备份旧版并保留 `userdata/` 阅读进度、笔记、冷暖光设置及 `storage/` 书库）
   - 写入 NickelMenu 启动项 `.adds/nm/reeden-kobo`
4. 安全弹出 USB，回到 Kobo 原生主界面，点击右下角 **NickelMenu → `Reeden Kobo (test)`** 即可启动。

#### 方式 B：Wi-Fi SSH 无线一键安装 / 升级
若 Kobo 已开启 KOReader SSH（默认端口 `2222`）或独立 SSH（端口 `2223`）：
```sh
# 全新安装
python3 install.py --ssh 192.0.2.10 --port 2222

# 保留书库、阅读进度与冷暖光设置升级
python3 install.py --ssh 192.0.2.10 --port 2222 --upgrade
```

#### 方式 C：仅在电脑生成完整运行包 (`package/`)
```sh
python3 install.py --official-core /path/to/Reeden-kindle.zip --output package
```

---

## 三、核心适配特性 (0.7.0)

- **原字节复用官方核心**：`libflutter_engine.so`、`libapp.so` 及原始资源保持原字节不变；不修改账号、授权或付费逻辑；禁用 Kindle 自更新覆盖 Kobo 宿主。
- **墨水屏刷新策略（对齐 KOReader MTK）**：
  - **白底灰阶**：局部 `GLR16 (4)` / 清屏 `GC16 (2)`
  - **纯灰阶黑底（夜间模式）**：局部 `GLKW16 (9)` / 清屏 `GCK16 (8)`，配合 KOReader MTK `night_mode 4` 硬件反相与互补灰阶提交，消除黑底全刷白闪
  - **真实彩色与旧色擦除**：局部 `GLRC16 (11)` / 清屏 `GCC16 (10)` + `CFA G2 (0x600)`，抑制 2 级以内 RGB 舍入噪声误触发彩色模式
  - **帧同步与边界对齐**：16 像素对齐 + 边缘余量，RAM 帧缓存跳过重复帧，每次 FULL REAGL/CFA 请求等待刷新完成同步
- **阅读界面冷暖光扩展 (0.5.0+)**：
  - 在「书页中央 → 显示」前光行下方合成硬件「冷暖」控制行（0 最冷 ～ 100 最暖，10% 步进，对应底层 `lm3630a_led/color` 0–10 反向混光），松手持久化至 `userdata/kobo-light.conf`
- **电源键锁屏、深度休眠与隔夜唤醒保护 (0.7.0)**：
  - 支持「自定义锁屏画面」，短按电源键锁屏并进入 Linux `mem` 深度休眠（充电时按 MTK 限制仅锁屏关灯、跳过内核深睡），再按直接唤醒回到当前书页
  - 使用独立非 `SIGCHLD` (`__WCLONE`) 监督进程等待休眠脚本，避免与 Dart 3.12.2 全局 `wait()` 回收线程竞争导致唤醒卡死
  - 记录 `preparing / suspended / resuming / complete` 阶段时间戳；准备或唤醒恢复超过 45 秒由 `guardian.sh` 自动恢复 Kobo 原生界面
- **安全交接与退出恢复**：
  - 首帧在内存中渲染完成后才暂停 Nickel 并接管屏幕与触控
  - **同时按住屏幕左上角和右上角约 2 秒**即可正常退出 Reeden，还原硬件反相与前光，并以断电干净状态将 Wi-Fi 交还给新启动的 Kobo 原生界面

---

## 四、日常使用与故障恢复

1. **启动**：先从 KOReader 退出回到 Kobo 原生主页并连接 Wi-Fi，在 NickelMenu 点击 `Reeden Kobo (test)`。
2. **导书**：应用内 `/mnt/us` 映射到 `/mnt/onboard/.adds/reeden-kobo/storage/`（如放入 `storage/documents/` 或使用 Wi-Fi 传书）。
3. **锁屏与唤醒**：建议在「我的 → 墨水屏」开启「自定义锁屏画面」。短按电源键休眠，再按唤醒继续阅读。
4. **退出回原生系统**：同时按住屏幕 **左上角 + 右上角约 2 秒**。
5. **紧急恢复与卸载**：
   - NickelMenu 点击 `Reeden Kobo - Return Home`，或 SSH 运行 `sh /mnt/onboard/.adds/reeden-kobo/recover.sh`
   - 卸载（保留全部阅读数据与书籍）：退出后运行 `sh /mnt/onboard/.adds/reeden-kobo/uninstall.sh`

详细验收记录与已知限制请参阅 [docs/测试说明.md](docs/测试说明.md)。

---

## 五、从源码交叉编译与运行测试（开发者）

本仓库已内置 `prebuilt/` 预编译二进制，普通用户无需编译。开发者如需自行从 C 源码交叉编译：

1. 准备 [Zig 0.13.0](https://ziglang.org/download/)。
2. 编译 ARMHF 宿主、兼容库、静态帧缓冲守卫与目标机测试程序（支持无官方二进制时通过 `src/flutter_engine_stub.c` 独立完成编译，产物哈希与连接官方库完全一致）：
   ```sh
   ZIG=/path/to/zig sh scripts/build.sh
   sha256sum -c prebuilt/PREBUILT_SHA256SUMS
   ```
3. 运行电脑端隔离回归测试：
   ```sh
   python3 tests/launcher_test.py
   python3 tests/native_network_test.py
   python3 tests/power_guard_test.py
   python3 tests/wake_guard_test.py
   ```

---

## 六、开源许可与致谢

- 适配层代码采用 [MIT License](LICENSE)。
- 官方 Reeden 核心归 Reeden 官方所有，遵循其自身条款，严禁在公开仓库或衍生包中默认分发官方闭源二进制。
- 包含 Flutter Embedder Header (`vendor/Flutter-LICENSE`)、cJSON (`vendor/cJSON-LICENSE`)、Noto CJK / Math (`vendor/NotoSans*-LICENSE`)、musl (`vendor/musl-LICENSE`) 与 Zig (`vendor/Zig-LICENSE`) 许可证声明。
- 硬件接口参考：[KOReader Kobo device](https://github.com/koreader/koreader/blob/master/frontend/device/kobo/device.lua)、[KOReader MTK framebuffer](https://github.com/koreader/koreader-base/blob/master/ffi/framebuffer_mxcfb.lua)、[Kobo MT8113 Kernel](https://github.com/kobolabs/Kobo-Reader/tree/master/hw/mt8113-libraC_vision7)。
