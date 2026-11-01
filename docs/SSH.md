# 可选诊断 SSH

阅读器和 USB 安装不需要 SSH，也不依赖 KOReader。公开安装包不自动启动 SSH，默认菜单仅提供 **Reeden SSH - Stop**。

## 从旧版升级

v0.7.0 的诊断脚本使用 KOReader dropbear 的密码检查跳过选项。升级脚本不会中断已有远程会话。请在原生菜单点击 **Reeden SSH - Stop** 关闭旧监听服务，结束已有 SSH 会话；或退出 Reeden 后重启设备。停止监听本身不会强制断开已连接的会话。

## 确实需要诊断服务时

此工具依赖 KOReader 的定制 dropbear 二进制，但不会直接复用 KOReader 的认证配置。先在电脑上生成 SSH 密钥并妥善保存私钥；设备只接收公钥。

1. 通过 USB 在 `.adds/reeden-kobo/diagnostics/ssh/settings/SSH/` 下创建 `authorized_keys`，放入你自己的完整 OpenSSH 公钥行。建议使用 Ed25519 公钥；不要复制私钥。
2. 确保已安装 KOReader（提供 dropbear），或在 `.adds/reeden-kobo/diagnostics/ssh/reeden-ssh` 放置兼容的 KOReader dropbear。工具不下载 SSH 服务器。
3. 从已有管理终端明确运行 `sh /mnt/onboard/.adds/reeden-kobo/reeden-ssh.sh start`。脚本缺少公钥或 Wi-Fi 地址时拒绝启动；不传参数只显示状态。
4. 服务仅使用公钥认证，禁用密码认证和端口转发，绑定当前 wlan0 IPv4 地址的 2223 端口。用你的私钥连接：`ssh -i /path/to/private_key -p 2223 root@<Kobo_IP>`。首次连接核对设备主机密钥。
5. 结束后运行同一脚本的 `stop` 子命令，并关闭已有会话；`status` 查询状态。Wi-Fi 地址改变后需手动停止并重新启动监听。

本工具没有经过本轮真实设备上的密钥登录验收；自动化测试覆盖启动参数、无公钥拒绝启动、默认不启动，以及状态/停止不启动服务。不要在尚未确认新密钥能连接前删除你现有的管理入口。
