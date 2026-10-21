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

分配器也需要随加载器一起修改：上游 `NativeAdrenoGmuDefaultSizes` / `AssembleGmuConfig`
把icache固定为 `0xffc000` 且没有dcache对象；本地Linux的A640分支分别分配
`0x4000..0x40000` 和 `0x44000..0x80000`，每块 `0x3c000` 字节。
中间的DTCM通过MMIO装入。两块缓存范围均为16KiB对齐，可由完整CPU页拥有，
再切为4KiB SMMU叶子；页属性修改仍须按XNU的 `PAGE_SHIFT` 处理，
不能沿用上游 `pmap_set_cache_attributes(pa >> 12)` 的页号。

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

CI [39611757924](https://github.com/HeliumStudio-Dev/ios-raphael/actions/runs/39611757924)
已通过，源码 `bcfdce1`；0088于2026-10-21 22:02临时启动，镜像SHA256为
`d9b8446591f8a15838ddf4ad5f17baab2627afd424b1d802acd0a03a29ba315b`。
用户已确认锁屏、触控和按键正常。README日志217998字节、flush72，八核检查通过，未记录到panic。
CX上电后memnoc/dvm分别为 `0x221/1`，SMMU可读：IDR0=`0x4c017e06`、
IDR1=`0x20000005`、IDR2=`0x5555`、sCR0=`0x240406`、GFSR=0。
实际为4KiB寄存器页、5个上下文、6个流槽；没有有效SMR，5个SCTLR.M均为0。
关闭上下文的TTBR/TCR呈未初始化值，不能据此认定有可复用映射。
探测完整结束，CX控制位恢复并确认关闭。尚未配置SMMU或启动DMA。

## 0089：合并 GMU 时钟、TCM 和内存准备测试

按用户要求减少拆分，继续用同一 `--gpu-cx-test`，在一次临时启动中完成：

1. 复用0088的CX/SMMU门控及快照。
2. 分配实际连续32KiB内存，前一个16KiB页拥有页表，后一个拥有数据；
   复用MIT授权的ArmSmmu4K核心 `29f386ae`，生成并软件遍历四个4KiB叶子，
   清理完整分配的CPU缓存，然后释放。页表保持未激活，不修改CPU页属性。
3. 要求GPLL0锁定且L/alpha/postdiv与600MHz/div2完全匹配；仅开启GPU专用输出投票bit16，
   通过本地RCG选择parent6/HID2，配置名义200MHz，不重编共享PLL。
4. GMU保持复位，在ITCM/DTCM各保存末尾32字节，写入模式、校验，再恢复并核对。
5. RCG恢复XO，关闭CX和本地分支；确认RCG关闭后恢复原来的输出投票bit16。
   若根时钟仍开或掉电超时，保留投票并明确记录恢复失败，避免关掉仍使用的父时钟。

主机测试直接运行实际C代码和导入的建表核心，覆盖分配/物理连续性失败、
输出位宽不足、200MHz/XO更新超时、TCM写入失败、原有父时钟投票保留及CX失败回退。
三个翻译单元本地arm64交叉编译通过。200MHz由寄存器配置推算，未做频率测量。
本轮不写SMMU上下文/路由，不释放GMU复位，不装入固件、不启动DMA或发布accelerator。

CI [39615436048](https://github.com/HeliumStudio-Dev/ios-raphael/actions/runs/39615436048)
已通过，源码 `0448a42`。0089于2026-10-21 22:31临时启动，发送/启动均成功；
镜像SHA256为 `1c4e6b840f7e3d3027c8b8d436361ed56bd6cbe5f9b44a7e1ed7a201a249c831`。
用户确认锁屏、触控与按键正常。持久日志207195字节、flush69，八核检查通过，未记录panic。
内存owned=1/build=0/walked=1，3个表页及4个叶子；200MHz配置成功，ITCM/DTCM
均write=1/restored=1且reset=1。XO、CX和父时钟投票全部恢复。
这些验证了实际分配、软件页表遍历与时钟/TCM访问；尚未验证硬件翻译、DMA或GPU渲染。

## 0090：合并固件装载与 SMMU 上下文测试

同一 `--gpu-cx-test` 可增加 `--gmu-firmware /private/path/a640_gmu.bin`。
构建器把私有固件放入临时ADT；构建器、镜像检查器和内核都核对37680字节及上述SHA256。
固件不进入git，也不写入根文件系统；旧镜像及不带固件的测试仍可使用。

一次启动中，在已验证的CX/200MHz门控后完成：

1. 复用AdrenoFirmware解析器验证完整块布局，分配连续 `0x94000` 字节，逐个16KiB页核实物理所有权。
2. 以32KiB表池构建5个4KiB表页、129个叶子，分别映射icache、dcache、dummy、log、HFI。
   dummy只映射其所属16KiB CPU页的首个4KiB，不映射相邻数据；icache只读且可执行。
3. 按Linux A640初始化两队列/120字节HFI表；保存完整ITCM/DTCM，装入全部固件块并读回，清理整个分配的缓存。
4. 要求实际SMMU ID/全局fault策略匹配、全部上下文关闭、所有stream槽无效、GMU保持复位且GX已关闭并clamp。
   暂时使用CB4/ASID5以及两个空闲槽，设置DT规定的ACTLR=0x303和SID4/5、mask0x400。
   先核对关闭状态的完整寄存器，再启用上下文并核对路由；不改sCR0或其他上下文。
5. 路由先设FAULT再撤除，关闭上下文并执行真正的TLBIALL/TLBSYNC；恢复原始上下文、路由和完整TCM。
   若撤除、TLB排空或寄存器恢复不能确认，保留内存到重启，避免回收仍可能被引用的页表。

主机ASan/UBSan测试运行实际C、解析/编码核心及本机私有固件，覆盖固件损坏/长度、
分配失败、非连续物理页、已有stream/上下文、寄存器和路由写入失败、TCM写入失败、
TLB排空/路由撤除失败时保留内存，以及整个时钟→装载→上下文→恢复链路。
五个翻译单元本地arm64编译通过；ADT往返/坏固件拒绝、补丁重建和仓库结构检查通过。
CI [39620456482](https://github.com/HeliumStudio-Dev/ios-raphael/actions/runs/39620456482)
已通过，源码 `fc4b2e2`。2026-10-21 23:01临时启动成功；
镜像SHA256为 `23d906fb43421171a14b5e881024ed206f33dfbcba34ca9a1db946261f5d3994`。
用户确认锁屏/输入正常。持久日志208018字节、flush71，八核检查通过，未记录panic。
固件完整装载读回成功，context programmed=1，但routed=0；撤除detached=0、TLB drained=1。
代码保留分配，TCM及外层电源/时钟恢复成功。SCTLR=0x67、TCR=0x80802020、FSR=0x400。
本地Linux定义FSR[10:9]为FORMAT，0x400不含fault位；0090用原始FSR非零判断失败有误。
撤除失败还与Qualcomm固件的FAULT写入过滤特性一致，需0091记录S2CR读回后验证，不能宣称路由已通过。
GMU全程保持复位，本轮仍不能证明硬件页表遍历、固件执行或GPU渲染。
正式释放复位前还需完成RPMh ARC/BCM、RSC/PDC、DMA缓存属性和fault中断处理。

后续执行参数已核对到本机固件：DTCM `0x43fe0` 的版本字为 `0x20000105`，
按本地Linux `a6xx_gmu_start()` 应等待完整 `0xbabeface`，不能沿用新版固件的
`(result & 0x1ff)==0x100`。本机chip ID转换后的HFI_SFR值为 `0x06040100`。
A640 PDC第三个资源地址 `0x30090` 在实际command-db中是 `xo.lvl`；
同表的cx/mx/gfx分别为 `0x30000/0x30010/0x30050`。ARC命令数据是该资源
corner表的索引，须逐项匹配电压等级；现有L11C的VRM毫伏/模式/enable三命令不可复用为ARC投票。
实际apps-RSC的地址、DRV2及ACTIVE2/SLEEP3/WAKE3布局与现有传输层一致，
可复用其空闲TCS检查、锁、完成确认和超时隔离；须扩展资源解析及命令格式。

## 0091：修正 FSR 判断及 Qualcomm FAULT 写入

故障判断改用 Linux 的 `FSR_FAULT=0xc00001fe`，允许正常的 `FORMAT=0x400`。
只有确认无效且独占的 stream 槽才尝试 FAULT；若读回未生效，尝试 Linux 记录的
Qualcomm 编码转换，并要求实际读回 TYPE=FAULT，之后才允许发布路由。
撤除先取消并核实 SMR，再隔离到 FAULT，避免转换探测留下有效的 BYPASS 路由。
恢复同样处理原始 FAULT 编码，逐字段核对，失败继续保留页表内存。
日志增加首次/实际 S2CR 值、转换分支及每条路由的原始/当前 SMR/S2CR。

实际 C 的 ASan/UBSan 检查覆盖正常、转换和不支持转换三种硬件行为，
FORMAT 位与所有真实故障位，原始 FAULT 状态恢复，以及取消匹配/撤除/TLB 排空失败。
五个翻译单元交叉编译通过；此时真机结果和转换特性仍待本轮合并测试验证。

## 下一批电源和 HFI 输入核对

本地6.12 `a6xx_gmu_rpmh_arc_votes_init()` 使用OPP level查command-db索引，
把primary level、secondary index、primary index打包为32位值。
已用固定版本的 `AdrenoHfiArcVotes()` 实际C代码及本机完整aux字节做ASan/UBSan检查：

| 频率 | OPP level | HFI ARC vote |
| --- | --- | --- |
| GMU 200MHz | 64 | `0x00400202` |
| GPU 257MHz | 128 | `0x00800204` |
| GPU 345MHz | 192 | `0x00c00305` |
| GPU 427MHz | 256 | `0x01000407` |
| GPU 499.2MHz | 320 | `0x01400508` |
| GPU 585MHz | 384 | `0x01800609` |

这是软件生成检查，尚未下发投票或证明电压正确。GX speed bin仍需按实际熔丝筛选，
表中不启用675MHz。不要把整个HFI打包值作为CPU侧ARC命令的data；后者只发送corner索引。
本机未出现gmxc.lvl，GPU secondary使用mx.lvl；内核读取仍必须区分缺失与解析错误。

另一个移植陷阱是6.12 `a640_build_bw_table()` 的固定CNOC地址
`0x50034/0x5007c/0x5004c`：后两个未出现在本机command-db，
第一个在本机是SH3，不能仅按A640型号复制此表。
实际CN0是 `0x500a8`；MC0/SH0/ACV是 `0x50000/0x5003c/0x5000c`，
对应VCD分别为0/1/11。必须按本机拓扑、aux单位、总线宽度和VCD提交边界重建。
本地SM8150拓扑的GPU master有2通道、每通道32字节；不能把频率直接作为带宽票值。
缓存路径同样不能只放开NativeAdreno的4KiB CPU检查：本机完整16KiB页所有权与4KiB叶子
需要分别计算，CPU修改后clean、设备修改后invalidate，HFI队列发布和接收各需明确同步。

## 接下来的通过条件

按实际探测结果完成 A640 CX 电源、200MHz GMU 时钟、RPMh ARC/BCM 投票和 RSC/PDC；
建立独立的4KiB GMU/GPU SMMU映射，处理16KiB CPU分配与缓存同步，不能使用 DMA bypass。
主机上用上游 ArmSmmu4K 实际代码已将模拟16KiB分配映射成四个4KiB叶子，使用3个表页；
0089已验证真机分配与缓存清理调用；仍未证明硬件页表遍历、DMA或缓存一致性正确。NativeAdreno中的CPU页号移位、
BO分配取整、导入页所有权和页属性恢复仍需适配；不能只删除4KiB检查。
A640 DT 没有 sheng 的 dma-coherent 声明，页表遍历一致性也必须单独验证。
正确装入 A640 固件并取得真实 FW/HFI ACK 后，再做 SQE、ring、scratch write 与 fence。
ZAP/PAS13 和非安全模式切换应参照 A640/Linux 与真机保留区，不能复用 sheng 的固件物理地址。

只有 GPU 实际写回 scratch、fence 前进、显存清屏/拷贝校验正确后，才接入 IOSurface 与
显示提交；随后移植适配 iOS16 的 Metal/Turnip 用户态链路，用真实 draw/着色器结果和 GUI
验证 GPU 渲染。命令处理器工作、GPU 拷贝和 GPU 着色渲染是不同里程碑。
