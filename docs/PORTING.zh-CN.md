# 仓库分析与其他机型移植路线

分析日期：2026-10-20。源码基线：`11da58b`；分析对象是仓库中已提交的工具、CI 和 XNU 补丁。真机结果引用 `NOTES.md`，本次没有重现实机启动。

**结论：这个仓库提供了可复用的 XNU / iOS 用户空间兼容基础，但硬件层仍是 sweet 的单机实现。移植需要逐项适配启动环境和驱动，不能只替换 DTB 或改设备名。** 当前目录和 GitHub 仓库叫 ios-raphael，源码实际目标仍是 Redmi Note 10 Pro / sweet / SM7150；没有看到 raphael 的板级配置或实测记录。

## 项目实际做了什么

启动链是：

```text
解锁的 Android 引导程序 ABL
  → 临时启动 Android boot.img v2 格式的 shim
  → shim 从 Linux FDT 的 /chosen 读取 ramdisk 地址
  → 加载自编译的 XNU Mach-O、生成的 Apple Device Tree、boot_args
  → XNU 的 UFS 驱动找到 userdata 内的 HFS+ 根文件系统
  → iPhone X iOS 16.7.16 / 20H392 的 launchd、dyld、系统服务
  → IOSurface / IOMobileFramebuffer / HID 接口支持 backboardd 和 SpringBoard
```

这里有两棵不同用途的设备树：Android/Linux 的 FDT 供 ABL 和 shim 使用；生成的 Apple ADT 供 XNU 和 iOS 服务使用。`shim/fdt.c` 只提取 initrd 地址，没有自动把目标机的全部硬件信息转换成 ADT。

XNU 是自己编译、修改的内核；iOS 程序来自 iPhone X 固件。根镜像构建及 tweaks 会改变文件系统布局、launchd 作业和偏好设置。因此，复用了 Apple 用户空间程序，不等于完整原厂固件未经调整直接运行。

| 代码位置 | 职责及复用边界 |
| --- | --- |
| `shim/` | Linux Image 入口、屏幕诊断、payload 加载及只读 UFS 探测。包含板级地址和启动状态假设 |
| `tools/mkadt.py` | 生成硬件资源、CPU 拓扑和 iPhone X 身份；大多数值直接写在代码里 |
| `tools/mkpayload.py`、`adt.py` | Mach-O 重定位、段打包、ADT 编解码；主体可继续复用 |
| `xnu/patches/0001–0081` | 工具链兼容、通用 ARM 支持、缺失内核组件、iOS 接口和 sweet 硬件驱动 |
| `tools/mkiosroot.sh`、`sweet-root-tweaks.py` | 固定 iOS 版本的根镜像与启动配置；换 Android 机型通常先沿用这一套 |
| `.github/workflows/xnu.yml` | macOS / Xcode 构建，默认 `MACHINE_CONFIG=SWEET`；收集内核、编译树 |
| `tools/xnu-cc.py`、`qemu-sweet.py` | 单文件编译和通用 ARM 虚拟机检查；不能验证 Qualcomm 真机外设 |

补丁里还集成了 libpthread、HFS、BearSSL、Apple IOHIDFamily 的相关代码。仓库以补丁序列交付 XNU 修改，并未提交完整、可直接构建的 XNU 源码树。

## 已有成果与证据限制

| 项目 | 仓库所能支持的结论 |
| --- | --- |
| SpringBoard、触摸、按键、HFS+ 根 | `NOTES.md` 记录 sweet 上成功；本次未实测 |
| 多核 | 0078 源码支持最多 8 核，NOTES 记录成功；用单个同构 SMP 集群描述，未实现按核心性能分级调度 |
| 返回手势 | NOTES 记录 0070 / 0071 修复成功；README 的“无法离开应用”已经落后 |
| USB | NOTES 记录 ECM 链路和 ping 成功；这与 iOS 应用具备互联网连接是两回事 |
| USB 互联网 | 0081 增加链路状态上报；提交说明记录 0080 下 configd 未加默认路由，当前没有 0081 之后联网成功的实测证据 |
| 显示 | CPU 渲染，再复制到 ABL 留下的 framebuffer；无 Adreno GPU 驱动 |
| 显示电源 | 0079 实现淡出、黑屏和恢复画面；不能据此认定 DSI、面板供电或系统休眠已完成 |
| 电池 | 默认静态电量；真实 SPMI 读取为可选路径，不能当作目标机充电/温控已支持 |
| 通信及媒体 | 没有可用的蜂窝、Wi-Fi、蓝牙、音频、相机等完整驱动 |
| 安全能力 | AMFI / sandbox 放宽，AppleKeyStore 是替代实现；没有真实 SEP 和原厂数据保护 |

