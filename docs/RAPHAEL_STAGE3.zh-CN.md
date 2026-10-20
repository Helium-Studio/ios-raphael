# raphael 第三阶段：触控与 sweet 差异

2026-10-20：用户已确认 0082e 能显示苹果 Logo 并进入锁屏，Logo 停留是启动慢。
第三阶段先恢复触控；当前已安装的 boot 和 userdata 保留，触控版本用临时启动验证。

## 已抓取的启动日志

按 README 的 `tools/sweet-log-pull.sh` 读取 userdata 尾部；使用本机 Recovery
（`fastboot oem reboot-recovery`）和 Windows ADB，不需要在 Recovery 中挂载 HFS+。
日志与原始环形缓冲区保存在私有 `research/raphael-0082e-boot.txt` / `.txt.bin`。
1025 个 4 KiB 块，共 4198400 字节；SWEETLOG v1，有效日志 156275 字节，flush 53，未回卷。

已确认：UFS LUN0 的 userdata 以 read-write 接管、journaled HFS+ 根挂载、launchd
缓存加载完成，SpringBoard 和 backboardd 运行，AppleCLCD 使用 1080×2340、stride4320，
以 1125×2436 逻辑画布提交了 BGRA surface。没有记录到 kernel panic。
这与用户看到锁屏一致，不能把等待线程或缺少 IOAcceleratorES 当作启动死锁。
日志中 driverkitd 被 SIGKILL，bluetoothd / fairplayd.H2 多次重启；尚未定位它们的退出原因。

## 触控：不能只改芯片名

| 项目 | 原 sweet 实现 | raphael 的来源与实测 |
| --- | --- | --- |
| 芯片 | GT9896 Yellowstone，另支持 Focaltech 54:52 | GT9886 Normandy；Recovery 实测 PID9886、VID03.04.02.23、SensorID1 |
| I²C | SE7，0xa84000，wrapper1/local S1 | SE19，0xc88000，**wrapper2/local S2**，地址0x5d |
| GCC | vote5200c，RCG18148 | vote52014 bits1/2/6，RCG1e3a8；branch1e004/1e008/1e3a4 |
| TLMM | NORTH@3900000；SDA6/SCL7，mux1 | SOUTH@3d00000；SDA57/SCL58，mux2 |
| 复位/IRQ | GPIO8/9 | GPIO54/122 |
| 供电 | GPIO90 + RPMh PM6150L L11C | GPIO98/100；不向 sweet 的 L11C 投票 |
| 实际固件寄存器 | PID4022，event4180 | PID4535，sensor4541，event4100，ESD30f3 |
| 报文 | 8字节头、16位校验、坐标大端 | 2字节状态+每点8字节+2字节尾；8位累加和为0，坐标小端 |
| 电源协议 | 现有 Yellowstone 路径 | doze控制30f0：AA唤醒，3100应为BB；退出CC；动态ESD喂AA |
| 物理坐标 | 0..1079 / 0..2399 | Recovery input 实测 0..1079 / 0..2339 |
| 映射到逻辑画布 | Y偏移18 | Y偏移48；底边手势判定也随实际高度改变 |

Linux 参考为 `$HOME/kernel/zundamon_raphael` 的 DTS、`gcc-sm8150.c`、
`pinctrl-sm8150.c`、`goodix_driver_gt9886/` 与 `firmware/raphael/goodix_gt9886_cfg_f11.bin`。
配置文件校验通过，两个 sensor 包都使用上述寄存器表；真机 I²C 读取也确认4535处为9886。
源码里未使用的8240/824e默认值不适用于这版固件。

0083 复用已有 FIFO 传输和 HID 事件队列，新增由 ADT 机型匹配选择的 raphael 路径，
校验芯片、触点数量、校验和、重复ID、坐标边界后才提交事件；Sensor0 支持双轴镜像，
真机 Sensor1 不镜像。HID 物理尺寸改为读取 boot-video，与显示的裁剪保持一致。
没有上传触控固件或配置、没有写 PMIC，也没有自动启用其他外设。

