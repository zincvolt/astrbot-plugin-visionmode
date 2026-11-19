# astrbot-plugin-visionmode

读图方式切换插件，用于 [AstrBot](https://github.com/AstrBotDevs/AstrBot)。

它决定机器人"怎么看图"——用本地小视觉模型、用第三方视觉 API，还是干脆关闭。

## 功能

管理员命令 `/读图 本地|第三方|关`：

- **本地 local**：由本机 VL 服务（默认 8085 端口，Qwen3-VL）先把图转成文字，再注入给聊天模型——聊天模型永远收不到图片本体，省钱省显存。
- **第三方 third_party**：把原图直接交给支持看图的第三方模型（如 DeepSeek flash）。
- **关闭 off**：不读图。

状态存在 `data/vision_mode.json`：

```json
{ "mode": "local | third_party | off", "port": 8085, "model": "Qwen3VL-2B-Instruct" }
```

本地 VL 服务不可用时，caption 会降级成 `（读图能力不可用）`，不会让整条回复失败。

## 依赖

- AstrBot 4.28+
- 本地模式需 8085 端口的 VL 服务；第三方模式需模型本身支持图片输入

## 许可证

AGPL-3.0-or-later，见 [LICENSE](LICENSE)。