README 与 `xnu/README.md` 都有历史内容，判断进度要结合最新补丁、提交说明和带版本号的实测交接。

## 哪些能直接复用，哪些必须改

**优先保留：** 现有 arm64 非 PAC 的内核路线、线程和文件系统组件、iOS ABI 修补、IOSurface / IOMobileFramebuffer 用户客户端、HID 上层接口，以及同一个 iPhone X 用户空间。Android 主板型号与呈现给 iOS 的产品身份应分开处理，移植安卓机型不要求同步换成新款 iPhone 的 arm64e 用户空间。

**逐项核对：** 以下为修改触达范围，表中的补丁路径是仓库路径，括号内为应用补丁后生成的 XNU 文件。

| 层次 | 当前绑定与代码位置 | 新机型要提供/验证的内容 |
| --- | --- | --- |
| 启动封装 | `shim/build.sh`、`start.S`：boot header v2、固定 DTB 路径及 offsets；入口按 EL1、MMU off 处理 | bootloader 能否临时启动、实际 boot header/DTB/DTBO 交付方式、入口 EL、加载地址和缓存状态 |
| 物理内存 | `mkadt.py`：低位 `0xb0000000+0x4d000000` 或高位 `0x100000000+0xfcc00000`；`shim/mmu.c` 的诊断映射 | 实际 RAM 与 reserved-memory、TZ/modem/XPU carve-out、连续可用区；不能按内存总容量推断 |
| 早期显示 | `shim/console.h`、`mmu.h`、`loader.c`；0010 / 0012 的 `start.s`、`sweet_early.c`、`arm_vm_init.c` | framebuffer 地址、长度、像素格式、stride、尺寸及页表映射；这些并不全部来自 ADT |
| 平台匹配 | 0016 / 0018 的 `KernelConfigTables.cpp`；`mkadt.py` | `xiaomi,sweet` 与 `qcom,kryo470` 的精确匹配要同步调整，否则服务不会注册 |
| 中断与时钟 | 0004 / 0017（`pe_fiq.c`、`sleh.c`、`SWEET.h`）；shim 有独立常量 | GICD/GICR、redistributor 布局、Non-secure Group 1、timer PPI、CNTFRQ、SGI；验证真实 IRQ 计数 |
| CPU / SMP | 0065 / 0078（`SweetCPU.cpp`、`start.s`、`machine_routines.c`） | PSCI conduit、MPIDR、boot CPU、核心数量、二级核入口和缓存一致性；目前校验的是 sweet 的 Aff1 编号布局 |
| UFS | `shim/ufs.c`、0028 / 0030 / 0034 / 0069（`sweet_ufs.c`） | 控制器版本/地址、ABL 是否保留运行链路、LUN、逻辑块大小、64 位 DMA、SMMU 映射和缓存维护 |
| GUI 输出 | 0046 / 0056 / 0061 / 0079（`SweetFramebuffer.cpp`）、`mkadt.py` | 持续扫描输出还是需要 command-mode 刷新；物理尺寸与 iPhone X 逻辑画布之间的裁剪/缩放/旋转 |
| 输入 | 0058 / 0060 / 0061 / 0063 / 0071（`SweetHID.cpp`、`sweet_keys.c`、`sweet_touch.c`） | 触摸芯片与协议、GENI I2C/SPI、GPIO、复位时序、PMIC 键位、坐标及边缘手势；HID 前端可保留 |
| 电源 | 0062（`sweet_rpmh.c`、`sweet_spmi.c`、`SweetBattery.cpp`） | PMIC 型号、SPMI SID/外设、RPMh Command DB、实际供电 rail 与电压；当前调压函数只接受 `ldoc11` 和特定电压范围 |
| USB | 0072–0081（`sweet_usb.c`） | DWC3 版本、PHY、GCC/GDSC、VBUS override、ABL 状态、DMA；ECM 前端可复用 |
| 工具与回归 | `qemu-sweet.py`、`sweet-log-pull.sh`、文档、CI | 保留现有 QEMU 配置；目标机变化不能破坏 sweet 基线。日志工具通过 by-name 找分区，不必照抄旧笔记里的 `sda34` |