验证：`tools/check-raphael-touch.py XNU_TREE` 对实际 C 解码函数执行 ASan/UBSan
测试，覆盖0–10触点、抬起、镜像、截断、坏校验、重复ID及越界；两个修改文件本地
arm64 Mach-O 交叉编译通过。CI0083：[39424091174](https://github.com/HeliumStudio-Dev/ios-raphael/actions/runs/39424091174)。
0083 CI 已通过（7分27秒），真机能进锁屏，但触控无响应。日志表明初始化停在
GCC1e008的80000002，尚未读取触控IC。该时钟设置了HWCGbit1，Linux的
`clk_branch_wait()`在自动门控模式跳过halt等待；0084补上这一处理，仍检查真正
未开启的时钟。主机回归覆盖了现场HWCG状态、无HWCG的halt、未开启SE时钟及sweet路径。

临时shim探针的用户读数为GENI_FW303、HW_PARAM0、TX_HW20102a64、RX_HW20104900、
SE_STAT0，确认ABL留下可用的I²C固件、32位/深度16的FIFO及空闲控制器。
0084 CI：[39426109080](https://github.com/HeliumStudio-Dev/ios-raphael/actions/runs/39426109080)。
真机触控结果见 NOTES.md；构建和前置条件检查通过本身不代表触控已验证。

构建触控测试镜像（内核须包含0083）：

```sh
bash tools/build-raphael-stage2.sh KERNEL RAPHAEL_DTB --touch
python3 tools/check-raphael-stage2.py shim/out/raphael-stage3.img --touch
fastboot boot shim/out/raphael-stage3.img
```

测试：等待锁屏，先从底边上滑，再检查顶部/中部/底部点击、连续滑动及双指抬起。
触控初始化延迟45秒；失败时进入 Recovery 拉取新的 SWEETLOG，检查
`SWEET TOUCH` 的时钟、GENI固件、Normandy识别及 `SWEET HID: touch` 事件。
初期使用100Hz轮询并保持芯片唤醒；IRQ、休眠、功耗优化待输入可靠后再做。

## 其他差异与修复顺序

| 优先级 | 差异 | 后续动作 |
| --- | --- | --- |
| 紧接触控 | sweet 音量上为 PM6150L SID4/GPIO2；raphael 为 PM8150 SID0/GPIO6，电源/音量下走PON | 重查 SPMI APID/ownership，先只读验证再启用 keys；不能只把 sweetkeys 改1 |
| 启动与交互性能 | sweet 为6×A55+2×A76；raphael 为4×A55+3×A76+1×A76 Prime | 当前1CPU已验证。先适配并验证4个A55，再处理大核、拓扑、IPI、缓存与频率；不要复制 sweet 的6小核假设 |
| 调试/联网 | DWC3地址同为a600000，但 raphael USB2 PHY 是7nm SNPS HS PHY，sweet 为QUSB2；GCC及DMA/SMMU关系要核实 | 保持sweetusb=0。先核对控制器状态/时钟/PHY/DMA，再复用ECM前端 |
| 显示与功耗 | raphael EA8076 command-mode，物理高度2340 | 当前借用ABL面板并启用PP autorefresh已可显示；后续补DSI/DPU时钟、真正亮灭屏、TE/vsync及休眠恢复 |
| 电池/充电 | PM6150系列换成PM8150/PM8150B/PM8150L，fuel-gauge/charger寄存器与SID不同 | 保留静态电量；单独移植读取/校准及充电、温控，不启用旧真实电量路径 |
| GPU/媒体 | Adreno618换成640；两端都没有可用的XNU GPU驱动 | 继续CPU渲染。音频、相机、Wi-Fi等要单独移植，不能从Linux加载ko来补齐 |
| 存储 | 相同UFSHCI地址，但分区几何不同 | 已按GPT名称找到userdata，4K块和64位DMA实测成功；不改GPT，不复用sweet分区号 |

## shim 还需要什么适配

- 已工作的入口、段加载、boot_args、2340高度和command-mode刷新应保留。成功路径直接跳入
  XNU，`mmu_enable()`、SMP/定时器探针及reset诊断不在该路径上；触控驱动运行在XNU中。
- framebuffer、stride、显示寄存器仍是板级常量，面板和时钟依赖ABL预先初始化。
  真正冷启动面板/休眠恢复需要显示驱动；不能把维持刷新等同于完成显示电源管理。
- `shim/fdt.c` 只读initrd地址；RAM窗口和reserved-memory检查仍依赖主机预检。
  `loader.c` / FDT解析后续应补长度、段边界、整数溢出及加载区校验，避免错误payload写错RAM。
- `IMEM_RESTART_REASON` 仍为sweet的146aa65c，而raphael live FDT是146bf65c。
  当前raphael构建出错后原地停止，不经过reset分支，因此不是本次慢启动的原因；
  重新启用复位诊断或增加XNU重启支持前必须修正。
- `RAPHAEL_STAGE1` 宏也用于第二、三阶段，现有行为是板级显示选择及失败时禁止落入sweet UFS探测。
  名称需要整理，但它不限制XNU读userdata；真正的存储开关是ADT no-storage和ufsrw/rootrw。
