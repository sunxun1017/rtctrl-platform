# 最小实际 Kbuild 建议（未执行）

主控在新私有完整 source/output 中整合稳定 source-v4 五源及另审的 codec shared-I/O
改动；原 SDK、已接受 Image-v4 source/build、冻结模块不写入。以实际 v4 .config
1268f3061ecf94e063d8785010a793cc7edaaf0d61d29d6c29887a9dccfed912 为基准，保存新
实际配置与 olddefconfig/prepare 的命令和差异；不手改 generated headers。

与旧 Image 相同工具链为 aarch64-linux-gnu-gcc 11.4.0，host-tools/bin 提供真实
bison/flex/m4。新 source/out 路径由主控分配；下列参数中 PRIVATE_SOURCE、PRIVATE_OUT
是明确的待填路径，不是已执行记录。

    make -C PRIVATE_SOURCE O=PRIVATE_OUT ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- olddefconfig
    make -C PRIVATE_SOURCE O=PRIVATE_OUT ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- prepare
    make -C PRIVATE_SOURCE O=PRIVATE_OUT ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- V=1 sound/soc/soc-pcm.o sound/soc/generic/simple-card-utils.o sound/soc/rockchip/rockchip_i2s_tdm.o sound/soc/codecs/rk817_codec.o

四个实际独立 TU 对象能捕获 host 单 unit 模型掩盖的 static/macro 可见性、真实 ops
签名、字段/头依赖问题。保存实际 .cmd、argv、stdout/stderr、exit 与 ELF；按实际 board
config 记录各对象是否带 -DMODULE，不用模型 typedef 作为真实类型或 ABI 证据。

include/sound/soc-dai.h 尾部新增 ops callbacks 改变内部 ops 布局，后续须整套 Image 与
关联模块由同一新树重新构建。旧 rk817_codec.ko 不能复用；上述对象成功只代表有限 TU
Kbuild，不能代替新 Image/模块 ABI 或硬件验收。若要验证 opt-in 的 DT/parser、完整
driver 注册，还需新实际整体构建与独立复核，不能以 synthetic model registration 代替。