两个容易漏掉的细节：

- `SweetHID.cpp` 还把物理触摸区域写成 1080×2400，逻辑区域为 1125×2436；只改 framebuffer 尺寸会使触摸和手势错位。更小屏幕需要明确采用裁剪还是缩放，并同步输出和输入变换。
- 当前 shim 无 payload 时先执行 UFS 探测，再调用不返回的 `reset()`；后面的 MMU、PSCI、GIC 诊断流程不会执行。移植前要明确选择探测入口，不能认为“空 payload 启动”会自动测完全部硬件。

## 为什么开机 Logo 的显示方式是关键

sweet 使用 ABL 初始化好的连续视频输出，CPU 写内存即可更新屏幕。这省掉了完整的 DPU / DSI 驱动。其他机型即使能显示启动 Logo，也不一定继续从同一块内存扫描输出。

新机应先测试“持续写 framebuffer，物理屏幕是否持续变化”。如果只有首帧、command-mode 面板需要刷新命令，或显示 SMMU/时钟在交接后失效，就需要实现对应显示提交和时钟/电源管理；改分辨率无法解决。是否如此必须以目标面板驱动和实际结果为准。

UFS 和 USB 也依赖 ABL 已初始化的状态。控制器 IP 和基地址相同只是复用起点，不能替代 PHY、时钟、DMA 和 SMMU 检查。Linux 驱动适合用来确认寄存器与协议，其 `.ko` 和 Android HAL 不能直接装到 XNU；需要保留/移植硬件访问逻辑并接入 XNU 的服务和内存接口。

**选择其他机型时的判断：** 以下难度是依据本仓库实现作的工程判断，均不代表已支持。

| 目标类型 | 复用程度与主要障碍 |
| --- | --- |
| 同 SM7150、相近固件的另一块板 | 可复用部分最多，仍要核对面板、触摸、供电、RAM 和 ABL 状态 |
| 其他 Qualcomm ARM64 平台 | 若仍用 GICv3、PSCI、UFS、DWC3，可逐个复用框架；MMIO/版本/固件状态必须重验 |
| 使用 eMMC 的设备 | 当前 UFS 后端不能使用，需要额外的存储驱动；早期可先用 RAM 根 |
| MediaTek / Exynos 等不同 SoC | iOS 服务接口仍有价值，但中断、存储、显示、USB、电源等后端需重新评估，工作量明显增加 |
| 32 位或不支持 16K 页的 CPU | 不符合当前 arm64 / 16K 实现，超出单纯板级适配范围 |

此外，需有实际可用的自定义镜像启动路径。解锁状态、`fastboot boot` 支持和 boot image 格式必须查目标固件；本仓库没有通用的锁定 bootloader 启动方案。

## 如果目标是 raphael / SM8150

这是根据目录名作的条件分析，用户尚未指定具体目标机、面板版本或内存版本。下面只使用 SoC 级信息，不认定目标手机已满足条件。

