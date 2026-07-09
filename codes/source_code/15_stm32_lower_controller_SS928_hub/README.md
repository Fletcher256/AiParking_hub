# SS928_hub

STM32F103 遥控/自主小车固件。

## 构建

已检入的 Keil 工程仍可使用：`LED_1.uvprojx`。

同时提供了一个 GCC 构建入口，用于命令行验证：

```powershell
powershell -ExecutionPolicy Bypass -File build_gcc\build.ps1
```

该脚本会优先查找本地 `tools/gcc-arm/...` 下的 xPack 工具链；如果不存在，则回退使用 `PATH` 中的 `arm-none-eabi-gcc`。

构建产物输出到：

- `build/gcc/SS928_hub.elf`
- `build/gcc/SS928_hub.hex`
- `build/gcc/SS928_hub.bin`

## 串口命令帧格式

文本命令通过 USART3 发送，格式如下：

```text
@COMMAND\r\n
```

## 控制命令

仍然支持旧版命令：

- `SR_ACC`：增加速度档位。
- `SR_DEC`：降低速度档位。
- `SR_SETn`：设置速度档位，`n` 为 `0..6`。
- `SR_PAU`：停止速度输出。
- `DT_1`：前进。
- `DT_0`：后退。
- `DT_STA`：直行保持模式。
- `DT_TUR`：手动转向模式。
- `RT_TOx`：使用旧版映射设置转向，`servo = 180 - x`。
- `ST_KP/ST_KI/ST_KD`：调整航向 PID 参数。
- `ST_SB`：待机并停车。
- `ST_PK`：进入泊车运行状态，但不启动运动。
- `ST_ER`：紧急/错误停止。

新的遥控/自主命令：

- `RC_MAN`：手动模式。
- `RC_STOP` 或 `AU_STOP`：立即停车并进入待机。
- `RC_HB`：心跳命令。手动驾驶时应周期性发送。
- `RC_STR`：使用 IMU 航向和编码器横向偏差修正的直行保持模式。
- `RC_SPDn`：设置速度档位，`n` 为 `0..6`。
- `RC_STEx`：直接设置舵机角度，并限制在安全转向范围内。固件默认范围为 `55..125`。
- `RC_DSTx`：直线行驶 `x` cm。负值表示后退。
- `RC_YAWx`：相对当前 yaw 转向 `x` 度。正值表示左转。
- `RC_AUTO` 或 `AU_RUN`：执行默认自主路线：前进 100 cm，左转 90 度，前进 60 cm，停止。

## 安全行为

- 手动模式和直行保持模式在车辆运动时，如果 2 秒内没有收到命令或心跳，会自动停车。
- 定距动作如果 30 秒内未到达目标，会自动停止。
- 转角动作如果 8 秒内未到达目标，会自动停止。
- 当前硬件配置不包含障碍物检测，因此自主模式仅基于里程计/IMU。

## OLED 动作图像

OLED 被用作 128x64 单色状态显示屏。动作级图像通过 `OLED_StateAnim_ShowAction()` 分发，并且只在动作变化时渲染，因此 I2C 显示更新不会在控制循环中持续运行。

自定义图片推荐使用 LVGL Image Converter 的以下设置：

- 尺寸：`128 x 64`。
- 颜色：1-bit 单色。
- 当数组已经是 SSD1306 页格式时，使用 `OLED_DrawBitmap128x64()`：8 页 x 128 字节。
- 当数组是按行排列的 1-bit 像素时，使用 `OLED_DrawMonoBitmap128x64()`：64 行 x 16 字节。
- 每张全屏图片的最终像素数据保持为 `1024` 字节。

该固件并未链接完整的 LVGL 库。小型的 `lvgl.h` / `lvgl/lvgl.h` 兼容头文件只提供 LVGL Image Converter 常见输出所需的图像描述符类型和常量。它们仅用于位图资源，不用于 LVGL 控件、定时器、样式或显示驱动。