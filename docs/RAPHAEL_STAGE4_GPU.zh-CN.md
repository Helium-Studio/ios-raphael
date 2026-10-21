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

2026-10-21 21:07 已临时启动首个探测镜像，发送与启动均OKAY，尚待屏幕反馈和持久日志。
CI [39443279478](https://github.com/HeliumStudio-Dev/ios-raphael/actions/runs/39443279478)
通过，内核源码为 `3af6f55`；镜像 `shim/out/raphael-0086-gpu-probe.img` 的SHA256为
`4d83c4ca3d5a15fc7ade5cf4f4018a080e8fca9391f89acd5449ffcbdb02fd92`。
该镜像保留八核、触控与按键；没有安装Metal插件，也没有刷写分区。

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