[Linux 上游 sm8150.dtsi](https://github.com/torvalds/linux/blob/master/arch/arm64/boot/dts/qcom/sm8150.dtsi) 描述了以下资源（2026-10-20 查询）：

- GICD `0x17a00000`、GICR `0x17a60000`，与本项目常量相同；virtual timer 为 PPI 3，对应 INTID 19。
- PSCI 使用 SMC；CPU `reg` 按 `0x000…0x700` 编号，但 CPU0–3、4–6、7 分属三个频率域，不能照搬 sweet 的 6+2 描述。
- UFS 标准寄存器从 `0x01d84000` 开始，DWC3 从 `0x0a600000` 开始，Qualcomm USB wrapper 为 `0x0a6f8800`，也与现有常量有重合。

**推断：SM8150 值得按现有 GIC / PSCI / UFS / DWC3 框架尝试第二块板。** 上述 DTS 不能证明目标固件的 framebuffer、RAM、面板模式、触摸和 PMIC 参数；也没有证明 16K 页、DMA 交接或具体服务可在目标机工作。XO 时钟不能直接当作架构 timer 的 CNTFRQ 使用。

第一轮应准备目标机 live FDT（含生效的 DTBO）、原厂 boot header、RAM/reserved-memory、面板与触摸驱动及配置、UFS 分区/LUN/块大小。不要先改用户空间，也不必为了更快的 Adreno 而先做 GPU。

## 推荐的最短落地顺序

| 阶段 | 工作与通过标准 | 是否需要覆盖 userdata |
| --- | --- | --- |
| 0. 收集事实 | 校验离线备份；确定 FDT、boot header、RAM、面板、触摸、PMIC；区分静态 DTS 与真机测量 | 否 |
| 1. shim | 目标屏幕连续变化；打印入口 EL、CPU 特征；确认 16K 页支持、实际 CNTFRQ、timer IRQ 和 SGI | 否 |
| 2. XNU 单核 | 适配安全 RAM、早期控制台、平台匹配；`cpus=1` 进入 BSD；未知外设先关闭 | 否 |
| 3. RAM 根 | 用 `mkpayload.py --ramdisk` / `rd=md0` 和最小测试 init 验证用户态；不是只看“没有 panic” | 否 |
| 4. UFS 只读 | 验证 LUN、容量/块大小、GPT 与备份数据比对，确认 DMA 可工作；不启动持久日志写入 | 否 |
| 5. iOS 根 | 构建固定版本 HFS+ 镜像，确认根和日志区域不重叠；单独确认破坏性步骤后才写 userdata | 是 |
| 6. 桌面与输入 | 保持 iPhone X 身份；看到 SpringBoard；触摸坐标、返回手势和电源/音量键均正确 | 使用已写入的根 |
| 7. 完善 | 分别验证 SMP、USB ECM、默认路由/DNS，再处理真实电量、功耗、其他外设 | 按具体操作判断 |

早期 XNU 测试应关闭未知硬件的访问路径，例如 `sweettouch=0 sweetkeys=0 sweetusb=0`，保持静态电池；UFS 验证前采用 RAM 根并关闭持久日志。需要 RAM 镜像和测试 init，单写 `rd=md0` 不能创造根文件系统。

临时 `fastboot boot` 只保证没有覆盖 boot 分区，不保证内核不写存储：`ufsrw=1` 会允许写根分区，默认持久日志还会写选中分区最后 1025 个 4 KiB 块。现有代码未向文件系统分配器保留这段日志区，必须让根镜像显著小于分区，核对边界。不能把这些参数用于仍需保留原数据的 Android userdata。覆盖 userdata 的每个破坏性步骤仍须单独向用户确认。

新增支持时先做第二块板所需的最小配置：复用 payload 格式和 iOS 接口，把确实不同的资源移入板级配置/ADT；引入目标机驱动匹配。早期汇编拿不到完整 ADT 的地方保留明确的板级常量。不要全局替换 `sweet`，否则会破坏编译条件、服务匹配和 QEMU 基线。若需要独立 machine config，要同时更新 board_config、MASTER/files、构建目标和 CI，不能只改 workflow 输入。

## 本次验证与仍缺的材料

- `tools/validate-repo.py` 通过：81 个连续编号补丁、15 个 Python 工具语法、7 个 Shell 脚本语法。该工具不验证整个补丁序列是否能应用到上游，也不编译内核。
- 对 phone 低位内存、phone 高位内存、QEMU 三种 ADT 做了生成→序列化→解析→序列化一致性检查，并断言 CPU 数/MPIDR、RAM、timer INTID、UFS 节点选择，全部通过。
- 本机没有 `aarch64-linux-gnu-gcc`、`qemu-system-aarch64`、`llvm-nm`，也没有已构建内核、原厂 DTB 或 D22AP ADT。生成器会警告缺少 `/product`，上述 ADT 检查不代表足以启动 iOS。
- 没有下载 Apple 固件、触发 CI、接触手机、刷分区或修改内核。下一步是先确定目标机并补齐阶段 0 的硬件事实；无法从当前仓库给出可信的移植工期或成功保证。
