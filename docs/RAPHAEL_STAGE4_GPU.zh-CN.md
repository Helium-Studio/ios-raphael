# raphael 第四阶段：Adreno 640

2026-10-20：GPU 渲染尚未实现；0085 的八核、触控与按键是已验证基线。
本阶段先完成 GPU 硬件探测，再逐步验证 GMU、SMMU、命令处理器和用户态渲染。
只用 `fastboot boot`；不重新刷写 userdata 或 boot。

## NativeAdreno 可以复用什么

参考 [NativeAdreno](https://github.com/UniXNU/NativeAdreno/tree/04aa607911c914028fcc9d657b97c004128a93a4)，
它针对 sheng/SM8550 的 A740，包含 BO、SMMU、ring、fence、缓存同步及 IOKit 接口。
完整板级启动还依赖 [UniXNU-sheng](https://github.com/UniXNU/UniXNU-sheng/tree/902ae7bd252f1d29262236cf551ba8bc82393d3c)
中的电源、时钟、GMU、ZAP 代码，以及生成的板级参数。
软件渲染切到 GPU 还需要 [NativeMetal](https://github.com/UniXNU/NativeMetal)：
Metal 插件、metal2vulkan/AIR 编译、Turnip 和显示交接；当前 iOS 根镜像未安装这些组件。

可参考其分层、真实 fence 验证和缓存同步方式，不能只改 compatible 或注册
`IOAcceleratorES` 来宣称加速可用。后者还会让系统选择尚不能执行的 GPU 路径。

实际20H392的Metal框架导出 `MTLAddDevice`，上游iOS17 accelerator基类头文件中的
`sizeof(IOService)==136` 检查也在当前XNU8796头文件下交叉编译通过。
这些是可行性证据，仍未审计完整vtable或装入原始IOGPUFamily父类，也未运行插件。

进一步检查 [NativeMetal 源码](https://github.com/UniXNU/NativeMetal/tree/6dcd4cbb69eb5625988706de42aa8ad3009b8ee7)：
`NativeBridgeMetalFrontend.mm` 按 iPadOS17.7.11 要求 `_MTLDevice` 实例大小为536字节；
本地20H392缓存的 Objective-C `class_ro_t.instanceSize` 实测为528字节，原样移植会返回nil。
`NativeAdrenoMetalPlugin.mm` 的 `reportDisplayState`/`sampleDisplay` 还使用特定QuartzCore
版本的绝对地址与对象偏移，并通过 `vm_write` 修改显示状态，不能直接在20H392启用。
适配时须核对本机Metal私有协议与方法签名、重新验证显示格式处理，不能只改大小断言。
该插件通过 `IOAcceleratorES → MetalPluginName → initWithAcceleratorPort:` 进入；
默认只运行异步测试并返回nil，旁置 `.publish` 文件才发布真实设备。
只有GPU测试、Turnip设备创建与iOS16 ABI验证通过后，才应安装和开启发布模式。

显示交接也有接口差异：上游 `GpuScanoutClient.h` 通过accelerator的 `0x7000..0x7003`
方法及 `0x5343` 内存类型接入NativeMobileDisplay的NGP协议；当前 `SweetFramebuffer.cpp`
使用IOMobileFramebuffer SwapEnd记录IOSurface，再由vsync定时器用CPU复制到面板。
移植时要保留实际surface的内存所有权和映射生命周期，增加经过验证的GPU提交/完成交接，
并在GPU失败时维持现有显示路径；安装Metal插件本身不会替换这段CPU复制。

| 项目 | NativeAdreno / sheng | raphael 实测与本地 Linux 参考 |
| --- | --- | --- |
| GPU | Adreno 740 / SM8550 | Adreno640v2，live DT chip ID `0x06040001` |
| CPU 页 | 内存层要求 native 4 KiB | 当前 XNU 为 16 KiB；SMMU 的 4 KiB 页表须与 CPU 分配/页属性分开处理 |
| 寄存器 | SM8550 的 0x3d… 地址族 | GPU `0x2c00000/0x40000`，GPUCC `0x2c90000/0x9000` |
| GMU/PDC | A740 固件、时钟和电源序列 | GMU `0x2c6a000/0x30000`，PDC `0xb290000`、sequencer `0xb490000` |
| GMU DTCM | `0x10004000` | `0x40000`；icache `0x4000..0x40000`，dcache `0x44000..0x80000` |
| SMMU | native 4 KiB，A740 板级 stream/context | `0x2ca0000/0x10000`；GPU SID0/mask0x401，GMU kernel SID5/mask0x400 |
| 电源 | SM8550 GPUCC/RPMh/command-db | PM8150 系列、SM8150 GPUCC；CX/GX 完成状态与请求位要分别判断 |
| 固件 | A740 SQE/GMU/ZAP | `a630_sqe.fw`、`a640_gmu.bin`、`a640_zap.*` 已从真机只读取得 |
| CP 初始化 | A7xx `CP_THREAD_CONTROL` + 7-word `CP_ME_INIT`，BR/BV 提交 | Linux A6xx 为 8-word `CP_ME_INIT`，首字0x2f；不能沿用 A7xx ring framing |
| 频率 | A740 参数 | Recovery 可用257/345/427/499.2/585MHz；GMU启动200MHz，均不是已实现的 XNU DVFS |

Linux 参考位置（`$HOME/kernel/zundamon_raphael`，未改动）：

- `arch/arm64/boot/dts/qcom/sm8150.dtsi`：地址、stream、IRQ和时钟。
- `drivers/clk/qcom/{gpucc-sm8150,gcc-sm8150,gdsc}.c`：配置时钟和电源状态。
- `drivers/gpu/drm/msm/adreno/{a6xx_gpu,a6xx_gmu,a6xx_hfi,a6xx_catalog}.c`：启动、固件、ring、HFI。
- `drivers/gpu/msm-kgsl/{adreno-gpulist.h,a6xx_reg.h,adreno_a6xx_gmu.c}`：下游 A640 寄存器与固件参考。

## 已采集的证据

本机 Recovery 的实际设备树和硬件信息保存在私有 `research/raphael-gpu-*`。
Android vendor 是 retrofit dynamic EROFS：只读挂载 mapper/vendor，提取固件后已卸载。
没有挂载 iOS userdata，也没有写入 vendor。固件及其校验表不进 git。

| 文件 | 大小 | SHA256 |
| --- | --- | --- |
| a630_sqe.fw | 35384 | `02bbf612ea37dc3630c3f194a3b314203e674bb7115963c402a036e463df607f` |
| a640_gmu.bin | 37680 | `3ff0c02708bbe78641db887fa62f3a7f9337934d0c2ce0b961ef7c43172591d2` |
| a640_zap.mdt | 6860 | `2a3fc1d598483a61cd96f9467465fc56ced87783588a091eab39af019c479760` |

调用上游 AdrenoFirmware 的实际解析器验证 A640 固件：7个数据块覆盖 ITCM、ICACHE、
DTCM、DCACHE，完整消费37680字节，截断输入被拒绝。A740的大 icache 范围会在结构检查时
把 A640 的 DTCM 接受为外部 icache，因此“解析通过”不能替代正确的板级内存布局。
详见私有 `research/raphael-gpu-firmware/gmu-plan.json`。

Recovery command-db 已读到 `cx.lvl=0x30000`、`mx.lvl=0x30010`、`gfx.lvl=0x30050`，
及各资源的实际 corner 表；BCM MC0/SH0 等表也已保存。
现有 `sweet_rpmh.c` 只接受 VRM 电压资源，不能把 ARC corner 当毫伏写入。

## 0086：先观察 ABL 留下的状态

`0086-raphael-a640-readonly-probe.patch` 添加默认关闭的 `raphaelgpu=1`：

1. 严格匹配 raphael，记录 CPU 页尺寸/TCR，再读取 GCC 配置和总线时钟。
2. 仅在配置时钟启用时读取 GPUCC。
3. CX 必须同时有 GDSCR 与 HW_CTRL 的上电状态；GX 检查 CFG_GDSCR 的完成位及 I/O clamp。
4. GMU、GX、SMMU 分别要求其电源与时钟满足后才读状态。
5. 全程没有 GPU MMIO 写入、固件上传、DMA 或 accelerator 服务注册。

```sh
bash tools/build-raphael-stage2.sh KERNEL RAPHAEL_DTB --touch --keys --cpus 8 --gpu-probe
python3 tools/check-raphael-stage2.py shim/out/raphael-stage3.img --touch --keys --cpus 8 --gpu-probe
fastboot boot shim/out/raphael-stage3.img
```

构建器要求保留已验证的输入/八核组合，检查器会拒绝缺少探测代码的旧内核。
`tools/check-raphael-gpu.py XNU_TREE` 对实际 C 代码做 ASan/UBSan 测试，覆盖板型、
截断 compatible、默认关闭、映射失败、时钟/电源门控、尚未完成的电源请求与 clamp，
并检查模拟 MMIO 保持原值、全1无效状态被拒绝；本地 GPU/UFS 两个文件交叉编译通过。
真机启动结果与 CI 信息持续记录在 `NOTES.md`，未获日志前不宣称探测通过。

2026-10-21 21:07 已临时启动首个探测镜像，用户确认锁屏、触控和按键正常。
CI [39443279478](https://github.com/HeliumStudio-Dev/ios-raphael/actions/runs/39443279478)
通过，内核源码为 `3af6f55`；镜像 `shim/out/raphael-0086-gpu-probe.img` 的SHA256为
`4d83c4ca3d5a15fc7ade5cf4f4018a080e8fca9391f89acd5449ffcbdb02fd92`。
该镜像保留八核、触控与按键；没有安装Metal插件，也没有刷写分区。

随后按README从Recovery取得新日志（212334字节，flush31）：八核SGI1均通过，
没有记录到panic，GPU探测完整结束。GPUCC的CX/GX均为 `0x222001`，
CX_HW=`0x5ff4`、GX_CFG=`0x88400`、clamp=`0x3c0001`；两域均未上电。
GMU分支为 `0x80004220`，RCG为 `0x80000000/0`，尚未启用。
配置AHB可读，但GMU/GX/SMMU均按门控跳过；这不是已启动GPU。

## 0087：CX 上电与回退测试已通过

`--gpu-cx-test` 使用 `raphaelgpu=2 ufslogsecs=1`，保留输入/八核配置。
只接受未上电、软件控制的CX和GMU源仍为XO的状态；先等待3秒让日志保存检查点。
依照本地Linux的GDSC时序设置wait2/8/2，解除CX collapse并等待HW完成位；
成功后启用本地AHB/CXO/GMU分支，确认时钟状态后读取GMU，最后恢复控制位并检查CX关闭。
失败路径同样回退，所有轮询均有上限。此测试含GPUCC控制寄存器写入，
不写电压/频率、GX、SMMU或固件，不启动DMA，也不发布accelerator。

```sh
bash tools/build-raphael-stage2.sh KERNEL RAPHAEL_DTB --touch --keys --cpus 8 --gpu-cx-test
```

主机测试直接运行C实现，覆盖上电/时钟/掉电超时、映射失败、拒绝未知状态和控制位恢复；
实际硬件能否上电及安全访问仍须用临时启动与持久日志验证。

CI [39607750670](https://github.com/HeliumStudio-Dev/ios-raphael/actions/runs/39607750670)
已通过（源码 `4360fb9`，7分10秒）。0087镜像于2026-10-21 21:34临时启动成功，
SHA256为 `0b460ae3dac13c0dbafc1f1a2036a392667ab56fdd3ce3b55c7202cafc5ac3e7`。
用户确认锁屏、触控和按键正常。README持久日志217718字节、flush123；八核SGI通过，
没有记录到panic。CX成功上电，GDSCR=`0xf8282000`、HW=`0x80001fe0`；
AHB/CXO=`1`、GMU=`0x4221`、RCG=`0/0`，GMU复位位仍为1。
测试后 `restored=1 off=1`，CX回到 `0x222001/0x5ff4`。
这证明本地CX和XO分支可启用、访问、恢复，尚未运行GMU固件。

## 0088：在同一上电窗口读取 SMMU

继续使用 `--gpu-cx-test`，不增加启动选项。只有GMU仍保持复位、
GCC memnoc/dvm及GPUCC AHB时钟均启用时才访问SMMU；不尝试开启共享总线分支。
读取ID、故障状态及受几何检查约束的有效SMR/S2CR、上下文寄存器和TTBR，
用于区分固件保留路由与未启用的上下文。寄存器页尺寸由IDR1推导，
要求完整区域恰好落在设备树的64KiB窗口内；未知/全1/越界几何或扩展SID模式会停止深入读取。
访问前额外等待3秒保存日志检查点，结束后仍走0087的控制位恢复流程。
不清故障、不写路由/上下文、不复位SMMU、不使用DMA bypass。
主机ASan/UBSan覆盖有效及畸形几何、时钟/复位门控、映射失败与恢复；真机结果待验证。

## 接下来的通过条件

按实际探测结果完成 A640 CX 电源、200MHz GMU 时钟、RPMh ARC/BCM 投票和 RSC/PDC；
建立独立的4KiB GMU/GPU SMMU映射，处理16KiB CPU分配与缓存同步，不能使用 DMA bypass。
主机上用上游 ArmSmmu4K 实际代码已将模拟16KiB分配映射成四个4KiB叶子，使用3个表页；
这只证明软件布局可行，未证明真机分配/缓存/DMA正确。NativeAdreno中的CPU页号移位、
BO分配取整、导入页所有权和页属性恢复仍需适配；不能只删除4KiB检查。
A640 DT 没有 sheng 的 dma-coherent 声明，页表遍历一致性也必须单独验证。
正确装入 A640 固件并取得真实 FW/HFI ACK 后，再做 SQE、ring、scratch write 与 fence。
ZAP/PAS13 和非安全模式切换应参照 A640/Linux 与真机保留区，不能复用 sheng 的固件物理地址。

只有 GPU 实际写回 scratch、fence 前进、显存清屏/拷贝校验正确后，才接入 IOSurface 与
显示提交；随后移植适配 iOS16 的 Metal/Turnip 用户态链路，用真实 draw/着色器结果和 GUI
验证 GPU 渲染。命令处理器工作、GPU 拷贝和 GPU 着色渲染是不同里程碑。
